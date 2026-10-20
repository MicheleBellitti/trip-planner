"""The plan consumer: one asyncio task per active plan, from Managed Agents streams to UI events.

Spec: "Backend FastAPI" -> "Il consumer (consumer.py), un task asyncio per piano attivo", steps
1-6; "Log e resilienza" (status_rescheduled, 429/5xx with backoff, at most 5 attempts, stuck
plans); "Costi e controlli di spesa" (budget_reached -> budget_paused). API facts and the spec
corrections they force: docs/managed-agents-notes.md §2e-§2g and §3 items 7-11.

What a consumer does, in order (the six spec steps, corrected by the notes):

1. Open the session stream BEFORE the first `user.message` (streams never replay). A fresh
   consumer then sends the first message (`first_message`) and signals `wait_started()`.
2. On `session.thread_created` open that thread's stream, THEN list that thread's history and
   skip ids already seen (thread streams don't replay either, notes §3.9). Subagent tool
   activity is only on thread streams; the session stream has their start, end and messages.
3. Every received event goes through `events.normalize()` into a `UIEvent` with the next `seq`,
   is stored in `events` (`ma_event_id` unique) and published on the `PlanHub` after commit.
   `session.usage` updates `plans.cost_cents` (US cents) and the events' `cost_cents`; when
   the consumer stops, one `retrieve_session` raises `plans.cost_cents` to the session's list
   cost if no `session.usage` carried it (notes §2d).
4. `agent.custom_tool_use` named `submit_plan`: validate (`Plan`), translate (`plan_to_trip`
   with pre-fetched FX), check the Trip against trip.json. Accepted: store `plans.plan` and
   `plans.trip`, answer `PLAN_ACCEPTED_TEXT`. Rejected: answer the error list with
   `is_error=True` so the agent fixes it. The `MAX_FAILED_SUBMISSIONS`th failure -> `failed`.
5. `session.status_idle` (see `decide_idle`): once a plan is accepted (its Trip is already
   stored) every idle except one waiting on our own `submit_plan` answer -> `ready` and archive
   the session, whatever the stop reason; before that, `end_turn` -> `interrupted` after an
   interrupt request, else `failed`; `budget_reached` -> `interrupted` after an interrupt
   request, else `budget_paused`; an unexpected `requires_action` (a confirmation nobody will
   give) -> `blocked`, logged;
   `session.status_rescheduled` is only logged (the platform retries).
6. Resume (process start, stream drop, "Continua"): open the session stream, list the history,
   persist what is unseen, reopen every subagent thread (`list_threads`) and wait (bounded,
   `RESUME_BACKFILL_WAIT_SECONDS`) until their histories are listed, act on pending tool uses
   and the latest unseen status, then tail.
   Reconcile like the SDK's own session runner [SDK lib/tools/_beta_session_runner.py:574-627,
   657-666]: open the stream first, read the WHOLE history before acting on any of it (two
   passes: pending `submit_plan` uses = `agent.custom_tool_use` ids minus the
   `custom_tool_use_id`s of the `user.custom_tool_result`s in history), and if a listing page
   fails halfway, act on nothing from that pass and mark nothing as handled: the next
   reconnect reconciles again. (The runner itself is not used: the backend needs every event
   for the UI, not only the tool calls.)
7. Threads: a session holds at most 25 concurrent child threads, idle ones included until
   archived (notes §2a). The roster (4 subagents, at most 2 follow-ups each) stays far below it
   even if every delegation opened a new thread, so threads are not archived routinely: only
   an idle child thread superseded by a newer thread of the same agent is archived
   (`superseded_threads`, `client.archive_thread`), because the coordinator addresses agents
   by name and the old thread can get no more work [INFERRED, probe P6]. A failed archive is
   logged, never fatal.

Invariants the implementation must keep:

- One writer per plan: the `ConsumerRegistry` never runs two consumers for the same plan in a
  process, and across processes a consumer follows its plan only while it holds the plan's
  lease (`PlanLease`: a Postgres session-level advisory lock on a dedicated connection, held
  from before the first stream opens until the consumer stops). During a Railway redeploy the
  old and the new process overlap and both resume the `running` plans: the one that can't take
  the lease opens no stream and tries again every `LEASE_RETRY_SECONDS` while the plan is still
  `running`, so the new process takes over as soon as the old one shuts down (and resumes from
  the history like any restart). Other modules (sessions, jobs) write events through
  `EventSink`, which allocates `seq` under a row lock on `plans`, so concurrent writers stay
  safe anyway. An interrupt asked through the process that does not follow the plan reaches the
  consumer through `plans.interrupt_requested_at`, re-read before a status decision.
- "Seen implies handled": an event that changes the plan (idle, error, terminated, custom tool
  use) is stored in the SAME transaction as the plan change it causes (`PlanUpdate`). On resume
  an event already in `events` is therefore never acted on again, and of the unseen status
  events only the latest one is acted on (older ones are superseded and only stored).
- A custom tool use is answered after the transaction that records its outcome commits. On
  resume, a `submit_plan` use without a `user.custom_tool_result` in history is answered again
  from the recorded outcome (the synthetic `backend:` event), never re-evaluated, so attempts
  are never double counted. Sending a second result is harmless (notes §2e).
- Dedupe key (`dedupe_key`): `ma_event_id` = the event `id`; for an event with an empty id
  (`user.interrupt` [SKILL]) a synthetic key built from the plan, the stream scope, the type
  and `processed_at`, so a resume that lists it again never stores it twice; an empty-id event
  without `processed_at` (still queued) is not persisted, its processed copy will be. NULL is
  never used for API events (NULLs bypass the UNIQUE constraint). Cross-posted copies carry
  different ids, so each copy is persisted from one stream only (`stream_owns`). Backend-made
  events use `backend_event_id()` keys.
- Retries: HTTP calls are retried inside `SdkManagedAgentsClient` (1 + `MAX_RETRIES` = 5
  attempts); what still fails (`ApiUnavailableError`) fails the plan with the reason. Stream
  (re)connections are retried here: `RECONNECT_ATTEMPTS` consecutive failures with exponential
  backoff and jitter (`backoff_delay`), the counter resetting after any received event. A
  `StreamDisconnectedError` (network drop, `event: error` mid-stream, malformed payload) is a
  reconnection, never a plan failure by itself.
- "Settled" before `end` reaches a browser: after its last decision the consumer still stores
  the events its streams had already delivered (a thread's backfill often lands after the
  session's decisive idle), so a terminal status is not always the plan's last stored event.
  `PlanConsumer.wait_settled()` returns once the consumer will store nothing more (right after
  that drain, or when it stops); the SSE route waits for it before its final catch-up and
  `event: end`, so the browser never misses those events (spec: "non perde nulla"). The drain
  first waits (bounded, `SETTLE_BACKFILL_WAIT_SECONDS`) for thread histories still being
  listed, so a thread created just before the decisive idle is stored too.
- A plan the backend fails for its own reasons (a crash, API errors after the retries, a lost
  stream) gets a `user.interrupt` after the settle, so the agents stop spending with nobody
  following them; the final cost is read on every stop (decision 11b, `record_session_cost`).
- Logs: structlog with `plan_id`, `session_id`, `agent` and `event_type` on every line; never
  event content, tool inputs or results, web page text, or personal data. `run()` binds
  `plan_id` and `session_id` in `structlog.contextvars` (the tasks it creates inherit them),
  and each handled event binds its lane (`agent`) and `event_type` while it is processed, so
  the lines other modules write on the consumer's behalf (ma_client, fx, events) carry them.
- The consumer never sends the user's name or email to the session: the brief built by
  `sessions.build_brief` holds only cities, dates, travellers' count and ages, budget and
  free-text preferences.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import random
import re
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, cast

import structlog
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app import clock
from app.choices import AnsweredBy, PendingChoice, answered_title, asked_title, request_of
from app.db import ChoiceRecord, EventRecord, PlanRecord, PlanStatus
from app.events import NOISE_EVENT_TYPES, AgentName, EventKind, UIEvent, normalize, one_line
from app.fx import fx_keys
from app.link_health import NO_LINK_CHECKS, LinkHealthChecker, LinkHealthMap
from app.ma_client import (
    PRIMARY_SCOPE,
    ApiRejectedError,
    ApiUnavailableError,
    ManagedAgentsError,
    RawEvent,
    SessionNotFoundError,
    StreamDisconnectedError,
    archive_when_idle,
    iter_session_history,
    iter_thread_history,
    usage_from_event,
)
from app.mapping import RandomTripIds, plan_to_trip
from app.plan import Plan, Problems, describe_validation_errors, plan_rejection_message
from app.results import parse_result
from app.triptracker_schema import TripSchemaUnavailableError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

    from app.config import Settings
    from app.fx import FxConverter, FxRates
    from app.hub import PlanHub
    from app.ma_client import EventStream, ManagedAgentsClient
    from app.mapping import TripIds
    from app.triptracker_schema import TripSchema, TripSchemaStore

SUBMIT_PLAN_TOOL = "submit_plan"
MAX_FAILED_SUBMISSIONS = 3
"""Spec: "Dopo 3 tentativi falliti il piano e' failed"."""

PLAN_ACCEPTED_TEXT = "Plan accepted."
"""Tool result for an accepted plan (spec wording)."""

PLAN_ALREADY_ACCEPTED_TEXT = (
    "Plan already accepted. Do not call submit_plan again; end your turn with a short summary."
)
UNKNOWN_TOOL_TEXT = "Unknown tool {name!r}: the only custom tool is submit_plan."
NO_ATTEMPTS_LEFT_TEXT = (
    "No attempts left: the plan was rejected {count} times and the run is being stopped."
)

RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY_SECONDS = 1.0
RECONNECT_MAX_DELAY_SECONDS = 30.0
START_TIMEOUT_SECONDS = 75.0
"""How long `sessions.start_plan` waits in `PlanConsumer.wait_started` (stream open + first
message) before giving up. Above one stream open plus one `send_user_message` attempt
(`ma_client.REQUEST_TIMEOUT_SECONDS`, 30 s each) with room to spare, so a slow but successful
send of the brief is not cut off halfway (the session would then run with nobody following
it). A start that still times out is cleaned up by `sessions.start_plan` (interrupt, archive,
final cost)."""

RESUME_BACKFILL_WAIT_SECONDS = 30.0
"""On resume, how long the reconcile waits for every subagent thread's history to be listed
before it answers pending tool uses and acts on the latest status found in the session
history. A decision taken first would end the consumer while those listings are in flight,
and the events of the downtime would never be stored (spec "Ripresa": nothing is lost)."""

SETTLE_BACKFILL_WAIT_SECONDS = 5.0
"""After the last decision, how long the consumer waits for thread backfills still in flight
(a thread created just before the decisive idle, or a listing slower than the resume wait)
before its final drain and `wait_settled()`. Below `routes.END_SETTLE_SECONDS` (10 s), the
bound a browser's `end` waits for the settle."""

LEASE_RETRY_SECONDS = 2.0
"""How often a consumer whose plan's lease another process holds (a redeploy's overlap) tries
again while the plan is still `running`. Below `routes.END_SETTLE_SECONDS`: a waiting consumer
notices within one period that the plan ended elsewhere, so a browser's `end` never waits on it
for long."""

LEASE_NAMESPACE = b"trip-planner/plan-consumer/"
"""Hashed with the plan id into the advisory lock key (`plan_lease_key`), so the key space is
this backend's own."""

BACKEND_EVENT_PREFIX = "backend:"

PRIMARY_OWNED_TYPES: frozenset[str] = frozenset(
    {
        "session.thread_created",
        "session.thread_status_running",
        "session.thread_status_idle",
        "session.thread_status_rescheduled",
        "session.thread_status_terminated",
        "agent.thread_message_sent",
        "agent.thread_message_received",
    }
)
"""Thread lifecycle and inter-agent messages: persisted from the session stream only."""

ACTION_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "agent.custom_tool_use",
        "session.status_idle",
        "session.status_terminated",
        "session.error",
        "session.deleted",
        "session.thread_created",
    }
)
"""Events the consumer acts on. `events.normalize` must return a UIEvent (never None) for
these, so that "seen implies handled" holds on resume."""

StreamScope = str
"""`ma_client.PRIMARY_SCOPE` ("session") or a thread id (`sthr_...`)."""

FIRST_MESSAGE_ATTEMPTS = 5
"""Attempts for the first `user.message`, which the client sends without SDK retries (a retried
message may be enqueued twice): after an `ApiUnavailableError` the history is checked for the
message before it is sent again."""

MAX_ERROR_LINES = 40
"""Error lines kept in a rejection's `Rejected.errors` (and the UI event's detail)."""

STATUS_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "session.status_running",
        "session.status_idle",
        "session.status_rescheduled",
        "session.status_terminated",
        "session.deleted",
    }
)
"""Session status events (plus a terminal `session.error`): on resume only the latest one in
the history is acted on, the older ones are superseded."""

RESULTS_PATH = re.compile(r"^/workspace/results/(?P<agent>[A-Za-z0-9_-]+)\.json")
"""A subagent's results file (`/workspace/results/<agent>.json`), temp files included."""

