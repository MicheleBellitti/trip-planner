"""Terminal entry points: one real plan with a live timeline, or an offline replay.

Spec: "Piano di lavoro in 4 giorni" -> day 1 ("consumer.py, events.py, POST /plans, python -m
app.cli run"; "Fine giornata: un piano development completo, validato e salvato, sotto 0,60 $")
and "Backend FastAPI" (`cli.py  # python -m app.cli run: terminal timeline`).

    uv run python -m app.cli run --request request.json [--yes]
    uv run python -m app.cli replay tests/fixtures/ma/<scenario>.jsonl [--request request.json]
    uv run python -m app.cli import-evals RESULTS.json [--comparison FILE] [--workflow-run-url URL]

`run` drives a REAL Managed Agents session (it costs money; CLAUDE.md: only when Michele asks).
It uses the same path as POST /plans: `sessions.start_planner` with the SDK client, then
`sessions.start_plan` with the AUTH_MODE=local user (the first PLANNER_ALLOWED_EMAILS entry),
against DATABASE_URL. Guards: refuses unless AGENT_PROFILE=development (production only with
`--allow-production`), prints the session budget and asks for confirmation unless `--yes`
(required without a TTY). Ctrl-C sends `user.interrupt` and waits for the plan to stop.

`replay` is fully offline: the same start path, but with `tests.fakes.FakeManagedAgentsClient`
loaded from a JSONL script (backend/tests/fakes/README.md), FX in offline mode and the dev
fallback trip.json. It still needs a Postgres DATABASE_URL (the consumer persists events).
The fake is imported lazily from tests/, which ships with the backend directory.

`import-evals` stores an eval results file (evals/run.py) in the eval history, through the same
function as POST /evals/runs (`evals_store.store_eval_run`), in DATABASE_URL: offline and free.
It prints the run's id and whether it was new (importing it again is harmless). Exit 0 stored,
2 for an unreadable or invalid file.

Both answer the traveller's questions (`ask_traveller`) as the timeline shows them, so a run
never waits for the 4-minute deadline: by default the first option (`Scelta automatica: ...`);
`run --choose` asks at the terminal ("1,3", or an empty line for "Scegli tu").

`run` and `replay` print the timeline as the hub publishes it, one line per UI event
(`render_event`), and finally the plan's status, cost, and the path of the stored Trip when
ready. Exit codes: 0 ready, 1 any other final status, 2 usage or configuration errors.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO, cast

import httpx
import structlog
from pydantic import ValidationError

from app import clock, evals_store, sessions
from app.auth import CurrentUser
from app.choices import ChoiceAnswer
from app.config import BACKEND_DIR, Settings, add_message_key, add_plan_log_keys, get_settings
from app.consumer import StatusChange, load_events_after, set_plan_status
from app.db import PlanRecord, PlanStatus, create_engine, create_session_factory
from app.events import AgentName, EventKind, UIEvent, format_usd
from app.hub import PlanEnded, SubscriptionLaggedError
from app.ma_client import ManagedAgentsError
from app.request import ALLOW_PAST_DATES, PlanRequest
from app.triptracker_schema import DEV_FALLBACK_SCHEMA_PATH, TripSchemaUnavailableError

if TYPE_CHECKING:
    from app.ma_client import ManagedAgentsClient

EXIT_READY = 0
EXIT_NOT_READY = 1
EXIT_USAGE = 2

DEFAULT_REPLAY_REQUEST = {
    "origin": "Milano",
    "destination": "Lisbona",
    "dates": {"exact_start": "2026-11-14", "exact_end": "2026-11-18"},
    "travelers": [{"kind": "adult"}, {"kind": "adult"}],
    "budget_eur": 1500,
}
"""Request used by `replay` without `--request` (validated with past dates allowed, so the
fixture keeps working after November 2026)."""

REPLAY_LOCKFILE_DIR = BACKEND_DIR / "tests" / "fixtures" / "lockfile"
"""`replay` resolves its roster from the fixture lockfiles: the fake ignores agent ids, and a
replayed plan must never record real ones."""

DEFAULT_OUT_DIR = Path(tempfile.gettempdir()) / "trip-planner"
"""Where the Trip JSON of a ready plan is written unless `--out` says otherwise."""

LANE_WIDTH = 10
KIND_WIDTH = 8
POLL_SECONDS = 0.5
"""How often the timeline re-reads Postgres when the hub is quiet."""
CHOICE_HINT = "Scrivi i numeri separati da virgola (per esempio 1,3), oppure invio per Scegli tu."
CHOICE_HINT_SINGLE = "Questa domanda vuole una sola opzione: scrivi un numero, oppure invio."
CHOICE_CLOSED_LINE = "Tempo scaduto: sceglie Atlas"
CHOICE_SKIPPED_LINE = "Scegli tu: decide Atlas"
REPLAY_STALL_SECONDS = 5.0
"""`replay`: once the script has finished, how long the consumer may stay silent before the
replay gives up (a scenario that needs a test to act at a checkpoint)."""

_RESET = "\033[0m"
_DIM = "\033[2m"
_RED = "\033[31m"
LANE_COLORS: Mapping[AgentName, str] = {
    AgentName.COORDINATOR: "\033[35m",
    AgentName.FLIGHTS: "\033[36m",
    AgentName.LODGING: "\033[32m",
    AgentName.ACTIVITIES: "\033[33m",
    AgentName.TRANSPORT: "\033[34m",
}

REASON_REPLAY_STOPPED = "Replay fermato: lo scenario aspettava un'azione che non è arrivata."
TITLE_REPLAY_STOPPED = "Replay fermato"

STATUS_LABELS: Mapping[PlanStatus, str] = {
    PlanStatus.RUNNING: "in corso",
    PlanStatus.READY: "pronto",
    PlanStatus.FAILED: "non riuscito",
    PlanStatus.BUDGET_PAUSED: "in pausa: budget raggiunto",
    PlanStatus.BLOCKED: "bloccato",
    PlanStatus.INTERRUPTED: "interrotto",
}
"""Italian labels next to the status code in the closing lines."""


def build_parser() -> argparse.ArgumentParser:
    """`run` (--request PATH required, --yes, --allow-production, --no-color) and `replay`
    (FIXTURE positional, --request PATH, --no-color). Both also take `--out DIR`, where the
    Trip JSON of a ready plan is written (default: the system temp dir, `trip-planner/`)."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Run one plan with a live terminal timeline, or replay a scripted session.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="one REAL plan: a Managed Agents session (costs money)")
    run.add_argument("--request", type=Path, required=True, help="PlanRequest JSON file")
    run.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    run.add_argument(
        "--allow-production",
        action="store_true",
        help="allow AGENT_PROFILE=production (Opus coordinator, 4 $ budget)",
    )
    run.add_argument("--no-color", action="store_true", help="plain text, no ANSI colors")
    run.add_argument("--out", type=Path, default=None, help="directory for the Trip JSON")
    run.add_argument(
        "--choose",
        action="store_true",
        help="answer the traveller's questions at the terminal (default: pick automatically)",
    )

    replay = commands.add_parser(
        "replay", help="offline: play a scripted session through the fake client"
    )
    replay.add_argument("fixture", type=Path, help="tests/fixtures/ma/<scenario>.jsonl")
    replay.add_argument(
        "--request", type=Path, default=None, help="PlanRequest JSON (default: the script's)"
    )
    replay.add_argument("--no-color", action="store_true", help="plain text, no ANSI colors")
    replay.add_argument("--out", type=Path, default=None, help="directory for the Trip JSON")

    import_evals = commands.add_parser(
        "import-evals", help="offline: store an eval results file in the eval history"
    )
    import_evals.add_argument("results", type=Path, help="evals/results/<date>-<sha>.json")
    import_evals.add_argument(
        "--comparison", type=Path, default=None, help="evals/compare.py --json output"
    )
    import_evals.add_argument(
        "--workflow-run-url", default=None, help="link to the CI run that produced the results"
    )
    return parser


