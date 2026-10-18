"""The plan consumer (app/consumer.py): pure decisions, `EventSink`, submit_plan, and every
shipped Managed Agents scenario played end to end through `FakeManagedAgentsClient`.

Everything is offline: the fake replaces Managed Agents, trip.json is the vendored copy loaded
through a `file://` URL, the FX converter runs cache-only, and backoff sleeps are recorded
instead of slept. The resume cases (the spec's "Ripresa" row) are in test_consumer_resume.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import datetime as dt
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import LogCapture
from structlog.typing import EventDict

from app import consumer as consumer_module
from app.config import Settings
from app.consumer import (
    MAX_FAILED_SUBMISSIONS,
    PLAN_ACCEPTED_TEXT,
    PLAN_ALREADY_ACCEPTED_TEXT,
    REASON_END_TURN_WITHOUT_PLAN,
    REASON_INTERNAL,
    REASON_SCHEMA_UNAVAILABLE,
    REASON_SESSION_ERROR,
    REASON_STREAM_LOST,
    REASON_TOO_MANY_REJECTIONS,
    REASON_UNEXPECTED_CONFIRMATION,
    RECONNECT_ATTEMPTS,
    Accepted,
    ConsumerAlreadyRunningError,
    ConsumerDeps,
    ConsumerRegistry,
    ConsumerState,
    EventSink,
    IdleDecision,
    PlanConsumer,
    PlanNotFoundError,
    PlanUpdate,
    Rejected,
    StatusChange,
    backend_event,
    backend_event_id,
    backoff_delay,
    check_result_writes,
    decide_idle,
    dedupe_key,
    evaluate_submission,
    is_terminal_error,
    lane_for,
    load_events_after,
    parse_submission,
    set_plan_status,
    stream_owns,
    superseded_threads,
    translate_submission,
)
from app.db import EventRecord, PlanRecord, PlanStatus
from app.events import AgentName, EventKind, UIEvent
from app.fx import FxConverter, FxRates
from app.hub import PlanEnded, PlanHub
from app.link_health import NO_LINK_CHECKS, LinkHealth, LinkHealthMap
from app.ma_client import PRIMARY_SCOPE, RawEvent, SessionNotFoundError
from app.mapping import SeededTripIds
from app.plan import Plan
from app.triptracker_schema import (
    DEV_FALLBACK_SCHEMA_PATH,
    TripSchema,
    TripSchemaStore,
    TripSchemaUnavailableError,
    load_dev_fallback_schema,
)
from tests.fakes import FIXTURES_ROOT, FakeManagedAgentsClient

ROME = ZoneInfo("Europe/Rome")
NOW = dt.datetime(2026, 10, 12, 12, 30, tzinfo=ROME)
"""The frozen clock of every consumer here (the scenarios run on 2026-10-12)."""
SID = "sesn_fake_0001"
BRIEF = (
    "Today is 2026-10-12 (Europe/Rome).\n\nAll user-facing text (titles, notes, summary, "
    "warnings) must be in Italian.\n\n```json\n{}\n```\n\nSave this JSON verbatim to "
    "/workspace/shared/request.json before delegating."
)
VALID_PLAN_PATH = FIXTURES_ROOT / "ma" / "plans" / "lisbon_valid.json"
RUN_TIMEOUT = 20.0


def valid_plan_input() -> dict[str, Any]:
    return json.loads(VALID_PLAN_PATH.read_text(encoding="utf-8"))


# --- harness ------------------------------------------------------------------------------------


class RecordingHub(PlanHub):
    """The real hub, also recording what the sink published (after commit) and ended."""

    def __init__(self) -> None:
        super().__init__()
        self.published: list[UIEvent] = []
        self.ended: list[tuple[uuid.UUID, PlanStatus]] = []

    def publish(self, plan_id: uuid.UUID, event: UIEvent) -> None:
        self.published.append(event)
        super().publish(plan_id, event)

    def end(self, plan_id: uuid.UUID, status: PlanStatus) -> None:
        self.ended.append((plan_id, status))
        super().end(plan_id, status)


class UnavailableSchemaStore:
    """A `TripSchemaStore` stand-in whose schema never loads."""

    async def require(self) -> TripSchema:
        raise TripSchemaUnavailableError("trip.json is not available (test)")


class BlockingFx:
    """An `FxConverter` stand-in whose prefetch blocks until released (a process killed
    mid-evaluation)."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def prefetch(self, keys: Any) -> FxRates:
        self.entered.set()
        await self.release.wait()
        return FxRates()


@dataclass
class Harness:
    """A consumer's dependencies over the fake, the test database and the vendored schema."""

    factory: async_sessionmaker[AsyncSession]
    fake: FakeManagedAgentsClient
    deps: ConsumerDeps
    hub: RecordingHub
    sleeps: list[float] = field(default_factory=list[float])

    async def create_plan(
        self,
        *,
        status: PlanStatus = PlanStatus.RUNNING,
        session_id: str | None = SID,
        **fields: Any,
    ) -> uuid.UUID:
        plan_id = uuid.uuid4()
        request = self.fake.meta.get("request") or {"origin": "Milano"}
        async with self.factory() as db:
            db.add(
                PlanRecord(
                    id=plan_id,
                    user_email="test@example.com",
                    session_id=session_id,
                    agent_profile="development",
                    status=status.value,
                    request=request,
                    budget_cents=60,
                    **fields,
                )
            )
            await db.commit()
        return plan_id

    def consumer(self, plan_id: uuid.UUID, *, fresh: bool = True) -> PlanConsumer:
        return PlanConsumer(plan_id, SID, self.deps, first_message=BRIEF if fresh else None)

    async def run(self, plan_id: uuid.UUID, *, fresh: bool = True) -> PlanStatus:
        async with asyncio.timeout(RUN_TIMEOUT):
            return await self.consumer(plan_id, fresh=fresh).run()

    async def plan(self, plan_id: uuid.UUID) -> PlanRecord:
        async with self.factory() as db:
            record = await db.get(PlanRecord, plan_id)
        assert record is not None
        return record

    async def events(self, plan_id: uuid.UUID) -> list[EventRecord]:
        async with self.factory() as db:
            rows = await db.scalars(
                select(EventRecord).where(EventRecord.plan_id == plan_id).order_by(EventRecord.seq)
            )
            return list(rows)