# Italian, user-facing: `plans.failure_reason` and backend event titles.
REASON_END_TURN_WITHOUT_PLAN = "Il coordinatore ha chiuso senza consegnare il piano."
REASON_RETRIES_EXHAUSTED = "Gli agenti si sono fermati dopo troppi errori della piattaforma."
REASON_REFUSAL = "Il modello si è rifiutato di proseguire con la richiesta."
REASON_UNEXPECTED_CONFIRMATION = "Gli agenti aspettano una conferma che nessuno darà."
REASON_UNKNOWN_STOP = "Gli agenti si sono fermati per un motivo non riconosciuto."
REASON_INTERRUPTED = "Interrotto su richiesta."
REASON_TOO_MANY_REJECTIONS = (
    f"Il piano è stato respinto {MAX_FAILED_SUBMISSIONS} volte: non superava i controlli."
)
REASON_SESSION_TERMINATED = "La sessione degli agenti si è chiusa prima di consegnare il piano."
REASON_SESSION_DELETED = "La sessione degli agenti è stata eliminata."
REASON_SESSION_ERROR = "La sessione degli agenti si è fermata per un errore irreparabile."
REASON_STREAM_LOST = "Persa la connessione con la sessione degli agenti."
REASON_API_UNAVAILABLE = "Il servizio degli agenti non risponde: riprova più tardi."
REASON_API_REJECTED = "Il servizio degli agenti ha rifiutato una richiesta del planner."
REASON_SESSION_NOT_FOUND = "La sessione degli agenti non esiste più."
REASON_SCHEMA_UNAVAILABLE = (
    "Lo schema dei viaggi di TripTracker non è disponibile: il piano non può essere convalidato."
)
REASON_INTERNAL = "Errore interno del planner."

TITLE_PLAN_ACCEPTED = "Piano accettato"
TITLE_PLAN_ALREADY_ACCEPTED = "Piano già accettato: nuova consegna ignorata"
TITLE_FAILED = "Piano non riuscito"
TITLE_READY = "Piano pronto"

SCHEMA_UNAVAILABLE_TEXT = (
    "The backend cannot validate plans right now (TripTracker's trip schema is unavailable); "
    "the run is being stopped."
)

TERMINAL_STATUSES: frozenset[PlanStatus] = frozenset(
    {PlanStatus.READY, PlanStatus.FAILED, PlanStatus.BLOCKED, PlanStatus.INTERRUPTED}
)
"""Statuses after which no more events come (`hub.end`); `budget_paused` is not one."""

log = structlog.get_logger(__name__)


# --- dependencies -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConsumerDeps:
    """Everything a consumer needs, built once by `sessions.start_planner()`."""

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    client: ManagedAgentsClient
    hub: PlanHub
    trip_schema: TripSchemaStore
    fx: FxConverter
    now: Callable[[], dt.datetime]
    """Timezone-aware clock (`clock.now` in production; frozen in tests)."""
    ids: Callable[[], TripIds] = RandomTripIds
    """Factory of the id source for each accepted Trip (`SeededTripIds` in tests)."""
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    """Backoff sleeps (tests pass a no-op)."""
    link_checker: LinkHealthChecker = NO_LINK_CHECKS
    """Checks the accepted plan's URLs (`link_health`); checks nothing by default."""


# --- plan updates and event persistence ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusChange:
    """A conditional status transition: applied only when the current status is in
    `only_from` (compare-and-set), so late events never overwrite a newer decision."""

    to: PlanStatus
    reason: str | None = None
    """Italian, user-facing (`plans.failure_reason`); None clears it."""
    only_from: Collection[PlanStatus] = (PlanStatus.RUNNING,)


@dataclass(frozen=True, slots=True)
class PlanUpdate:
    """Changes to the `plans` row committed together with one event."""

    status: StatusChange | None = None
    """Applied with compare-and-set. A change to `running` also sets `plans.running_since` to
    the transaction's `now()` (the stuck check counts its 45 minutes from there)."""
    cost_cents: int | None = None
    """New cumulative list cost (US cents); only ever increases the stored value."""
    budget_cents: int | None = None
    """New session budget cap (US cents), `plans.budget_cents`: set at start, raised by
    "Continua"."""
    continues_increment: int = 0
    """Added to `plans.continues`: 1 for every "Continua" (its cap: MAX_CONTINUES_PER_PLAN)."""
    interrupt_requested_at: dt.datetime | None = None
    """Sets `plans.interrupt_requested_at` (only when still NULL; never cleared): the user or the
    stuck check asked to interrupt. Persisted so a consumer resumed after a restart still turns
    the coming `end_turn` into `interrupted`."""
    submit_attempts_increment: int = 0
    plan: Mapping[str, Any] | None = None
    """The accepted Plan as JSON (`Plan.model_dump(mode="json")` plus mapping warnings)."""
    trip: Mapping[str, Any] | None = None
    """The translated TripTracker Trip (`TripMapping.trip`)."""
    link_health: Mapping[str, Any] | None = None
    """The link verdicts as JSON (`LinkHealthMap.to_json()`), stored in `plans.link_health`."""


@dataclass(frozen=True, slots=True)
class EmitResult:
    """What `EventSink.emit` did."""

    event: UIEvent | None
    """The stored event; None when `build` returned None, `ma_event_id` was a duplicate or the
    `guard` refused."""
    duplicate: bool
    """True when an event with the same `ma_event_id` was already stored: NOTHING was changed,
    `update` included. A caller whose change must happen checks `status_applied`."""
    status_applied: bool
    """True when `update.status` was applied (False when absent, when its precondition failed,
    or when the event was a duplicate)."""
    refused: bool = False
    """True when the `guard` returned False: NOTHING was stored or changed."""


Guard = Callable[["AsyncSession"], Awaitable[bool]]
"""Runs inside `emit`'s transaction, after the plan-row lock and the duplicate check; False
refuses the whole emit (nothing is stored). It may write on the session (its writes commit with
the event and roll back with a refusal)."""

EventBuilder = Callable[[int], UIEvent | None]
"""Builds the UIEvent for a given `seq` (e.g. `lambda seq: normalize(raw, seq=seq, ...)`)."""


class _DuplicateEventError(Exception):
    """Internal: the insert hit `ma_event_id`'s UNIQUE constraint; roll the transaction back."""


class _GuardRefusedError(Exception):
    """Internal: the guard returned False; roll the transaction back (its writes included)."""


class EventSink:
    """Persists and publishes one plan's UI events. Shared by the consumer, sessions and jobs."""

    def __init__(
        self,
        plan_id: uuid.UUID,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        hub: PlanHub,
    ) -> None:
        self._plan_id = plan_id
        self._session_factory = session_factory
        self._hub = hub

    @property
    def plan_id(self) -> uuid.UUID:
        return self._plan_id

    async def emit(
        self,
        build: EventBuilder,
        *,
        ma_event_id: str,
        update: PlanUpdate | None = None,
        guard: Guard | None = None,
    ) -> EmitResult:
        """In one transaction: lock the `plans` row (`SELECT ... FOR UPDATE`), skip if
        `ma_event_id` is already stored, allocate `seq = max(seq) + 1` (0 for the first event),
        `build(seq)`, insert it (`ON CONFLICT (ma_event_id) DO NOTHING`), apply `update`, commit.

        After commit: publish the event on the hub, and call `hub.end()` when `update` moved the
        plan to a terminal status (ready, failed, blocked, interrupted). `build` returning None
        stores no event but still applies `update`. Raises `PlanNotFoundError` when the plan row
        is gone (deleted by the nightly job).

        `ma_event_id` is always a key (`dedupe_key` or `backend_event_id`), never None: a NULL
        would bypass the UNIQUE constraint and a replay would store the event twice. The built
        `UIEvent` is storable by construction (`events.strip_nul` removes U+0000 from
        `title` and `detail`), and every other JSON this writes (`plan`, `trip`) comes from
        contract models that reject control characters, so Postgres `jsonb` never refuses a
        write here.

        `guard`, when given, runs after the lock and the duplicate check, before `seq` is
        allocated: when it returns False nothing is stored or changed and the result says
        `refused`. Two emits of one plan serialize on the row lock, so a guard that does a
        conditional UPDATE decides a race between them.
        """
        return await self._emit(
            build, ma_event_id=ma_event_id, update=update, all_or_nothing=False, guard=guard
        )

    async def _emit(
        self,
        build: EventBuilder,
        *,
        ma_event_id: str,
        update: PlanUpdate | None,
        all_or_nothing: bool,
        guard: Guard | None = None,
    ) -> EmitResult:
        """`emit`; with `all_or_nothing`, a status change whose precondition fails stores
        nothing at all (no event, no other change): `set_plan_status` semantics."""
        if not ma_event_id:
            msg = "ma_event_id must be a non-empty key"
            raise ValueError(msg)
        event: UIEvent | None = None
        status_applied = False
        try:
            async with self._session_factory() as db, db.begin():
                plan = await db.scalar(
                    select(PlanRecord).where(PlanRecord.id == self._plan_id).with_for_update()
                )
                if plan is None:
                    raise PlanNotFoundError(str(self._plan_id))
                existing = await db.scalar(
                    select(EventRecord.seq).where(EventRecord.ma_event_id == ma_event_id)
                )
                if existing is not None:
                    return EmitResult(event=None, duplicate=True, status_applied=False)
                change = update.status if update is not None else None
                allowed = change is not None and _status_allowed(plan.status, change)
                if all_or_nothing and change is not None and not allowed:
                    return EmitResult(event=None, duplicate=False, status_applied=False)
                if guard is not None and not await guard(db):
                    raise _GuardRefusedError
                next_seq = await db.scalar(
                    select(func.coalesce(func.max(EventRecord.seq), -1) + 1).where(
                        EventRecord.plan_id == self._plan_id
                    )
                )
                seq = int(next_seq or 0)
                event = build(seq)
                if event is not None:
                    if event.seq != seq:
                        event = event.model_copy(update={"seq": seq})
                    inserted = await db.scalar(
                        pg_insert(EventRecord)
                        .values(
                            plan_id=self._plan_id,
                            seq=seq,
                            ts=event.ts,
                            agent=event.agent.value,
                            kind=event.kind.value,
                            title=event.title,
                            detail=event.detail,
                            cost_cents=event.cost_cents,
                            ma_event_id=ma_event_id,
                        )
                        .on_conflict_do_nothing(index_elements=[EventRecord.ma_event_id])
                        .returning(EventRecord.seq)
                    )
                    if inserted is None:
                        raise _DuplicateEventError
                if update is not None:
                    status_applied = _apply_update(plan, update, allowed=allowed)
        except _DuplicateEventError:
            return EmitResult(event=None, duplicate=True, status_applied=False)
        except _GuardRefusedError:
            return EmitResult(event=None, duplicate=False, status_applied=False, refused=True)
        ended = update.status.to if status_applied and update and update.status else None
        self._publish(event, ended)
        return EmitResult(event=event, duplicate=False, status_applied=status_applied)

    def _publish(self, event: UIEvent | None, status: PlanStatus | None) -> None:
        """After commit; the hub never raises by contract, but a failure here must not make a
        committed write look failed to the caller."""
        try:
            if event is not None:
                self._hub.publish(self._plan_id, event)
            if status is not None and status in TERMINAL_STATUSES:
                self._hub.end(self._plan_id, status)
        except Exception:
            log.exception("hub_publish_failed", plan_id=str(self._plan_id))


def _status_allowed(current: str, change: StatusChange) -> bool:
    return current in {PlanStatus(status).value for status in change.only_from}


def _apply_update(plan: PlanRecord, update: PlanUpdate, *, allowed: bool) -> bool:
    """Apply `update` to the locked row; returns whether the status change was applied."""
    applied = False
    if update.status is not None and allowed:
        plan.status = update.status.to.value
        plan.failure_reason = update.status.reason
        if update.status.to is PlanStatus.RUNNING:
            plan.running_since = cast(dt.datetime, func.now())
        applied = True
    if update.cost_cents is not None and update.cost_cents > (plan.cost_cents or 0):
        plan.cost_cents = update.cost_cents
    if update.budget_cents is not None:
        plan.budget_cents = update.budget_cents
    if update.continues_increment:
        plan.continues = (plan.continues or 0) + update.continues_increment
    if update.interrupt_requested_at is not None and plan.interrupt_requested_at is None:
        plan.interrupt_requested_at = update.interrupt_requested_at
    if update.submit_attempts_increment:
        plan.submit_attempts = (plan.submit_attempts or 0) + update.submit_attempts_increment
    if update.plan is not None:
        plan.plan = dict(update.plan)
    if update.trip is not None:
        plan.trip = dict(update.trip)
    if update.link_health is not None:
        plan.link_health = dict(update.link_health)
    return applied


class PlanNotFoundError(Exception):
    """The plan row does not exist (any more)."""


