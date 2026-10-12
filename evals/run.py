"""Run the eval dataset through the real backend, in-process. IT SPENDS REAL MONEY.

    cd backend
    uv run python ../evals/run.py                       # all five requests, development
    uv run python ../evals/run.py --tags train,smoke    # requests with any of these tags
    uv run python ../evals/run.py --ids sea-week-family --no-judge
    uv run python ../evals/run.py --dry-run             # validate and print, spend nothing
    uv run python ../evals/run.py --profile production  # final check only (spec)

Spec: "Eval sui piani" and "Eval strutturate e versioning dei prompt". For every selected
request of evals/requests.yaml this script takes the same path as POST /plans:

1. `app.sessions.start_planner` with the real SDK client (ANTHROPIC_API_KEY, or in development
   Workload Identity Federation, from the environment or backend/.env), the profile's lockfile
   (`backend/claude-lock.<profile>.json`, or `--lockfile`) and a DEDICATED database:
   DATABASE_URL with `_evals` appended to the database name (or `--database-url` /
   EVAL_DATABASE_URL), created and migrated if needed, so eval plans never mix with the plans
   of the dev database;
2. `app.sessions.start_plan` with a fixed eval user, then polls `plans.status` until it leaves
   `running` (ready, failed, blocked, interrupted, or budget_paused, which is never continued
   here); after `--timeout-minutes` the plan is interrupted;
3. collects the plan, the Trip, `submit_attempts` and `agent_versions` from the database, and
   the session usage (`list_cost`, web searches) from `client.retrieve_session`;
4. runs evals/checks.py and the judge (evals/judge.py, at most `judge.JUDGE_CAP_CENTS` for the
   whole run);
5. writes evals/results/<date>-<git sha>.json (`-2`, `-3`... when that name exists).

Then evals/compare.py checks the results against evals/baseline.json.

Guards: the development profile unless `--profile production` is given explicitly (an
AGENT_PROFILE=production in the environment or backend/.env is refused without it); the
spending ceiling is printed and confirmed (`--yes` skips the question; without a terminal it is
required). Ctrl-C interrupts the plans in flight and writes the partial results.

Exit codes: 0 results written; 1 the planner could not start (missing key, lockfile or
trip.json: nothing spent); 2 usage or configuration error; 130 aborted (partial results
written).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

EVALS_DIR = Path(__file__).resolve().parent
REPO_DIR = EVALS_DIR.parent
BACKEND_DIR = REPO_DIR / "backend"
for _path in (BACKEND_DIR, EVALS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import yaml  # noqa: E402

import checks  # noqa: E402
import judge  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import Settings
    from app.db import PlanRecord
    from app.request import PlanRequest
    from app.sessions import PlannerServices

Profile = Literal["development", "production"]

DATASET_PATH = EVALS_DIR / "requests.yaml"
RESULTS_DIR = EVALS_DIR / "results"
RESULTS_KIND = "trip-planner-eval-results"
RESULTS_FORMAT = 1

EVAL_USER_EMAIL = "evals@trip-planner.invalid"
"""Stored as `plans.user_email` of eval plans (never sent to the agents)."""
EVAL_DATABASE_SUFFIX = "_evals"
EVAL_DATABASE_URL_ENV = "EVAL_DATABASE_URL"

DEFAULT_TIMEOUT_MINUTES = 40.0
"""Below the backend's 45-minute stuck-plan threshold; the spec expects ~15 minutes."""
INTERRUPT_GRACE_SECONDS = 120.0
POLL_SECONDS = 5.0

EXIT_OK = 0
EXIT_PLANNER_UNAVAILABLE = 1
EXIT_USAGE = 2
EXIT_ABORTED = 130


class UsageError(Exception):
    """A bad argument, dataset or configuration: exit 2 with the message, nothing spent."""


# --- dataset ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One entry of evals/requests.yaml."""

    id: str
    title: str
    tags: tuple[str, ...]
    request: Mapping[str, Any]
    expect: Mapping[str, Any]

    @property
    def expectations(self) -> checks.Expectations:
        return checks.Expectations.from_mapping(self.expect)


@dataclass(frozen=True, slots=True)
class Dataset:
    version: int
    authored_on: dt.date
    valid_until: dt.date
    cases: tuple[EvalCase, ...]