@asynccontextmanager
async def offline_http() -> AsyncIterator[httpx.AsyncClient]:
    """The backend's own HTTP client: never used here (file:// schema, offline FX)."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP request to {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
        yield client


HarnessFactory = Callable[..., Harness]


def harness_factory(
    factory: async_sessionmaker[AsyncSession],
    make_settings: Callable[..., Settings],
    http: httpx.AsyncClient,
) -> HarnessFactory:
    """`build(fake, trip_schema=None, fx=None, link_checker=None)`: a `Harness` with real
    collaborators
    (`TripSchemaStore` over the vendored trip.json through a file:// URL, an offline
    `FxConverter`, `PlanHub`); also used by test_consumer_resume.py."""
    settings = make_settings(trip_schema_url=DEV_FALLBACK_SCHEMA_PATH.as_uri())

    def build(
        fake: FakeManagedAgentsClient,
        *,
        trip_schema: Any = None,
        fx: Any = None,
        link_checker: Any = None,
    ) -> Harness:
        sleeps: list[float] = []

        async def record_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            await asyncio.sleep(0)

        hub = RecordingHub()
        store = trip_schema or TripSchemaStore(settings, http, now=lambda: NOW)
        converter = fx or FxConverter(
            session_factory=factory, http=http, offline=True, today=NOW.date
        )
        deps = ConsumerDeps(
            settings=settings,
            session_factory=factory,
            client=fake,
            hub=hub,
            trip_schema=store,
            fx=converter,
            now=lambda: NOW,
            ids=lambda: SeededTripIds(7),
            sleep=record_sleep,
            link_checker=link_checker or NO_LINK_CHECKS,
        )
        return Harness(factory, fake, deps, hub, sleeps)

    return build


@pytest.fixture
async def harness(
    db_session_factory: async_sessionmaker[AsyncSession],
    make_settings: Callable[..., Settings],
) -> AsyncIterator[HarnessFactory]:
    async with offline_http() as http:
        yield harness_factory(db_session_factory, make_settings, http)


def scenario(name: str, **kwargs: Any) -> FakeManagedAgentsClient:
    return FakeManagedAgentsClient.from_scenario(name, await_timeout=10, **kwargs)


def owned_keys(
    fake: FakeManagedAgentsClient, plan_id: uuid.UUID, *, skip_types: Sequence[str] = ()
) -> set[str]:
    """The `ma_event_id` of every event the consumer must have stored: the owned copy of each
    event in the session history and in every thread history."""
    keys: set[str] = set()
    scopes: list[tuple[str, list[RawEvent]]] = [(PRIMARY_SCOPE, fake.history)]
    scopes += [(t.id, fake.thread_history(t.id)) for t in fake.threads() if not t.is_primary]
    for scope, events in scopes:
        for raw in events:
            if raw["type"] in skip_types or not stream_owns(scope, raw):
                continue
            key = dedupe_key(raw, plan_id=plan_id, scope=scope)
            if key is not None:
                keys.add(key)
    return keys


def api_keys(rows: Sequence[EventRecord]) -> list[str]:
    return [
        cast(str, row.ma_event_id)
        for row in rows
        if row.ma_event_id and not row.ma_event_id.startswith("backend:")
    ]


def tool_results(fake: FakeManagedAgentsClient) -> list[Mapping[str, Any]]:
    return [s.payload for s in fake.sent if s.payload["type"] == "user.custom_tool_result"]


def by_key(rows: Sequence[EventRecord]) -> dict[str, EventRecord]:
    return {cast(str, row.ma_event_id): row for row in rows if row.ma_event_id}


# --- pure decisions -------------------------------------------------------------------------------


def test_backoff_delay_doubles_from_one_second_caps_at_thirty_and_jitters() -> None:
    assert [backoff_delay(n, jitter=1.0) for n in range(1, 7)] == [1, 2, 4, 8, 16, 30]
    assert backoff_delay(1, jitter=0.0) == 0.75
    assert backoff_delay(3, jitter=0.5) == pytest.approx(4 * 0.875)
    assert backoff_delay(500, jitter=0.0) == 30 * 0.75
    assert backoff_delay(0, jitter=0.0) == 0.75  # 1-based; anything lower counts as the first


def test_dedupe_key_uses_the_id_or_a_deterministic_synthetic_key() -> None:
    plan_id = uuid.UUID("7f3c0000-0000-4000-8000-000000000001")
    assert dedupe_key({"id": "sevt_1", "type": "x"}, plan_id=plan_id, scope="session") == "sevt_1"
    echo = {"id": "", "type": "user.interrupt", "processed_at": "2026-10-12T10:00:14.123Z"}
    key = dedupe_key(echo, plan_id=plan_id, scope="session")
    assert key == f"noid:{plan_id}:session:user.interrupt:2026-10-12T10:00:14.123000+00:00"
    # The same instant written with another offset (a listing vs the stream) maps to one key.
    listed = {**echo, "processed_at": "2026-10-12T12:00:14.123+02:00"}
    assert dedupe_key(listed, plan_id=plan_id, scope="session") == key
    assert dedupe_key({**echo, "id": None}, plan_id=plan_id, scope="session") == key
    assert dedupe_key(echo, plan_id=plan_id, scope="sthr_1") != key
    # A queued echo (no processed_at yet) is not stored: its processed copy will be.
    queued = {"id": "", "type": "user.interrupt", "processed_at": None}
    assert dedupe_key(queued, plan_id=plan_id, scope="session") is None
    assert dedupe_key({"type": "user.interrupt"}, plan_id=plan_id, scope="session") is None


@pytest.mark.parametrize(
    ("scope", "event", "owned"),
    [
        ("session", {"type": "agent.message"}, True),
        ("session", {"type": "agent.mcp_tool_use", "session_thread_id": "sthr_1"}, False),
        ("session", {"type": "user.custom_tool_result", "session_thread_id": "sthr_1"}, False),
        ("session", {"type": "agent.tool_use", "session_thread_id": None}, True),
        ("session", {"type": "session.thread_status_idle", "session_thread_id": "sthr_1"}, True),
        ("session", {"type": "agent.thread_message_received", "from_agent_name": "x"}, True),
        ("session", {"type": "session.checkpoint_created"}, True),
        ("sthr_1", {"type": "agent.mcp_tool_use"}, True),
        ("sthr_1", {"type": "agent.tool_progress"}, True),
        ("sthr_1", {"type": "session.thread_status_running"}, False),
        ("sthr_1", {"type": "agent.thread_message_sent"}, False),
        ("sthr_1", {"type": "agent.thread_message_received"}, False),
        ("sthr_1", {"type": "session.usage"}, False),
    ],
)
def test_stream_owns_persists_each_copy_from_one_stream(
    scope: str, event: RawEvent, owned: bool
) -> None:
    assert stream_owns(scope, event) is owned


def test_lane_for_follows_threads_and_named_agents() -> None:
    state = ConsumerState(
        status=PlanStatus.RUNNING,
        threads={"sthr_f": AgentName.FLIGHTS, "sthr_x": AgentName.COORDINATOR},
        mcp_servers={"kiwi": AgentName.FLIGHTS},
    )

    def lane(event: RawEvent, scope: str = "session") -> AgentName:
        return lane_for(event, scope=scope, state=state)

    assert lane({"type": "agent.mcp_tool_use"}, "sthr_f") is AgentName.FLIGHTS
    assert lane({"type": "agent.tool_use", "agent_name": "lodging"}, "sthr_new") is (
        AgentName.LODGING
    )
    assert lane({"type": "agent.message"}) is AgentName.COORDINATOR
    sent = {"type": "agent.thread_message_sent", "to_agent_name": "activities"}
    assert lane(sent) is AgentName.ACTIVITIES
    sent_by_id = {"type": "agent.thread_message_sent", "to_session_thread_id": "sthr_f"}
    assert lane(sent_by_id) is AgentName.FLIGHTS
    received = {"type": "agent.thread_message_received", "from_agent_name": "transport"}
    assert lane(received) is AgentName.TRANSPORT
    created = {"type": "session.thread_created", "agent_name": "flights"}
    assert lane(created) is AgentName.FLIGHTS
    cross_post = {"type": "agent.mcp_tool_use", "session_thread_id": "sthr_f"}
    assert lane(cross_post) is AgentName.FLIGHTS
    assert lane({"type": "x", "agent_name": "anthropic.advisor"}) is AgentName.COORDINATOR
    assert lane({"type": "x"}, "sthr_x") is AgentName.COORDINATOR

    # An MCP error names the server, not the agent: the lane of the agent that called it.
    def mcp_error(server: str | None) -> RawEvent:
        error = {"type": "mcp_connection_failed_error", "retry_status": {"type": "retrying"}}
        return {"type": "session.error", "error": {**error, "mcp_server_name": server}}

    assert lane(mcp_error("kiwi")) is AgentName.FLIGHTS
    assert lane(mcp_error("lastminute")) is AgentName.COORDINATOR
    assert lane(mcp_error(None)) is AgentName.COORDINATOR
    assert lane({"type": "session.error", "error": None}) is AgentName.COORDINATOR


def idle(reason: str, **extra: Any) -> RawEvent:
    return {
        "id": "sevt_idle",
        "type": "session.status_idle",
        "stop_reason": {"type": reason, **extra},
    }


@pytest.mark.parametrize(
    ("event", "accepted", "interrupt", "decision"),
    [
        (idle("requires_action", event_ids=["sevt_u1"]), False, False, IdleDecision.WAIT),
        (idle("requires_action", event_ids=["sevt_u1"]), True, False, IdleDecision.WAIT),
        (idle("requires_action", event_ids=["sevt_u1", "sevt_ask"]), False, False, "blocked"),
        (idle("requires_action", event_ids=["sevt_ask"]), True, False, IdleDecision.READY),
        (idle("requires_action", event_ids=[]), False, False, IdleDecision.BLOCKED),
        (idle("end_turn"), True, False, IdleDecision.READY),
        (idle("end_turn"), True, True, IdleDecision.READY),
        (idle("end_turn"), False, True, IdleDecision.INTERRUPTED),
        (idle("end_turn"), False, False, IdleDecision.FAILED),
        (idle("budget_reached"), True, False, IdleDecision.READY),
        (idle("budget_reached"), False, True, IdleDecision.INTERRUPTED),
        (idle("budget_reached"), False, False, IdleDecision.BUDGET_PAUSED),
        (idle("retries_exhausted"), False, False, IdleDecision.FAILED),
        (idle("refusal"), False, False, IdleDecision.FAILED),
        (idle("refusal"), True, False, IdleDecision.READY),
        (idle("something_new"), False, False, IdleDecision.BLOCKED),
        ({"type": "session.status_idle"}, False, False, IdleDecision.BLOCKED),
    ],
)
def test_decide_idle(
    event: RawEvent, accepted: bool, interrupt: bool, decision: IdleDecision | str
) -> None:
    state = ConsumerState(
        status=PlanStatus.RUNNING,
        accepted=accepted,
        interrupt_requested=interrupt,
        custom_tool_use_ids={"sevt_u1"},
    )
    outcome = decide_idle(event, state)
    assert outcome.decision == decision
    if outcome.decision in (IdleDecision.FAILED, IdleDecision.BLOCKED):
        assert outcome.reason  # an Italian failure_reason for the UI
    if outcome.decision is IdleDecision.READY:
        assert outcome.reason is None


def test_decide_idle_reasons_and_log_details() -> None:
    state = ConsumerState(status=PlanStatus.RUNNING)
    assert decide_idle(idle("end_turn"), state).reason == REASON_END_TURN_WITHOUT_PLAN
    blocked = decide_idle(idle("requires_action", event_ids=["sevt_ask"]), state)
    assert blocked.reason == REASON_UNEXPECTED_CONFIRMATION
    refusal = {**idle("refusal"), "stop_details": {"category": "cyber", "explanation": "..."}}
    assert decide_idle(refusal, state).log_reason == "refusal:cyber"
    assert decide_idle(idle("weird"), state).log_reason == "unknown:weird"


def test_superseded_threads_are_idle_threads_with_a_newer_thread_of_the_same_agent() -> None:
    state = ConsumerState(
        status=PlanStatus.RUNNING,
        thread_order=[
            ("sthr_a1", "activities"),
            ("sthr_f1", "flights"),
            ("sthr_a2", "activities"),
            ("sthr_a3", "activities"),
        ],
        idle_threads={"sthr_a1", "sthr_f1", "sthr_a2", "sthr_a3"},
    )
    assert superseded_threads(state) == ["sthr_a1", "sthr_a2"]
    state.archived_threads.add("sthr_a1")
    state.idle_threads.discard("sthr_a2")  # running again: not archived
    assert superseded_threads(state) == []
    assert superseded_threads(ConsumerState(status=PlanStatus.RUNNING)) == []


def test_is_terminal_error() -> None:
    def error(retry: Any) -> RawEvent:
        return {"type": "session.error", "error": {"type": "unknown_error", "retry_status": retry}}

    assert is_terminal_error(error({"type": "terminal"}))
    assert not is_terminal_error(error({"type": "retrying"}))
    assert not is_terminal_error(error({"type": "exhausted"}))
    assert not is_terminal_error(error(None))
    assert not is_terminal_error({"type": "session.error"})
    assert not is_terminal_error({"type": "session.status_terminated"})


# --- submit_plan --------------------------------------------------------------------------------


def dev_schema() -> TripSchema:
    return TripSchema.from_document(
        load_dev_fallback_schema(), source="dev_fallback", url="file:///trip.json", loaded_at=NOW
    )


def test_parse_submission_rejects_with_the_plan_rejection_message() -> None:
    bad = valid_plan_input()
    bad["bookings"][0]["book_by"] = bad["bookings"][0]["scheduled_for"]
    bad["title"] = "x" * 121
    outcome = parse_submission(bad)
    assert isinstance(outcome, Rejected)
    assert outcome.stage == "plan"
    assert outcome.message.startswith("Plan rejected: 2 validation errors.")
    assert any(line.startswith("title:") for line in outcome.errors)
    assert any("bookings[0].book_by" in line for line in outcome.errors)
    assert isinstance(parse_submission(valid_plan_input()), Plan)
    assert isinstance(parse_submission(cast(Any, None)), Rejected)


def test_translate_submission_rejects_a_book_by_in_the_past() -> None:
    data = valid_plan_input()
    data["bookings"][1]["book_by"] = "2026-10-01T20:00:00+02:00"
    plan = Plan.model_validate(data)
    outcome = translate_submission(
        plan, schema=dev_schema(), fx=FxRates(), now=NOW, ids=SeededTripIds(1)
    )
    assert isinstance(outcome, Rejected)
    assert outcome.stage == "plan"
    assert outcome.errors == [
        "bookings[1].book_by: book_by (2026-10-01T20:00:00+02:00) is in the past (now "
        "2026-10-12T12:30:00+02:00); set a future deadline, or null to let the backend derive it"
    ]
    assert outcome.message.startswith("Plan rejected: 1 validation error.")
    assert outcome.message.endswith(f"- {outcome.errors[0]}")


def test_translate_submission_accepts_and_keeps_the_trip_and_warnings() -> None:
    plan = Plan.model_validate(valid_plan_input())
    outcome = translate_submission(
        plan, schema=dev_schema(), fx=FxRates(), now=NOW, ids=SeededTripIds(1)
    )
    assert isinstance(outcome, Accepted)
    assert outcome.trip["title"] == plan.title
    assert dev_schema().validate(outcome.trip) == []
    assert outcome.plan_json["warnings"][: len(plan.warnings)] == plan.warnings
    assert len(set(outcome.plan_json["warnings"])) == len(outcome.plan_json["warnings"])
    json.dumps(outcome.plan_json)  # JSON-ready, as stored in plans.plan


def test_translate_submission_rejects_a_trip_that_fails_trip_json() -> None:
    document = copy.deepcopy(load_dev_fallback_schema())
    document["properties"]["title"]["maxLength"] = 5  # stricter than the Plan contract
    strict = TripSchema.from_document(
        document, source="file", url="file:///strict.json", loaded_at=NOW
    )
    plan = Plan.model_validate(valid_plan_input())
    outcome = translate_submission(plan, schema=strict, fx=FxRates(), now=NOW, ids=SeededTripIds(1))
    assert isinstance(outcome, Rejected)
    assert outcome.stage == "trip"
    assert outcome.errors
    assert outcome.errors[0].startswith("title:")
    assert "TripTracker's own schema" in outcome.message
    assert outcome.message.splitlines()[1] == f"- {outcome.errors[0]}"


DEAD_BOOKING_LINK = valid_plan_input()["bookings"][0]["link"]


def dead_link_health() -> LinkHealthMap:
    return LinkHealthMap(
        {
            DEAD_BOOKING_LINK: LinkHealth(
                "dead",
                "http_404",
                404,
                fallback="https://www.expedia.it/",
                fallback_allowed=True,
                checked_at=NOW,
            )
        }
    )


class StubLinkChecker:
    """A link checker that returns a fixed map and records its calls."""

    def __init__(self, health: LinkHealthMap, *, wait_for: asyncio.Event | None = None) -> None:
        self.health = health
        self.calls = 0
        self.closed = False
        self._wait_for = wait_for

    async def check_plan(self, plan: Plan) -> LinkHealthMap:
        self.calls += 1
        if self._wait_for is not None:
            await asyncio.wait_for(self._wait_for.wait(), timeout=5)
        return self.health

    async def aclose(self) -> None:
        self.closed = True


class SignalFx(FxConverter):
    """The real offline converter, which sets an event once its prefetch has started."""

    def __init__(self, started: asyncio.Event, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._started = started

    async def prefetch(self, keys: Any) -> FxRates:
        self._started.set()
        return await super().prefetch(keys)


def test_translate_submission_passes_health_to_the_trip_and_the_outcome() -> None:
    plan = Plan.model_validate(valid_plan_input())
    health = dead_link_health()
    outcome = translate_submission(
        plan,
        schema=dev_schema(),
        fx=FxRates(),
        now=NOW,
        ids=SeededTripIds(1),
        health=health,
    )
    assert isinstance(outcome, Accepted)
    assert outcome.link_health == health.to_json()
    assert outcome.trip["bookings"][0]["url"] == "https://www.expedia.it/"
    json.dumps(outcome.link_health)  # JSON-ready, as stored in plans.link_health


def test_translate_submission_without_health_has_an_empty_verdict_map() -> None:
    plan = Plan.model_validate(valid_plan_input())
    outcome = translate_submission(
        plan, schema=dev_schema(), fx=FxRates(), now=NOW, ids=SeededTripIds(1)
    )
    assert isinstance(outcome, Accepted)
    assert outcome.link_health == {}


async def test_accepted_plan_stores_link_health(harness: HarnessFactory) -> None:
    checker = StubLinkChecker(dead_link_health())
    fake = scenario("happy_path")
    h = harness(fake, link_checker=checker)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    record = await h.plan(plan_id)
    assert checker.calls == 1
    assert record.link_health == dead_link_health().to_json()
    assert record.trip is not None
    assert record.trip["bookings"][0]["url"] == "https://www.expedia.it/"


async def test_accepted_plan_without_checks_stores_an_empty_verdict_map(
    harness: HarnessFactory,
) -> None:
    fake = scenario("happy_path")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    assert (await h.plan(plan_id)).link_health == {}


async def test_rejected_plan_stores_no_link_health(harness: HarnessFactory) -> None:
    checker = StubLinkChecker(dead_link_health())
    fake = scenario("three_rejections_failed")
    h = harness(fake, link_checker=checker)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.FAILED
    assert (await h.plan(plan_id)).link_health is None


async def test_link_check_runs_with_fx_and_schema_concurrently(
    harness: HarnessFactory,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The checker waits for the FX prefetch to start: sequential awaits would deadlock."""
    fx_started = asyncio.Event()
    async with offline_http() as http:
        fx = SignalFx(fx_started, session_factory=db_session_factory, http=http, offline=True)
        checker = StubLinkChecker(LinkHealthMap.empty(), wait_for=fx_started)
        fake = scenario("happy_path")
        h = harness(fake, fx=fx, link_checker=checker)
        plan_id = await h.create_plan()
        assert await h.run(plan_id) is PlanStatus.READY
    assert checker.calls == 1


