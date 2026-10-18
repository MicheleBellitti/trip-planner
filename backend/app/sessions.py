"""Plan lifecycle: create a session with its budget, interrupt it, continue it, resume it.

Spec: "Backend FastAPI" (`sessions.py  # create session, budget, interrupt`; POST /plans "crea
la sessione con budget, avvia il consumer, manda il primo user.message"; POST
/plans/{id}/interrupt; consumer step 6, resume at process start), "Costi e controlli di spesa"
(per-session budget, monthly limit `MONTHLY_LIMIT_CENTS`), "Interfaccia e design" (state
`budget_paused`: "Continua con 2 $ in piu'"), "Eval strutturate" (`plans.agent_versions`), and
"Sicurezza e privacy" (agents only get cities, dates, travellers' count and ages, budget).

This module also builds the process-wide services (`start_planner` / `stop_planner`), which
main.py's lifespan calls, so the wiring lives next to the code that needs it.

Money: every `*_cents` here is US cents of Managed Agents list cost (SESSION_BUDGET_CENTS,
MONTHLY_LIMIT_CENTS, `plans.cost_cents`), never euro.

Local demo (DEMO_MODE, development only, for UI work): `start_planner` drives the plans with
`tests.fakes.demo.DemoManagedAgentsClient`, which replays the scripted sessions of
backend/tests/fixtures/ma at their recorded pace (DEMO_PACE) under `DEMO_SESSION_PREFIX`
session ids, with `demo_roster()` and the vendored trip.json: no key, lockfile, network or cost.
`start_plan(demo_scenario=...)` picks the scenario (POST /plans?demo_scenario=). The lifecycle
is otherwise the real one: "Continua" and "Interrompi" go through the same code.

Logs: the functions that work for one plan bind `plan_id` (and `session_id` once known) in
`structlog.contextvars`, so every line written on the plan's behalf carries them, the tasks
they create included.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import functools
import json
import re
import subprocess
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app import clock, quota
from app import consumer as consumer_api
from app.auth import SessionVerifier, user_is_admin
from app.config import BACKEND_DIR
from app.consumer import (
    ConsumerDeps,
    ConsumerRegistry,
    EventSink,
    PlanNotFoundError,
    PlanUpdate,
    StatusChange,
    backend_event,
    backend_event_id,
    record_session_cost,
    set_plan_status,
)
from app.db import PlanRecord, PlanStatus
from app.events import AgentName, EventKind
from app.fx import FxConverter
from app.hub import PlanHub
from app.lockfile import LockfileError, Roster, load_roster
from app.ma_client import AgentPin, ManagedAgentsError, SdkManagedAgentsClient, archive_when_idle
from app.triptracker_schema import DEV_FALLBACK_SCHEMA_PATH, TripSchemaStore

if TYPE_CHECKING:
    import httpx
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.auth import CurrentUser
    from app.config import AgentProfile, Settings
    from app.ma_client import ManagedAgentsClient
    from app.request import PlanRequest

log = structlog.get_logger(__name__)

CONTINUE_INCREMENT_CENTS = 200
""""Continua con 2 $ in piu'": the budget grows by $2 over what was consumed."""

CONTINUE_RESUME_WAIT_SECONDS = 5.0
"""After raising the budget, how long to wait for the session to resume by itself before
sending `CONTINUE_MESSAGE` [INFERRED, probe P9]."""

CONTINUE_MESSAGE = (
    "The session budget was raised. Continue the work from where it stopped and call "
    "submit_plan when the plan is complete."
)

SEND_MESSAGE_ATTEMPTS = 5
"""Attempts for the first `user.message` (sent with SDK retries off, see ma_client)."""

SHUTDOWN_CLEANUP_GRACE_SECONDS = 10.0
"""How long `stop_planner` lets in-flight session cleanups (`_stop_abandoned_session`) finish
before it cancels the background tasks: a plan already `failed` is never resumed, so a
cleanup cut short would leave its session running unwatched."""

TITLE_PLAN_CREATED = "Piano avviato"
TITLE_INTERRUPT_REQUESTED = "Interruzione richiesta"
TITLE_INTERRUPTED = "Piano interrotto"
TITLE_CONTINUED = "Budget aumentato: si riprende"
REASON_SESSION_START_FAILED = "Non sono riuscito ad avviare la sessione degli agenti."
REASON_NO_SESSION = "La sessione degli agenti non era stata creata: il piano non può riprendere."
REASON_INTERRUPTED = "Interrotto da te."
TITLE_START_FAILED = "Avvio non riuscito"
TITLE_PLAN_FAILED = "Piano non riuscito"

APP_METADATA = "trip-planner"
"""`metadata["app"]` of every session this backend creates (the nightly orphan sweep's filter)."""

DEMO_SESSION_PREFIX = "sesn_demo_"
"""Session ids of the local demo (DEMO_MODE, `tests/fakes/demo.py`). Such a session exists
only inside the process that created it: a demo plan still `running` at the next start is
closed, never resumed (`resume_running_plans`)."""
DEMO_SCENARIO_METADATA = "demo_scenario"
"""Session metadata key that tells the demo client which scenario to play (demo mode only)."""
DEFAULT_DEMO_SCENARIO = "happy_path"
DEMO_ENVIRONMENT_ID = "env_demo"
REASON_DEMO_ENDED = "Demo interrotta: il server è stato riavviato."
TITLE_DEMO_ENDED = "Demo interrotta"

BRIEF_REQUEST_PATH = "/workspace/shared/request.json"
BRIEF_TIMEZONE = "Europe/Rome"

GIT_TIMEOUT_SECONDS = 2.0
_GIT_SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


# --- errors -------------------------------------------------------------------------------------


class PlannerUnavailableError(Exception):
    """The planner can't start plans: no API key, no usable lockfile, or no trip.json schema.
    `reasons` are English lines for the logs; routes answer 503 with an Italian message."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class MonthlyLimitReachedError(Exception):
    """POST /plans or "Continua" refused: this month's spend is at the limit."""

    def __init__(self, spent_cents: int, limit_cents: int) -> None:
        super().__init__(f"monthly spend {spent_cents} >= limit {limit_cents} (US cents)")
        self.spent_cents = spent_cents
        self.limit_cents = limit_cents


class UserGoneError(Exception):
    """POST /plans refused: the signed-in user's `users` row no longer exists (the account was
    deleted while a verified session was still cached, `auth.SessionCache`), so the
    `plans.user_id` foreign key refused the insert. Routes answer 401 `not_authenticated`."""


PLANS_USER_FK = "fk_plans_user_id_users"
"""The `plans.user_id` -> `users.id` foreign key (db.NAMING_CONVENTION, migration 600fbb922f91)."""

_FOREIGN_KEY_VIOLATION = "23503"


def is_plans_user_fk_violation(exc: IntegrityError) -> bool:
    """True only when `exc` is Postgres refusing `plans.user_id` because the user is gone; any
    other integrity error (another key, a check, a duplicate) is not this one."""
    orig = exc.orig
    if getattr(orig, "sqlstate", None) != _FOREIGN_KEY_VIOLATION:
        return False
    # SQLAlchemy's asyncpg adapter raises its own error from asyncpg's, which names the constraint.
    return getattr(getattr(orig, "__cause__", None), "constraint_name", None) == PLANS_USER_FK


class PlanStateError(Exception):
    """The plan is not in a status that allows the operation (e.g. interrupt a ready plan)."""

    def __init__(
        self, plan_id: uuid.UUID, status: PlanStatus, allowed: tuple[PlanStatus, ...]
    ) -> None:
        super().__init__(f"plan {plan_id} is {status}, expected one of {allowed}")
        self.plan_id = plan_id
        self.status = status
        self.allowed = allowed


# --- services ---------------------------------------------------------------------------------


@dataclass(slots=True)
class PlanLocks:
    """Per-plan `asyncio.Lock`s that serialize the user's lifecycle requests on one plan
    ("Continua", interrupt) across their API calls. The compare-and-set of `set_plan_status`
    alone comes too late: "Continua" raises the session's budget BEFORE it moves the plan back
    to `running`, so two concurrent requests (a double click, two tabs, or an interrupt racing
    a "Continua") would each change the session first and only then find out they lost. The
    spec runs one process, so an in-process lock is enough (during a redeploy's brief overlap
    each process has its own locks, and the compare-and-set of `set_plan_status` still refuses
    the request that lost). A lock is dropped as soon as no request holds or waits for it."""

    _locks: dict[uuid.UUID, asyncio.Lock] = field(default_factory=dict[uuid.UUID, asyncio.Lock])
    _users: dict[uuid.UUID, int] = field(default_factory=dict[uuid.UUID, int])

    @contextlib.asynccontextmanager
    async def hold(self, plan_id: uuid.UUID) -> AsyncIterator[None]:
        """Hold `plan_id`'s lock for the block (waiting for the request before it)."""
        lock = self._locks.setdefault(plan_id, asyncio.Lock())
        self._users[plan_id] = self._users.get(plan_id, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self._users[plan_id] -= 1
            if self._users[plan_id] == 0:
                del self._users[plan_id]
                del self._locks[plan_id]

    def __len__(self) -> int:
        return len(self._locks)


@dataclass(frozen=True, slots=True)
class ReadyPlanner:
    """The parts that must exist to run plans (see `PlannerServices.require_ready`)."""

    client: ManagedAgentsClient
    roster: Roster
    registry: ConsumerRegistry
    deps: ConsumerDeps


@dataclass(slots=True)
class PlannerServices:
    """Everything the process shares, built by `start_planner` and kept on `app.state.planner`
    (main.py also exposes `hub` and `session_verifier` on `app.state` for auth and SSE)."""

    settings: Settings
    http: httpx.AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    hub: PlanHub
    trip_schema: TripSchemaStore
    fx: FxConverter
    session_verifier: SessionVerifier
    client: ManagedAgentsClient | None
    """None without Anthropic credentials (an API key, or federation in development); tests use
    the fake, local runs without a key get None."""
    roster: Roster | None
    """None when the lockfile is missing or doesn't resolve AGENT_PROFILE."""
    registry: ConsumerRegistry | None
    """None when `client` is None."""
    unavailable_reasons: list[str] = field(default_factory=list[str])
    background_tasks: list[asyncio.Task[None]] = field(default_factory=list[asyncio.Task[None]])
    """Periodic tasks tied to the planner's life (main.py adds jobs.start_stuck_plan_checker);
    cancelled by `stop_planner`."""
    plan_locks: PlanLocks = field(default_factory=PlanLocks)
    """Serializes `continue_plan` and `interrupt_plan` per plan (`PlanLocks`)."""
    cleanup_tasks: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])
    """The `background_tasks` that stop a session nobody follows: `stop_planner` gives them
    `SHUTDOWN_CLEANUP_GRACE_SECONDS` before cancelling."""
    demo_scenarios: tuple[str, ...] = ()
    """DEMO_MODE only: the scenario names POST /plans?demo_scenario= accepts (empty otherwise)."""

    def require_ready(self) -> ReadyPlanner:
        """The ready parts, or `PlannerUnavailableError` listing what is missing."""
        client, roster, registry = self.client, self.roster, self.registry
        if client is None or roster is None or registry is None:
            reasons = list(self.unavailable_reasons)
            if not reasons:
                if client is None:
                    reasons.append("no Managed Agents client (ANTHROPIC_API_KEY unset)")
                if roster is None:
                    reasons.append("no agent roster (lockfile not loaded)")
                if client is not None and registry is None:
                    reasons.append("no consumer registry")
            raise PlannerUnavailableError(reasons)
        return ReadyPlanner(client=client, roster=roster, registry=registry, deps=registry.deps)