def load_dataset(path: Path = DATASET_PATH) -> Dataset:
    """Parse evals/requests.yaml (shape only; `validate_requests` checks the requests)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    if not isinstance(data, Mapping) or not isinstance(data.get("requests"), list):
        raise UsageError(f"{path}: expected a mapping with a 'requests' list")
    data = cast(Mapping[str, Any], data)
    cases: list[EvalCase] = []
    for index, raw in enumerate(cast(list[Any], data["requests"])):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("request"), Mapping):
            raise UsageError(f"{path}: requests[{index}] needs 'id', 'request' and 'expect'")
        raw = cast(Mapping[str, Any], raw)
        cases.append(
            EvalCase(
                id=str(raw["id"]),
                title=str(raw.get("title") or raw["id"]),
                tags=tuple(str(tag) for tag in raw.get("tags") or ()),
                request=cast(Mapping[str, Any], raw["request"]),
                expect=cast(Mapping[str, Any], raw.get("expect") or {}),
            )
        )
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise UsageError(f"{path}: duplicate request ids")
    return Dataset(
        version=int(data.get("version", 1)),
        authored_on=dt.date.fromisoformat(str(data["authored_on"])),
        valid_until=dt.date.fromisoformat(str(data["valid_until"])),
        cases=tuple(cases),
    )


def select_cases(
    cases: Sequence[EvalCase], *, tags: Sequence[str] = (), ids: Sequence[str] = ()
) -> list[EvalCase]:
    """The cases with any of `tags` and, when `ids` is given, one of `ids`; all when both are
    empty. Unknown ids are a usage error (a typo must not silently run nothing)."""
    known = {case.id for case in cases}
    unknown = sorted(set(ids) - known)
    if unknown:
        raise UsageError(f"unknown request id(s): {', '.join(unknown)}")
    selected = [
        case
        for case in cases
        if (not tags or set(tags) & set(case.tags)) and (not ids or case.id in ids)
    ]
    if not selected:
        raise UsageError("no request matches the given --tags/--ids")
    return selected


def validate_requests(
    cases: Sequence[EvalCase], *, allow_past_dates: bool = False
) -> dict[str, PlanRequest]:
    """Every case's request as a `PlanRequest` (dates in the future, unless allowed)."""
    from pydantic import ValidationError

    from app.request import PlanRequest

    requests: dict[str, PlanRequest] = {}
    problems: list[str] = []
    for case in cases:
        try:
            if allow_past_dates:
                requests[case.id] = PlanRequest.from_stored(case.request)
            else:
                requests[case.id] = PlanRequest.model_validate(case.request)
        except ValidationError as error:
            problems.append(f"{case.id}: {error}")
    if problems:
        raise UsageError(
            "invalid request(s) in evals/requests.yaml (dates in the past? see its header):\n"
            + "\n".join(problems)
        )
    return requests


# --- arguments and guards -----------------------------------------------------------------------


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evals/run.py",
        description="Run the eval requests through the real backend (spends real money).",
    )
    parser.add_argument("--tags", type=_csv, default=[], help="comma separated; any matches")
    parser.add_argument("--ids", type=_csv, default=[], help="comma separated request ids")
    parser.add_argument(
        "--profile",
        choices=("development", "production"),
        default=None,
        help="agent profile; development unless production is given explicitly",
    )
    parser.add_argument("--lockfile", type=Path, default=None, help="override the lockfile")
    parser.add_argument(
        "--database-url",
        default=None,
        help=f"eval database (default: ${EVAL_DATABASE_URL_ENV}, else DATABASE_URL + "
        f"'{EVAL_DATABASE_SUFFIX}')",
    )
    parser.add_argument("--concurrency", type=int, default=1, help="plans run at the same time")
    parser.add_argument("--timeout-minutes", type=float, default=DEFAULT_TIMEOUT_MINUTES)
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    parser.add_argument(
        "--judge-cap-cents", type=float, default=judge.JUDGE_CAP_CENTS, help=argparse.SUPPRESS
    )
    parser.add_argument("--output", type=Path, default=None, help="results file path")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and print the selection only"
    )
    return parser


def resolve_profile(explicit: str | None, configured: str | None) -> Profile:
    """The profile to run. Development unless `--profile production` is explicit; a
    configured AGENT_PROFILE=production without the flag is refused, never followed."""
    if explicit == "production":
        return "production"
    if explicit is None and configured == "production":
        raise UsageError(
            "AGENT_PROFILE=production is configured, but evals run on development unless "
            "--profile production is given explicitly. Pass --profile production for the "
            "final production check, or --profile development."
        )
    return "development"