async def test_schema_unavailable_still_propagates_with_a_link_checker(
    harness: HarnessFactory,
) -> None:
    checker = StubLinkChecker(LinkHealthMap.empty())
    with pytest.raises(TripSchemaUnavailableError):
        await evaluate_submission(
            valid_plan_input(),
            deps=harness(
                FakeManagedAgentsClient(),
                trip_schema=UnavailableSchemaStore(),
                link_checker=checker,
            ).deps,
        )


class RaisingLinkChecker:
    """A link checker with a bug: `check_plan` raises (its message names a URL)."""

    async def check_plan(self, plan: Plan) -> LinkHealthMap:
        raise RuntimeError("check of https://secret.example/x failed")

    async def aclose(self) -> None:
        return None


@pytest.fixture
def consumer_logs(monkeypatch: pytest.MonkeyPatch) -> list[EventDict]:
    """Every consumer log entry at any level, independent of the global configuration."""
    capture = LogCapture()
    logger = structlog.wrap_logger(
        structlog.PrintLogger(),
        processors=[capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    monkeypatch.setattr(consumer_module, "log", logger)
    return capture.entries


async def test_a_failing_link_check_never_rejects_the_plan(
    harness: HarnessFactory, consumer_logs: list[EventDict]
) -> None:
    """The FX prefetch and the trip.json load are unaffected: the plan is accepted with no
    verdicts, and the failure is logged once, by its class only."""
    outcome = await evaluate_submission(
        valid_plan_input(),
        deps=harness(FakeManagedAgentsClient(), link_checker=RaisingLinkChecker()).deps,
    )
    assert isinstance(outcome, Accepted)
    assert outcome.link_health == {}
    assert outcome.trip["bookings"][0]["url"] == DEAD_BOOKING_LINK
    failures = [entry for entry in consumer_logs if entry["event"] == "link_check_failed"]
    assert failures == [
        {"event": "link_check_failed", "error": "RuntimeError", "log_level": "warning"}
    ]
    assert "secret.example" not in repr(consumer_logs)


async def test_schema_unavailable_still_propagates_when_the_link_check_fails(
    harness: HarnessFactory,
) -> None:
    with pytest.raises(TripSchemaUnavailableError):
        await evaluate_submission(
            valid_plan_input(),
            deps=harness(
                FakeManagedAgentsClient(),
                trip_schema=UnavailableSchemaStore(),
                link_checker=RaisingLinkChecker(),
            ).deps,
        )


def results_write(fake: FakeManagedAgentsClient, agent: str) -> str:
    for step in fake.script:
        event = step.get("event") or {}
        tool_input = event.get("input") or {}
        if event.get("name") == "write" and str(tool_input.get("file_path", "")).startswith(
            f"/workspace/results/{agent}.json"
        ):
            return tool_input["content"]
    raise AssertionError(f"no results write for {agent}")


def test_check_result_writes_reports_only_malformed_files() -> None:
    fake = scenario("happy_path")
    writes = {
        "flights": results_write(fake, "flights"),
        "lodging": "{not json",
        "transport": json.dumps({"agent": "lodging"}),
        "weather": "{}",
    }
    problems = check_result_writes(writes)
    assert set(problems) == {"lodging", "transport", "weather"}
    assert all(problems[name] for name in problems)
    assert check_result_writes({}) == {}


# --- persistence ----------------------------------------------------------------------------------


def test_backend_event_ids_and_builders() -> None:
    plan_id = uuid.UUID("7f3c0000-0000-4000-8000-000000000001")
    assert backend_event_id(plan_id, "submit", "sevt_1") == f"backend:{plan_id}:submit:sevt_1"
    build = backend_event(
        EventKind.PLAN, "Piano\naccettato", ts=NOW, detail={"a": 1}, cost_cents=-3
    )
    event = build(4)
    assert event is not None
    assert (event.seq, event.title, event.detail, event.cost_cents) == (
        4,
        "Piano accettato",
        {"a": 1},
        None,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        backend_event(EventKind.STATUS, "x", ts=dt.datetime(2026, 10, 12))  # noqa: DTZ001


async def test_event_sink_allocates_seq_dedupes_and_applies_updates(
    harness: HarnessFactory,
) -> None:
    h = harness(FakeManagedAgentsClient())
    plan_id = await h.create_plan()
    sink = EventSink(plan_id, session_factory=h.factory, hub=h.hub)

    first = await sink.emit(
        backend_event(EventKind.USAGE, "Costo", ts=NOW),
        ma_event_id="sevt_a",
        update=PlanUpdate(cost_cents=40, submit_attempts_increment=1),
    )
    assert first.event is not None
    assert first.event.seq == 0
    assert (first.duplicate, first.status_applied) == (False, False)
    second = await sink.emit(
        backend_event(EventKind.USAGE, "Costo", ts=NOW),
        ma_event_id="sevt_b",
        update=PlanUpdate(cost_cents=30),  # never decreases
    )
    assert second.event is not None
    assert second.event.seq == 1
    again = await sink.emit(
        backend_event(EventKind.USAGE, "Costo", ts=NOW),
        ma_event_id="sevt_a",
        update=PlanUpdate(cost_cents=99, status=StatusChange(PlanStatus.FAILED)),
    )
    assert (again.event, again.duplicate, again.status_applied) == (None, True, False)
    no_event = await sink.emit(
        lambda seq: None, ma_event_id="sevt_none", update=PlanUpdate(budget_cents=260)
    )
    assert (no_event.event, no_event.duplicate) == (None, False)

    record = await h.plan(plan_id)
    assert (record.cost_cents, record.submit_attempts, record.status) == (40, 1, "running")
    assert record.budget_cents == 260
    assert [row.ma_event_id for row in await h.events(plan_id)] == ["sevt_a", "sevt_b"]
    assert [event.seq for event in h.hub.published] == [0, 1]
    assert h.hub.ended == []


async def test_event_sink_status_changes_are_compare_and_set(harness: HarnessFactory) -> None:
    h = harness(FakeManagedAgentsClient())
    plan_id = await h.create_plan()
    sink = EventSink(plan_id, session_factory=h.factory, hub=h.hub)
    plan_json = {"title": "Lisbona"}
    ready = await sink.emit(
        backend_event(EventKind.STATUS, "Pronto", ts=NOW),
        ma_event_id="sevt_ready",
        update=PlanUpdate(status=StatusChange(PlanStatus.READY), plan=plan_json, trip={"id": "t"}),
    )
    assert ready.status_applied
    late = await sink.emit(
        backend_event(EventKind.STATUS, "Fallito", ts=NOW),
        ma_event_id="sevt_late",
        update=PlanUpdate(status=StatusChange(PlanStatus.FAILED, reason="no")),
    )
    assert not late.status_applied
    assert late.event is not None
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("ready", None)
    assert (record.plan, record.trip) == (plan_json, {"id": "t"})
    assert h.hub.ended == [(plan_id, PlanStatus.READY)]


async def test_event_sink_raises_for_a_missing_plan(harness: HarnessFactory) -> None:
    h = harness(FakeManagedAgentsClient())
    sink = EventSink(uuid.uuid4(), session_factory=h.factory, hub=h.hub)
    with pytest.raises(PlanNotFoundError):
        await sink.emit(backend_event(EventKind.STATUS, "x", ts=NOW), ma_event_id="sevt_x")


async def test_set_plan_status_is_all_or_nothing_and_keys_are_single_use(
    harness: HarnessFactory,
) -> None:
    h = harness(FakeManagedAgentsClient())
    plan_id = await h.create_plan(status=PlanStatus.BUDGET_PAUSED)
    before = (await h.plan(plan_id)).running_since

    wrong = await set_plan_status(
        h.factory, h.hub, plan_id, StatusChange(PlanStatus.FAILED), title="No", event_key="k1"
    )
    assert (wrong.event, wrong.status_applied, wrong.duplicate) == (None, False, False)
    assert await h.events(plan_id) == []

    change = StatusChange(PlanStatus.RUNNING, only_from=(PlanStatus.BUDGET_PAUSED,))
    resumed = await set_plan_status(
        h.factory,
        h.hub,
        plan_id,
        change,
        title="Si riprende",
        event_key="continue:260",
        budget_cents=260,
    )
    assert resumed.status_applied
    assert resumed.event is not None
    assert resumed.event.detail == {"event_type": "backend.status", "plan_status": "running"}
    record = await h.plan(plan_id)
    assert (record.status, record.budget_cents) == ("running", 260)
    assert record.running_since >= before
    rows = await h.events(plan_id)
    assert [row.ma_event_id for row in rows] == [
        backend_event_id(plan_id, "status", "continue:260")
    ]

    replay = await set_plan_status(
        h.factory, h.hub, plan_id, change, title="Si riprende", event_key="continue:260"
    )
    assert replay.duplicate
    assert not replay.status_applied


async def test_load_events_after_pages_in_seq_order(harness: HarnessFactory) -> None:
    h = harness(FakeManagedAgentsClient())
    plan_id = await h.create_plan()
    other = await h.create_plan()
    sink = EventSink(plan_id, session_factory=h.factory, hub=h.hub)
    for index in range(5):
        await sink.emit(
            backend_event(EventKind.STATUS, f"Evento {index}", ts=NOW, detail={"i": index}),
            ma_event_id=f"sevt_{index}",
        )
    await EventSink(other, session_factory=h.factory, hub=h.hub).emit(
        backend_event(EventKind.STATUS, "Altro", ts=NOW), ma_event_id="sevt_other"
    )
    async with h.factory() as db:
        everything = await load_events_after(db, plan_id, None)
        tail = await load_events_after(db, plan_id, 2)
        page = await load_events_after(db, plan_id, 0, limit=2)
    assert [event.seq for event in everything] == [0, 1, 2, 3, 4]
    assert [event.title for event in tail] == ["Evento 3", "Evento 4"]
    assert [event.seq for event in page] == [1, 2]
    assert everything[0].ts == NOW
    assert everything[0].detail == {"i": 0}


# --- scenarios ------------------------------------------------------------------------------------


async def test_happy_path_end_to_end(harness: HarnessFactory) -> None:
    fake = scenario("happy_path")
    h = harness(fake)
    plan_id = await h.create_plan()
    status = await h.run(plan_id)
    await fake.wait_until_done()
    fake.assert_script_done()
    assert status is PlanStatus.READY

    # Stream open before the brief; one answer, "Plan accepted."; archived after the poll.
    assert fake.sent[0].payload["type"] == "user.message"
    assert PRIMARY_SCOPE in fake.sent[0].open_streams
    assert [(r["custom_tool_use_id"], r["is_error"]) for r in tool_results(fake)] == [
        ("sevt_011CZeGzLRh4ATERYGUCJyYV", False)
    ]
    assert tool_results(fake)[0]["content"] == [{"type": "text", "text": PLAN_ACCEPTED_TEXT}]
    assert fake.archived == [SID]
    methods = [call.method for call in fake.calls]
    assert methods.index("archive_session") > max(
        i for i, method in enumerate(methods) if method == "retrieve_session"
    )
    assert fake.archived_threads == []  # threads reused or never re-created: none archived

    record = await h.plan(plan_id)
    assert (record.status, record.submit_attempts, record.cost_cents) == ("ready", 1, 41)
    assert record.failure_reason is None
    assert record.plan is not None
    assert record.plan["title"] == valid_plan_input()["title"]
    assert record.trip is not None
    assert dev_schema().validate(record.trip) == []

    rows = await h.events(plan_id)
    assert [row.seq for row in rows] == list(range(len(rows)))
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))
    # Everything the API persisted, each copy once, except the archive's own terminated event.
    assert set(keys) == owned_keys(fake, plan_id, skip_types=["session.status_terminated"])
    stored = by_key(rows)
    # The flights MCP call is stored from its thread (flights lane), its cross-post is not.
    assert stored["sevt_011CZoVJQuoEkfKwS9qBajYL"].agent == "flights"
    assert "sevt_011CZTywa34a7nn1qmYKWhQg" not in stored
    # The transport thread's first events predate its stream: they come from the backfill.
    assert stored["sevt_011CZgFk7gSR1PHG9D6cpV1Z"].agent == "transport"
    # Thread lifecycle is stored from the session stream's copy, never from the thread's.
    assert stored["sevt_011CZ6por9wTujqSo5F6nv8P"].agent == "transport"
    assert "sevt_011CZ3CgM7VRJtftnue7mo32" not in stored
    assert stored["sevt_011CZTjVPm3mhPY3t5QPdM54"].agent == "flights"  # report to coordinator
    assert stored["sevt_011CZ9KPkQzSSh4pFa5EAj8A"].agent == "flights"  # task to flights
    assert stored["sevt_011CZxxCmakx1653dPbmyVvu"].agent == "coordinator"
    # Durations are paired from the thread's tool use and result.
    mcp_result = stored["sevt_011CZQXGr9rVp5R7gqX7b4yk"]
    assert mcp_result.detail is not None
    assert mcp_result.detail["duration_ms"] == 2656
    # Cost: the usage events carry their own cost, later events the cumulative one.
    assert stored["sevt_011CZSosTeeVW2iHyuqpUVaE"].cost_cents == 38
    assert stored["sevt_011CZSx9sAVdvWJ4U6SxP2aX"].cost_cents == 41

    accepted = stored[backend_event_id(plan_id, "submit", "sevt_011CZeGzLRh4ATERYGUCJyYV")]
    assert (accepted.kind, accepted.title) == ("plan", "Piano accettato")
    assert accepted.detail is not None
    assert accepted.detail["outcome"] == "accepted"
    assert h.hub.ended == [(plan_id, PlanStatus.READY)]
    assert [event.seq for event in h.hub.published] == [row.seq for row in rows]


async def test_settled_before_the_archive_and_nothing_stored_after_it(
    harness: HarnessFactory,
) -> None:
    """`wait_settled()` (what the SSE route waits for before `end`) resolves once the consumer
    stored what its streams had delivered, without waiting for the slow archive."""
    fake = scenario("happy_path")
    h = harness(fake)
    plan_id = await h.create_plan()
    fake.fail_next("archive_session", "hang")
    consumer = h.consumer(plan_id)
    task = asyncio.create_task(consumer.run())
    try:
        async with asyncio.timeout(RUN_TIMEOUT):
            await consumer.wait_settled()
        assert (await h.plan(plan_id)).status == "ready"
        stored = len(await h.events(plan_id))
        await fake.called("archive_session")  # hanging: the consumer is still winding down
        assert not consumer.done
        assert len(await h.events(plan_id)) == stored
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await fake.wait_until_done()
    fake.assert_script_done()


async def test_a_thread_backfill_in_flight_at_the_decision_is_stored_before_settling(
    harness: HarnessFactory,
) -> None:
    """A subagent thread created just before the decisive idle: its history listing is still
    in flight when the plan ends. The consumer waits for it (bounded) before the final drain,
    so `wait_settled()` (and the browser's `end`) comes after those events are stored."""
    thread = "sthr_flights_1"
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        {"op": "emit", "event": {"type": "session.status_running"}},
        {
            "op": "emit",
            "event": {
                "type": "session.thread_created",
                "session_thread_id": thread,
                "agent_name": "flights",
            },
        },
        {
            "op": "emit",
            "scope": thread,
            "event": {"type": "agent.message", "content": [{"type": "text", "text": "Fatto."}]},
        },
        {
            "op": "emit",
            "event": {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}},
        },
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    # Slow enough that the thread's event exists only in its history when the stream opens.
    fake.set_latency("stream_thread", 0.2)
    fake.set_latency("list_thread_events", 0.2)
    h = harness(fake)
    plan_id = await h.create_plan()
    consumer = h.consumer(plan_id)
    task = asyncio.create_task(consumer.run())
    async with asyncio.timeout(RUN_TIMEOUT):
        await consumer.wait_settled()
        stored = set(api_keys(await h.events(plan_id)))
        assert await task is PlanStatus.FAILED
    fake.assert_script_done()
    [thread_event] = fake.thread_history(thread)
    assert thread_event["id"] in stored
    assert stored == owned_keys(fake, plan_id)
    assert set(api_keys(await h.events(plan_id))) == stored  # nothing after the settle