async def start_planner(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    client: ManagedAgentsClient | None = None,
    resume: bool = True,
    fx_offline: bool = False,
) -> PlannerServices:
    """Build every service for the process, in this order: `PlanHub`, `SessionVerifier`,
    `TripSchemaStore.load()`, `FxConverter`, the Managed Agents client (`client` if given,
    else `SdkManagedAgentsClient.from_settings` when a key is set), `lockfile.load_roster`
    (a `LockfileError` is logged and recorded in `unavailable_reasons`), `ConsumerDeps` and
    `ConsumerRegistry`; then `resume_running_plans` (when `resume` and ready).

    The hourly stuck-plan checker is NOT started here (jobs imports sessions, so sessions must
    not import jobs): main.py's lifespan appends `jobs.start_stuck_plan_checker(services)` to
    `services.background_tasks`, which `stop_planner` cancels.

    Never raises for a missing key, lockfile or schema: /health must stay up, and POST /plans
    answers 503 instead. Raises only for programming errors.

    `fx_offline=True` builds the `FxConverter` in offline mode (cache only): `app.cli replay`.
    When trip.json could not be loaded (production without TripTracker), a background task
    retries it (`TripSchemaStore.retry_until_loaded`), cancelled by `stop_planner`.

    DEMO_MODE (development only): the client is `tests.fakes.demo.DemoManagedAgentsClient`
    (imported lazily, like `app.cli replay` imports the fake; `client`, when given, wins), the
    roster is `demo_roster()` (no lockfile), trip.json is the vendored copy
    (`DEV_FALLBACK_SCHEMA_PATH`) and FX is offline: no key, no network, no cost.
    """
    demo = settings.demo_mode
    hub = PlanHub()
    session_verifier = SessionVerifier(settings, http)
    schema_settings = (
        settings.model_copy(update={"trip_schema_url": DEV_FALLBACK_SCHEMA_PATH.as_uri()})
        if demo
        else settings
    )
    trip_schema = TripSchemaStore(schema_settings, http)
    await trip_schema.load()
    fx = FxConverter(session_factory=session_factory, http=http, offline=fx_offline or demo)

    reasons: list[str] = []
    scenarios: tuple[str, ...] = ()
    if demo:
        try:
            from tests.fakes.demo import DemoManagedAgentsClient, demo_scenarios
        except ImportError as exc:
            reasons.append(f"DEMO_MODE needs backend/tests/fakes (run from backend/): {exc}")
        else:
            scenarios = demo_scenarios()
            if client is None:
                client = DemoManagedAgentsClient(pace=settings.demo_pace)
    elif client is None:
        if not settings.anthropic_credentials_available:
            reasons.append("ANTHROPIC_API_KEY is not set")
        else:
            try:
                client = SdkManagedAgentsClient.from_settings(settings)
            except ValueError as exc:
                reasons.append(f"cannot build the Managed Agents client: {exc}")

    roster: Roster | None = None
    if demo:
        roster = demo_roster(settings.agent_profile)
    else:
        try:
            roster = load_roster(settings)
        except LockfileError as exc:
            reasons.append(str(exc))
            log.error("lockfile_unavailable", reason=str(exc), agent_profile=settings.agent_profile)

    registry: ConsumerRegistry | None = None
    if client is not None:
        deps = ConsumerDeps(
            settings=settings,
            session_factory=session_factory,
            client=client,
            hub=hub,
            trip_schema=trip_schema,
            fx=fx,
            now=clock.now,
        )
        registry = ConsumerRegistry(deps)

    services = PlannerServices(
        settings=settings,
        http=http,
        session_factory=session_factory,
        hub=hub,
        trip_schema=trip_schema,
        fx=fx,
        session_verifier=session_verifier,
        client=client,
        roster=roster,
        registry=registry,
        unavailable_reasons=reasons,
        demo_scenarios=scenarios,
    )
    if trip_schema.current() is None:
        services.background_tasks.append(
            asyncio.create_task(_retry_trip_schema(trip_schema), name="trip-schema-retry")
        )
    if reasons:
        log.warning("planner_unavailable", reasons=reasons, agent_profile=settings.agent_profile)
    else:
        log.info(
            "planner_ready",
            agent_profile=settings.agent_profile,
            lockfile_sha256=roster.lockfile_sha256 if roster else None,
            demo_mode=demo,
        )
    if resume:
        try:
            await resume_running_plans(services)
        except Exception:  # startup must survive: the plans stay running for the next start
            log.exception("resume_running_plans_failed")
    return services