def eval_database_url(database_url: str) -> str:
    """The dedicated eval database on the same server: `<name>_evals` (a name that already
    says "eval" is kept). Raises UsageError for a URL without a database name."""
    from sqlalchemy import make_url

    from app.config import normalize_database_url

    url = make_url(normalize_database_url(database_url))
    if not url.database:
        raise UsageError("DATABASE_URL has no database name")
    if "eval" in url.database:
        return url.render_as_string(hide_password=False)
    return url.set(database=url.database + EVAL_DATABASE_SUFFIX).render_as_string(
        hide_password=False
    )


def spending_ceiling_cents(cases: int, profile: Profile, *, judge_cap_cents: float) -> int:
    """Sessions at their budget cap plus the judge's cap (the real cost is usually lower; a
    session can overshoot its cap by one model request per thread)."""
    estimate = checks.COST_ESTIMATES[profile]
    return cases * estimate.session_budget_cents + math.ceil(judge_cap_cents)


def confirm(message: str, *, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise UsageError("no terminal to confirm the spending: pass --yes")
    answer = input(f"{message} Continue? [y/N] ")
    return answer.strip().lower() in {"y", "yes", "s", "si"}


# --- git sha and results files ------------------------------------------------------------------


def current_git_sha(settings: Settings | None = None) -> str | None:
    """The backend's sha (`sessions.backend_git_sha`: GIT_SHA / RAILWAY_GIT_COMMIT_SHA, else
    `git rev-parse`), falling back to `git rev-parse HEAD` in the repository."""
    if settings is not None:
        try:
            from app.sessions import backend_git_sha

            sha = backend_git_sha(settings)
            if sha:
                return sha
        except Exception:  # not implemented yet, or no git: try git directly
            pass
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def results_path(results_dir: Path, *, date: dt.date, git_sha: str | None) -> Path:
    """evals/results/<date>-<sha>.json (first 12 hex digits; `nogit` without git), with a
    `-2`, `-3`... suffix when the name is taken, so no run overwrites another."""
    stem = f"{date.isoformat()}-{(git_sha or 'nogit')[:12]}"
    candidate = results_dir / f"{stem}.json"
    counter = 2
    while candidate.exists():
        candidate = results_dir / f"{stem}-{counter}.json"
        counter += 1
    return candidate


def write_results(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --- one plan -----------------------------------------------------------------------------------


TERMINAL_FOR_EVALS = frozenset({"ready", "failed", "blocked", "interrupted", "budget_paused"})
"""`budget_paused` ends the eval of a plan: "Continua" would spend more than the profile's
budget, which is part of what the eval measures."""


async def load_plan(
    session_factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID
) -> PlanRecord | None:
    from app.db import PlanRecord

    async with session_factory() as db:
        return await db.get(PlanRecord, plan_id)


async def wait_for_terminal(
    session_factory: async_sessionmaker[AsyncSession],
    plan_id: uuid.UUID,
    *,
    timeout_seconds: float,
    poll_seconds: float = POLL_SECONDS,
) -> PlanRecord | None:
    """The plan row once its status is in `TERMINAL_FOR_EVALS`; None on timeout."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        record = await load_plan(session_factory, plan_id)
        if record is not None and record.status in TERMINAL_FOR_EVALS:
            return record
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(poll_seconds)


def usage_json(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    names = (
        "list_cost_cents",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "web_search_requests",
        "active_seconds",
    )
    return {name: getattr(usage, name, None) for name in names}


@dataclass(slots=True)
class RunContext:
    """What every plan of a run shares."""

    planner: PlannerServices
    profile: Profile
    today: dt.date
    timeout_seconds: float
    judge_client: judge.JudgeClient | None
    judge_budget: judge.JudgeBudget
    rubric: str
    poll_seconds: float = POLL_SECONDS
    interrupt_grace_seconds: float = INTERRUPT_GRACE_SECONDS


def build_entry(
    case: EvalCase,
    request: PlanRequest,
    *,
    record: Mapping[str, Any] | None,
    usage: Any,
    profile: Profile,
    judge_result: judge.JudgeResult,
    extra: Mapping[str, Any],
    link_checker: checks.LinkChecker | None = None,
    trip_schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One request's results entry: run data, checks and judge. `record` holds the `plans`
    row fields this needs (status, plan, trip, cost_cents, submit_attempts, ...)."""
    row = dict(record or {})
    list_cost = getattr(usage, "list_cost_cents", None) if usage is not None else None
    cost = list_cost if list_cost is not None else row.get("cost_cents") or None
    cost_source = (
        "session_usage" if list_cost is not None else ("plans.cost_cents" if cost else None)
    )
    searches = getattr(usage, "web_search_requests", None) if usage is not None else None
    plan = row.get("plan")
    trip = row.get("trip")
    metadata = checks.RunMetadata(
        profile=profile,
        status=row.get("status"),
        submit_attempts=row.get("submit_attempts"),
        cost_cents=cost,
        web_search_requests=searches,
    )
    results = checks.run_checks(
        request,
        plan,
        trip,
        metadata,
        expect=case.expectations,
        link_checker=link_checker,
        trip_schema=trip_schema,
    )
    warnings = plan.get("warnings") if isinstance(plan, Mapping) else None
    return {
        "id": case.id,
        "title": case.title,
        "tags": list(case.tags),
        "request": request.model_dump(mode="json", exclude_none=True),
        "expect": dict(case.expect),
        "plan_id": row.get("id"),
        "session_id": row.get("session_id"),
        "status": row.get("status"),
        "failure_reason": row.get("failure_reason"),
        "submit_attempts": row.get("submit_attempts"),
        "cost_cents": cost,
        "cost_source": cost_source,
        "web_search_requests": searches,
        "usage": usage_json(usage),
        "checks": [result.to_json() for result in results],
        "checks_passed": not checks.blocking_failures(results),
        "blocking_failures": [result.name for result in checks.blocking_failures(results)],
        "warnings_count": len(warnings) if isinstance(warnings, list) else None,
        "judge": judge_result.to_json(),
        "agent_versions": row.get("agent_versions"),
        "plan": plan,
        "trip": trip,
        **extra,
    }


def record_fields(record: PlanRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "id": str(record.id),
        "session_id": record.session_id,
        "status": record.status,
        "failure_reason": record.failure_reason,
        "submit_attempts": record.submit_attempts,
        "cost_cents": record.cost_cents,
        "plan": record.plan,
        "trip": record.trip,
        "agent_versions": record.agent_versions,
    }


async def run_case(case: EvalCase, request: PlanRequest, ctx: RunContext) -> dict[str, Any]:
    """Start one plan, wait for it, collect, check and judge it."""
    from app import sessions
    from app.auth import CurrentUser

    planner = ctx.planner
    user = CurrentUser(email=planner.settings.local_user_email or EVAL_USER_EMAIL)
    started = time.monotonic()
    extra: dict[str, Any] = {"timed_out": False, "error": None}
    record: PlanRecord | None = None
    plan_id: uuid.UUID | None = None
    print(f"[{case.id}] starting", flush=True)
    try:
        plan_id = await sessions.start_plan(request, user, services=planner)
        extra["plan_id"] = str(plan_id)
        record = await wait_for_terminal(
            planner.session_factory,
            plan_id,
            timeout_seconds=ctx.timeout_seconds,
            poll_seconds=ctx.poll_seconds,
        )
        if record is None:
            extra["timed_out"] = True
            print(f"[{case.id}] timed out: interrupting", flush=True)
            await sessions.interrupt_plan(plan_id, user, services=planner)
            record = await wait_for_terminal(
                planner.session_factory,
                plan_id,
                timeout_seconds=ctx.interrupt_grace_seconds,
                poll_seconds=ctx.poll_seconds,
            ) or await load_plan(planner.session_factory, plan_id)
    except asyncio.CancelledError:
        if plan_id is not None:  # Ctrl-C: stop spending on this plan, then propagate
            try:
                async with asyncio.timeout(30):
                    await sessions.interrupt_plan(plan_id, user, services=planner)
            except Exception as error:
                print(f"[{case.id}] interrupt failed: {error}", file=sys.stderr, flush=True)
        raise
    except Exception as error:  # start refused or failed: record it, go on with the others
        extra["error"] = f"{type(error).__name__}: {error}"
        if plan_id is not None:
            record = await load_plan(planner.session_factory, plan_id)
    usage = None
    if record is not None and record.session_id and planner.client is not None:
        try:
            info = await planner.client.retrieve_session(record.session_id)
            usage = info.usage
        except Exception as error:
            extra["usage_error"] = f"{type(error).__name__}: {error}"
    fields = record_fields(record)
    judge_result = await judge_entry(fields, request, ctx)
    extra["duration_seconds"] = round(time.monotonic() - started, 1)
    entry = build_entry(
        case,
        request,
        record=fields,
        usage=usage,
        profile=ctx.profile,
        judge_result=judge_result,
        extra=extra,
    )
    print(
        f"[{case.id}] {entry['status']}: checks {'ok' if entry['checks_passed'] else 'FAILED'}, "
        f"cost {entry['cost_cents']}¢, judge {judge_result.status}",
        flush=True,
    )
    return entry


async def judge_entry(
    fields: Mapping[str, Any] | None, request: PlanRequest, ctx: RunContext
) -> judge.JudgeResult:
    plan = fields.get("plan") if fields else None
    if ctx.judge_client is None:
        return judge.JudgeResult(status="skipped", error="judge disabled (--no-judge)")
    if not isinstance(plan, Mapping):
        return judge.JudgeResult(status="skipped", error="no accepted plan to judge")
    return await judge.judge_plan(
        ctx.judge_client,
        request=request.model_dump(mode="json", exclude_none=True),
        plan=cast(Mapping[str, Any], plan),
        today=ctx.today,
        budget=ctx.judge_budget,
        rubric=ctx.rubric,
    )


# --- the run ------------------------------------------------------------------------------------


def summarize(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregates of a run (compare.py recomputes what it compares from the entries)."""
    costs = [e["cost_cents"] for e in entries if isinstance(e.get("cost_cents"), int)]
    searches = [
        e["web_search_requests"] for e in entries if isinstance(e.get("web_search_requests"), int)
    ]
    judge_means: dict[str, float | None] = {}
    for criterion in judge.CRITERIA:
        scores = [
            score
            for e in entries
            if isinstance(
                score := ((e.get("judge") or {}).get("scores") or {})
                .get(criterion, {})
                .get("score"),
                int,
            )
        ]
        judge_means[criterion] = round(sum(scores) / len(scores), 3) if scores else None
    return {
        "plans": len(entries),
        "ready": sum(1 for e in entries if e.get("status") == "ready"),
        "valid": sum(1 for e in entries if e.get("status") == "ready" and e.get("checks_passed")),
        "blocking_failures": sum(len(e.get("blocking_failures") or ()) for e in entries),
        "warnings": sum(e.get("warnings_count") or 0 for e in entries),
        "total_cost_cents": sum(costs),
        "mean_cost_cents": round(sum(costs) / len(costs), 2) if costs else None,
        "cost_known": len(costs),
        "total_web_search_requests": sum(searches),
        "judge_means": judge_means,
    }


def results_document(
    *,
    entries: Sequence[Mapping[str, Any]],
    profile: Profile,
    git_sha: str | None,
    started_at: dt.datetime,
    finished_at: dt.datetime,
    dataset: Dataset,
    selected: Sequence[EvalCase],
    tags: Sequence[str],
    agent_versions: Mapping[str, Any] | None,
    judge_budget: judge.JudgeBudget,
    judge_enabled: bool,
    aborted: bool,
) -> dict[str, Any]:
    estimate = checks.COST_ESTIMATES[profile]
    return {
        "kind": RESULTS_KIND,
        "format": RESULTS_FORMAT,
        "date": started_at.date().isoformat(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "git_sha": git_sha,
        "profile": profile,
        "aborted": aborted,
        "dataset": {
            "version": dataset.version,
            "valid_until": dataset.valid_until.isoformat(),
            "selected": [case.id for case in selected],
            "tags": list(tags),
        },
        "estimate": {
            "cost_cents": estimate.cost_cents,
            "web_search_requests": estimate.web_search_requests,
            "session_budget_cents": estimate.session_budget_cents,
        },
        "agent_versions": dict(agent_versions) if agent_versions is not None else None,
        "judge": {
            "enabled": judge_enabled,
            "model": judge.JUDGE_MODEL,
            "cap_cents": judge_budget.cap_cents,
            "spent_cents": round(judge_budget.spent_cents, 4),
            "exhausted": judge_budget.exhausted,
        },
        "requests": list(entries),
        "summary": summarize(entries),
    }


def build_settings(*, profile: Profile, database_url: str, lockfile: Path | None) -> Settings:
    """The eval's Settings: the environment's (and backend/.env's), with the profile, its
    default session budget and lockfile, and the eval database forced."""
    from app.config import DEFAULT_SESSION_BUDGET_CENTS, Settings, default_lockfile_path

    overrides: dict[str, Any] = {
        "agent_profile": profile,
        "session_budget_cents": DEFAULT_SESSION_BUDGET_CENTS[profile],
        "lockfile_path": lockfile or default_lockfile_path(profile),
        "database_url": database_url,
    }
    return Settings(**overrides)


async def prepare_database(url: str) -> None:
    """Create the eval database if missing and migrate it to head (Alembic)."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import Connection, make_url, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    target = make_url(url)
    admin = create_async_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if not exists:
                quoted = conn.dialect.identifier_preparer.quote(str(target.database))
                await conn.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        await admin.dispose()

    def upgrade(connection: Connection) -> None:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(upgrade)
    finally:
        await engine.dispose()


async def run_eval(
    selected: Sequence[EvalCase],
    requests: Mapping[str, PlanRequest],
    *,
    settings: Settings,
    profile: Profile,
    args: argparse.Namespace,
    entries: list[dict[str, Any]],
    judge_budget: judge.JudgeBudget,
    state: dict[str, Any],
) -> int:
    """Start the planner, run the cases (`args.concurrency` at a time), fill `entries` as
    plans finish (so an abort keeps what is done)."""
    import httpx

    from app import sessions
    from app.db import create_engine, create_session_factory

    engine = create_engine(settings)
    http = httpx.AsyncClient(follow_redirects=False)
    planner: PlannerServices | None = None
    judge_client: judge.JudgeClient | None = None
    try:
        planner = await sessions.start_planner(
            settings, session_factory=create_session_factory(engine), http=http, resume=False
        )
        try:
            ready = planner.require_ready()
        except sessions.PlannerUnavailableError as error:
            print("The planner cannot start plans: " + "; ".join(error.reasons), file=sys.stderr)
            return EXIT_PLANNER_UNAVAILABLE
        try:
            state["agent_versions"] = ready.roster.agent_versions(
                git_sha=state.get("git_sha"), trip_schema_sha256=None
            )
        except Exception as error:  # informational: every plan row keeps its own copy
            print(f"agent versions unavailable: {error!r}", file=sys.stderr)
        if not args.no_judge and settings.anthropic_credentials_available:
            judge_client = judge.make_client(settings)
        ctx = RunContext(
            planner=planner,
            profile=profile,
            today=state["today"],
            timeout_seconds=args.timeout_minutes * 60,
            judge_client=judge_client,
            judge_budget=judge_budget,
            rubric=judge.load_rubric(),
        )
        semaphore = asyncio.Semaphore(max(args.concurrency, 1))

        async def guarded(case: EvalCase) -> None:
            async with semaphore:
                entries.append(await run_case(case, requests[case.id], ctx))

        await asyncio.gather(*(guarded(case) for case in selected))
        return EXIT_OK
    finally:
        close = getattr(judge_client, "close", None)
        if close is not None:
            await close()
        if planner is not None:
            await sessions.stop_planner(planner)
        await http.aclose()
        await engine.dispose()


@dataclass(slots=True)
class Prepared:
    """Everything decided before the first cent is spent."""

    dataset: Dataset
    selected: list[EvalCase]
    requests: dict[str, PlanRequest]
    profile: Profile
    settings: Settings
    database_url: str
    judge_cap_cents: float


def prepare(args: argparse.Namespace) -> Prepared | None:
    """Validate the selection and the configuration, print the ceiling and confirm. None for a
    dry run (or a "no" at the prompt): nothing is spent."""
    if args.judge_cap_cents > judge.JUDGE_CAP_CENTS or args.judge_cap_cents < 0:
        raise UsageError(f"the judge cap is at most {judge.JUDGE_CAP_CENTS:.0f}¢ (spec: 1 $)")
    dataset = load_dataset()
    selected = select_cases(dataset.cases, tags=args.tags, ids=args.ids)
    requests = validate_requests(selected)
    judge_cap = 0.0 if args.no_judge else float(args.judge_cap_cents)
    if args.dry_run:
        profile = resolve_profile(args.profile, None)
        ceiling = spending_ceiling_cents(len(selected), profile, judge_cap_cents=judge_cap)
        print(f"{len(selected)} request(s), profile {profile}, ceiling {ceiling / 100:.2f} $:")
        for case in selected:
            print(f"  {case.id:28} {', '.join(case.tags)}")
        return None

    from pydantic import ValidationError

    from app.config import Settings

    explicit_url = args.database_url or os.environ.get(EVAL_DATABASE_URL_ENV)
    overrides: dict[str, Any] = {"database_url": explicit_url} if explicit_url else {}
    try:  # the environment and backend/.env, as the backend reads them
        base = Settings(**overrides)
    except ValidationError as error:
        raise UsageError(f"backend settings are invalid: {error}") from error
    profile = resolve_profile(args.profile, base.agent_profile)
    database_url = eval_database_url(base.database_url.get_secret_value())
    try:
        settings = build_settings(
            profile=profile, database_url=database_url, lockfile=args.lockfile
        )
    except ValidationError as error:
        raise UsageError(f"eval settings are invalid: {error}") from error
    if not settings.anthropic_credentials_available:
        raise UsageError(
            "no Anthropic credentials: set ANTHROPIC_API_KEY (backend/.env), or in development "
            "the Workload Identity Federation variables (ANTHROPIC_FEDERATION_RULE_ID, "
            "ANTHROPIC_ORGANIZATION_ID, ANTHROPIC_IDENTITY_TOKEN_FILE): evals need real credentials"
        )
    ceiling = spending_ceiling_cents(len(selected), profile, judge_cap_cents=judge_cap)
    message = (
        f"evals: {len(selected)} real session(s) on the {profile} profile, at most "
        f"{checks.COST_ESTIMATES[profile].session_budget_cents}¢ each plus "
        f"{judge_cap:.0f}¢ for the judge: up to {ceiling / 100:.2f} $."
    )
    print(message)
    if not confirm(message, yes=args.yes):
        print("Nothing started.")
        return None
    return Prepared(
        dataset=dataset,
        selected=selected,
        requests=requests,
        profile=profile,
        settings=settings,
        database_url=database_url,
        judge_cap_cents=judge_cap,
    )


async def execute(prepared: Prepared, args: argparse.Namespace) -> int:
    """Migrate the eval database, run the plans, write the results file."""
    from app import clock

    await prepare_database(prepared.database_url)
    started_at = clock.now()
    state: dict[str, Any] = {
        "today": started_at.date(),
        "git_sha": current_git_sha(prepared.settings),
    }
    entries: list[dict[str, Any]] = []
    budget = judge.JudgeBudget(cap_cents=prepared.judge_cap_cents)
    aborted = False
    try:
        code = await run_eval(
            prepared.selected,
            prepared.requests,
            settings=prepared.settings,
            profile=prepared.profile,
            args=args,
            entries=entries,
            judge_budget=budget,
            state=state,
        )
    except asyncio.CancelledError:  # Ctrl-C: plans in flight were interrupted by run_case
        aborted = True
        code = EXIT_ABORTED
    if code == EXIT_PLANNER_UNAVAILABLE:
        return code
    order = {case.id: index for index, case in enumerate(prepared.selected)}
    entries.sort(key=lambda entry: order.get(entry["id"], len(order)))
    document = results_document(
        entries=entries,
        profile=prepared.profile,
        git_sha=state.get("git_sha"),
        started_at=started_at,
        finished_at=clock.now(),
        dataset=prepared.dataset,
        selected=prepared.selected,
        tags=args.tags,
        agent_versions=state.get("agent_versions"),
        judge_budget=budget,
        judge_enabled=not args.no_judge,
        aborted=aborted,
    )
    path = args.output or results_path(
        RESULTS_DIR, date=started_at.date(), git_sha=state.get("git_sha")
    )
    write_results(path, document)
    summary = document["summary"]
    print(
        f"Results: {path}\n"
        f"  {summary['valid']}/{summary['plans']} valid plans, "
        f"{summary['blocking_failures']} blocking check failure(s), "
        f"sessions {summary['total_cost_cents']}¢, judge {budget.spent_cents:.1f}¢\n"
        f"Next: uv run python ../evals/compare.py {path}"
    )
    return code


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        prepared = prepare(args)
        if prepared is None:
            return EXIT_OK
        return asyncio.run(execute(prepared, args))
    except UsageError as error:
        print(f"evals/run.py: {error}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        return EXIT_ABORTED


if __name__ == "__main__":
    raise SystemExit(main())