async def set_plan_status(
    session_factory: async_sessionmaker[AsyncSession],
    hub: PlanHub,
    plan_id: uuid.UUID,
    change: StatusChange,
    *,
    title: str,
    event_key: str,
    agent: AgentName = AgentName.COORDINATOR,
    budget_cents: int | None = None,
    continues_increment: int = 0,
) -> EmitResult:
    """Apply `change` (and `budget_cents` and `continues_increment`, when given) and store a
    `status` UIEvent titled
    `title` (Italian, one line) with `ma_event_id = backend_event_id(plan_id, "status",
    event_key)`, through `EventSink.emit`. The convenience used by sessions (interrupt,
    continue) and jobs (stuck plans).

    `event_key` must be unique per occurrence of the transition, e.g. `continue:<new budget
    cents>` (every "Continua" raises the budget) or `interrupted:<uuid4>`: a key that was
    already stored makes the call a silent no-op (`EmitResult.duplicate`, nothing applied).
    Callers that need the change check `status_applied` and raise when it is False.

    All or nothing: when `change`'s precondition fails (the plan is no longer in
    `change.only_from`) nothing is stored, neither the event nor `budget_cents`, so the
    timeline never shows a transition that did not happen."""
    sink = EventSink(plan_id, session_factory=session_factory, hub=hub)
    detail = {"event_type": "backend.status", "plan_status": change.to.value}
    return await sink._emit(  # pyright: ignore[reportPrivateUsage]
        backend_event(EventKind.STATUS, title, ts=clock.now(), agent=agent, detail=detail),
        ma_event_id=backend_event_id(plan_id, "status", event_key),
        update=PlanUpdate(
            status=change, budget_cents=budget_cents, continues_increment=continues_increment
        ),
        all_or_nothing=True,
    )


async def record_session_cost(
    client: ManagedAgentsClient,
    sink: EventSink,
    session_id: str,
    *,
    known_cents: int | None = None,
) -> int | None:
    """Decision 11b: read the session's `usage.list_cost` with one `retrieve_session` and raise
    `plans.cost_cents` to it through `sink` (`PlanUpdate(cost_cents=...)`, key
    `backend_event_id(plan_id, "cost", <cents>)`, no timeline event; the stored cost never goes
    down). The write is skipped when the read is not above `known_cents`.

    Shared by every path that stops following a session: the consumer when it stops,
    `sessions` (a start that timed out, an interrupt without a live consumer) and `jobs` (a
    stuck plan forced to `interrupted`), so the monthly limit (`sessions.monthly_spend_cents`)
    counts what those sessions spent even when no `session.usage` reached the backend.

    Returns the cost read (US cents), or None when it is unknown or could not be read. Never
    raises except on cancellation: failures are logged."""
    bound = log.bind(
        plan_id=str(sink.plan_id), session_id=session_id, agent="coordinator", event_type=None
    )
    try:
        info = await client.retrieve_session(session_id)
    except ManagedAgentsError as exc:
        bound.warning("final_cost_unavailable", error_type=exc.error_type)
        return None
    cost = info.usage.list_cost_cents
    if cost is None or cost <= (known_cents or 0):
        return cost
    try:
        await sink.emit(
            lambda seq: None,
            ma_event_id=backend_event_id(sink.plan_id, "cost", str(cost)),
            update=PlanUpdate(cost_cents=cost),
        )
    except Exception as exc:
        bound.warning("final_cost_write_failed", error=type(exc).__name__)
    else:
        bound.info("final_cost_recorded", cost_cents=cost)
    return cost


def backend_event_id(plan_id: uuid.UUID, name: str, key: str) -> str:
    """`backend:<plan_id>:<name>:<key>`: the dedupe key of events made by the backend itself
    (submit outcomes, status changes), so a replayed step never stores them twice."""
    return f"{BACKEND_EVENT_PREFIX}{plan_id}:{name}:{key}"


def backend_event(
    kind: EventKind,
    title: str,
    *,
    ts: dt.datetime,
    agent: AgentName = AgentName.COORDINATOR,
    detail: Mapping[str, Any] | None = None,
    cost_cents: int | None = None,
) -> EventBuilder:
    """An `EventBuilder` for an event made by the backend (not normalized from the API)."""
    if ts.tzinfo is None:
        msg = "backend events need a timezone-aware ts"
        raise ValueError(msg)
    line = one_line(title) or "Evento"
    payload = dict(detail) if detail is not None else None
    cost = cost_cents if cost_cents is not None and cost_cents >= 0 else None

    def build(seq: int) -> UIEvent:
        return UIEvent(
            seq=seq, ts=ts, agent=agent, kind=kind, title=line, detail=payload, cost_cents=cost
        )

    return build


# --- ask_traveller ---------------------------------------------------------------------------


def choice_asked_event(record: ChoiceRecord, *, cost_cents: int | None) -> EventBuilder:
    """The timeline event of a question put to the traveller. Emit it with
    `backend_event_id(plan_id, "choice", f"{record.id}:asked")` as its key."""
    view = PendingChoice.from_record(record)
    return backend_event(
        EventKind.CHOICE,
        asked_title(view.kind),
        ts=record.asked_at,
        detail={
            "event_type": "backend.choice",
            "phase": "asked",
            "choice": view.model_dump(mode="json"),
        },
        cost_cents=cost_cents,
    )


async def close_choice(
    sink: EventSink,
    choice_id: str,
    *,
    answered_by: AnsweredBy,
    selected: Sequence[str],
    now: dt.datetime,
    cost_cents: int | None = None,
) -> ChoiceRecord | None:
    """Close a choice exactly once, whoever answers first (the traveller, the deadline, the
    platform on interrupt). Returns the closed row only when THIS call closed it; None when it
    was already closed or does not exist (nothing is stored then).

    The conditional UPDATE runs as the `emit` guard, under the plan row's lock, so two closes of
    one plan's choices serialize and exactly one wins; the answered event is stored with it."""
    closed: list[ChoiceRecord] = []

    async def guard(db: AsyncSession) -> bool:
        row = await db.scalar(
            update(ChoiceRecord)
            .where(
                ChoiceRecord.id == choice_id,
                ChoiceRecord.plan_id == sink.plan_id,
                ChoiceRecord.answered_by.is_(None),
            )
            .values(answer=list(selected), answered_by=answered_by, answered_at=now)
            .returning(ChoiceRecord)
            .execution_options(populate_existing=True)
        )
        if row is None:
            return False
        closed.append(row)
        return True

    def build(seq: int) -> UIEvent | None:
        row = closed[0]
        request = request_of(row)
        return backend_event(
            EventKind.CHOICE,
            answered_title(request, answered_by, selected),
            ts=now,
            detail={
                "event_type": "backend.choice",
                "phase": "answered",
                "choice_id": choice_id,
                "kind": row.kind,
                "answered_by": answered_by,
                "selected": list(selected),
                "answered_at": now.isoformat(),
            },
            cost_cents=cost_cents,
        )(seq)

    result = await sink.emit(
        build,
        ma_event_id=backend_event_id(sink.plan_id, "choice", f"{choice_id}:closed"),
        guard=guard,
    )
    return closed[0] if result.event is not None and closed else None


async def load_events_after(
    db: AsyncSession, plan_id: uuid.UUID, after_seq: int | None, *, limit: int = 1000
) -> list[UIEvent]:
    """The plan's stored events with `seq > after_seq` (all when None), ascending, at most
    `limit`. Used by the SSE route for the Last-Event-ID replay and by `app.cli`."""
    stmt = select(EventRecord).where(EventRecord.plan_id == plan_id)
    if after_seq is not None:
        stmt = stmt.where(EventRecord.seq > after_seq)
    rows = await db.scalars(stmt.order_by(EventRecord.seq).limit(max(limit, 0)))
    return [
        UIEvent(
            seq=row.seq,
            ts=row.ts,
            agent=AgentName(row.agent),
            kind=EventKind(row.kind),
            title=row.title,
            detail=row.detail,
            cost_cents=row.cost_cents,
        )
        for row in rows
    ]


async def load_latest_event(db: AsyncSession, plan_id: uuid.UUID) -> UIEvent | None:
    """The plan's stored event with the highest `seq`, or None when it has none."""
    row = await db.scalar(
        select(EventRecord)
        .where(EventRecord.plan_id == plan_id)
        .order_by(EventRecord.seq.desc())
        .limit(1)
    )
    if row is None:
        return None
    return UIEvent(
        seq=row.seq,
        ts=row.ts,
        agent=AgentName(row.agent),
        kind=EventKind(row.kind),
        title=row.title,
        detail=row.detail,
        cost_cents=row.cost_cents,
    )


# --- pure decisions -----------------------------------------------------------------------------


@dataclass(slots=True)
class ConsumerState:
    """What a consumer knows about its plan. Rebuilt from the `plans` row (never from replayed
    events) when a consumer starts, then kept in memory."""

    status: PlanStatus
    submit_attempts: int = 0
    failed_submissions: int = 0
    accepted: bool = False
    cost_cents: int | None = None
    interrupt_requested: bool = False
    """`plans.interrupt_requested_at is not None` when the consumer starts; set in memory by
    `PlanConsumer.request_interrupt()` afterwards (the row was written by the caller)."""
    threads: dict[str, AgentName] = field(default_factory=dict[str, AgentName])
    """Thread id -> lane. Agent names that are not an `AgentName` map to the coordinator."""
    thread_order: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """(thread id, agent name) of every child thread, in creation order."""
    idle_threads: set[str] = field(default_factory=set[str])
    """Child threads whose latest status is idle with `end_turn`."""
    archived_threads: set[str] = field(default_factory=set[str])
    custom_tool_use_ids: set[str] = field(default_factory=set[str])
    """Ids of every `agent.custom_tool_use` seen on the session stream (the coordinator's, the
    only ones the consumer answers): a `requires_action` idle waiting only on these is expected
    (we are answering), not a block."""
    answered_tool_use_ids: set[str] = field(default_factory=set[str])
    mcp_servers: dict[str, AgentName] = field(default_factory=dict[str, AgentName])
    """MCP server name -> lane of the agent that last called it (`agent.mcp_tool_use`), so a
    `session.error` about that server (which names the server, not the agent) is shown as a
    warning in that agent's lane. Best effort: unknown servers stay on the coordinator."""


class IdleDecision(StrEnum):
    """What a `session.status_idle` means for the plan."""

    READY = "ready"  # any idle after an accepted plan (except WAIT): ready + archive
    INTERRUPTED = "interrupted"  # end_turn/budget_reached after an interrupt, no plan: archive
    BUDGET_PAUSED = "budget_paused"  # budget_reached: wait for "Continua"
    BLOCKED = "blocked"  # requires_action on something we will never confirm; unknown reason
    FAILED = "failed"  # retries_exhausted, refusal, end_turn without a plan
    WAIT = "wait"  # requires_action only on our own submit_plan uses: keep following