async def test_a_cancelled_consumer_is_settled(harness: HarnessFactory) -> None:
    fake = scenario("interrupt")
    h = harness(fake)
    plan_id = await h.create_plan()
    consumer = h.consumer(plan_id)
    task = asyncio.create_task(consumer.run())
    await fake.reached("working")
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    async with asyncio.timeout(1):
        await consumer.wait_settled()
    assert (await h.plan(plan_id)).status == "running"  # the next process resumes it
    await fake.shutdown()


async def test_the_live_hub_sees_every_event_then_the_end(harness: HarnessFactory) -> None:
    fake = scenario("happy_path")
    h = harness(fake)
    plan_id = await h.create_plan()
    received: list[Any] = []
    with h.hub.subscribe(plan_id) as live:
        status = await h.run(plan_id)

        async def collect() -> None:
            async for message in live:
                received.append(message)

        async with asyncio.timeout(2):
            await collect()
    assert status is PlanStatus.READY
    assert received[-1] == PlanEnded(plan_id, PlanStatus.READY)
    events = [m for m in received if isinstance(m, UIEvent)]
    assert len(events) == len(await h.events(plan_id))


async def test_rejected_then_accepted(harness: HarnessFactory) -> None:
    fake = scenario("rejected_then_accepted")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    fake.assert_script_done()

    results = tool_results(fake)
    assert [r["is_error"] for r in results] == [True, False]
    feedback = results[0]["content"][0]["text"]
    assert feedback.startswith("Plan rejected:")
    assert "bookings[0].book_by" in feedback
    record = await h.plan(plan_id)
    assert (record.status, record.submit_attempts) == ("ready", 2)
    plan_events = [
        row
        for row in await h.events(plan_id)
        if (row.detail or {}).get("event_type") == "backend.submit_plan"
    ]
    assert [row.title.split(":")[0] for row in plan_events] == [
        "Piano respinto",
        "Piano accettato",
    ]
    rejected = plan_events[0].detail
    assert rejected is not None
    assert rejected["errors"]
    assert rejected["stage"] == "plan"
    assert rejected["attempt"] == 1