async def _retry_trip_schema(store: TripSchemaStore) -> None:
    await store.retry_until_loaded()


def demo_roster(profile: AgentProfile) -> Roster:
    """The synthetic roster of DEMO_MODE: made-up agent ids at version 1, `DEMO_ENVIRONMENT_ID`,
    no skills and no lockfile (`lockfile_sha256` "demo"), so `plans.agent_versions` of a demo
    plan never looks like a real run's."""
    pins = {name: AgentPin(id=f"agent_demo_{name.value}", version=1) for name in AgentName}
    return Roster(
        profile=profile,
        coordinator=pins[AgentName.COORDINATOR],
        subagents={name: pin for name, pin in pins.items() if name is not AgentName.COORDINATOR},
        environment_id=DEMO_ENVIRONMENT_ID,
        skills={},
        lockfile_path=BACKEND_DIR / "demo",
        lockfile_sha256="demo",
        workspace_id=None,
    )


async def stop_planner(services: PlannerServices) -> None:
    """Shutdown: let in-flight session cleanups finish (at most
    `SHUTDOWN_CLEANUP_GRACE_SECONDS`), cancel the background tasks, `registry.aclose()` (plans
    stay `running`, the next process resumes them), `client.aclose()`. The shared httpx client
    and the DB engine belong to main.py and are closed there."""
    cleanups = [task for task in services.cleanup_tasks if not task.done()]
    if cleanups:
        await asyncio.wait(cleanups, timeout=SHUTDOWN_CLEANUP_GRACE_SECONDS)
    tasks = list(services.background_tasks)
    services.background_tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    if services.registry is not None:
        try:
            await services.registry.aclose()
        except Exception:
            log.exception("consumer_registry_close_failed")
    if services.client is not None:
        try:
            await services.client.aclose()
        except Exception:
            log.exception("managed_agents_client_close_failed")


# --- the lifecycle ------------------------------------------------------------------------------