@dataclass(frozen=True, slots=True)
class IdleOutcome:
    decision: IdleDecision
    reason: str | None = None
    """Italian `failure_reason` for FAILED/BLOCKED (e.g. "Il coordinatore ha chiuso senza
    consegnare il piano."), None otherwise."""
    log_reason: str | None = None
    """English detail for the logs (stop_reason type, refusal category); no content."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def decide_idle(raw: RawEvent, state: ConsumerState) -> IdleOutcome:
    """Classify a `session.status_idle` event (`raw["stop_reason"]["type"]`), in this order:

    1. `requires_action` whose `stop_reason.event_ids` are all in `state.custom_tool_use_ids`:
       WAIT (we are answering our own `submit_plan` use), accepted or not.
    2. `state.accepted`: READY for every other stop reason (`end_turn`, `budget_reached`,
       `retries_exhausted`, `refusal`, a blocking `requires_action`, unknown), with the stop
       reason in `log_reason`. The plan is finished, validated and its Trip stored: never ask
       for $2 more or fail it for what happens after.
    3. Not accepted:
       - `end_turn`: INTERRUPTED if `state.interrupt_requested`; else FAILED (the coordinator
         ended without a plan). DECISION: no automatic nudge message, it would spend money
         outside the spec's flow.
       - `budget_reached`: INTERRUPTED if `state.interrupt_requested` (the user already asked to
         stop: don't offer "Continua"); else BUDGET_PAUSED.
       - `requires_action` (anything else pending): BLOCKED.
       - `retries_exhausted`, `refusal`: FAILED.
       - anything else: BLOCKED (needs a human), logged as unknown.
    Pure.
    """
    stop_reason = _mapping(raw.get("stop_reason"))
    reason = _text(stop_reason.get("type")) or _text(raw.get("stop_reason"))
    log_reason = reason or "missing"

    if reason == "requires_action":
        event_ids = stop_reason.get("event_ids")
        ids = list(cast(list[Any], event_ids)) if isinstance(event_ids, list) else []
        if ids and all(isinstance(item, str) and item in state.custom_tool_use_ids for item in ids):
            return IdleOutcome(IdleDecision.WAIT, log_reason="requires_action:submit_plan")

    if reason == "refusal":
        category = _text(_mapping(raw.get("stop_details")).get("category"))
        log_reason = f"refusal:{category or 'unknown'}"

    if state.accepted:
        return IdleOutcome(IdleDecision.READY, log_reason=log_reason)

    match reason:
        case "end_turn":
            if state.interrupt_requested:
                return IdleOutcome(
                    IdleDecision.INTERRUPTED, REASON_INTERRUPTED, log_reason=log_reason
                )
            return IdleOutcome(
                IdleDecision.FAILED, REASON_END_TURN_WITHOUT_PLAN, log_reason=log_reason
            )
        case "budget_reached":
            if state.interrupt_requested:
                return IdleOutcome(
                    IdleDecision.INTERRUPTED, REASON_INTERRUPTED, log_reason=log_reason
                )
            return IdleOutcome(IdleDecision.BUDGET_PAUSED, log_reason=log_reason)
        case "requires_action":
            return IdleOutcome(
                IdleDecision.BLOCKED, REASON_UNEXPECTED_CONFIRMATION, log_reason=log_reason
            )
        case "retries_exhausted":
            return IdleOutcome(IdleDecision.FAILED, REASON_RETRIES_EXHAUSTED, log_reason=log_reason)
        case "refusal":
            return IdleOutcome(IdleDecision.FAILED, REASON_REFUSAL, log_reason=log_reason)
        case _:
            return IdleOutcome(
                IdleDecision.BLOCKED, REASON_UNKNOWN_STOP, log_reason=f"unknown:{log_reason}"
            )


def stream_owns(scope: StreamScope, raw: RawEvent) -> bool:
    """Whether the copy of `raw` received on `scope` is the one to persist and act on.

    Session stream: everything except subagent tool activity cross-posted with a
    `session_thread_id` (its thread stream has the authoritative copy). Thread streams:
    everything except `PRIMARY_OWNED_TYPES` and `session.*` events. [INFERRED] from notes
    §2f/§2g; probe P7 confirms which copies exist and their ids. Pure.
    """
    event_type = raw.get("type")
    kind = event_type if isinstance(event_type, str) else ""
    session_level = kind in PRIMARY_OWNED_TYPES or kind.startswith("session.")
    if scope == PRIMARY_SCOPE:
        return session_level or _text(raw.get("session_thread_id")) is None
    return not session_level


def dedupe_key(raw: RawEvent, *, plan_id: uuid.UUID, scope: StreamScope) -> str | None:
    """The `ma_event_id` to store `raw` under, or None when it must not be stored:

    - `raw["id"]` when it is a non-empty string (`sevt_...`);
    - an empty or missing id with `processed_at` set: `noid:<plan_id>:<scope>:<type>:
      <processed_at normalized to UTC ISO>`, deterministic, so the same echo listed again on a
      resume maps to the same key (`user.interrupt` echoes may have empty ids [SKILL]);
    - an empty id without `processed_at` (a queued echo): None, not persisted (its processed
      copy will be, under the key above). None is never stored as a NULL `ma_event_id`.
    Pure."""
    event_id = _text(raw.get("id"))
    if event_id is not None:
        return event_id
    processed_at = raw.get("processed_at")
    if not isinstance(processed_at, str) or not processed_at.strip():
        return None
    instant = _parse_instant(processed_at)
    stamp = instant.astimezone(dt.UTC).isoformat() if instant else processed_at.strip()
    event_type = _text(raw.get("type")) or "unknown"
    return f"noid:{plan_id}:{scope}:{event_type}:{stamp}"


_EXCESS_FRACTION = re.compile(r"(\.\d{6})\d+")


def _parse_instant(value: Any) -> dt.datetime | None:
    """An ISO 8601 instant as an aware datetime (a naive one is read as UTC); None when it is
    missing or unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(_EXCESS_FRACTION.sub(r"\1", value.strip(), count=1))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def superseded_threads(state: ConsumerState) -> list[str]:
    """Child threads to archive: idle (`state.idle_threads`), not yet archived, and followed in
    `state.thread_order` by a newer thread of the same agent name. Empty in the common case
    (threads reused or never re-created). Pure."""
    newest: dict[str, int] = {}
    for index, (_, agent_name) in enumerate(state.thread_order):
        newest[agent_name] = index
    return [
        thread_id
        for index, (thread_id, agent_name) in enumerate(state.thread_order)
        if index < newest[agent_name]
        and thread_id in state.idle_threads
        and thread_id not in state.archived_threads
    ]


def _lane(name: Any) -> AgentName | None:
    """The lane of an agent name as the API writes it; None when it is not one of ours."""
    if not isinstance(name, str):
        return None
    try:
        return AgentName(name.strip().lower())
    except ValueError:
        return None


def lane_for(raw: RawEvent, *, scope: StreamScope, state: ConsumerState) -> AgentName:
    """The timeline lane of `raw`: the thread's agent on a thread stream; on the session stream
    the coordinator, unless the event names a subagent (`agent_name`, `session_thread_id`,
    `from_agent_name`/`to_agent_name` for thread messages, which go to the subagent's lane) or
    is a `session.error` about an MCP server a subagent has called (`state.mcp_servers`).
    Pure."""
    if scope != PRIMARY_SCOPE:
        known = state.threads.get(scope)
        if known is not None:
            return known
        return _lane(raw.get("agent_name")) or AgentName.COORDINATOR

    def by_thread(thread_id: Any) -> AgentName | None:
        return state.threads.get(thread_id) if isinstance(thread_id, str) else None

    event_type = raw.get("type")
    if event_type == "agent.thread_message_sent":
        lane = _lane(raw.get("to_agent_name")) or by_thread(raw.get("to_session_thread_id"))
    elif event_type == "agent.thread_message_received":
        lane = _lane(raw.get("from_agent_name")) or by_thread(raw.get("from_session_thread_id"))
    elif event_type == "session.error":
        server = _text(_mapping(raw.get("error")).get("mcp_server_name"))
        lane = state.mcp_servers.get(server) if server is not None else None
    elif _text(raw.get("agent_name")) is not None:
        lane = _lane(raw.get("agent_name"))
    else:
        lane = by_thread(raw.get("session_thread_id"))
    return lane or AgentName.COORDINATOR


def is_terminal_error(raw: RawEvent) -> bool:
    """True for a `session.error` whose `error.retry_status.type` is `terminal` (the session
    will terminate). `retrying` and `exhausted` are only logged. Pure."""
    if raw.get("type") != "session.error":
        return False
    retry = _mapping(raw.get("error")).get("retry_status")
    retry_type = _mapping(retry).get("type") if isinstance(retry, Mapping) else retry
    return retry_type == "terminal"


def backoff_delay(attempt: int, *, jitter: float) -> float:
    """Seconds before reconnection attempt `attempt` (1-based): `min(BASE * 2**(attempt-1),
    MAX) * (0.75 + 0.25 * jitter)` with `jitter` in [0, 1). Pure."""
    exponent = min(max(attempt, 1) - 1, 32)
    base = min(RECONNECT_BASE_DELAY_SECONDS * 2**exponent, RECONNECT_MAX_DELAY_SECONDS)
    return base * (0.75 + 0.25 * min(max(jitter, 0.0), 1.0))


# --- submit_plan ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Accepted:
    """A plan that passed every check: what gets stored and answered."""

    plan: Plan
    plan_json: dict[str, Any]
    """`plan.model_dump(mode="json")` with the mapping's warnings appended (no duplicates)."""
    trip: dict[str, Any]
    """`TripMapping.trip`, exactly what GET /plans/{id}/trip will serve."""
    link_health: dict[str, Any] = field(default_factory=dict[str, Any])
    """`LinkHealthMap.to_json()`: the verdicts the trip followed (`{}` without checks)."""


@dataclass(frozen=True, slots=True)
class Rejected:
    """A plan that failed: `message` is the whole tool result sent with `is_error=True`."""

    stage: Literal["plan", "trip"]
    """`plan`: Pydantic validation of the input; `trip`: the translated Trip failed trip.json."""
    message: str
    errors: list[str]
    """One line per problem (also stored in the UI event's detail, at most 40)."""


SubmitOutcome = Accepted | Rejected


def _plan_rejected(error: ValidationError) -> Rejected:
    return Rejected(
        stage="plan",
        message=plan_rejection_message(error),
        errors=describe_validation_errors(error, limit=MAX_ERROR_LINES - 1),
    )


def parse_submission(tool_input: Mapping[str, Any]) -> Plan | Rejected:
    """`Plan.model_validate(tool_input)`; on `ValidationError` a `Rejected(stage="plan")` whose
    message is `plan.plan_rejection_message(error)`. Pure."""
    try:
        return Plan.model_validate(tool_input)
    except ValidationError as error:
        return _plan_rejected(error)


def translate_submission(
    plan: Plan,
    *,
    schema: TripSchema,
    fx: FxRates,
    now: dt.datetime,
    ids: TripIds,
    health: LinkHealthMap | None = None,
) -> SubmitOutcome:
    """Check the deadlines against `now`, then `mapping.plan_to_trip`, then
    `schema.validate(trip)`. Pure.

    1. Every `plan.bookings[i].book_by` that is set must be at or after `now` (a deadline in the
       past would land in TripTracker already overdue). Violations become a
       `Rejected(stage="plan")` in the `plan_rejection_message` format, one line each:
       `bookings[i].book_by: book_by (<value>) is in the past (now <now>); set a future
       deadline, or null to let the backend derive it`. Alternatives are not checked (they
       never reach TripTracker).
    2. Trip errors become a `Rejected(stage="trip")` whose message says the translated
       TripTracker trip failed TripTracker's own schema, lists `path: message` lines and asks
       for a corrected plan.
    """
    problems = Problems(type(plan).__name__)
    for index, booking in enumerate(plan.bookings):
        if booking.book_by is not None and booking.book_by < now:
            problems.add(
                ("bookings", index, "book_by"),
                "book_by_in_past",
                "book_by ({book_by}) is in the past (now {now}); set a future deadline, or null "
                "to let the backend derive it",
                # A mapping, so the error line carries no "(got ...)" suffix.
                {"book_by": booking.book_by.isoformat()},
                book_by=booking.book_by,
                now=now,
            )
    try:
        problems.raise_if_any()
    except ValidationError as error:
        return _plan_rejected(error)

    mapping = plan_to_trip(plan, now=now, fx=fx, ids=ids, health=health)
    trip = dict(mapping.trip)
    trip_errors = schema.validate(trip)
    if trip_errors:
        lines = [f"{error.path}: {error.message}" for error in trip_errors]
        if len(lines) > MAX_ERROR_LINES:
            lines = [
                *lines[: MAX_ERROR_LINES - 1],
                f"... and {len(lines) - MAX_ERROR_LINES + 1} more",
            ]
        noun = "error" if len(trip_errors) == 1 else "errors"
        header = (
            f"Plan rejected: the TripTracker trip translated from your plan failed "
            f"TripTracker's own schema (trip.json) with {len(trip_errors)} {noun}. Paths are "
            "TripTracker's field names, not your input's: bookings[k] is your bookings[k], "
            "days[d] is the d-th date of the trip. Fix the plan so these pass and call "
            "submit_plan again with the complete corrected plan."
        )
        message = "\n".join([header, *(f"- {line}" for line in lines)])
        return Rejected(stage="trip", message=message, errors=lines)

    plan_json = plan.model_dump(mode="json")
    warnings: list[str] = list(plan_json.get("warnings") or [])
    for warning in mapping.warnings:
        if warning not in warnings:
            warnings.append(warning)
    plan_json["warnings"] = warnings
    return Accepted(
        plan=plan,
        plan_json=plan_json,
        trip=trip,
        link_health=health.to_json() if health is not None else {},
    )


async def evaluate_submission(
    tool_input: Mapping[str, Any], *, deps: ConsumerDeps
) -> SubmitOutcome:
    """The I/O wrapper: `parse_submission`; the link check (`_check_links`) starts as a task
    while the FX prefetch and `deps.trip_schema.require()` run; `translate_submission(...,
    now=deps.now(), ids=deps.ids())` without verdicts; a Rejected is answered at once and
    cancels the check; an accepted plan waits for the check (at most its deadline) and is
    translated again with `health=`. `TripSchemaUnavailableError` propagates (the plan fails
    with a backend reason; it does not count as the agent's attempt) and cancels the check too.
    A link never rejects the plan, and neither does a failing link check: verdicts only replace
    a URL by its homepage or drop it, and if the second translation still refused the plan the
    first one, without verdicts, is kept (docs/backend-interfaces.md decision 40)."""
    parsed = parse_submission(tool_input)
    if isinstance(parsed, Rejected):
        return parsed
    check = asyncio.ensure_future(_check_links(deps.link_checker, parsed))
    try:
        rates = await deps.fx.prefetch(fx_keys(parsed))
        schema = await deps.trip_schema.require()
        now = deps.now()
        plain = translate_submission(parsed, schema=schema, fx=rates, now=now, ids=deps.ids())
        if isinstance(plain, Rejected):
            return plain
        health = await check
    finally:
        check.cancel()  # a no-op once the check has finished
        await asyncio.wait([check])
    outcome = translate_submission(
        parsed, schema=schema, fx=rates, now=now, ids=deps.ids(), health=health
    )
    if isinstance(outcome, Rejected):
        log.warning("link_health_trip_rejected", stage=outcome.stage)
        return plain
    return outcome


async def _check_links(checker: LinkHealthChecker, plan: Plan) -> LinkHealthMap:
    """`checker.check_plan(plan)`, which never fails because of a URL. An unexpected failure (a
    bug) is logged once, by its class only (the message could carry a URL), and gives no
    verdicts, so the task never ends with an exception nobody retrieves. Cancellation
    propagates."""
    try:
        return await checker.check_plan(plan)
    except Exception as exc:
        log.warning("link_check_failed", error=type(exc).__name__)
        return LinkHealthMap.empty()


def check_result_writes(writes: Mapping[str, str]) -> dict[str, list[str]]:
    """Best-effort validation of the subagents' blackboard files, logged only (spec: "un esito
    malformato si vede nei log anche se il piano passa"). `writes` maps agent name -> the last
    content seen in an `agent.tool_use` named `write` whose path starts with
    `/workspace/results/<agent>.json` (temp files included). Returns agent -> error lines from
    `results.parse_result`. [INFERRED]: the backend cannot read the session filesystem
    directly, so the write tool inputs on thread streams are the only source. Pure."""
    problems: dict[str, list[str]] = {}
    for agent_name, content in writes.items():
        try:
            parse_result(agent_name, content)
        except ValidationError as error:
            problems[agent_name] = describe_validation_errors(error, limit=MAX_ERROR_LINES - 1)
        except ValueError as error:
            problems[agent_name] = [str(error)]
    return problems


# --- the plan's lease across processes ----------------------------------------------------------


def plan_lease_key(plan_id: uuid.UUID) -> int:
    """The `bigint` key of the plan's advisory lock: the first 8 bytes of
    BLAKE2b(`LEASE_NAMESPACE` + the plan id's 16 bytes), signed. The same in every process and
    every version of the backend (a deploy's old and new process must agree on it). Pure."""
    digest = hashlib.blake2b(LEASE_NAMESPACE + plan_id.bytes, digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def _bound_engine(session_factory: async_sessionmaker[AsyncSession]) -> AsyncEngine:
    bind = session_factory.kw.get("bind")
    if not isinstance(bind, AsyncEngine):  # pragma: no cover - a programming error
        msg = "the session factory must be bound to an AsyncEngine"
        raise TypeError(msg)
    return bind


class PlanLease:
    """One plan's consumer lease: `pg_try_advisory_lock(plan_lease_key(plan_id))`, a Postgres
    session-level lock, on a connection of its own held until `release()`.

    The connection comes from a private engine without a pool (`NullPool`, autocommit) on the
    same database, never from the application's pool: a lease is held for a whole plan, and a
    pooled connection held that long would starve the request handlers. No transaction stays
    open on it. Releasing unlocks and closes the physical connection; Postgres also drops the
    lock by itself when the connection dies (a killed process, a dropped network), so a lease
    is never left behind. A connection lost while the consumer runs (a database restart) loses
    the lock silently until the consumer stops: writes stay safe (unique event ids,
    compare-and-set statuses), and the overlap it allows is the same as a redeploy's without
    a lease.
    """

    def __init__(
        self, plan_id: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.plan_id = plan_id
        self.key = plan_lease_key(plan_id)
        self._source = _bound_engine(session_factory)
        self._engine: AsyncEngine | None = None
        self._conn: AsyncConnection | None = None

    @property
    def held(self) -> bool:
        return self._conn is not None

    async def try_acquire(self) -> bool:
        """Take the lock without waiting: True when this lease holds it (now or already),
        False when another connection does. Database errors propagate."""
        if self._conn is not None:
            return True
        engine = create_async_engine(
            self._source.url,
            poolclass=NullPool,
            isolation_level="AUTOCOMMIT",
            hide_parameters=True,
        )
        conn: AsyncConnection | None = None
        try:
            conn = await engine.connect()
            acquired = await conn.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}
            )
        except BaseException:
            await _close_lease_connection(conn, engine)
            raise
        if not acquired:
            await _close_lease_connection(conn, engine)
            return False
        self._engine, self._conn = engine, conn
        return True

    async def release(self) -> None:
        """Unlock and close the connection; a no-op when not held. Never raises (closing the
        connection releases the lock anyway)."""
        conn, engine = self._conn, self._engine
        self._conn = self._engine = None
        if conn is None or engine is None:
            return
        try:
            await conn.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
        except Exception as exc:
            log.warning(
                "plan_lease_unlock_failed", plan_id=str(self.plan_id), error=type(exc).__name__
            )
        await _close_lease_connection(conn, engine)


async def _close_lease_connection(conn: AsyncConnection | None, engine: AsyncEngine) -> None:
    with contextlib.suppress(Exception):
        if conn is not None:
            await conn.close()
    with contextlib.suppress(Exception):
        await engine.dispose()


# --- the consumer -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Received:
    """One event read from a stream (or a thread's backfill)."""

    scope: StreamScope
    raw: RawEvent


@dataclass(frozen=True, slots=True)
class _SessionStreamClosed:
    """The session stream of connection `generation` ended: normally (`error` None, after
    `session.status_terminated` / `session.deleted`) or with an error (reconnect)."""

    generation: int
    error: BaseException | None


_InboxItem = _Received | _SessionStreamClosed


class _ReconnectError(Exception):
    """Internal: the session stream must be opened again (a drop, or a listing that failed)."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause


_RECONNECTABLE = (StreamDisconnectedError, ApiUnavailableError)
"""Errors that make the consumer reopen a stream instead of failing the plan."""


@dataclass(frozen=True, slots=True)
class _Change:
    """What one received event does to the plan, decided before it is stored."""

    update: PlanUpdate | None = None
    target: PlanStatus | None = None
    """The status the event moves the plan to (None: the plan keeps running)."""
    log_reason: str | None = None


class PlanConsumer:
    """Follows one plan's session until the plan leaves `running` (module docstring)."""

    plan_id: uuid.UUID
    session_id: str

    def __init__(
        self,
        plan_id: uuid.UUID,
        session_id: str,
        deps: ConsumerDeps,
        *,
        first_message: str | None = None,
    ) -> None:
        """`first_message` set: a fresh plan (open stream, send it, follow). None: resume (open
        stream, backfill history and threads, follow)."""
        self.plan_id = plan_id
        self.session_id = session_id
        self._deps = deps
        self._first_message = first_message
        self._first_sent = False
        self._sink = EventSink(plan_id, session_factory=deps.session_factory, hub=deps.hub)
        self._log = log.bind(
            plan_id=str(plan_id), session_id=session_id, agent="coordinator", event_type=None
        )
        self._state: ConsumerState | None = None
        self._interrupt_requested = False
        self._started = asyncio.Event()
        self._settled = asyncio.Event()
        self._start_error: BaseException | None = None
        self._done = False
        self._task: asyncio.Task[PlanStatus] | None = None
        self._inbox: asyncio.Queue[_InboxItem] = asyncio.Queue()
        self._generation = 0
        self._session_events_received = False
        self._thread_tasks: dict[str, asyncio.Task[None]] = {}
        self._tool_started: dict[str, dt.datetime] = {}
        self._result_writes: dict[str, str] = {}
        self._thread_backfilled: dict[str, asyncio.Event] = {}
        """Thread id -> set once that thread's history listing is all in the inbox (or its
        task gave up): what the resume and the final drain wait for."""
        self._archive_on_exit = False
        self._interrupt_on_exit = False
        """Set when this consumer failed the plan for a backend-side reason (crash, API errors,
        lost stream) while the session may still be working: `_conclude` sends
        `user.interrupt`, so nobody-followed agents stop spending."""
        self._first_attempted = False
        # True once a session stream was opened: the session exists and has a cost to read.
        self._followed = False
        self._lease: PlanLease | None = None

    # --- public surface ------------------------------------------------------------------------

    async def run(self) -> PlanStatus:
        """The task body. Returns the plan's status when it stops following: `ready`, `failed`,
        `blocked`, `interrupted` or `budget_paused`; `running` only when cancelled (shutdown),
        in which case the next process start resumes it. Never raises except
        `asyncio.CancelledError`: every other failure becomes `failed` with a reason.

        First it takes the plan's lease (`PlanLease`); while another process holds it, it opens
        nothing and tries again every `LEASE_RETRY_SECONDS` as long as the plan is `running`
        (it returns the plan's status once that changes). The lease is released when it stops,
        before `done` turns True."""
        # Cancellation (shutdown, `ConsumerRegistry.stop`) is re-raised, never swallowed: the
        # plan stays `running` in the database and the next process start resumes it.
        with structlog.contextvars.bound_contextvars(
            plan_id=str(self.plan_id), session_id=self.session_id
        ):
            try:
                try:
                    status = await self._run()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    status = await self._finish_on_exception(exc)
                await self._conclude(status)
                return status
            finally:
                self._settled.set()
                try:
                    await self._stop_threads()
                    await self._release_lease()
                finally:
                    self._done = True
                    if not self._started.is_set():
                        if self._start_error is None:
                            self._start_error = ManagedAgentsError(
                                "the consumer stopped before the session started"
                            )
                        self._started.set()

    async def wait_started(self) -> None:
        """Wait until the session stream is open and, for a fresh plan, the first message is
        sent. Re-raises the `ManagedAgentsError` that prevented it (the plan is then already
        `failed`). Callers bound the wait: `async with asyncio.timeout(START_TIMEOUT_SECONDS)`.
        """
        await self._started.wait()
        if self._start_error is not None:
            raise self._start_error

    async def wait_settled(self) -> None:
        """Wait until this consumer stores no more events: right after it stored what its
        streams had already delivered when it took its last decision (`_conclude`), or once it
        stopped for any reason (cancelled, crashed). Never raises. The SSE route waits for it,
        bounded, before sending `event: end` (module docstring, "Settled")."""
        await self._settled.wait()

    def request_interrupt(self) -> None:
        """Note in memory that an interrupt was asked (`sessions.interrupt_plan` has already
        stored `plans.interrupt_requested_at` and sends the API event): the next `end_turn` (or
        `budget_reached`) without an accepted plan becomes `interrupted`, not `failed`. A
        consumer started later reads the same fact from the row."""
        self._interrupt_requested = True
        if self._state is not None:
            self._state.interrupt_requested = True
        self._log.info("interrupt_noted")

    @property
    def done(self) -> bool:
        """True once `run()` returned or was cancelled."""
        return self._done or (self._task is not None and self._task.done())

    @property
    def leased(self) -> bool:
        """True while this consumer holds its plan's lease (it follows the plan)."""
        return self._lease is not None and self._lease.held

    @property
    def state(self) -> ConsumerState | None:
        """What the consumer knows (tests, logs); None before the plan row is read."""
        return self._state

    # --- the lease -----------------------------------------------------------------------------

    async def _acquire_lease(self) -> PlanStatus | None:
        """Take the plan's lease, waiting while another process holds it. None once held; the
        plan's status when it left `running` meanwhile (the other process decided it).

        While it waits, the events the other process stores reach only that process's hub, so
        every period the latest stored event is published on this process's hub (its browsers
        fill the gap from Postgres, see hub.py), and `hub.end` when the plan ended there: a
        browser connected here still follows the plan and gets its `end`."""
        lease = PlanLease(self.plan_id, self._deps.session_factory)
        loop = asyncio.get_running_loop()
        began = loop.time()
        waited = False
        relayed: int | None = None
        while not await lease.try_acquire():
            status = await self._current_status()
            relayed = await self._relay_latest_event(relayed)
            if status is not PlanStatus.RUNNING:
                if status in TERMINAL_STATUSES:
                    self._deps.hub.end(self.plan_id, status)
                self._log.info("plan_lease_not_needed", status=status.value)
                return status
            if not waited:
                self._log.info("plan_lease_busy", retry_seconds=LEASE_RETRY_SECONDS)
                waited = True
            await asyncio.sleep(LEASE_RETRY_SECONDS)
        self._lease = lease
        if waited:
            self._log.info("plan_lease_acquired", waited_seconds=round(loop.time() - began, 1))
        return None

    async def _relay_latest_event(self, relayed: int | None) -> int | None:
        """Publish the plan's latest stored event on this process's hub when its `seq` is above
        `relayed`; returns the latest `seq` published. Subscribers skip what they already sent
        and read a gap from Postgres, so one event is enough to catch them up."""
        async with self._deps.session_factory() as db:
            latest = await load_latest_event(db, self.plan_id)
        if latest is None or (relayed is not None and latest.seq <= relayed):
            return relayed
        self._deps.hub.publish(self.plan_id, latest)
        return latest.seq

    async def _release_lease(self) -> None:
        lease, self._lease = self._lease, None
        if lease is not None:
            # Shielded: a second cancellation must not leave the connection (and the lock) open.
            await asyncio.shield(lease.release())

    # --- the loop ------------------------------------------------------------------------------

    async def _run(self) -> PlanStatus:
        elsewhere = await self._acquire_lease()
        if elsewhere is not None:
            self._started.set()
            return elsewhere
        state = await self._load_state()
        if state.status is not PlanStatus.RUNNING:
            self._log.info("consumer_not_needed", status=state.status.value)
            self._started.set()
            return state.status
        self._log.info("consumer_started", resume=self._first_message is None)
        failures = 0
        while True:
            self._session_events_received = False
            try:
                return await self._connect_and_follow()
            except _ReconnectError as exc:
                if self._session_events_received:
                    failures = 0
                failures += 1
                error_type = getattr(exc.cause, "error_type", None)
                if failures > RECONNECT_ATTEMPTS:
                    self._log.error(
                        "session_stream_lost",
                        failures=failures,
                        error=type(exc.cause).__name__,
                        error_type=error_type,
                    )
                    return await self._finish(REASON_STREAM_LOST, stop_session=True)
                delay = backoff_delay(failures, jitter=random.random())
                self._log.warning(
                    "session_stream_reconnecting",
                    attempt=failures,
                    delay_seconds=round(delay, 2),
                    error=type(exc.cause).__name__,
                    error_type=error_type,
                )
                await self._deps.sleep(delay)

    async def _connect_and_follow(self) -> PlanStatus:
        """One connection of the session stream: open it, send the first message (fresh plan)
        or reconcile with the history (resume, reconnect), then tail. Raises `_ReconnectError`
        for a drop or a failed listing."""
        self._generation += 1
        generation = self._generation
        fresh = self._first_message is not None and not self._first_sent
        async with contextlib.AsyncExitStack() as stack:
            try:
                events = await stack.enter_async_context(
                    self._deps.client.stream_session(self.session_id)
                )
            except _RECONNECTABLE as exc:
                if fresh:
                    raise  # nothing was sent yet: the start fails (the SDK already retried)
                raise _ReconnectError(exc) from exc
            self._followed = True
            reader = asyncio.create_task(
                self._pump_session(events, generation),
                name=f"plan-consumer-{self.plan_id}-session-{generation}",
            )
            stack.push_async_callback(_cancel_and_wait, reader)
            if fresh:
                await self._send_first_message()
                self._first_sent = True
                self._started.set()
                self._log.info("session_started")
            else:
                self._started.set()
                outcome = await self._reconcile()
                if outcome is not None:
                    return outcome
            return await self._tail(generation)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _pump_session(self, events: EventStream, generation: int) -> None:
        error: BaseException | None = None
        try:
            async for raw in events:
                self._inbox.put_nowait(_Received(PRIMARY_SCOPE, raw))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = exc
        self._inbox.put_nowait(_SessionStreamClosed(generation, error))

    async def _tail(self, generation: int) -> PlanStatus:
        while True:
            item = await self._inbox.get()
            if isinstance(item, _SessionStreamClosed):
                if item.generation != generation:
                    continue
                if item.error is not None:
                    raise _ReconnectError(item.error)
                return await self._session_stream_ended()
            if item.scope == PRIMARY_SCOPE:
                self._session_events_received = True
            outcome = await self._handle(item.scope, item.raw)
            if outcome is not None:
                return outcome

    async def _session_stream_ended(self) -> PlanStatus:
        """The session stream ended normally (after `session.status_terminated` or
        `session.deleted`) without a decision taken on this connection."""
        current = await self._current_status()
        if current is not PlanStatus.RUNNING:
            return current
        self._log.warning("session_stream_ended")
        return await self._finish(REASON_SESSION_TERMINATED)

    async def _send_first_message(self) -> None:
        text = cast(str, self._first_message)
        self._first_attempted = True
        for attempt in range(1, FIRST_MESSAGE_ATTEMPTS + 1):
            try:
                await self._deps.client.send_user_message(self.session_id, text)
                return
            except ApiUnavailableError as exc:
                if await self._first_message_in_history():
                    self._log.info("first_message_found_in_history", attempt=attempt)
                    return
                if attempt == FIRST_MESSAGE_ATTEMPTS:
                    raise
                self._log.warning("first_message_retry", attempt=attempt, error_type=exc.error_type)
                await self._deps.sleep(backoff_delay(attempt, jitter=random.random()))

    async def _first_message_in_history(self) -> bool:
        try:
            async for raw in iter_session_history(self._deps.client, self.session_id):
                if raw.get("type") == "user.message":
                    return True
        except ManagedAgentsError:
            return False
        return False

    # --- resume ------------------------------------------------------------------------------

    async def _reconcile(self) -> PlanStatus | None:
        """Resume after a restart or a drop (module docstring, step 6)."""
        state = self._require_state()
        try:
            history = [
                raw async for raw in iter_session_history(self._deps.client, self.session_id)
            ]
        except _RECONNECTABLE as exc:
            # Nothing of this pass was stored or acted on: the next connection reconciles again.
            raise _ReconnectError(exc) from exc

        answered = {
            key
            for raw in history
            if raw.get("type") == "user.custom_tool_result"
            and (key := _text(raw.get("custom_tool_use_id"))) is not None
        }
        tool_uses = [
            raw
            for raw in history
            if raw.get("type") == "agent.custom_tool_use"
            and _text(raw.get("id")) is not None
            and stream_owns(PRIMARY_SCOPE, raw)
        ]
        latest = None
        for index, raw in enumerate(history):
            if raw.get("type") in STATUS_EVENT_TYPES or is_terminal_error(raw):
                latest = index
        deferred: RawEvent | None = None
        for index, raw in enumerate(history):
            if index == latest and _actionable_status(raw):
                deferred = raw
                continue
            await self._handle(PRIMARY_SCOPE, raw, act=False)
        self._log.info(
            "session_reconciled",
            events=len(history),
            pending_tool_uses=sum(1 for raw in tool_uses if raw["id"] not in answered),
        )

        try:
            threads = await self._deps.client.list_threads(self.session_id)
        except _RECONNECTABLE as exc:
            raise _ReconnectError(exc) from exc
        for thread in threads:
            if thread.is_primary:
                continue
            self._register_thread(thread.id, thread.agent_name)
            if thread.archived:
                state.archived_threads.add(thread.id)
            # An archived thread gets no new events: its history is all there is to store.
            self._follow_thread(thread.id, history_only=thread.archived)
        # Every thread's history must be in the inbox before a decision can end the consumer:
        # the final drain stores only what the inbox holds (bounded: a slow listing is logged).
        await self._wait_for_backfills(RESUME_BACKFILL_WAIT_SECONDS)

        for raw in tool_uses:
            tool_use_id = cast(str, raw["id"])
            if tool_use_id in answered or tool_use_id in state.answered_tool_use_ids:
                continue
            outcome = await self._answer_tool_use(raw)
            if outcome is not None:
                return outcome

        if deferred is not None:
            outcome = await self._handle(PRIMARY_SCOPE, deferred)
            if outcome is not None:
                return outcome
        await self._archive_superseded()
        return None

    # --- one event -----------------------------------------------------------------------------

    async def _handle(
        self, scope: StreamScope, raw: RawEvent, *, act: bool = True
    ) -> PlanStatus | None:
        """Store one received event (when this stream owns it) and, with `act`, do what it
        means. Returns the plan's new status when the consumer must stop following."""
        state = self._require_state()
        event_type = _text(raw.get("type"))
        if raw.get("type") == "user.custom_tool_result":
            answered = _text(raw.get("custom_tool_use_id"))
            if answered is not None:
                state.answered_tool_use_ids.add(answered)
        if not stream_owns(scope, raw):
            return None
        key = dedupe_key(raw, plan_id=self.plan_id, scope=scope)
        if key is None:
            return None
        self._observe(scope, raw)
        lane = lane_for(raw, scope=scope, state=state)
        # Every line written while the event is handled (here, ma_client, fx...) names it.
        with structlog.contextvars.bound_contextvars(agent=lane.value, event_type=event_type):
            return await self._handle_owned(scope, raw, key=key, lane=lane, act=act)

    async def _handle_owned(
        self, scope: StreamScope, raw: RawEvent, *, key: str, lane: AgentName, act: bool
    ) -> PlanStatus | None:
        """`_handle` for an event this stream owns (already observed), stored under `key`."""
        state = self._require_state()
        event_type = _text(raw.get("type"))
        if act and not state.accepted and not state.interrupt_requested and _actionable_status(raw):
            await self._refresh_interrupt_request()
        change = self._plan_change(raw, act=act)
        duration = self._duration_ms(raw)
        cost = state.cost_cents
        result = await self._sink.emit(
            lambda seq: _ui_event(raw, seq=seq, agent=lane, cost_cents=cost, duration_ms=duration),
            ma_event_id=key,
            update=change.update,
        )
        if result.duplicate or not act:
            return None
        bound = self._log.bind(agent=lane.value, event_type=event_type)

        match event_type:
            case "session.thread_created":
                thread_id = _text(raw.get("session_thread_id"))
                if thread_id is not None:
                    self._follow_thread(thread_id)
                await self._archive_superseded()
            case "session.thread_status_idle":
                await self._archive_superseded()
            case "agent.custom_tool_use" if scope == PRIMARY_SCOPE:
                return await self._answer_tool_use(raw)
            case "session.status_rescheduled":
                bound.info("session_rescheduled")
            case "session.error" if change.target is None:
                error = _mapping(raw.get("error"))
                bound.warning(
                    "session_error",
                    error_type=_text(error.get("type")),
                    retry_status=_text(_mapping(error.get("retry_status")).get("type")),
                )
            case _:
                pass

        if change.target is None:
            if change.log_reason is not None:
                bound.info("session_idle_waiting", stop_reason=change.log_reason)
            return None
        if not result.status_applied:
            current = await self._current_status()
            bound.warning(
                "plan_status_not_applied", wanted=change.target.value, current=current.value
            )
            return current if current is not PlanStatus.RUNNING else None
        return self._decided(change.target, bound, change.log_reason)

    async def _refresh_interrupt_request(self) -> None:
        """Before a status decision: an interrupt may have been asked through another process
        (a redeploy's overlap: the request reached the process that does not hold the lease),
        which stored `plans.interrupt_requested_at` but could not tell this consumer."""
        async with self._deps.session_factory() as db:
            requested = await db.scalar(
                select(PlanRecord.interrupt_requested_at).where(PlanRecord.id == self.plan_id)
            )
        if requested is not None:
            self._require_state().interrupt_requested = True
            self._log.info("interrupt_noted_from_row")

    def _decided(self, target: PlanStatus, bound: Any, log_reason: str | None) -> PlanStatus:
        state = self._require_state()
        state.status = target
        if target in (PlanStatus.READY, PlanStatus.INTERRUPTED):
            self._archive_on_exit = True
        level = "info" if target in (PlanStatus.READY, PlanStatus.BUDGET_PAUSED) else "warning"
        getattr(bound, level)("plan_status_changed", status=target.value, reason=log_reason)
        return target

    def _observe(self, scope: StreamScope, raw: RawEvent) -> None:
        """Track what an owned event tells about the session (no I/O, idempotent)."""
        state = self._require_state()
        event_type = raw.get("type")
        if event_type == "agent.custom_tool_use":
            # Only the coordinator's uses are answered (subagents have no custom tool): one on a
            # thread that a `requires_action` idle waits on is a block, never a wait.
            tool_use_id = _text(raw.get("id"))
            if tool_use_id is not None and scope == PRIMARY_SCOPE:
                state.custom_tool_use_ids.add(tool_use_id)
        elif event_type == "session.thread_created":
            self._register_thread(raw.get("session_thread_id"), raw.get("agent_name"))
        elif event_type == "session.thread_status_idle":
            thread_id = _text(raw.get("session_thread_id"))
            if thread_id is not None:
                if _text(_mapping(raw.get("stop_reason")).get("type")) == "end_turn":
                    state.idle_threads.add(thread_id)
                else:
                    state.idle_threads.discard(thread_id)
        elif event_type in PRIMARY_OWNED_TYPES and str(event_type).startswith("session.thread_"):
            thread_id = _text(raw.get("session_thread_id"))
            if thread_id is not None:
                state.idle_threads.discard(thread_id)
        elif event_type == "session.usage":
            usage = usage_from_event(raw)
            if usage is not None and usage.list_cost_cents is not None:
                state.cost_cents = max(state.cost_cents or 0, usage.list_cost_cents)
        elif event_type in ("agent.tool_use", "agent.mcp_tool_use"):
            tool_use_id = _text(raw.get("id"))
            started = _parse_instant(raw.get("processed_at"))
            if tool_use_id is not None and started is not None:
                self._tool_started[tool_use_id] = started
            if event_type == "agent.tool_use" and raw.get("name") == "write":
                self._note_result_write(_mapping(raw.get("input")))
            server = _text(raw.get("mcp_server_name"))
            if event_type == "agent.mcp_tool_use" and server is not None:
                state.mcp_servers[server] = lane_for(raw, scope=scope, state=state)

    def _note_result_write(self, tool_input: Mapping[str, Any]) -> None:
        path = _text(tool_input.get("file_path")) or _text(tool_input.get("path"))
        content = tool_input.get("content")
        if path is None or not isinstance(content, str):
            return
        match = RESULTS_PATH.match(path)
        if match is not None:
            self._result_writes[match.group("agent")] = content

    def _duration_ms(self, raw: RawEvent) -> int | None:
        event_type = raw.get("type")
        if event_type == "agent.tool_result":
            tool_use_id = _text(raw.get("tool_use_id"))
        elif event_type == "agent.mcp_tool_result":
            tool_use_id = _text(raw.get("mcp_tool_use_id"))
        else:
            return None
        started = self._tool_started.pop(tool_use_id, None) if tool_use_id else None
        ended = _parse_instant(raw.get("processed_at"))
        if started is None or ended is None:
            return None
        return max(0, int((ended - started).total_seconds() * 1000))

    def _plan_change(self, raw: RawEvent, *, act: bool) -> _Change:
        """The `PlanUpdate` stored with `raw`: the cost of a `session.usage` always, a status
        change only when the event is acted on (`act`)."""
        state = self._require_state()
        event_type = raw.get("type")
        if event_type == "session.usage":
            usage = usage_from_event(raw)
            if usage is not None and usage.list_cost_cents is not None:
                return _Change(update=PlanUpdate(cost_cents=usage.list_cost_cents))
            return _Change()
        if not act:
            return _Change()
        if event_type == "session.status_idle":
            outcome = decide_idle(raw, state)
            target = _IDLE_TARGETS.get(outcome.decision)
            if target is None:
                return _Change(log_reason=outcome.log_reason)
            change = StatusChange(target, reason=outcome.reason)
            return _Change(PlanUpdate(status=change), target, outcome.log_reason)
        if event_type == "session.status_terminated":
            return self._session_over(REASON_SESSION_TERMINATED, "terminated")
        if event_type == "session.deleted":
            return self._session_over(REASON_SESSION_DELETED, "deleted")
        if is_terminal_error(raw):
            error_type = _text(_mapping(raw.get("error")).get("type"))
            return self._session_over(REASON_SESSION_ERROR, f"error:{error_type}")
        return _Change()

    def _session_over(self, reason: str, log_reason: str) -> _Change:
        """The session ended (terminated, deleted or a terminal error) on its own."""
        state = self._require_state()
        if state.accepted:
            target, failure = PlanStatus.READY, None
        elif state.interrupt_requested:
            target, failure = PlanStatus.INTERRUPTED, REASON_INTERRUPTED
        else:
            target, failure = PlanStatus.FAILED, reason
        change = StatusChange(target, reason=failure)
        return _Change(PlanUpdate(status=change), target, log_reason)

    # --- submit_plan -------------------------------------------------------------------------

    async def _answer_tool_use(self, raw: RawEvent) -> PlanStatus | None:
        """Answer one `agent.custom_tool_use` (live or pending on resume): from the recorded
        outcome when there is one, else by evaluating it (submit_plan) once."""
        state = self._require_state()
        tool_use_id = cast(str, raw.get("id"))
        name = _text(raw.get("name"))
        bound = self._log.bind(event_type="agent.custom_tool_use")
        key = backend_event_id(self.plan_id, "submit", tool_use_id)
        stored = await self._stored_answer(key)
        if stored is not None:
            bound.info("tool_use_answered_from_record", tool=name)
            await self._send_tool_result(tool_use_id, *stored)
            return None

        if name != SUBMIT_PLAN_TOOL:
            answer = UNKNOWN_TOOL_TEXT.format(name=name or "")
            title = f"Strumento sconosciuto richiesto: {name or 'senza nome'}"
            bound.warning("unknown_custom_tool", tool=(name or "")[:64])
            return await self._record_answer(
                key,
                tool_use_id,
                EventKind.ERROR,
                title,
                answer,
                is_error=True,
                outcome="unknown_tool",
            )
        if state.accepted:
            bound.info("submit_plan_after_acceptance")
            return await self._record_answer(
                key,
                tool_use_id,
                EventKind.PLAN,
                TITLE_PLAN_ALREADY_ACCEPTED,
                PLAN_ALREADY_ACCEPTED_TEXT,
                is_error=False,
                outcome="already_accepted",
            )

        tool_input = raw.get("input")
        try:
            outcome = await evaluate_submission(
                cast(Mapping[str, Any], tool_input), deps=self._deps
            )
        except TripSchemaUnavailableError:
            bound.error("trip_schema_unavailable")
            return await self._schema_unavailable(tool_use_id)
        self._log_result_writes()

        attempt = state.submit_attempts + 1
        if isinstance(outcome, Accepted):
            update = PlanUpdate(
                submit_attempts_increment=1,
                plan=outcome.plan_json,
                trip=outcome.trip,
                link_health=outcome.link_health,
            )
            result = await self._emit_outcome(
                key,
                EventKind.PLAN,
                TITLE_PLAN_ACCEPTED,
                {
                    "tool_use_id": tool_use_id,
                    "outcome": "accepted",
                    "attempt": attempt,
                    "warnings": len(outcome.plan_json.get("warnings") or []),
                    "is_error": False,
                    "answer": PLAN_ACCEPTED_TEXT,
                },
                update,
            )
            if result.duplicate:
                return await self._resend_recorded(key, tool_use_id)
            state.accepted = True
            state.submit_attempts = attempt
            bound.info("submit_plan_accepted", attempt=attempt)
            await self._send_tool_result(tool_use_id, PLAN_ACCEPTED_TEXT, False)
            return None

        failures = state.failed_submissions + 1
        last = failures >= MAX_FAILED_SUBMISSIONS
        answer = outcome.message
        if last:
            answer += "\n\n" + NO_ATTEMPTS_LEFT_TEXT.format(count=failures)
        count = len(outcome.errors)
        problems = "problema" if count == 1 else "problemi"
        if last:
            title = f"Piano respinto {failures} volte: tentativi esauriti"
        else:
            title = (
                f"Piano respinto: {count} {problems} da correggere "
                f"(tentativo {failures} di {MAX_FAILED_SUBMISSIONS})"
            )
        status = (
            StatusChange(PlanStatus.FAILED, reason=REASON_TOO_MANY_REJECTIONS) if last else None
        )
        detail: dict[str, Any] = {
            "tool_use_id": tool_use_id,
            "outcome": "rejected",
            "stage": outcome.stage,
            "attempt": attempt,
            "failed_submissions": failures,
            "errors": outcome.errors,
            "is_error": True,
            "answer": answer,
        }
        if status is not None:
            # Like the backend's status events: the web app re-reads GET /plans/{id} on it.
            detail["plan_status"] = status.to.value
        result = await self._emit_outcome(
            key,
            EventKind.PLAN,
            title,
            detail,
            PlanUpdate(submit_attempts_increment=1, status=status),
        )
        if result.duplicate:
            return await self._resend_recorded(key, tool_use_id)
        state.submit_attempts = attempt
        state.failed_submissions = failures
        bound.warning(
            "submit_plan_rejected", attempt=attempt, stage=outcome.stage, errors=count, last=last
        )
        await self._send_tool_result(tool_use_id, answer, True)
        if not last:
            return None
        if not result.status_applied:
            current = await self._current_status()
            return current if current is not PlanStatus.RUNNING else None
        await self._interrupt_quietly()
        return self._decided(PlanStatus.FAILED, bound, "too_many_rejections")

    async def _record_answer(
        self,
        key: str,
        tool_use_id: str,
        kind: EventKind,
        title: str,
        answer: str,
        *,
        is_error: bool,
        outcome: str,
    ) -> PlanStatus | None:
        detail = {
            "tool_use_id": tool_use_id,
            "outcome": outcome,
            "is_error": is_error,
            "answer": answer,
        }
        result = await self._emit_outcome(key, kind, title, detail, None)
        if result.duplicate:
            return await self._resend_recorded(key, tool_use_id)
        await self._send_tool_result(tool_use_id, answer, is_error)
        return None

    async def _emit_outcome(
        self,
        key: str,
        kind: EventKind,
        title: str,
        detail: Mapping[str, Any],
        update: PlanUpdate | None,
    ) -> EmitResult:
        state = self._require_state()
        payload = {"event_type": "backend.submit_plan", **detail}
        return await self._sink.emit(
            backend_event(
                kind, title, ts=self._deps.now(), detail=payload, cost_cents=state.cost_cents
            ),
            ma_event_id=key,
            update=update,
        )

    async def _resend_recorded(self, key: str, tool_use_id: str) -> None:
        stored = await self._stored_answer(key)
        if stored is not None:
            await self._send_tool_result(tool_use_id, *stored)

    async def _stored_answer(self, key: str) -> tuple[str, bool] | None:
        """The answer recorded under `key` (`backend:<plan>:submit:<tool use id>`), if any."""
        async with self._deps.session_factory() as db:
            row = (
                await db.execute(select(EventRecord.detail).where(EventRecord.ma_event_id == key))
            ).first()
        if row is None:
            return None
        detail = _mapping(row[0])
        answer = _text(detail.get("answer")) or PLAN_ALREADY_ACCEPTED_TEXT
        return answer, detail.get("is_error") is True

    async def _send_tool_result(self, tool_use_id: str, content: str, is_error: bool) -> None:
        await self._deps.client.send_custom_tool_result(
            self.session_id, tool_use_id, content, is_error
        )
        self._require_state().answered_tool_use_ids.add(tool_use_id)

    async def _schema_unavailable(self, tool_use_id: str) -> PlanStatus:
        status = await self._finish(
            REASON_SCHEMA_UNAVAILABLE, event_key=f"schema-unavailable:{tool_use_id}"
        )
        if status is PlanStatus.FAILED:
            with contextlib.suppress(ManagedAgentsError):
                await self._send_tool_result(tool_use_id, SCHEMA_UNAVAILABLE_TEXT, True)
            await self._interrupt_quietly()
        return status

    async def _interrupt_quietly(self) -> None:
        try:
            await self._deps.client.send_interrupt(self.session_id)
        except ManagedAgentsError as exc:
            self._log.warning("interrupt_send_failed", error_type=exc.error_type)

    def _log_result_writes(self) -> None:
        for agent_name, lines in check_result_writes(self._result_writes).items():
            paths = sorted({line.split(":", 1)[0] for line in lines})[:10]
            self._log.warning(
                "result_file_invalid",
                agent=agent_name[:32],
                event_type="agent.tool_use",
                errors=len(lines),
                paths=paths,
            )

    # --- threads -----------------------------------------------------------------------------

    def _register_thread(self, thread_id: Any, agent_name: Any) -> None:
        state = self._require_state()
        if not isinstance(thread_id, str) or not thread_id or thread_id in state.threads:
            return
        state.threads[thread_id] = _lane(agent_name) or AgentName.COORDINATOR
        state.thread_order.append((thread_id, agent_name if isinstance(agent_name, str) else ""))

    def _follow_thread(self, thread_id: str, *, history_only: bool = False) -> None:
        task = self._thread_tasks.get(thread_id)
        if task is not None and not task.done():
            return
        backfilled = asyncio.Event()
        self._thread_backfilled[thread_id] = backfilled
        self._thread_tasks[thread_id] = asyncio.create_task(
            self._thread_loop(thread_id, backfilled, history_only=history_only),
            name=f"plan-consumer-{self.plan_id}-thread-{thread_id}",
        )

    async def _thread_loop(
        self, thread_id: str, backfilled: asyncio.Event, *, history_only: bool = False
    ) -> None:
        """Follow one thread: open its stream, THEN backfill its history (thread streams don't
        replay), then tail; reconnect with backoff. With `history_only` (an archived thread,
        which gets no new events) only the history is read. Thread events never change the
        plan, so a thread that can't be followed is logged and given up (the next session
        reconnect retries it). `backfilled` is set once the history is all in the inbox, and
        whenever the task ends (given up, failed, cancelled), so nobody waits on it forever."""
        lane = self._require_state().threads.get(thread_id, AgentName.COORDINATOR).value
        bound = self._log.bind(agent=lane)
        # This task runs in a copy of the context it was created in (the handling of the
        # thread's `session.thread_created`): name the thread's lane, no event.
        structlog.contextvars.bind_contextvars(agent=lane, event_type=None)
        failures = 0
        try:
            while True:
                received = False
                try:
                    if history_only:
                        await self._backfill_thread(thread_id)
                        return
                    async with self._deps.client.stream_thread(
                        self.session_id, thread_id
                    ) as events:
                        await self._backfill_thread(thread_id)
                        backfilled.set()
                        async for raw in events:
                            received = True
                            self._inbox.put_nowait(_Received(thread_id, raw))
                    return
                except asyncio.CancelledError:
                    raise
                except _RECONNECTABLE as exc:
                    if received:
                        failures = 0
                    failures += 1
                    if failures > RECONNECT_ATTEMPTS:
                        bound.warning("thread_stream_lost", thread_id=thread_id, failures=failures)
                        return
                    delay = backoff_delay(failures, jitter=random.random())
                    bound.info(
                        "thread_stream_reconnecting",
                        thread_id=thread_id,
                        attempt=failures,
                        error=type(exc).__name__,
                    )
                    await self._deps.sleep(delay)
                except Exception as exc:
                    bound.warning(
                        "thread_stream_failed", thread_id=thread_id, error=type(exc).__name__
                    )
                    if not backfilled.is_set():
                        # The stream can't be followed (e.g. refused for a session that has
                        # ended), but what the thread already did is still in its history.
                        with contextlib.suppress(Exception):
                            await self._backfill_thread(thread_id)
                    return
        finally:
            backfilled.set()

    async def _backfill_thread(self, thread_id: str) -> None:
        """Put the thread's whole history in the inbox (ids already stored are skipped when
        handled)."""
        async for raw in iter_thread_history(self._deps.client, self.session_id, thread_id):
            self._inbox.put_nowait(_Received(thread_id, raw))

    async def _wait_for_backfills(self, bound_seconds: float) -> None:
        """Wait, at most `bound_seconds`, until every followed thread's history listing is in
        the inbox; the threads still listing after that are logged (their late events are
        stored only if the consumer is still running when they arrive)."""
        pending = {
            thread_id: event
            for thread_id, event in self._thread_backfilled.items()
            if not event.is_set()
        }
        if not pending:
            return
        try:
            async with asyncio.timeout(bound_seconds):
                for event in pending.values():
                    await event.wait()
        except TimeoutError:
            late = sorted(thread_id for thread_id, event in pending.items() if not event.is_set())
            self._log.warning("thread_backfill_late", threads=late, waited_seconds=bound_seconds)

    async def _archive_superseded(self) -> None:
        state = self._require_state()
        for thread_id in superseded_threads(state):
            state.archived_threads.add(thread_id)
            try:
                await self._deps.client.archive_thread(self.session_id, thread_id)
            except ManagedAgentsError as exc:
                self._log.warning(
                    "thread_archive_failed", thread_id=thread_id, error_type=exc.error_type
                )
            else:
                self._log.info("thread_archived", thread_id=thread_id)

    async def _stop_threads(self) -> None:
        tasks = [task for task in self._thread_tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- ending ------------------------------------------------------------------------------

    async def _conclude(self, status: PlanStatus) -> None:
        """After the last decision: wait (bounded) for thread backfills still in flight, store
        what the streams already delivered (no more actions) and signal `wait_settled()`;
        then stop a session this consumer failed for a backend-side reason
        (`user.interrupt`), read the session's final list cost (no event), and archive a
        `ready` or `interrupted` session."""
        try:
            await self._wait_for_backfills(SETTLE_BACKFILL_WAIT_SECONDS)
            await self._drain()
        except Exception as exc:
            self._log.warning("drain_failed", error=type(exc).__name__)
        finally:
            self._settled.set()  # nothing is stored after this: browsers may get `end`
        if self._interrupt_on_exit:
            await self._interrupt_quietly()
        if self._followed or self._interrupt_on_exit:
            await self._refresh_cost()
        if self._archive_on_exit and status in (PlanStatus.READY, PlanStatus.INTERRUPTED):
            try:
                await archive_when_idle(self._deps.client, self.session_id)
            except Exception as exc:
                self._log.warning(
                    "session_archive_failed",
                    error=type(exc).__name__,
                    error_type=getattr(exc, "error_type", None),
                )
            else:
                self._log.info("session_archived", status=status.value)
        self._log.info("consumer_stopped", status=status.value)

    async def _refresh_cost(self) -> None:
        """Raise `plans.cost_cents` to the session's list cost from `retrieve_session` (notes
        §2d: `list_cost` from `session.usage`, else `sessions.retrieve`): a cost that no
        `session.usage` event reached the consumer with still counts toward the monthly limit.
        Stores no event; a failure is logged, never fatal. Never lowers the stored cost
        (`record_session_cost`)."""
        state = self._state
        known = state.cost_cents if state is not None else None
        cost = await record_session_cost(
            self._deps.client, self._sink, self.session_id, known_cents=known
        )
        if cost is not None and state is not None and cost > (state.cost_cents or 0):
            state.cost_cents = cost

    async def _drain(self) -> None:
        if self._state is None:
            return
        while True:
            try:
                item = self._inbox.get_nowait()
            except asyncio.QueueEmpty:
                return
            if isinstance(item, _Received):
                await self._handle(item.scope, item.raw, act=False)

    async def _finish(
        self, reason: str, *, event_key: str | None = None, stop_session: bool = False
    ) -> PlanStatus:
        """End the plan for a reason no event carries (lost stream, API errors, ...): `failed`
        with `reason`, or `ready` when a plan was already accepted (its Trip is stored).

        `stop_session`: the failure is the backend's, not the session's, so the agents may
        still be working (and spending) with nobody following them: when this call moves the
        plan to `failed`, `_conclude` sends `user.interrupt` (best effort) after the settle.
        Not for a fresh plan whose brief was never sent (nothing runs)."""
        state = self._state
        accepted = state is not None and state.accepted
        target = PlanStatus.READY if accepted else PlanStatus.FAILED
        change = StatusChange(target, reason=None if accepted else reason)
        key = event_key or f"{target.value}:{uuid.uuid4()}"
        result = await set_plan_status(
            self._deps.session_factory,
            self._deps.hub,
            self.plan_id,
            change,
            title=TITLE_READY if accepted else TITLE_FAILED,
            event_key=key,
        )
        if not result.status_applied:
            return await self._current_status()
        brief_never_sent = self._first_message is not None and not self._first_attempted
        if stop_session and target is PlanStatus.FAILED and not brief_never_sent:
            self._interrupt_on_exit = True
        return self._decided(target, self._log, None if accepted else reason)

    async def _finish_on_exception(self, exc: Exception) -> PlanStatus:
        if isinstance(exc, PlanNotFoundError):
            self._log.warning("plan_row_missing")
            self._set_start_error(exc)
            return PlanStatus.FAILED
        if isinstance(exc, ManagedAgentsError):
            reason = _reason_for(exc)
            self._log.error(
                "managed_agents_error",
                error=type(exc).__name__,
                status_code=exc.status_code,
                error_type=exc.error_type,
            )
        else:
            reason = REASON_INTERNAL
            self._log.exception("consumer_crashed", error=type(exc).__name__)
        try:
            return await self._finish(reason, stop_session=True)
        except Exception:
            self._log.exception("plan_fail_write_failed")
            return PlanStatus.FAILED
        finally:
            # Only now: `wait_started` promises the plan is already `failed` when it raises.
            self._set_start_error(exc)

    def _set_start_error(self, exc: Exception) -> None:
        if self._started.is_set():
            return
        if isinstance(exc, ManagedAgentsError | PlanNotFoundError):
            self._start_error = exc
        else:
            error = ManagedAgentsError(f"the consumer failed to start: {type(exc).__name__}")
            error.__cause__ = exc
            self._start_error = error
        self._started.set()

    # --- state -------------------------------------------------------------------------------

    async def _load_state(self) -> ConsumerState:
        async with self._deps.session_factory() as db:
            plan = await db.get(PlanRecord, self.plan_id)
        if plan is None:
            raise PlanNotFoundError(str(self.plan_id))
        accepted = plan.plan is not None
        attempts = plan.submit_attempts or 0
        self._state = ConsumerState(
            status=PlanStatus(plan.status),
            submit_attempts=attempts,
            failed_submissions=max(0, attempts - (1 if accepted else 0)),
            accepted=accepted,
            cost_cents=plan.cost_cents if plan.cost_cents else None,
            interrupt_requested=self._interrupt_requested
            or plan.interrupt_requested_at is not None,
        )
        return self._state

    async def _current_status(self) -> PlanStatus:
        async with self._deps.session_factory() as db:
            status = await db.scalar(select(PlanRecord.status).where(PlanRecord.id == self.plan_id))
        if status is None:
            raise PlanNotFoundError(str(self.plan_id))
        current = PlanStatus(status)
        if self._state is not None:
            self._state.status = current
        return current

    def _require_state(self) -> ConsumerState:
        if self._state is None:  # pragma: no cover - a programming error
            msg = "the consumer state is not loaded yet"
            raise RuntimeError(msg)
        return self._state


_IDLE_TARGETS: dict[IdleDecision, PlanStatus] = {
    IdleDecision.READY: PlanStatus.READY,
    IdleDecision.INTERRUPTED: PlanStatus.INTERRUPTED,
    IdleDecision.BUDGET_PAUSED: PlanStatus.BUDGET_PAUSED,
    IdleDecision.BLOCKED: PlanStatus.BLOCKED,
    IdleDecision.FAILED: PlanStatus.FAILED,
}


def _actionable_status(raw: RawEvent) -> bool:
    """A status event that can change the plan (as opposed to running/rescheduled)."""
    return raw.get("type") in (
        "session.status_idle",
        "session.status_terminated",
        "session.deleted",
    ) or is_terminal_error(raw)


def _ui_event(
    raw: RawEvent,
    *,
    seq: int,
    agent: AgentName,
    cost_cents: int | None,
    duration_ms: int | None,
) -> UIEvent | None:
    """`normalize`, never None (nor an exception) for the events the consumer acts on."""
    event_type = _text(raw.get("type"))
    try:
        event = normalize(raw, seq=seq, agent=agent, cost_cents=cost_cents, duration_ms=duration_ms)
    except Exception:
        log.exception("normalize_failed", event_type=event_type)
        event = None
    if event is not None or event_type in NOISE_EVENT_TYPES:
        return event
    # Never lose an event (an action event above all: "seen implies handled").
    return UIEvent(
        seq=seq,
        ts=_parse_instant(raw.get("processed_at")) or clock.now(),
        agent=agent,
        kind=EventKind.STATUS,
        title=one_line(f"Evento {event_type or 'senza tipo'}"),
        detail={"event_type": event_type},
        cost_cents=cost_cents,
    )


def _reason_for(exc: ManagedAgentsError) -> str:
    if isinstance(exc, SessionNotFoundError):
        return REASON_SESSION_NOT_FOUND
    if isinstance(exc, ApiRejectedError):
        return REASON_API_REJECTED
    if isinstance(exc, StreamDisconnectedError):
        return REASON_STREAM_LOST
    return REASON_API_UNAVAILABLE


async def _cancel_and_wait(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


class ConsumerAlreadyRunningError(Exception):
    """`ConsumerRegistry.start` was called for a plan that already has a live consumer."""


class ConsumerRegistry:
    """The process's consumers by plan id (`sessions.PlannerServices.registry`). A consumer it
    starts follows the plan only once it holds the plan's lease (`PlanLease`); until then it is
    live here but waits (another process follows the plan)."""

    def __init__(self, deps: ConsumerDeps) -> None:
        self._deps = deps
        self._consumers: dict[uuid.UUID, PlanConsumer] = {}
        self._tasks: dict[uuid.UUID, asyncio.Task[PlanStatus]] = {}

    @property
    def deps(self) -> ConsumerDeps:
        return self._deps

    def start(
        self, plan_id: uuid.UUID, session_id: str, *, first_message: str | None = None
    ) -> PlanConsumer:
        """Create the consumer and its task (named `plan-consumer-<plan_id>`); the registry
        forgets it when the task ends. Raises `ConsumerAlreadyRunningError` if one is live."""
        if self.get(plan_id) is not None:
            msg = f"plan {plan_id} already has a live consumer"
            raise ConsumerAlreadyRunningError(msg)
        consumer = PlanConsumer(plan_id, session_id, self._deps, first_message=first_message)
        task = asyncio.get_running_loop().create_task(
            consumer.run(), name=f"plan-consumer-{plan_id}"
        )
        consumer._task = task  # pyright: ignore[reportPrivateUsage]
        self._consumers[plan_id] = consumer
        self._tasks[plan_id] = task

        def forget(finished: asyncio.Task[PlanStatus]) -> None:
            if self._tasks.get(plan_id) is finished:
                del self._tasks[plan_id]
                self._consumers.pop(plan_id, None)
            if not finished.cancelled() and finished.exception() is not None:
                log.error(
                    "consumer_task_crashed",
                    plan_id=str(plan_id),
                    session_id=session_id,
                    error=type(finished.exception()).__name__,
                )

        task.add_done_callback(forget)
        return consumer

    def get(self, plan_id: uuid.UUID) -> PlanConsumer | None:
        """The live consumer of `plan_id`, if any."""
        consumer = self._consumers.get(plan_id)
        if consumer is None or consumer.done:
            return None
        return consumer

    async def stop(self, plan_id: uuid.UUID, *, grace_seconds: float = 10.0) -> None:
        """Cancel the plan's task and wait for it, at most `grace_seconds` (streams closed; the
        plan's status untouched). No-op when none is live."""
        task = self._tasks.get(plan_id)
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.wait({task}, timeout=grace_seconds)

    def active_plan_ids(self) -> list[uuid.UUID]:
        return [plan_id for plan_id, task in self._tasks.items() if not task.done()]

    async def aclose(self) -> None:
        """Cancel every consumer (application shutdown). Their plans stay `running` and are
        resumed by the next process (`sessions.resume_running_plans`)."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=10.0)