async def test_three_rejections_fail_the_plan_and_interrupt(harness: HarnessFactory) -> None:
    fake = scenario("three_rejections_failed")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.FAILED
    await fake.wait_until_done()
    fake.assert_script_done()

    assert [r["is_error"] for r in tool_results(fake)] == [True, True, True]
    assert tool_results(fake)[-1]["content"][0]["text"].endswith(
        f"No attempts left: the plan was rejected {MAX_FAILED_SUBMISSIONS} times and the run "
        "is being stopped."
    )
    assert [s.payload["type"] for s in fake.sent][-1] == "user.interrupt"
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("failed", REASON_TOO_MANY_REJECTIONS)
    assert record.submit_attempts == 3
    assert record.plan is None
    assert fake.archived == []  # failed sessions are kept for inspection
    assert h.hub.ended == [(plan_id, PlanStatus.FAILED)]
    outcomes = [
        row.detail
        for row in await h.events(plan_id)
        if row.detail and row.detail["event_type"] == "backend.submit_plan"
    ]
    assert [detail.get("plan_status") for detail in outcomes] == [None, None, "failed"]


async def test_budget_reached_pauses_then_continue_resumes_to_ready(
    harness: HarnessFactory,
) -> None:
    fake = scenario("budget_reached")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.BUDGET_PAUSED
    record = await h.plan(plan_id)
    assert (record.status, record.cost_cents, record.failure_reason) == ("budget_paused", 61, None)
    assert fake.archived == []
    assert h.hub.ended == []
    stored_before = await h.events(plan_id)

    # "Continua con 2 $ in più", as sessions.continue_plan does it.
    info = await fake.retrieve_session(SID)
    budget = max(info.budget_cents or 0, info.usage.list_cost_cents or 0) + 200
    await fake.update_budget(SID, budget)
    continued = await set_plan_status(
        h.factory,
        h.hub,
        plan_id,
        StatusChange(PlanStatus.RUNNING, only_from=(PlanStatus.BUDGET_PAUSED,)),
        title="Budget aumentato: si riprende",
        event_key=f"continue:{budget}",
        budget_cents=budget,
    )
    assert continued.status_applied

    assert await h.run(plan_id, fresh=False) is PlanStatus.READY
    fake.assert_script_done()
    record = await h.plan(plan_id)
    assert (record.status, record.budget_cents, record.cost_cents) == ("ready", budget, 91)
    rows = await h.events(plan_id)
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))
    assert set(api_keys(stored_before)) <= set(keys)
    assert [r["is_error"] for r in tool_results(fake)] == [False]
    assert len([s for s in fake.sent if s.payload["type"] == "user.message"]) == 1
    assert fake.archived == [SID]