def load_request(path: Path, *, allow_past_dates: bool = False) -> PlanRequest:
    """Read and validate a PlanRequest JSON file; with `allow_past_dates` the "in the future"
    rules are skipped (`PlanRequest.from_stored`). Raises SystemExit(EXIT_USAGE) with the
    validation errors printed, never a traceback."""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"Impossibile leggere {path}: {exc.strerror or exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE) from exc
    except ValueError as exc:
        print(f"{path} non è JSON valido: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE) from exc
    try:
        if allow_past_dates:
            return PlanRequest.model_validate(data, context={ALLOW_PAST_DATES: True})
        return PlanRequest.model_validate(data)
    except ValidationError as exc:
        print(f"Richiesta non valida in {path}:", file=sys.stderr)
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "(richiesta)"
            print(f"  {location}: {error['msg']}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE) from exc


def _read_eval_document(path: Path) -> dict[str, Any] | None:
    """A JSON object file of at most `evals_store.MAX_INGEST_BYTES`, or None with the reason
    printed."""
    try:
        if path.stat().st_size > evals_store.MAX_INGEST_BYTES:
            limit = evals_store.MAX_INGEST_BYTES
            print(f"{path} supera i {limit} byte consentiti.", file=sys.stderr)
            return None
        raw = path.read_bytes()
    except OSError as exc:
        print(f"Impossibile leggere {path}: {exc.strerror or exc}", file=sys.stderr)
        return None
    try:
        document = evals_store.parse_json(raw)
    except evals_store.InvalidEvalResultsError as exc:
        print(f"{path} non è JSON valido: {exc}", file=sys.stderr)
        return None
    if not isinstance(document, dict):
        print(f"{path}: deve essere un oggetto JSON.", file=sys.stderr)
        return None
    return cast(dict[str, Any], document)


async def import_evals_command(
    results_path: Path,
    *,
    settings: Settings,
    comparison_path: Path | None,
    workflow_run_url: str | None,
) -> int:
    """`import-evals`: validate and store the run (`evals_store.store_eval_run`)."""
    results = _read_eval_document(results_path)
    comparison = _read_eval_document(comparison_path) if comparison_path is not None else None
    if results is None or (comparison_path is not None and comparison is None):
        return EXIT_USAGE  # the reason was printed
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as db:
            try:
                stored = await evals_store.store_eval_run(
                    db,
                    results=results,
                    comparison=comparison,
                    workflow_run_url=workflow_run_url,
                )
            except evals_store.InvalidEvalResultsError as exc:
                print("Risultati delle eval non validi:", file=sys.stderr)
                for error in exc.errors:
                    print(f"  {error['field']}: {error['reason']}", file=sys.stderr)
                return EXIT_USAGE
    finally:
        await engine.dispose()
    print(f"{'Importata' if stored.created else 'Già presente'}: esecuzione {stored.id}")
    return EXIT_READY


def render_event(event: UIEvent, *, color: bool) -> str:
    """One timeline line: local time (HH:MM:SS, Europe/Rome), the agent lane padded to 10, the
    kind, the title, and the cumulative cost when known, e.g.
    `15:04:05  flights     tool     Expedia · voli MXP→LIS · 14–18 nov   0,37 $`. ANSI colors
    per lane when `color`. Never prints `detail` (it may hold message text)."""
    when = event.ts.astimezone(clock.HOME_TIMEZONE).strftime("%H:%M:%S")
    lane = event.agent.value.ljust(LANE_WIDTH)
    kind = event.kind.value.ljust(KIND_WIDTH)
    cost = f"   {format_usd(event.cost_cents)}" if event.cost_cents is not None else ""
    if not color:
        return f"{when}  {lane}  {kind} {event.title}{cost}"
    lane_color = LANE_COLORS.get(event.agent, "")
    kind_text = f"{_RED}{kind}{_RESET}" if event.kind is EventKind.ERROR else kind
    cost_text = f"{_DIM}{cost}{_RESET}" if cost else ""
    return f"{_DIM}{when}{_RESET}  {lane_color}{lane}{_RESET}  {kind_text} {event.title}{cost_text}"


def render_summary(status: PlanStatus, *, cost_cents: int, trip_path: Path | None) -> str:
    """The closing lines: final status, cost in dollars, where the Trip JSON was written."""
    lines = [
        f"Stato finale: {status.value} ({STATUS_LABELS.get(status, status.value)})",
        f"Costo: {format_usd(cost_cents)}",
    ]
    if trip_path is not None:
        lines.append(f"Trip salvato in {trip_path}")
    return "\n".join(lines)


def render_trip_summary(trip: Mapping[str, Any]) -> str:
    """One line about the stored Trip: title, destination, dates, days and bookings."""
    days = trip.get("days")
    bookings = trip.get("bookings")
    parts = [
        str(trip.get("title") or "(senza titolo)"),
        str(trip.get("destinationName") or ""),
        f"{trip.get('startDate', '?')} → {trip.get('endDate', '?')}",
        f"{len(days) if isinstance(days, list) else 0} giorni",
        f"{len(bookings) if isinstance(bookings, list) else 0} prenotazioni",
    ]
    return "Viaggio: " + " · ".join(part for part in parts if part)


async def run_command(
    request_path: Path,
    *,
    settings: Settings,
    yes: bool,
    allow_production: bool,
    color: bool,
    out_dir: Path | None = None,
    choose: bool = False,
) -> int:
    """`run`: real session, live timeline, exit code by final status (module docstring).
    Refused under DEMO_MODE, whose planner replays scripted sessions instead of real ones."""
    if settings.demo_mode:
        print(
            "DEMO_MODE è attivo: `run` avvia una sessione reale, togli DEMO_MODE (o usa "
            "`replay` per uno scenario registrato).",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if settings.agent_profile != "development" and not allow_production:
        print(
            f"AGENT_PROFILE={settings.agent_profile}: `run` usa solo il profilo development "
            "(aggiungi --allow-production per le prove finali).",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if not settings.anthropic_credentials_available:
        print(
            "ANTHROPIC_API_KEY non è impostata (backend/.env) e la federazione non è configurata.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    user = _local_user(settings)
    if user is None:
        return EXIT_USAGE
    request = load_request(request_path)
    print(
        f"Sessione reale Managed Agents: profilo {settings.agent_profile}, budget "
        f"{format_usd(settings.session_budget_cents)} per piano."
    )
    if not yes:
        if not sys.stdin.isatty():
            print("Senza un terminale serve --yes.", file=sys.stderr)
            return EXIT_USAGE
        answer = await asyncio.to_thread(input, "Costa denaro. Procedo? [s/N] ")
        if answer.strip().lower() not in {"s", "si", "sì", "y", "yes"}:
            print("Annullato.")
            return EXIT_USAGE

    engine = create_engine(settings)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as http:
            services = await sessions.start_planner(
                settings,
                session_factory=create_session_factory(engine),
                http=http,
                resume=False,
            )
            try:
                return await _drive_plan(
                    services,
                    request,
                    user,
                    color=color,
                    out_dir=out_dir or DEFAULT_OUT_DIR,
                    handle_ctrl_c=True,
                    choose=choose,
                )
            finally:
                await sessions.stop_planner(services)
    finally:
        await engine.dispose()


async def replay_command(
    fixture_path: Path,
    *,
    settings: Settings,
    request_path: Path | None,
    color: bool,
    out_dir: Path | None = None,
    choose: bool = False,
) -> int:
    """`replay`: the fake client fed with `fixture_path`, otherwise identical to `run`.

    Offline by construction: the fake client, FX in offline mode (cache only), trip.json from
    the vendored dev fallback (a `file://` URL, never TripTracker), the roster from the fixture
    lockfile of the profile, and no resume of other running plans. Development only, because it
    writes a plan into DATABASE_URL. The scenario's event ids get a fresh namespace on every
    run (`FakeManagedAgentsClient(id_namespace=...)`), so a scenario can be replayed any number
    of times into the same database."""
    if settings.is_production:
        print("`replay` scrive nel database: solo con ENVIRONMENT=development.", file=sys.stderr)
        return EXIT_USAGE
    try:
        from tests.fakes import FakeManagedAgentsClient
    except ImportError as exc:
        print(f"`replay` usa tests/fakes (lancialo da backend/): {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        # A fresh id namespace per run: `events.ma_event_id` is unique across the database, so
        # the scenario's fixed ids would make a second replay into the same database a no-op.
        fake = FakeManagedAgentsClient.from_jsonl(fixture_path, id_namespace=uuid.uuid4().hex[:12])
    except FileNotFoundError:
        print(f"Scenario non trovato: {fixture_path}", file=sys.stderr)
        return EXIT_USAGE
    except (OSError, ValueError) as exc:
        print(f"Scenario non valido ({fixture_path}): {exc}", file=sys.stderr)
        return EXIT_USAGE
    user = _local_user(settings)
    if user is None:
        return EXIT_USAGE
    if request_path is not None:
        request = load_request(request_path, allow_past_dates=True)
    else:
        stored = fake.meta.get("request") or DEFAULT_REPLAY_REQUEST
        try:
            request = PlanRequest.from_stored(stored)
        except ValidationError as exc:
            print(f"La richiesta dello scenario non è valida: {exc}", file=sys.stderr)
            return EXIT_USAGE

    replay_settings = settings.model_copy(
        update={
            "trip_schema_url": DEV_FALLBACK_SCHEMA_PATH.as_uri(),
            "lockfile_path": REPLAY_LOCKFILE_DIR / f"claude-lock.{settings.agent_profile}.json",
            "anthropic_api_key": None,
            "demo_mode": False,  # the replay drives its own fake at full speed
        }
    )
    client = cast("ManagedAgentsClient", fake)
    engine = create_engine(replay_settings)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as http:
            services = await sessions.start_planner(
                replay_settings,
                session_factory=create_session_factory(engine),
                http=http,
                client=client,
                resume=False,
                fx_offline=True,
            )
            try:
                code = await _drive_plan(
                    services,
                    request,
                    user,
                    color=color,
                    out_dir=out_dir or DEFAULT_OUT_DIR,
                    script_done=lambda: fake.done or bool(fake.mismatches),
                    choose=choose,
                )
            finally:
                await sessions.stop_planner(services)
                await fake.shutdown()
    finally:
        await engine.dispose()
    for mismatch in fake.mismatches[:3]:
        print(f"Attenzione, lo scenario non è andato come scritto: {mismatch}", file=sys.stderr)
    return code


def _local_user(settings: Settings) -> CurrentUser | None:
    """The AUTH_MODE=local user: the first PLANNER_ALLOWED_EMAILS entry."""
    email = settings.local_user_email or next(iter(settings.planner_allowed_emails), None)
    if email is None:
        print("PLANNER_ALLOWED_EMAILS è vuota: serve l'utente del piano.", file=sys.stderr)
        return None
    return CurrentUser(email=email)


async def _drive_plan(
    services: sessions.PlannerServices,
    request: PlanRequest,
    user: CurrentUser,
    *,
    color: bool,
    out_dir: Path,
    handle_ctrl_c: bool = False,
    script_done: Callable[[], bool] | None = None,
    out: TextIO | None = None,
    choose: bool = False,
) -> int:
    """Start the plan like POST /plans, print its timeline until the consumer stops, then the
    closing lines. Returns the exit code.

    With `script_done` (replay), a plan still `running` when the replay stops is set
    `interrupted` (`REASON_REPLAY_STOPPED`): its fake session doesn't exist on the platform, so
    it must not be resumed by the next start of the web app.

    The traveller's questions (`ask_traveller`) are answered as soon as the timeline shows
    them, so a run never waits for the deadline: automatically (the first option), or at the
    terminal with `choose`."""
    stream = out or sys.stdout
    try:
        plan_id = await sessions.start_plan(request, user, services=services)
    except sessions.PlannerUnavailableError as exc:
        print("Il planner non è disponibile:", file=sys.stderr)
        for reason in exc.reasons:
            print(f"  - {reason}", file=sys.stderr)
        return EXIT_USAGE
    except TripSchemaUnavailableError as exc:
        print(f"trip.json non disponibile: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except sessions.MonthlyLimitReachedError as exc:
        print(
            f"Limite mensile raggiunto: spesi {format_usd(exc.spent_cents)} su "
            f"{format_usd(exc.limit_cents)}.",
            file=sys.stderr,
        )
        return EXIT_NOT_READY
    except (ManagedAgentsError, TimeoutError) as exc:
        print(f"Avvio della sessione non riuscito: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_NOT_READY

    print(
        f"Piano {plan_id} · profilo {services.settings.agent_profile} · budget "
        f"{format_usd(services.settings.session_budget_cents)}",
        file=stream,
    )
    stop_requests = 0
    stop_event = asyncio.Event()

    def on_ctrl_c() -> None:
        nonlocal stop_requests
        stop_requests += 1
        stop_event.set()

    loop = asyncio.get_running_loop()
    installed = False
    if handle_ctrl_c:
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signal.SIGINT, on_ctrl_c)
            installed = True

    async def on_stop() -> bool:
        """Ctrl-C: the first one interrupts the plan, the second stops following it."""
        if stop_requests > 1:
            print("Smetto di seguire il piano: resta running e riprende al prossimo avvio.")
            return True
        stop_event.clear()
        print("Interruzione richiesta: aspetto che gli agenti si fermino (Ctrl-C per uscire).")
        try:
            await sessions.interrupt_plan(plan_id, user, services=services)
        except (ManagedAgentsError, sessions.PlanStateError) as exc:
            print(f"Interruzione non riuscita: {type(exc).__name__}", file=sys.stderr)
        return False

    try:
        await _follow_timeline(
            services,
            plan_id,
            color=color,
            out=stream,
            stop_event=stop_event,
            on_stop=on_stop,
            script_done=script_done,
            chooser=(_terminal_chooser if choose else _automatic_chooser)(
                services, plan_id, user, stream
            ),
        )
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGINT)
        if services.registry is not None and services.registry.get(plan_id) is not None:
            await services.registry.stop(plan_id)

    if script_done is not None:
        await set_plan_status(
            services.session_factory,
            services.hub,
            plan_id,
            StatusChange(PlanStatus.INTERRUPTED, reason=REASON_REPLAY_STOPPED),
            title=TITLE_REPLAY_STOPPED,
            event_key="replay-stopped",
        )  # a no-op unless the plan is still running
    async with services.session_factory() as db:
        plan = await db.get(PlanRecord, plan_id)
    if plan is None:
        print("Il piano non esiste più.", file=sys.stderr)
        return EXIT_NOT_READY
    status = PlanStatus(plan.status)
    trip_path: Path | None = None
    print("", file=stream)
    if plan.trip is not None:
        trip_path = await asyncio.to_thread(_write_trip, out_dir, plan_id, plan.trip)
        print(render_trip_summary(plan.trip), file=stream)
    if plan.failure_reason:
        print(f"Motivo: {plan.failure_reason}", file=stream)
    print(render_summary(status, cost_cents=plan.cost_cents, trip_path=trip_path), file=stream)
    return EXIT_READY if status is PlanStatus.READY else EXIT_NOT_READY


async def _follow_timeline(
    services: sessions.PlannerServices,
    plan_id: uuid.UUID,
    *,
    color: bool,
    out: TextIO,
    stop_event: asyncio.Event,
    on_stop: Callable[[], Any],
    script_done: Callable[[], bool] | None,
    chooser: Chooser | None = None,
) -> None:
    """Print every event of the plan once, in `seq` order, until its consumer stops.

    A stored `choice` event with `detail.phase == "asked"` is handed to `chooser` right after it
    is printed (this loop sees each stored event exactly once).

    Postgres is the source of truth: the hub only wakes the loop up (any message means "read
    again"), so events committed before the subscription, published out of order or dropped
    by a lagging subscription are all printed from `events`."""
    last_seq: int | None = None
    loop = asyncio.get_running_loop()
    quiet_since = loop.time()

    async def catch_up() -> bool:
        nonlocal last_seq
        async with services.session_factory() as db:
            events = await load_events_after(db, plan_id, last_seq)
        for event in events:
            print(render_event(event, color=color), file=out, flush=True)
            last_seq = event.seq
            if chooser is not None and _is_asked_choice(event):
                await chooser(event)
        return bool(events)

    with services.hub.subscribe(plan_id) as subscription:
        live = aiter(subscription)
        listening = True
        while True:
            if await catch_up():
                quiet_since = loop.time()
            registry = services.registry
            consumer = registry.get(plan_id) if registry is not None else None
            if consumer is None or consumer.done:
                await catch_up()
                return
            if stop_event.is_set():
                result = on_stop()
                if asyncio.iscoroutine(result):
                    result = await result
                if result:
                    return
            stalled = loop.time() - quiet_since > REPLAY_STALL_SECONDS
            if script_done is not None and stalled and script_done():
                print(
                    "Lo scenario è finito ma il piano è ancora running: mi fermo.",
                    file=sys.stderr,
                )
                return
            if not listening:
                await asyncio.sleep(POLL_SECONDS)
                continue
            try:
                message = await asyncio.wait_for(anext(live), timeout=POLL_SECONDS)
            except TimeoutError:
                continue
            except (StopAsyncIteration, SubscriptionLaggedError):
                listening = False  # Postgres polling from now on
                continue
            if isinstance(message, PlanEnded):
                listening = False


Chooser = Callable[[UIEvent], Awaitable[None]]
"""Answers the question of an asked `choice` event."""


def _is_asked_choice(event: UIEvent) -> bool:
    return (
        event.kind is EventKind.CHOICE
        and event.detail is not None
        and event.detail.get("phase") == "asked"
        and isinstance(event.detail.get("choice"), dict)
    )


def parse_choice_line(line: str, *, count: int, multiple: bool) -> list[int] | None:
    """The 1-based numbers typed for a question with `count` options: "2", "1,3". An empty line
    is `[]` (skip). None when it does not fit: not numbers, out of range, repeated, or more
    than one on a single choice."""
    text = line.strip()
    if not text:
        return []
    try:
        numbers = [int(part) for part in text.split(",")]
    except ValueError:
        return None
    if len(set(numbers)) != len(numbers) or not all(1 <= n <= count for n in numbers):
        return None
    if len(numbers) > 1 and not multiple:
        return None
    return numbers


def _option_titles(event: UIEvent, selected: Sequence[str]) -> str:
    assert event.detail is not None
    options = event.detail["choice"]["options"]
    titles = {option["id"]: option["title"] for option in options}
    return ", ".join(titles.get(value, value) for value in selected)


def _automatic_chooser(
    services: sessions.PlannerServices, plan_id: uuid.UUID, user: CurrentUser, out: TextIO
) -> Chooser:
    """`run` and `replay` by default: `answer_pending_choice` (the first option, the first two
    when several can be picked)."""

    async def choose(event: UIEvent) -> None:
        try:
            answered = await sessions.answer_pending_choice(plan_id, user, services=services)
        except (
            sessions.PlanNotFoundError,
            sessions.PlannerUnavailableError,
            sessions.InvalidChoiceAnswerError,
        ) as exc:
            print(f"Scelta automatica non riuscita: {type(exc).__name__}", file=sys.stderr)
            return
        if answered is None:
            return  # closed by the deadline or the platform first
        picked = _option_titles(event, answered.selected) or "nessuna, sceglie Atlas"
        print(f"Scelta automatica: {picked}", file=out, flush=True)

    return choose


def _terminal_chooser(
    services: sessions.PlannerServices, plan_id: uuid.UUID, user: CurrentUser, out: TextIO
) -> Chooser:
    """`run --choose`: print the question and the numbered options, read the answer (the end
    of input skips)."""

    async def choose(event: UIEvent) -> None:
        assert event.detail is not None
        choice = event.detail["choice"]
        options = choice["options"]
        multiple = bool(choice["multiple"])
        print(choice["question"], file=out)
        for number, option in enumerate(options, start=1):
            print(f"  {number}. {option['title']}: {option['reason']}", file=out)
        hint = CHOICE_HINT if multiple else CHOICE_HINT_SINGLE
        while True:
            try:
                line = await asyncio.to_thread(input, "Scegli: ")
            except EOFError:  # a piped or closed stdin: "Scegli tu"
                line = ""
            numbers = parse_choice_line(line, count=len(options), multiple=multiple)
            if numbers is not None:
                break
            print(hint, file=out, flush=True)
        answer = (
            ChoiceAnswer(selected=[options[n - 1]["id"] for n in numbers])
            if numbers
            else ChoiceAnswer(skip=True)
        )
        try:
            await sessions.answer_choice(plan_id, choice["id"], answer, user, services=services)
        except sessions.ChoiceClosedError:
            print(CHOICE_CLOSED_LINE, file=out, flush=True)
        except (
            sessions.PlanNotFoundError,
            sessions.PlannerUnavailableError,
            sessions.InvalidChoiceAnswerError,
        ) as exc:
            print(f"Risposta non riuscita: {type(exc).__name__}", file=sys.stderr)
        else:
            if not numbers:
                print(CHOICE_SKIPPED_LINE, file=out, flush=True)

    return choose


def _write_trip(out_dir: Path, plan_id: uuid.UUID, trip: Mapping[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"trip-{plan_id}.json"
    path.write_text(json.dumps(trip, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _configure_logging() -> None:
    """WARNING and above, as JSON lines on stderr, so the timeline on stdout stays readable;
    the plan keys on every line (`config.add_plan_log_keys`, as in main.configure_logging)."""
    logging.basicConfig(format="%(message)s", level=logging.WARNING, stream=sys.stderr)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_plan_log_keys,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            add_message_key,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, load `get_settings()`, configure logging (WARNING, so the timeline
    stays readable) and run the command with `asyncio.run`."""
    args = build_parser().parse_args(argv)
    try:
        settings = get_settings()
    except ValidationError as exc:
        print(f"Configurazione non valida: {exc}", file=sys.stderr)
        return EXIT_USAGE
    _configure_logging()
    if args.command == "import-evals":
        return asyncio.run(
            import_evals_command(
                args.results,
                settings=settings,
                comparison_path=args.comparison,
                workflow_run_url=args.workflow_run_url,
            )
        )
    color = not args.no_color and sys.stdout.isatty()
    if args.command == "run":
        return asyncio.run(
            run_command(
                args.request,
                settings=settings,
                yes=args.yes,
                allow_production=args.allow_production,
                color=color,
                out_dir=args.out,
                choose=args.choose,
            )
        )
    return asyncio.run(
        replay_command(
            args.fixture,
            settings=settings,
            request_path=args.request,
            color=color,
            out_dir=args.out,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