async def start_plan(
    request: PlanRequest,
    user: CurrentUser,
    *,
    services: PlannerServices,
    demo_scenario: str | None = None,
    user_quota_applies: bool = True,
) -> uuid.UUID:
    """POST /plans: create a plan and start its session. Returns the new plan id.

    1. `services.require_ready()` and `await services.trip_schema.require()`: nothing is spent
       when the plan could never be validated (`PlannerUnavailableError`,
       `TripSchemaUnavailableError`).
    2. The economics (app/quota.py), in one transaction holding the quota lock
       (`quota.lock_checks`), with the insert of step 3, so two requests never both pass:
       the user's monthly quota unless they are an admin or `user_quota_applies` is False
       (`QuotaReachedError`: plans, or cents counting this plan's budget), the global ceiling
       with the running plans' unspent budgets reserved and this plan's budget included
       (`MonthlyLimitReachedError`), the cap on running plans (`PlannerBusyError`). Nothing is
       spent on a refusal.
    3. Insert the `plans` row: `user_email`, `user_id` (the web app's own `users.id`, only
       with `Settings.plans_carry_user_id`), `agent_profile`, status `running` (`running_since`
       defaults to `now()`), `request` (`request.model_dump(mode="json")`), `agent_versions`
       (`roster.agent_versions(git_sha=backend_git_sha(settings), trip_schema_sha256=...)`);
       then emit the `TITLE_PLAN_CREATED` status event.
    4. `client.create_session(agent=roster.coordinator, environment_id=roster.environment_id,
       budget_cents=settings.session_budget_cents, metadata=session_metadata(...),
       title=f"plan {plan_id}")`; store `session_id` and `budget_cents` (the cap the UI's cost
       bar is drawn against) in one update. On `ManagedAgentsError` the plan becomes `failed`
       (`REASON_SESSION_START_FAILED`) and the error propagates (routes: 502). A crash between
       `create_session` and that update leaves a session without `session_id` on the row: the
       nightly job's orphan sweep deletes it after the retention (`jobs.nightly_cleanup`).
    5. `registry.start(plan_id, session_id, first_message=build_brief(request, ...))` and
       `await consumer.wait_started()` inside `asyncio.timeout(consumer.START_TIMEOUT_SECONDS)`:
       the stream is open before the first message is sent. A `ManagedAgentsError` there has
       already marked the plan `failed` and propagates (the consumer itself interrupts a
       session whose brief may have been delivered); on timeout the consumer is stopped, the
       plan set `failed` (`REASON_SESSION_START_FAILED`) and TimeoutError propagates (routes:
       502). The brief may already have reached the session (a send that was accepted but
       answered late), and nobody follows that session any more: a background task tied to
       the planner sends `user.interrupt`, archives it once idle and records its final list
       cost in `plans.cost_cents` (`_stop_abandoned_session`), so it neither runs a whole plan
       unwatched nor escapes the monthly limit.

    `user_quota_applies=False` is for the eval runner alone (evals/run.py, a CLI with database
    access): its fixed user runs six plans per run, several runs a month, against a database
    that persists between runs. No route passes it, so nobody reaches it from the web; the
    global ceiling and the running cap still apply.

    DEMO_MODE: `demo_scenario` (default `DEFAULT_DEMO_SCENARIO`) goes into the session metadata
    under `DEMO_SCENARIO_METADATA`, where the demo client reads which scenario to play;
    outside demo mode a `demo_scenario` is a ValueError (the route answers 404 first).

    Logs: `plan_id`, then `session_id`, are bound in `structlog.contextvars` as soon as they
    exist (the consumer task created here inherits them).
    """
    settings = services.settings
    if demo_scenario is not None and not settings.demo_mode:
        msg = "demo_scenario is only accepted in DEMO_MODE"
        raise ValueError(msg)
    ready = services.require_ready()
    schema = await services.trip_schema.require()
    now = ready.deps.now()

    plan_id = uuid.uuid4()
    agent_versions = ready.roster.agent_versions(
        git_sha=backend_git_sha(settings), trip_schema_sha256=schema.sha256
    )
    async with services.session_factory() as db:
        await quota.lock_checks(db)
        await _admit_start(
            db, user, settings=settings, now=now, user_quota_applies=user_quota_applies
        )
        db.add(
            PlanRecord(
                id=plan_id,
                user_email=user.email,
                # Only the web app's own user ids are `users.id` (a foreign key): TripTracker's
                # and the local mode's never go here.
                user_id=user.auth_user_id if settings.plans_carry_user_id else None,
                agent_profile=settings.agent_profile,
                status=PlanStatus.RUNNING.value,
                request=request.model_dump(mode="json"),
                agent_versions=agent_versions,
            )
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            if not is_plans_user_fk_violation(exc):
                raise
            log.warning("plan_refused_user_gone", plan_id=str(plan_id))
            raise UserGoneError from None

    with contextlib.ExitStack() as context:
        context.enter_context(structlog.contextvars.bound_contextvars(plan_id=str(plan_id)))
        metadata = session_metadata(plan_id, settings.agent_profile)
        if settings.demo_mode:
            metadata[DEMO_SCENARIO_METADATA] = demo_scenario or DEFAULT_DEMO_SCENARIO

        def bind_session(session_id: str) -> None:
            context.enter_context(structlog.contextvars.bound_contextvars(session_id=session_id))

        return await _create_and_start(
            request,
            services=services,
            ready=ready,
            plan_id=plan_id,
            metadata=metadata,
            now=now,
            bind_session=bind_session,
        )


async def _admit_start(
    db: AsyncSession,
    user: CurrentUser,
    *,
    settings: Settings,
    now: dt.datetime,
    user_quota_applies: bool = True,
) -> None:
    """Step 2 of `start_plan`, on a connection that holds the quota lock: the user's quota
    (plans, then cents with this plan's budget counted; admins exempt), the global ceiling with
    the running plans' unspent budgets reserved and this plan's budget counted, the running
    cap. Each refusal is logged with its figures, never with the user."""
    budget = settings.session_budget_cents
    if user_quota_applies and not user_is_admin(user, settings):
        mine = await quota.month_usage(
            db,
            now=now,
            owner=plan_owner_filter(user, settings=settings),
            default_budget_cents=budget,
        )
        allowance = quota.user_quota(mine, settings=settings, now=now)
        kind = allowance.exceeded_by(plans=1, cents=budget)
        if kind is not None:
            log.info("quota_reached", kind=kind, **allowance.as_data())
            raise quota.QuotaReachedError(kind, allowance)
    everyone = await quota.month_usage(db, now=now, owner=None, default_budget_cents=budget)
    if everyone.cents + budget > settings.monthly_limit_cents:
        log.warning(
            "monthly_limit_reached",
            spent_cents=everyone.cost_cents,
            reserved_cents=everyone.reserved_cents,
            limit_cents=settings.monthly_limit_cents,
        )
        raise MonthlyLimitReachedError(everyone.cents, settings.monthly_limit_cents)
    running = await quota.running_plans(db)
    if running >= settings.max_running_plans:
        log.warning("planner_busy", running=running, limit=settings.max_running_plans)
        raise quota.PlannerBusyError(running, settings.max_running_plans)


async def _create_and_start(
    request: PlanRequest,
    *,
    services: PlannerServices,
    ready: ReadyPlanner,
    plan_id: uuid.UUID,
    metadata: dict[str, str],
    now: dt.datetime,
    bind_session: Callable[[str], None],
) -> uuid.UUID:
    """Steps 3 (the event) to 5 of `start_plan`, for a plan row already inserted and a plan id
    already bound in the logging context (`bind_session` binds the session id once the session
    exists)."""
    settings = services.settings
    bound = log.bind(plan_id=str(plan_id), agent_profile=settings.agent_profile)
    sink = EventSink(plan_id, session_factory=services.session_factory, hub=services.hub)
    await sink.emit(
        backend_event(EventKind.STATUS, TITLE_PLAN_CREATED, ts=now),
        ma_event_id=backend_event_id(plan_id, "status", "created"),
    )

    budget_cents = settings.session_budget_cents
    try:
        info = await ready.client.create_session(
            agent=ready.roster.coordinator,
            environment_id=ready.roster.environment_id,
            budget_cents=budget_cents,
            metadata=metadata,
            title=f"plan {plan_id}",
        )
    except ManagedAgentsError as exc:
        # The message is the seam's: call, status, error type and request id, never a body.
        bound.error(
            "session_create_failed",
            status_code=exc.status_code,
            error_type=exc.error_type,
            error=str(exc),
        )
        await _mark_start_failed(services, plan_id)
        raise
    session_id = info.id
    if info.budget_cents is not None:
        budget_cents = info.budget_cents
    async with services.session_factory() as db:
        await db.execute(
            update(PlanRecord)
            .where(PlanRecord.id == plan_id)
            .values(session_id=session_id, budget_cents=budget_cents)
        )
        await db.commit()
    bind_session(session_id)
    bound = bound.bind(session_id=session_id)

    brief = build_brief(request, today=now.astimezone(clock.HOME_TIMEZONE).date())
    consumer = ready.registry.start(plan_id, session_id, first_message=brief)
    try:
        async with asyncio.timeout(consumer_api.START_TIMEOUT_SECONDS):
            await consumer.wait_started()
    except TimeoutError:
        bound.error("plan_start_timeout", timeout_seconds=consumer_api.START_TIMEOUT_SECONDS)
        await ready.registry.stop(plan_id)
        await _mark_start_failed(services, plan_id, session_id=session_id)
        raise
    bound.info("plan_started", budget_cents=budget_cents)
    return plan_id


async def _mark_start_failed(
    services: PlannerServices, plan_id: uuid.UUID, *, session_id: str | None = None
) -> None:
    """The plan becomes `failed` (`REASON_SESSION_START_FAILED`). With `session_id` (the
    session exists and may have received the brief, but no consumer follows it) the session is
    also stopped in the background (`_stop_abandoned_session`)."""
    await set_plan_status(
        services.session_factory,
        services.hub,
        plan_id,
        StatusChange(PlanStatus.FAILED, reason=REASON_SESSION_START_FAILED),
        title=TITLE_START_FAILED,
        event_key="start-failed",
    )
    if session_id is not None and services.client is not None:
        _spawn(
            services,
            _stop_abandoned_session(services, services.client, plan_id, session_id),
            name=f"start-cleanup-{plan_id}",
            cleanup=True,
        )


async def _stop_abandoned_session(
    services: PlannerServices, client: ManagedAgentsClient, plan_id: uuid.UUID, session_id: str
) -> None:
    """Best effort, for a session nobody follows: `user.interrupt` (every thread), archive
    once idle, then raise `plans.cost_cents` to its list cost (`record_session_cost`). Failures
    are logged, never raised."""
    bound = log.bind(plan_id=str(plan_id), session_id=session_id)
    try:
        await client.send_interrupt(session_id)
    except ManagedAgentsError as exc:
        bound.warning("interrupt_send_failed", error_type=exc.error_type)
    await _archive_quietly(services, plan_id, session_id)
    sink = EventSink(plan_id, session_factory=services.session_factory, hub=services.hub)
    cost = await record_session_cost(client, sink, session_id)
    bound.info("abandoned_session_stopped", cost_cents=cost)


async def interrupt_plan(
    plan_id: uuid.UUID, user: CurrentUser, *, services: PlannerServices
) -> PlanStatus:
    """POST /plans/{id}/interrupt. Returns the plan's status after the call.

    - `running`: first store `TITLE_INTERRUPT_REQUESTED` with `PlanUpdate(
      interrupt_requested_at=now)` in one transaction (`EventSink.emit`, key
      `backend_event_id(plan_id, "status", f"interrupt-requested:{uuid4()}")`), so the request
      survives a restart; then tell the live consumer (`request_interrupt()`) and send
      `user.interrupt` to every thread; returns `running`. The consumer turns the coming
      `end_turn` into `interrupted` (or `ready` if a plan was already accepted). With no live
      consumer the plan goes straight to `interrupted` and the session is archived.
    - `budget_paused`: nothing runs; the plan becomes `interrupted` (`REASON_INTERRUPTED`,
      `set_plan_status(..., event_key=f"interrupted:{uuid4()}")`) and the session is archived;
      returns `interrupted`.
    - other statuses: `PlanStateError` (routes: 409).
    Raises `PlanNotFoundError` for a plan that doesn't exist or isn't the user's.

    Runs under the plan's lock (`PlannerServices.plan_locks`), so it never interleaves with a
    "Continua" of the same plan: each sees the status the other left.
    """
    with structlog.contextvars.bound_contextvars(plan_id=str(plan_id)):
        async with services.plan_locks.hold(plan_id):
            return await _interrupt_locked(plan_id, user, services=services)


async def _interrupt_locked(
    plan_id: uuid.UUID, user: CurrentUser, *, services: PlannerServices
) -> PlanStatus:
    async with services.session_factory() as db:
        plan = await get_user_plan(db, plan_id, user, settings=services.settings)
    status = PlanStatus(plan.status)
    if status is PlanStatus.RUNNING:
        return await request_interrupt(services, plan, reason=REASON_INTERRUPTED)
    with structlog.contextvars.bound_contextvars(session_id=plan.session_id):
        return await _interrupt_paused(plan, status, services=services)


async def _interrupt_paused(
    plan: PlanRecord, status: PlanStatus, *, services: PlannerServices
) -> PlanStatus:
    """`_interrupt_locked` for a plan that is not `running`."""
    plan_id = plan.id
    if status is PlanStatus.BUDGET_PAUSED:
        result = await set_plan_status(
            services.session_factory,
            services.hub,
            plan_id,
            StatusChange(
                PlanStatus.INTERRUPTED,
                reason=REASON_INTERRUPTED,
                only_from=(PlanStatus.BUDGET_PAUSED,),
            ),
            title=TITLE_INTERRUPTED,
            event_key=f"interrupted:{uuid.uuid4()}",
        )
        if not result.status_applied:
            raise PlanStateError(
                plan_id,
                await _current_status(services, plan_id),
                (PlanStatus.RUNNING, PlanStatus.BUDGET_PAUSED),
            )
        log.info("plan_interrupted", plan_id=str(plan_id), session_id=plan.session_id)
        await _archive_quietly(services, plan_id, plan.session_id)
        return PlanStatus.INTERRUPTED
    raise PlanStateError(plan_id, status, (PlanStatus.RUNNING, PlanStatus.BUDGET_PAUSED))


async def request_interrupt(
    services: PlannerServices,
    plan: PlanRecord,
    *,
    reason: str,
    interrupted_key: str | None = None,
    request_title: str = TITLE_INTERRUPT_REQUESTED,
) -> PlanStatus:
    """The `running` branch of `interrupt_plan`, without the ownership check (also used by
    `jobs.check_stuck_plans`): persist the request with its status event, tell the live
    consumer, send `user.interrupt` (every thread). Without a live consumer the plan goes
    straight to `interrupted` with `reason` (status event key `interrupted_key`, default
    `interrupted:<uuid4>`), the session is archived (best effort) and its final list cost
    recorded (`record_session_cost`: no consumer will read it). `request_title` is the
    title of the request's event (the stuck check says why it stops the plan).
    Returns the plan's status after the call. `ManagedAgentsError` from `send_interrupt`
    propagates when a consumer is live (the request is stored; the user may retry).

    A live consumer may be one that waits for the plan's lease while another process follows
    the plan (a redeploy's overlap): the stored `interrupt_requested_at` reaches the consumer
    that follows it (`PlanConsumer` re-reads it before a status decision)."""
    with structlog.contextvars.bound_contextvars(plan_id=str(plan.id), session_id=plan.session_id):
        return await _request_interrupt(
            services,
            plan,
            reason=reason,
            interrupted_key=interrupted_key,
            request_title=request_title,
        )


async def _request_interrupt(
    services: PlannerServices,
    plan: PlanRecord,
    *,
    reason: str,
    interrupted_key: str | None,
    request_title: str,
) -> PlanStatus:
    plan_id = plan.id
    session_id = plan.session_id
    now = _now(services)
    sink = EventSink(plan_id, session_factory=services.session_factory, hub=services.hub)
    await sink.emit(
        backend_event(EventKind.STATUS, request_title, ts=now),
        ma_event_id=backend_event_id(plan_id, "status", f"interrupt-requested:{uuid.uuid4()}"),
        update=PlanUpdate(interrupt_requested_at=now),
    )
    bound = log.bind(plan_id=str(plan_id), session_id=session_id)
    registry = services.registry
    consumer = registry.get(plan_id) if registry is not None else None
    if consumer is not None and not consumer.done:
        consumer.request_interrupt()
        if services.client is not None and session_id is not None:
            await services.client.send_interrupt(session_id)
        bound.info("plan_interrupt_requested")
        return PlanStatus.RUNNING

    # Nobody follows the session: stop it, then close the plan directly.
    if services.client is not None and session_id is not None:
        try:
            await services.client.send_interrupt(session_id)
        except ManagedAgentsError as exc:
            bound.warning("interrupt_send_failed", error_type=exc.error_type)
    result = await set_plan_status(
        services.session_factory,
        services.hub,
        plan_id,
        StatusChange(PlanStatus.INTERRUPTED, reason=reason),
        title=TITLE_INTERRUPTED,
        event_key=interrupted_key or f"interrupted:{uuid.uuid4()}",
    )
    if not result.status_applied:
        return await _current_status(services, plan_id)
    bound.info("plan_interrupted", live_consumer=False)
    await _archive_quietly(services, plan_id, session_id)
    if services.client is not None and session_id is not None:
        await record_session_cost(services.client, sink, session_id, known_cents=plan.cost_cents)
    return PlanStatus.INTERRUPTED


async def _archive_quietly(
    services: PlannerServices, plan_id: uuid.UUID, session_id: str | None
) -> None:
    """Archive the session once it is idle; failures are logged, never raised."""
    if services.client is None or session_id is None:
        return
    try:
        await archive_when_idle(services.client, session_id)
    except Exception as exc:
        log.warning(
            "session_archive_failed",
            plan_id=str(plan_id),
            session_id=session_id,
            error=type(exc).__name__,
        )


async def _current_status(services: PlannerServices, plan_id: uuid.UUID) -> PlanStatus:
    async with services.session_factory() as db:
        status = await db.scalar(select(PlanRecord.status).where(PlanRecord.id == plan_id))
    if status is None:
        raise PlanNotFoundError(f"plan {plan_id} not found")
    return PlanStatus(status)


def _now(services: PlannerServices) -> dt.datetime:
    registry = services.registry
    return registry.deps.now() if registry is not None else clock.now()


async def continue_plan(
    plan_id: uuid.UUID,
    user: CurrentUser,
    *,
    services: PlannerServices,
    extra_cents: int = CONTINUE_INCREMENT_CENTS,
) -> int:
    """POST /plans/{id}/continue ("Continua con 2 $ in piu'"). Returns the new budget (cents).

    Only from `budget_paused` (else `PlanStateError`), and only below `MAX_CONTINUES_PER_PLAN`
    (`ContinueLimitReachedError`). A consumer of the paused plan still winding down is stopped
    first. Then, per notes §2d (a `budget_reached` session accepts no `user.message`; only a
    budget update lets it go on):

    1. The economics and the reservation (`_reserve_continue`), in one transaction holding the
       quota lock (`quota.lock_checks`) like a start's: the user's monthly cents with the extra
       included unless they are an admin (`QuotaReachedError`), the global ceiling with the
       running plans' budgets reserved and the extra included (`MonthlyLimitReachedError`), the
       running cap (`PlannerBusyError`: the plan is about to run again). The same transaction
       turns the row `running` with `budget_cents = max(cap, cost) + extra_cents`, so every
       later admission counts this plan's extra and its place among the running plans before
       the session is touched; nothing is shown on the timeline yet.
    2. `info = client.retrieve_session(sid)`; consumed = `info.usage.list_cost_cents` (fallback
       `plans.cost_cents`); new budget = `max(cap, consumed) + extra_cents` (the cost may
       overshoot the cap by one request per thread, so base it on consumption), where `cap`
       is `plans.budget_cents` read with the status (`info.budget_cents` when NULL): a request
       that somehow raced another one repeats the same cap and never compounds it.
    3. `client.update_budget(sid, new_budget)` (`budget_not_raised` cannot happen with this
       formula). Any failure of steps 2-3 (an `ApiRejectedError`, a timeout, a cancellation)
       gives the reservation back (`_release_continue`: `budget_paused` and the old cap again)
       and propagates.
    4. `TITLE_CONTINUED`: `set_plan_status(..., budget_cents=new_budget, continues_increment=1,
       event_key=f"continue:{new_budget}")`, which stores the final cap in
       `plans.budget_cents`, counts the "Continua" in `plans.continues` and restarts
       `plans.running_since` (the stuck check's 45 minutes). The key is unique per "Continua"
       because every one raises the budget; if `status_applied` is False (a concurrent change
       won) raise `PlanStateError`. Then `registry.start(...)` in resume mode (the old
       `budget_reached` idle is already stored, so it is not acted on).
    5. [INFERRED, probe P9] if the session is still idle after `CONTINUE_RESUME_WAIT_SECONDS`,
       send `CONTINUE_MESSAGE` as a `user.message`.

    A process that dies between steps 1 and 4 leaves the plan `running` with no consumer: the
    next start resumes it, and the stuck check ends it if the session never moves again.

    Everything from the status read to the restart runs under the plan's lock
    (`PlannerServices.plan_locks`): a second "Continua" (double click, two tabs) or an
    interrupt waits, then reads the new status and is refused before touching the session, so
    the budget is raised once per approved $2 and never for a plan that was just interrupted.
    """
    ready = services.require_ready()
    with structlog.contextvars.bound_contextvars(plan_id=str(plan_id)):
        async with services.plan_locks.hold(plan_id):
            return await _continue_locked(
                plan_id, user, services=services, ready=ready, extra_cents=extra_cents
            )


async def _continue_locked(
    plan_id: uuid.UUID,
    user: CurrentUser,
    *,
    services: PlannerServices,
    ready: ReadyPlanner,
    extra_cents: int,
) -> int:
    async with services.session_factory() as db:
        plan = await get_user_plan(db, plan_id, user, settings=services.settings)
    status = PlanStatus(plan.status)
    session_id = plan.session_id
    if status is not PlanStatus.BUDGET_PAUSED or session_id is None:
        raise PlanStateError(plan_id, status, (PlanStatus.BUDGET_PAUSED,))
    with structlog.contextvars.bound_contextvars(session_id=session_id):
        return await _continue_session(
            plan, session_id, user, services=services, ready=ready, extra_cents=extra_cents
        )


async def _admit_continue(
    db: AsyncSession,
    user: CurrentUser,
    *,
    settings: Settings,
    now: dt.datetime,
    extra_cents: int,
) -> None:
    """The economics of a "Continua" (`continue_plan`'s docstring), on a connection that holds
    the quota lock: a paused plan reserves nothing (its cost reached its budget), so the extra
    is what counts; and the plan is about to run again, so the running cap applies as for a
    start."""
    budget = settings.session_budget_cents
    if not user_is_admin(user, settings):
        mine = await quota.month_usage(
            db,
            now=now,
            owner=plan_owner_filter(user, settings=settings),
            default_budget_cents=budget,
        )
        allowance = quota.user_quota(mine, settings=settings, now=now)
        if allowance.cents_used + extra_cents > allowance.cents_limit:
            log.info("quota_reached", kind="cents", **allowance.as_data())
            raise quota.QuotaReachedError("cents", allowance)
    everyone = await quota.month_usage(db, now=now, owner=None, default_budget_cents=budget)
    if everyone.cents + extra_cents > settings.monthly_limit_cents:
        log.warning(
            "monthly_limit_reached",
            spent_cents=everyone.cost_cents,
            reserved_cents=everyone.reserved_cents,
            extra_cents=extra_cents,
            limit_cents=settings.monthly_limit_cents,
        )
        raise MonthlyLimitReachedError(everyone.cents, settings.monthly_limit_cents)
    running = await quota.running_plans(db)
    if running >= settings.max_running_plans:
        log.warning("planner_busy", running=running, limit=settings.max_running_plans)
        raise quota.PlannerBusyError(running, settings.max_running_plans)


async def _reserve_continue(
    plan: PlanRecord,
    user: CurrentUser,
    *,
    services: PlannerServices,
    now: dt.datetime,
    extra_cents: int,
) -> int:
    """Step 1 of `continue_plan`: in one transaction holding the quota lock, the admission
    (`_admit_continue`) and the **reservation**: the row turns `running` with its cap raised to
    `max(cap, cost) + extra_cents` (no timeline event yet), so the next admission, a start or
    another "Continua", already counts this plan's extra and its place among the running plans
    before the lock is released. Returns the reserved cap. `PlanStateError` when the plan is no
    longer `budget_paused` (a change from another process won)."""
    settings = services.settings
    cap = plan.budget_cents or 0
    reserved_cap = max(cap, plan.cost_cents) + extra_cents
    async with services.session_factory() as db:
        await quota.lock_checks(db)
        await _admit_continue(db, user, settings=settings, now=now, extra_cents=extra_cents)
        moved = await db.scalar(
            update(PlanRecord)
            .where(
                PlanRecord.id == plan.id,
                PlanRecord.status == PlanStatus.BUDGET_PAUSED.value,
                PlanRecord.continues < settings.max_continues_per_plan,
            )
            .values(
                status=PlanStatus.RUNNING.value,
                budget_cents=reserved_cap,
                running_since=func.now(),
            )
            .returning(PlanRecord.id)
        )
        if moved is None:
            await db.rollback()
            raise PlanStateError(
                plan.id, await _current_status(services, plan.id), (PlanStatus.BUDGET_PAUSED,)
            )
        await db.commit()
    return reserved_cap


async def _release_continue(
    services: PlannerServices, plan: PlanRecord, *, reserved_cap: int
) -> None:
    """Give a reservation back after the session's budget could not be raised: the row returns to
    `budget_paused` with its old cap, unless something else changed it since. Never raises."""
    try:
        async with services.session_factory() as db:
            await db.execute(
                update(PlanRecord)
                .where(
                    PlanRecord.id == plan.id,
                    PlanRecord.status == PlanStatus.RUNNING.value,
                    PlanRecord.budget_cents == reserved_cap,
                )
                .values(status=PlanStatus.BUDGET_PAUSED.value, budget_cents=plan.budget_cents)
            )
            await db.commit()
    except Exception as exc:
        log.error("continue_release_failed", plan_id=str(plan.id), error=type(exc).__name__)


async def _continue_session(
    plan: PlanRecord,
    session_id: str,
    user: CurrentUser,
    *,
    services: PlannerServices,
    ready: ReadyPlanner,
    extra_cents: int,
) -> int:
    plan_id = plan.id
    settings = services.settings
    if plan.continues >= settings.max_continues_per_plan:
        log.info(
            "continue_limit_reached",
            plan_id=str(plan_id),
            continues=plan.continues,
            limit=settings.max_continues_per_plan,
        )
        raise quota.ContinueLimitReachedError(plan.continues, settings.max_continues_per_plan)
    if ready.registry.get(plan_id) is not None:
        # The paused consumer is still winding down: it stops before the row turns running, so
        # none of its late status changes can apply to the plan once it runs again.
        await ready.registry.stop(plan_id)
    reserved_cap = await _reserve_continue(
        plan, user, services=services, now=ready.deps.now(), extra_cents=extra_cents
    )

    bound = log.bind(plan_id=str(plan_id), session_id=session_id)
    try:
        info = await ready.client.retrieve_session(session_id)
        consumed = info.usage.list_cost_cents
        if consumed is None:
            consumed = plan.cost_cents
        cap = plan.budget_cents if plan.budget_cents is not None else info.budget_cents or 0
        new_budget = max(cap, consumed) + extra_cents
        await ready.client.update_budget(session_id, new_budget)
    except BaseException:
        # Nothing was raised on the session (or it is unknown and the next "Continua" repeats the
        # same cap): the reservation goes back, the plan is paused again.
        await _release_continue(services, plan, reserved_cap=reserved_cap)
        raise

    result = await set_plan_status(
        services.session_factory,
        services.hub,
        plan_id,
        # The reservation already turned the row `running`.
        StatusChange(PlanStatus.RUNNING, reason=None, only_from=(PlanStatus.RUNNING,)),
        title=TITLE_CONTINUED,
        event_key=f"continue:{new_budget}",
        budget_cents=new_budget,
        continues_increment=1,
    )
    if not result.status_applied:
        raise PlanStateError(
            plan_id, await _current_status(services, plan_id), (PlanStatus.BUDGET_PAUSED,)
        )
    bound.info("plan_continued", budget_cents=new_budget, consumed_cents=consumed)

    ready.registry.start(plan_id, session_id)
    _spawn(
        services,
        _nudge_if_still_idle(services, ready.client, plan_id, session_id, consumed_cents=consumed),
        name=f"continue-nudge-{plan_id}",
    )
    return new_budget


def _spawn(services: PlannerServices, work: Any, *, name: str, cleanup: bool = False) -> None:
    """Run `work` as a task tied to the planner's life (cancelled by `stop_planner`; with
    `cleanup`, only after its shutdown grace)."""
    task: asyncio.Task[None] = asyncio.create_task(work, name=name)
    services.background_tasks.append(task)
    if cleanup:
        services.cleanup_tasks.add(task)
        task.add_done_callback(services.cleanup_tasks.discard)

    def _forget(done: asyncio.Task[None]) -> None:
        if done in services.background_tasks:
            services.background_tasks.remove(done)

    task.add_done_callback(_forget)


async def _nudge_if_still_idle(
    services: PlannerServices,
    client: ManagedAgentsClient,
    plan_id: uuid.UUID,
    session_id: str,
    *,
    consumed_cents: int,
) -> None:
    """Step 4 of `continue_plan` [INFERRED, P9]: after the wait, a session that is still idle,
    whose plan is still `running` and whose cost hasn't moved never resumed by itself: send
    `CONTINUE_MESSAGE`. Errors are logged."""
    await asyncio.sleep(CONTINUE_RESUME_WAIT_SECONDS)
    bound = log.bind(plan_id=str(plan_id), session_id=session_id)
    try:
        if await _current_status(services, plan_id) is not PlanStatus.RUNNING:
            return
        info = await client.retrieve_session(session_id)
        cost = info.usage.list_cost_cents
        if info.status != "idle" or (cost is not None and cost > consumed_cents):
            return
        await client.send_user_message(session_id, CONTINUE_MESSAGE)
        bound.info("continue_message_sent")
    except Exception as exc:
        bound.warning("continue_message_failed", error=type(exc).__name__)


async def resume_running_plans(services: PlannerServices) -> list[uuid.UUID]:
    """Process start (consumer step 6): start a resume-mode consumer for every `running` plan
    with a `session_id`. A `running` plan without `session_id` (crash between insert and
    session creation) becomes `failed` with `REASON_NO_SESSION`. Returns the resumed ids.
    When the planner is not ready the plans are left `running` and an error is logged.

    Another process may follow some of these plans (a redeploy's overlap): their consumers wait
    for the plan's lease (`consumer.PlanLease`) and take over when that process stops.

    A demo plan (`DEMO_SESSION_PREFIX`) can't be resumed, its session died with the process
    that played it: it becomes `interrupted` (`REASON_DEMO_ENDED`). In DEMO_MODE the other
    `running` plans are left alone (the demo client can't follow real sessions): a later
    start without DEMO_MODE resumes them."""
    try:
        ready = services.require_ready()
    except PlannerUnavailableError as exc:
        # No database access here: a planner without a key must start without Postgres too.
        log.error("plans_not_resumed", reasons=exc.reasons)
        return []
    async with services.session_factory() as db:
        rows = (
            await db.execute(
                select(PlanRecord.id, PlanRecord.session_id)
                .where(PlanRecord.status == PlanStatus.RUNNING.value)
                .order_by(PlanRecord.created_at)
            )
        ).all()
    resumed: list[uuid.UUID] = []
    for plan_id, session_id in rows:
        with structlog.contextvars.bound_contextvars(plan_id=str(plan_id), session_id=session_id):
            if await _resume_one(services, ready, plan_id, session_id):
                resumed.append(plan_id)
    return resumed


async def _resume_one(
    services: PlannerServices, ready: ReadyPlanner, plan_id: uuid.UUID, session_id: str | None
) -> bool:
    """`resume_running_plans` for one plan; True when a consumer was started. Never raises."""
    bound = log.bind(plan_id=str(plan_id), session_id=session_id)
    try:
        if session_id is None:
            await set_plan_status(
                services.session_factory,
                services.hub,
                plan_id,
                StatusChange(PlanStatus.FAILED, reason=REASON_NO_SESSION),
                title=TITLE_PLAN_FAILED,
                event_key="no-session",
            )
            bound.warning("plan_without_session_failed")
            return False
        if session_id.startswith(DEMO_SESSION_PREFIX):
            await set_plan_status(
                services.session_factory,
                services.hub,
                plan_id,
                StatusChange(PlanStatus.INTERRUPTED, reason=REASON_DEMO_ENDED),
                title=TITLE_DEMO_ENDED,
                event_key="demo-ended",
            )
            bound.info("demo_plan_closed")
            return False
        if services.settings.demo_mode:
            bound.warning("plan_not_resumed_in_demo_mode")
            return False
        if ready.registry.get(plan_id) is not None:
            return False
        ready.registry.start(plan_id, session_id)
        bound.info("plan_resumed")
        return True
    except Exception:
        bound.exception("plan_resume_failed")
        return False


# --- queries and helpers ------------------------------------------------------------------------


def plan_owner_filter(user: CurrentUser, *, settings: Settings) -> ColumnElement[bool]:
    """SQL predicate: the plans that belong to `user`.

    When the signed-in id is one of this backend's `users.id` (`Settings.plans_carry_user_id`,
    AUTH_MODE=atlas): the rows whose `user_id` is that id, plus, when the account's email is
    verified (`CurrentUser.email_verified`: it proved it owns the address), the rows from before
    the switch that have no `user_id` and carry that email. An unverified account sees only the
    plans stored with its id: anyone may type someone else's address into a sign-up form, and
    the address alone must not hand them that person's old plans. Otherwise (TripTracker's and
    the local mode's plans) the rows with the user's email, compared trimmed and lower-cased.
    `owns_plan` is the same rule for a row already loaded.
    """
    email = user.email.strip().lower()
    by_email = func.lower(PlanRecord.user_email) == email
    if settings.plans_carry_user_id and user.auth_user_id:
        by_id = PlanRecord.user_id == user.auth_user_id
        if not user.email_verified:
            return by_id
        return or_(by_id, and_(PlanRecord.user_id.is_(None), by_email))
    return by_email


def owns_plan(plan: PlanRecord, user: CurrentUser, *, settings: Settings) -> bool:
    """`plan_owner_filter`'s rule for a loaded row."""
    same_email = plan.user_email.strip().lower() == user.email.strip().lower()
    if settings.plans_carry_user_id and user.auth_user_id:
        legacy = user.email_verified and plan.user_id is None and same_email
        return plan.user_id == user.auth_user_id or legacy
    return same_email


async def get_user_plan(
    db: AsyncSession, plan_id: uuid.UUID, user: CurrentUser, *, settings: Settings
) -> PlanRecord:
    """The plan row if it exists and `owns_plan(plan, user)`; else `PlanNotFoundError`
    (consumer.PlanNotFoundError: another user's plan is indistinguishable from a missing one)."""
    plan = await db.get(PlanRecord, plan_id)
    if plan is None or not owns_plan(plan, user, settings=settings):
        raise PlanNotFoundError(f"plan {plan_id} not found")
    return plan


async def monthly_spend_cents(db: AsyncSession, *, now: dt.datetime) -> int:
    """Sum of `plans.cost_cents` for plans created in `now`'s calendar month in Europe/Rome,
    all users: the cost already recorded. The checks use `quota.month_usage`, which adds the
    running plans' unspent budgets."""
    start, end = month_bounds(now)
    total = await db.scalar(
        select(func.coalesce(func.sum(PlanRecord.cost_cents), 0)).where(
            PlanRecord.created_at >= start, PlanRecord.created_at < end
        )
    )
    return int(total or 0)


month_bounds = quota.month_bounds
"""The month of the ceiling and the quotas (app/quota.py), kept here for its callers."""


def session_metadata(plan_id: uuid.UUID, profile: AgentProfile) -> dict[str, str]:
    """`{"plan_id": str(plan_id), "agent_profile": profile, "app": "trip-planner"}`: what the
    session carries for the Console. Never the user's email or name."""
    return {"plan_id": str(plan_id), "agent_profile": profile, "app": APP_METADATA}


def build_brief(request: PlanRequest, *, today: dt.date) -> str:
    """The first `user.message` to the coordinator, in English.

    It states today's date (Europe/Rome), says that user-facing text must be Italian, embeds
    the request as JSON (`request.model_dump(mode="json", exclude_none=True)`: origin,
    destination or "suggest one" with the idea, dates, travellers as kinds and ages, budget in
    EUR, free-text preferences) and asks the coordinator to save it as
    `/workspace/shared/request.json` before delegating. DECISION [INFERRED]: the spec has the
    backend write that file at start, but the API surface used here has no way to write into
    the session filesystem without a Files resource, so the coordinator writes it.
    Contains no personal data. Pure.

    The shape is a contract shared with the coordinator prompts, in this order: the line
    "Today is YYYY-MM-DD (Europe/Rome)."; the Italian-text sentence; the request JSON in a
    json code fence; "Save this JSON verbatim to /workspace/shared/request.json before
    delegating."
    """
    payload = json.dumps(
        request.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2
    )
    return "\n\n".join(
        [
            f"Today is {today.isoformat()} ({BRIEF_TIMEZONE}).",
            "All user-facing text (titles, notes, summary, warnings) must be in Italian.",
            f"```json\n{payload}\n```",
            f"Save this JSON verbatim to {BRIEF_REQUEST_PATH} before delegating.",
        ]
    )


def backend_git_sha(settings: Settings) -> str | None:
    """`settings.git_sha` (GIT_SHA, else RAILWAY_GIT_COMMIT_SHA), else `git rev-parse HEAD` run
    from `config.BACKEND_DIR` (local development only: Railway builds `backend/` without
    `.git`, so there only RAILWAY_GIT_COMMIT_SHA works), else None. Never raises."""
    if settings.git_sha:
        return settings.git_sha
    return _git_head()


@functools.cache
def _git_head() -> str | None:
    """`git rev-parse HEAD` in backend/, once per process; None when git or the repo is absent."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = completed.stdout.strip()
    if completed.returncode != 0 or not _GIT_SHA.fullmatch(sha):
        return None
    return sha