async def test_unexpected_requires_action_blocks_the_plan(harness: HarnessFactory) -> None:
    fake = scenario("requires_action_blocked")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.BLOCKED
    fake.assert_script_done()
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("blocked", REASON_UNEXPECTED_CONFIRMATION)
    assert fake.archived == []
    assert tool_results(fake) == []
    assert h.hub.ended == [(plan_id, PlanStatus.BLOCKED)]


async def test_end_turn_without_a_plan_fails(harness: HarnessFactory) -> None:
    fake = scenario("end_turn_without_plan")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.FAILED
    fake.assert_script_done()
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("failed", REASON_END_TURN_WITHOUT_PLAN)
    assert tool_results(fake) == []
    assert fake.archived == []


@pytest.mark.parametrize("retrieve_fails", [False, True])
async def test_the_final_cost_is_read_from_the_session_when_no_usage_event_carried_it(
    harness: HarnessFactory, *, retrieve_fails: bool
) -> None:
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        {"op": "emit", "event": {"type": "session.status_running"}},
        {"op": "usage", "list_cost_cents": 20},
        {"op": "set", "list_cost_cents": 27},  # spent after the last session.usage
        {
            "op": "emit",
            "event": {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}},
        },
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    if retrieve_fails:
        fake.fail_next("retrieve_session", "api_unavailable")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.FAILED
    fake.assert_script_done()
    assert len(fake.calls_of("retrieve_session")) == 1
    record = await h.plan(plan_id)
    assert (record.status, record.cost_cents) == ("failed", 20 if retrieve_fails else 27)
    # The refresh stores no timeline event of its own.
    rows = await h.events(plan_id)
    assert not any(":cost:" in (row.ma_event_id or "") for row in rows)


async def test_a_subagent_custom_tool_use_is_never_waited_on(harness: HarnessFactory) -> None:
    """Only the coordinator's custom tool uses are answered: an idle waiting on one made on a
    subagent thread would wait forever, so it blocks the plan."""
    thread = "sthr_flights_1"
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        {"op": "emit", "event": {"type": "session.status_running"}},
        {
            "op": "emit",
            "event": {
                "type": "session.thread_created",
                "session_thread_id": thread,
                "agent_name": "flights",
            },
        },
        {"op": "await_stream", "scope": thread},
        {
            "op": "emit",
            "scope": thread,
            "event": {
                "id": "sevt_thread_tool",
                "type": "agent.custom_tool_use",
                "name": "submit_plan",
                "input": {},
            },
        },
        {"op": "usage", "list_cost_cents": 9},
        {
            "op": "emit",
            "event": {
                "type": "session.status_idle",
                "stop_reason": {"type": "requires_action", "event_ids": ["sevt_thread_tool"]},
            },
        },
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    consumer = h.consumer(plan_id)
    async with asyncio.timeout(RUN_TIMEOUT):
        assert await consumer.run() is PlanStatus.BLOCKED
    fake.assert_script_done()
    assert tool_results(fake) == []
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("blocked", REASON_UNEXPECTED_CONFIRMATION)
    assert record.submit_attempts == 0
    stored = by_key(await h.events(plan_id))
    assert stored["sevt_thread_tool"].agent == "flights"
    assert consumer.state is not None
    assert "sevt_thread_tool" not in consumer.state.custom_tool_use_ids


async def test_an_mcp_failure_stays_a_lane_warning(harness: HarnessFactory) -> None:
    fake = scenario("mcp_failure")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    fake.assert_script_done()
    errors = [row for row in await h.events(plan_id) if row.kind == "error"]
    assert len(errors) >= 2
    session_errors = [r for r in errors if (r.detail or {}).get("event_type") == "session.error"]
    assert [(r.detail or {})["severity"] for r in session_errors] == ["warning", "warning"]
    # Shown in the lane of the agent that called the Kiwi MCP, not the coordinator's.
    assert [r.agent for r in session_errors] == ["flights", "flights"]
    record = await h.plan(plan_id)
    assert record.status == "ready"
    assert record.plan is not None
    assert any("Kiwi" in warning or "kiwi" in warning for warning in record.plan["warnings"])


async def test_unknown_event_types_become_generic_events(harness: HarnessFactory) -> None:
    fake = scenario("unknown_event_type")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    fake.assert_script_done()
    stored = by_key(await h.events(plan_id))
    checkpoint = stored["sevt_011CZHYE19V4hYhDUpB2GhXd"]
    progress = stored["sevt_011CZkucpbsXfFndeADKzDcH"]
    assert (checkpoint.kind, checkpoint.agent) == ("status", "coordinator")
    assert (progress.kind, progress.agent) == ("status", "flights")
    assert "session.checkpoint_created" in checkpoint.title


async def test_rescheduled_and_retrying_errors_are_logged_a_terminal_error_fails(
    harness: HarnessFactory,
) -> None:
    fake = scenario("rescheduled_and_errors")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.FAILED
    await fake.wait_until_done()
    fake.assert_script_done()
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("failed", REASON_SESSION_ERROR)
    stored = by_key(await h.events(plan_id))
    assert "sevt_011CZStneavWq6FLRGNnRDJR" in stored  # status_rescheduled: stored, not acted on
    assert "sevt_011CZ1zDpeShkeCtrjyffGye" in stored  # retrying error: a warning only


async def test_accepted_then_budget_reached_is_ready(harness: HarnessFactory) -> None:
    fake = scenario("accepted_then_budget_reached")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    fake.assert_script_done()
    assert fake.archived == [SID]
    assert (await h.plan(plan_id)).status == "ready"


async def test_a_superseded_thread_is_archived(harness: HarnessFactory) -> None:
    fake = scenario("redelegation")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    fake.assert_script_done()
    assert fake.archived_threads == [(SID, "sthr_011CZdgvJm32hFNaV92NtJp3")]


async def test_an_interrupt_ends_the_plan_interrupted(harness: HarnessFactory) -> None:
    fake = scenario("interrupt")
    h = harness(fake)
    plan_id = await h.create_plan()
    consumer = h.consumer(plan_id)
    task = asyncio.create_task(consumer.run())
    await fake.reached("working")
    # sessions.request_interrupt: the request is stored first, then the consumer is told.
    await EventSink(plan_id, session_factory=h.factory, hub=h.hub).emit(
        backend_event(EventKind.STATUS, "Interruzione richiesta", ts=NOW),
        ma_event_id=backend_event_id(plan_id, "status", "interrupt-requested:1"),
        update=PlanUpdate(interrupt_requested_at=NOW),
    )
    consumer.request_interrupt()
    await fake.send_interrupt(SID)
    fake.release("working")
    async with asyncio.timeout(RUN_TIMEOUT):
        assert await task is PlanStatus.INTERRUPTED
    fake.assert_script_done()
    assert fake.archived == [SID]
    rows = await h.events(plan_id)
    echoes = [row for row in rows if (row.detail or {}).get("event_type") == "user.interrupt"]
    assert len(echoes) == 1
    assert cast(str, echoes[0].ma_event_id).startswith(f"noid:{plan_id}:session:user.interrupt:")
    record = await h.plan(plan_id)
    assert record.status == "interrupted"
    assert record.failure_reason


async def test_duplicates_from_streams_and_history_are_stored_once(
    harness: HarnessFactory,
) -> None:
    """Every thread is backfilled after its stream opens, so its events arrive twice (listing
    and stream) for the transport thread, and the reconnect relists the session: each event is
    stored once."""
    fake = scenario("stream_error_event")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    rows = await h.events(plan_id)
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))
    assert set(keys) == owned_keys(fake, plan_id, skip_types=["session.status_terminated"])


# --- stream drops ---------------------------------------------------------------------------------


async def test_a_dropped_stream_reconnects_with_backoff_and_backfills(
    harness: HarnessFactory,
) -> None:
    fake = scenario("stream_error_event")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    fake.assert_script_done()
    assert len(fake.calls_of("stream_session")) == 2
    assert len(h.sleeps) == 1
    assert 0.75 <= h.sleeps[0] <= 1.0
    stored = by_key(await h.events(plan_id))
    # Emitted while the stream was down: recovered from the history.
    assert "sevt_011CZLGbtWcn6Zyr1LHiUK1r" in stored
    assert "sevt_011CZC5djs69BaCMGusr2ied" in stored


def drop_script(drops: int) -> list[dict[str, Any]]:
    """A session that drops its stream `drops` times, with an event in between each time."""
    steps: list[dict[str, Any]] = [
        {"op": "await", "match": {"type": "user.message"}},
        {"op": "emit", "event": {"type": "session.status_running"}},
    ]
    for index in range(drops):
        message = {"type": "agent.message", "content": [{"type": "text", "text": f"m{index}"}]}
        steps += [
            {"op": "disconnect"},
            {"op": "await_stream"},
            {"op": "emit", "event": message},
        ]
    end_turn = {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}}
    steps += [{"op": "usage", "list_cost_cents": 5}, {"op": "emit", "event": end_turn}]
    return steps


async def test_the_reconnect_counter_resets_after_any_received_event(
    harness: HarnessFactory,
) -> None:
    drops = RECONNECT_ATTEMPTS + 2
    fake = FakeManagedAgentsClient(drop_script(drops), await_timeout=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.FAILED  # end_turn without a plan
    fake.assert_script_done()
    assert len(h.sleeps) == drops
    assert all(0.75 <= delay <= 1.0 for delay in h.sleeps)  # always the first attempt's delay
    record = await h.plan(plan_id)
    assert record.failure_reason == REASON_END_TURN_WITHOUT_PLAN
    messages = [
        row
        for row in await h.events(plan_id)
        if (row.detail or {}).get("event_type") == "agent.message"
    ]
    assert len(messages) == drops


async def test_reconnection_gives_up_after_the_last_attempt(harness: HarnessFactory) -> None:
    steps: list[dict[str, Any]] = [
        {"op": "await", "match": {"type": "user.message"}},
        {"op": "emit", "event": {"type": "session.status_running"}},
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    fake.fail_next("stream_session", "disconnected", after=1)  # the first open succeeds
    for _ in range(RECONNECT_ATTEMPTS - 1):
        fake.fail_next("stream_session", "disconnected")
    h = harness(fake)
    plan_id = await h.create_plan()
    consumer = h.consumer(plan_id)
    task = asyncio.create_task(consumer.run())
    await consumer.wait_started()
    await fake.wait_until_done()
    fake.disconnect()
    async with asyncio.timeout(RUN_TIMEOUT):
        assert await task is PlanStatus.FAILED
    assert len(h.sleeps) == RECONNECT_ATTEMPTS
    assert h.sleeps == sorted(h.sleeps)  # 1, 2, 4, 8, 16 s (jittered)
    assert h.sleeps[-1] >= 16 * 0.75
    assert len(fake.calls_of("stream_session")) == 1 + RECONNECT_ATTEMPTS
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("failed", REASON_STREAM_LOST)
    # Nobody follows the session any more: it is told to stop, and its cost is read.
    assert [s.payload["type"] for s in fake.sent] == ["user.message", "user.interrupt"]
    assert len(fake.calls_of("retrieve_session")) == 1


async def test_a_consumer_crash_fails_the_plan_and_stops_the_session(
    harness: HarnessFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backend-side failure mid-run (a bug, a database error) fails the plan; the agents
    would keep working and spending with nobody following them, so the consumer sends
    `user.interrupt` once it has settled, and reads the final cost."""
    fake = scenario("happy_path")
    h = harness(fake)
    plan_id = await h.create_plan()
    real_lane_for = consumer_module.lane_for
    calls = 0

    def failing_once(raw: RawEvent, *, scope: str, state: ConsumerState) -> AgentName:
        nonlocal calls
        calls += 1
        if calls == 8:
            raise RuntimeError("simulated backend failure")
        return real_lane_for(raw, scope=scope, state=state)

    monkeypatch.setattr(consumer_module, "lane_for", failing_once)
    try:
        assert await h.run(plan_id) is PlanStatus.FAILED
    finally:
        await fake.shutdown()  # the script stops where the consumer did
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("failed", REASON_INTERNAL)
    assert [s.payload["type"] for s in fake.sent] == ["user.message", "user.interrupt"]
    assert len(fake.calls_of("retrieve_session")) == 1
    assert fake.archived == []  # failed sessions are kept for inspection (decision 8)


# --- start, errors, registry ----------------------------------------------------------------------


async def test_a_session_that_cannot_be_opened_fails_the_start(harness: HarnessFactory) -> None:
    fake = FakeManagedAgentsClient([{"op": "await", "match": {"type": "user.message"}}])
    fake.fail_next("stream_session", "not_found")
    h = harness(fake)
    plan_id = await h.create_plan()
    registry = ConsumerRegistry(h.deps)
    consumer = registry.start(plan_id, SID, first_message=BRIEF)
    with pytest.raises(SessionNotFoundError):
        async with asyncio.timeout(RUN_TIMEOUT):
            await consumer.wait_started()
    await registry.aclose()
    assert (await h.plan(plan_id)).status == "failed"
    assert fake.sent == []
    await fake.shutdown()


async def test_the_first_message_is_retried_only_when_it_did_not_arrive(
    harness: HarnessFactory,
) -> None:
    fake = scenario("end_turn_without_plan")
    fake.fail_next("send_user_message", "api_unavailable")
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.FAILED
    fake.assert_script_done()
    assert len(fake.calls_of("send_user_message")) == 2
    assert len([s for s in fake.sent if s.payload["type"] == "user.message"]) == 1


async def test_a_missing_trip_schema_fails_the_plan_without_counting_an_attempt(
    harness: HarnessFactory,
) -> None:
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        {"op": "emit", "event": {"type": "session.status_running"}},
        {
            "op": "emit",
            "event": {
                "id": "sevt_u1",
                "type": "agent.custom_tool_use",
                "name": "submit_plan",
                "input": {"$fixture": "ma/plans/lisbon_valid.json"},
            },
        },
        {"op": "await", "match": {"type": "user.custom_tool_result", "is_error": True}},
        {"op": "await", "match": {"type": "user.interrupt"}},
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    h = harness(fake, trip_schema=UnavailableSchemaStore())
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.FAILED
    await fake.wait_until_done()
    fake.assert_script_done()
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("failed", REASON_SCHEMA_UNAVAILABLE)
    assert record.submit_attempts == 0


async def test_other_custom_tools_and_late_submissions_are_answered_without_evaluation(
    harness: HarnessFactory,
) -> None:
    def tool_use(event_id: str, name: str) -> dict[str, Any]:
        return {
            "op": "emit",
            "event": {
                "id": event_id,
                "type": "agent.custom_tool_use",
                "name": name,
                "input": {"$fixture": "ma/plans/lisbon_valid.json"},
            },
        }

    end_turn = {"type": "end_turn"}
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        {"op": "emit", "event": {"type": "session.status_running"}},
        tool_use("sevt_t1", "book_hotel"),
        {"op": "await", "match": {"custom_tool_use_id": "sevt_t1", "is_error": True}},
        tool_use("sevt_t2", "submit_plan"),
        {"op": "await", "match": {"custom_tool_use_id": "sevt_t2", "is_error": False}},
        tool_use("sevt_t3", "submit_plan"),
        {
            "op": "emit",
            "event": {
                "type": "session.status_idle",
                "stop_reason": {"type": "requires_action", "event_ids": ["sevt_t3"]},
            },
        },
        {"op": "await", "match": {"custom_tool_use_id": "sevt_t3", "is_error": False}},
        {"op": "emit", "event": {"type": "session.status_running"}},
        {"op": "emit", "event": {"type": "session.status_idle", "stop_reason": end_turn}},
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    fake.assert_script_done()
    texts = [r["content"][0]["text"] for r in tool_results(fake)]
    assert texts[0] == "Unknown tool 'book_hotel': the only custom tool is submit_plan."
    assert texts[1:] == [PLAN_ACCEPTED_TEXT, PLAN_ALREADY_ACCEPTED_TEXT]
    assert (await h.plan(plan_id)).submit_attempts == 1


async def test_the_registry_runs_one_consumer_per_plan(harness: HarnessFactory) -> None:
    fake = scenario("interrupt")
    h = harness(fake)
    plan_id = await h.create_plan()
    registry = ConsumerRegistry(h.deps)
    assert registry.deps is h.deps
    consumer = registry.start(plan_id, SID, first_message=BRIEF)
    async with asyncio.timeout(RUN_TIMEOUT):
        await consumer.wait_started()
    assert registry.get(plan_id) is consumer
    assert registry.active_plan_ids() == [plan_id]
    with pytest.raises(ConsumerAlreadyRunningError):
        registry.start(plan_id, SID)
    await fake.reached("working")
    await registry.stop(plan_id)
    assert consumer.done
    assert registry.get(plan_id) is None
    assert registry.active_plan_ids() == []
    assert (await h.plan(plan_id)).status == "running"  # a stop never changes the plan
    await registry.stop(plan_id)  # no-op
    await fake.shutdown()


async def test_a_consumer_for_a_plan_that_is_not_running_does_nothing(
    harness: HarnessFactory,
) -> None:
    fake = FakeManagedAgentsClient()
    h = harness(fake)
    plan_id = await h.create_plan(status=PlanStatus.READY)
    consumer = h.consumer(plan_id, fresh=False)
    assert await consumer.run() is PlanStatus.READY
    await consumer.wait_started()
    assert fake.calls == []
    missing = PlanConsumer(uuid.uuid4(), SID, h.deps)
    assert await missing.run() is PlanStatus.FAILED
    with pytest.raises(PlanNotFoundError):
        await missing.wait_started()
