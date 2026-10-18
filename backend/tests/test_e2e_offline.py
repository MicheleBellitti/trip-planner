"""The whole spec flow, end to end and offline, through the real FastAPI app.

Each test builds the app with `create_app(settings)` and runs its real lifespan
(`sessions.start_planner` with resume, the consumer registry, the hub, the stuck-plan checker),
local auth, and the real routes, middleware and SSE. Only the edges are replaced:

- Managed Agents: `FakeManagedAgentsClient` playing a scenario from tests/fixtures/ma, injected
  through conftest's `make_app(client=...)` (`app.state.planner_client_override`). One fake is
  one remote session: two app instances on the same fake are two processes on the same API.
- TripTracker's trip.json: served by respx at TRIP_SCHEMA_URL from the vendored copy, so the
  production fetch path runs. Every other outgoing httpx request fails (respx's
  `assert_all_mocked`): FX for these EUR-only plans must not touch the network.
- The roster: the fixture lockfile of the development profile (`app.cli.REPLAY_LOCKFILE_DIR`).
- Time: frozen (ticking) on the scenarios' day, 2026-10-12, early enough that Postgres's own
  `now()` (`plans.running_since`) is never behind the app's clock, so the stuck-plan check that
  runs at every startup never mistakes a fresh plan for a stuck one.

The browser is played like a browser: POSTs carry `Origin: FRONTEND_ORIGIN`, the SSE reader
disconnects and reconnects with `Last-Event-ID`, and TripTracker's /import fetches GET
/plans/{id}/trip with its own Origin, whose answer must carry the CORS headers and a Trip that
passes trip.schema.json.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
import time_machine
from fastapi import FastAPI
from jsonschema.validators import validator_for
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import sessions
from app.cli import REPLAY_LOCKFILE_DIR
from app.config import Settings
from app.consumer import (
    PLAN_ACCEPTED_TEXT,
    REASON_TOO_MANY_REJECTIONS,
    TITLE_PLAN_ACCEPTED,
    load_events_after,
)
from app.db import EventRecord, PlanRecord, PlanStatus
from app.events import AgentName, EventKind, UIEvent
from app.request import PlanRequest
from app.sessions import PlannerServices
from app.triptracker_schema import TripSchema, validate_trip
from tests.conftest import TEST_USER_EMAIL, AppFactory, PlanRows
from tests.fakes import FIXTURES_DIR, FIXTURES_ROOT, FakeManagedAgentsClient, load_jsonl
from tests.test_sse import SseMessage, SseStream

ROME = ZoneInfo("Europe/Rome")
FROZEN_NOW = dt.datetime(2026, 10, 12, 8, 0, tzinfo=ROME)
"""The app's clock, ticking from here: the scenarios' day, before their own timestamps and before
any real run of this suite (so Postgres's `now()` is never behind it)."""

TRIP_SCHEMA_PATH = FIXTURES_ROOT / "triptracker" / "trip.schema.json"
EVIL_ORIGIN = "https://evil.example"
WAIT_SECONDS = 15.0
"""Upper bound for one step of a flow (the fake replays a whole scenario in well under 1 s)."""
POLL_SECONDS = 0.02
POLLS = int(WAIT_SECONDS / POLL_SECONDS)


# --- harness ------------------------------------------------------------------------------------


@pytest.fixture
def e2e_settings(make_settings: Callable[..., Settings]) -> Settings:
    """The test settings (development, AUTH_MODE=local, TRIP_SCHEMA_URL on TripTracker) with the
    fixture lockfile of the development profile."""
    return make_settings(lockfile_path=REPLAY_LOCKFILE_DIR / "claude-lock.development.json")


@pytest.fixture
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(FROZEN_NOW, tick=True):
        yield


@pytest.fixture
def triptracker_edge(e2e_settings: Settings) -> Iterator[respx.Route]:
    """TripTracker serves trip.json; any other outgoing httpx request is an error."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router.get(e2e_settings.trip_schema_url).mock(
            return_value=httpx.Response(
                200,
                content=TRIP_SCHEMA_PATH.read_bytes(),
                headers={"Content-Type": "application/json"},
            )
        )


@dataclass(slots=True)
class SseReader:
    """One SSE connection of the browser (tests/test_sse.py's `SseStream`, read patiently)."""

    stream: SseStream

    async def next(self) -> SseMessage:
        """The next message that is not a ping."""
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                try:
                    return await self.stream.event()
                except TimeoutError:
                    continue  # quiet for the reader's chunk timeout: keep waiting

    async def take(self, count: int) -> list[UIEvent]:
        events: list[UIEvent] = []
        while len(events) < count:
            message = await self.next()
            assert message.event is None, f"unexpected {message.event}: {message.data}"
            events.append(ui_event(message))
        return events

    async def until(self, predicate: Callable[[UIEvent], bool]) -> list[UIEvent]:
        """Events up to and including the first one matching `predicate`."""
        events: list[UIEvent] = []
        while not events or not predicate(events[-1]):
            events += await self.take(1)
        return events

    async def until_end(self) -> tuple[list[UIEvent], str]:
        """Every event until `event: end`; returns them and the final status. The server must
        close the stream right after `end` (so EventSource does not reconnect)."""
        events: list[UIEvent] = []
        while True:
            message = await self.next()
            if message.event == "end":
                await self.stream.expect_closed()
                return events, message.json["status"]
            assert message.event is None, f"unexpected {message.event}: {message.data}"
            events.append(ui_event(message))


def ui_event(message: SseMessage) -> UIEvent:
    assert message.data is not None
    event = UIEvent.model_validate_json(message.data)
    assert message.id == str(event.seq)  # Last-Event-ID is the seq
    return event


@dataclass(slots=True)
class Browser:
    """The web app (and TripTracker's /import) talking to one running app instance."""

    app: FastAPI
    http: httpx.AsyncClient
    settings: Settings

    @property
    def planner(self) -> PlannerServices:
        return self.app.state.planner

    @property
    def frontend(self) -> dict[str, str]:
        return {"Origin": self.settings.frontend_origin}

    async def create_plan(self, request: Mapping[str, Any]) -> uuid.UUID:
        response = await self.http.post("/plans", json=dict(request), headers=self.frontend)
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    async def detail(self, plan_id: uuid.UUID) -> dict[str, Any]:
        response = await self.http.get(f"/plans/{plan_id}")
        assert response.status_code == 200, response.text
        return response.json()

    async def wait_for_status(self, plan_id: uuid.UUID, status: PlanStatus) -> dict[str, Any]:
        """Poll GET /plans/{id} until the plan reaches `status`."""
        for _ in range(POLLS):
            detail = await self.detail(plan_id)
            if detail["status"] == status.value:
                return detail
            await asyncio.sleep(POLL_SECONDS)
        raise AssertionError(f"plan {plan_id} never reached {status}")

    async def wait_for_consumer_exit(self, plan_id: uuid.UUID) -> None:
        """The consumer finished its closing work (final cost, archive)."""
        registry = self.planner.registry
        assert registry is not None
        for _ in range(POLLS):
            if registry.get(plan_id) is None:
                return
            await asyncio.sleep(POLL_SECONDS)
        raise AssertionError(f"the consumer of {plan_id} never stopped")

    @asynccontextmanager
    async def events(
        self, plan_id: uuid.UUID, *, last_event_id: int | None = None
    ) -> AsyncIterator[SseReader]:
        """GET /plans/{id}/events, read incrementally; leaving the block disconnects."""
        headers = {"Origin": self.settings.frontend_origin}
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        stream = SseStream(self.app, f"/plans/{plan_id}/events", headers)
        await stream.open()
        assert stream.status == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["access-control-allow-origin"] == self.settings.frontend_origin
        try:
            yield SseReader(stream)
        finally:
            await stream.disconnect()


OpenBrowser = Callable[[FakeManagedAgentsClient], AbstractAsyncContextManager[Browser]]


@pytest.fixture
def open_browser(
    make_app: AppFactory,
    e2e_settings: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    triptracker_edge: respx.Route,
    frozen_clock: None,
) -> OpenBrowser:
    """`async with open_browser(fake) as browser:` starts a fresh app instance (its own
    lifespan, engine and planner) on the emptied test database, wired to `fake`."""

    @asynccontextmanager
    async def factory(fake: FakeManagedAgentsClient) -> AsyncIterator[Browser]:
        async with make_app(settings=e2e_settings, client=fake) as app:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                yield Browser(app=app, http=http, settings=e2e_settings)

    return factory


def scenario(name: str, **kwargs: Any) -> FakeManagedAgentsClient:
    return FakeManagedAgentsClient.from_scenario(name, await_timeout=WAIT_SECONDS, **kwargs)


def scenario_with_checkpoint(
    name: str, checkpoint: str, before: Callable[[Mapping[str, Any]], bool]
) -> FakeManagedAgentsClient:
    """The scenario with a `checkpoint` step inserted before the first step matching `before`,
    so a test can act at a precise point of the session."""
    steps, _ = load_jsonl(FIXTURES_DIR / f"{name}.jsonl")
    index = next(i for i, step in enumerate(steps) if before(step))
    steps.insert(index, {"op": "checkpoint", "name": checkpoint})
    return FakeManagedAgentsClient(steps, await_timeout=WAIT_SECONDS, source=f"{name}.jsonl")


def is_submit_plan(step: Mapping[str, Any]) -> bool:
    event = step.get("event") or {}
    return (
        step.get("op") == "emit"
        and event.get("type") == "agent.custom_tool_use"
        and event.get("name") == "submit_plan"
    )


async def stored_events(
    session_factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID
) -> list[UIEvent]:
    async with session_factory() as db:
        return await load_events_after(db, plan_id, None)


async def stored_keys(
    session_factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID
) -> list[str | None]:
    async with session_factory() as db:
        rows = await db.scalars(
            select(EventRecord.ma_event_id)
            .where(EventRecord.plan_id == plan_id)
            .order_by(EventRecord.seq)
        )
        return list(rows)


async def load_plan(
    session_factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID
) -> PlanRecord:
    async with session_factory() as db:
        plan = await db.get(PlanRecord, plan_id)
    assert plan is not None
    return plan


async def count_plans(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as db:
        return int(await db.scalar(select(func.count()).select_from(PlanRecord)) or 0)


def tool_results(fake: FakeManagedAgentsClient) -> list[Mapping[str, Any]]:
    return [s.payload for s in fake.sent if s.payload["type"] == "user.custom_tool_result"]


def result_text(payload: Mapping[str, Any]) -> str:
    return "".join(block["text"] for block in payload["content"])


def assert_contiguous(events: Sequence[UIEvent]) -> None:
    """Every event exactly once, in order, from seq 0."""
    assert [event.seq for event in events] == list(range(len(events)))


def assert_valid_trip(trip: Mapping[str, Any]) -> None:
    """The Trip passes TripTracker's trip.schema.json as a plain JSON Schema, and the backend's
    stricter check of the same file (Zod's pattern rules, endDate >= startDate)."""
    document = json.loads(TRIP_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = validator_for(document)(document)
    assert [error.message for error in validator.iter_errors(trip)] == []
    schema = TripSchema.from_document(
        document, source="file", url=TRIP_SCHEMA_PATH.as_uri(), loaded_at=FROZEN_NOW
    )
    assert validate_trip(trip, schema=schema) == []


def strings_in(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in cast(Mapping[str, Any], value).values():
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in cast(list[Any], value):
            yield from strings_in(item)


def tool_result_texts(fake: FakeManagedAgentsClient) -> list[str]:
    """The text of every tool result the agents received (web pages, MCP answers, files)."""
    events = list(fake.history)
    for thread in fake.threads():
        if not thread.is_primary:
            events += fake.thread_history(thread.id)
    texts: list[str] = []
    for raw in events:
        if raw.get("type") in ("agent.tool_result", "agent.mcp_tool_result"):
            texts += [t for t in strings_in(raw.get("content")) if len(t) >= 20]
    return texts


def assert_no_tool_results_shown(events: Sequence[UIEvent], fake: FakeManagedAgentsClient) -> None:
    """The UI never gets tool results or page content (spec, `UIEvent.detail`)."""
    shown = [text for event in events for text in [event.title, *strings_in(event.detail)]]
    leaked = [text for text in tool_result_texts(fake) if any(text in s for s in shown)]
    assert leaked == []


async def assert_trip_served_to_triptracker(
    browser: Browser, plan_id: uuid.UUID, record: PlanRecord
) -> dict[str, Any]:
    """TripTracker's /import: CORS preflight, then GET /plans/{id}/trip from its Origin."""
    tracker = browser.settings.triptracker_origin
    preflight = await browser.http.options(
        f"/plans/{plan_id}/trip",
        headers={"Origin": tracker, "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == tracker
    assert preflight.headers["access-control-allow-credentials"] == "true"

    response = await browser.http.get(f"/plans/{plan_id}/trip", headers={"Origin": tracker})
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == tracker
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["cache-control"] == "no-store"
    trip = response.json()
    assert trip == record.trip
    assert_valid_trip(trip)
    again = await browser.http.get(f"/plans/{plan_id}/trip", headers={"Origin": tracker})
    assert again.content == response.content  # same ids every time: /import deduplicates

    # TripTracker's origin is allowed on that one route only.
    other = await browser.http.get(f"/plans/{plan_id}", headers={"Origin": tracker})
    assert other.status_code == 200
    assert "access-control-allow-origin" not in other.headers
    return trip


# --- the happy path -------------------------------------------------------------------------------


async def test_happy_path_from_post_to_triptracker_import(
    open_browser: OpenBrowser,
    db_session_factory: async_sessionmaker[AsyncSession],
    triptracker_edge: respx.Route,
) -> None:
    fake = scenario_with_checkpoint("happy_path", "before_submit", is_submit_plan)
    request = fake.meta["request"]
    try:
        async with open_browser(fake) as browser:
            plan_id = await browser.create_plan(request)

            # The first SSE connection follows the plan live, then the browser loses it.
            async with browser.events(plan_id) as first_connection:
                first = await first_connection.take(6)
            await fake.reached("before_submit")
            assert (await browser.detail(plan_id))["status"] == "running"

            # EventSource reconnects with Last-Event-ID: the gap from Postgres, then live.
            async with browser.events(plan_id, last_event_id=first[-1].seq) as reconnected:
                fake.release("before_submit")
                rest, final = await reconnected.until_end()
            assert final == "ready"
            await browser.wait_for_consumer_exit(plan_id)
            await fake.wait_until_done()
            fake.assert_script_done()

            record = await load_plan(db_session_factory, plan_id)
            detail = await browser.detail(plan_id)
            trip = await assert_trip_served_to_triptracker(browser, plan_id, record)
            listed = (await browser.http.get("/plans")).json()["plans"]
            schema = browser.planner.trip_schema.current()
    finally:
        await fake.shutdown()

    # The session: created with the profile's budget and pin, no personal data, brief first.
    assert len(fake.created) == 1
    created = fake.created[0]
    assert created.budget_cents == 60
    assert dict(created.metadata) == {
        "plan_id": str(plan_id),
        "agent_profile": "development",
        "app": "trip-planner",
    }
    brief = fake.sent[0]
    assert "session" in brief.open_streams  # the stream was open before the first message
    expected_brief = sessions.build_brief(
        PlanRequest.model_validate(request), today=FROZEN_NOW.date()
    )
    assert brief.payload == {
        "type": "user.message",
        "content": [{"type": "text", "text": expected_brief}],
    }
    assert expected_brief.startswith("Today is 2026-10-12 (Europe/Rome).\n\n")
    assert expected_brief.endswith(
        "Save this JSON verbatim to /workspace/shared/request.json before delegating."
    )
    assert TEST_USER_EMAIL not in json.dumps([s.payload for s in fake.sent])

    # The browser saw every stored event exactly once, across the reconnect, normalized.
    delivered = first + rest
    assert_contiguous(delivered)
    assert delivered == await stored_events(db_session_factory, plan_id)
    assert delivered[0].title == sessions.TITLE_PLAN_CREATED
    assert set(AgentName) <= {event.agent for event in delivered}
    assert {EventKind.STATUS, EventKind.MESSAGE, EventKind.TOOL, EventKind.PLAN} <= {
        event.kind for event in delivered
    }
    assert [e.title for e in delivered if e.kind is EventKind.PLAN][-1] == TITLE_PLAN_ACCEPTED
    usage = [event for event in delivered if event.kind is EventKind.USAGE]
    assert usage
    assert usage[-1].cost_cents == record.cost_cents
    assert_no_tool_results_shown(delivered, fake)
    keys = await stored_keys(db_session_factory, plan_id)
    assert None not in keys
    assert len(set(keys)) == len(keys)

    # submit_plan: validated, mapped, checked against the trip.json TripTracker served.
    assert triptracker_edge.call_count == 1
    assert schema is not None
    assert schema.url == browser.settings.trip_schema_url
    assert record.agent_versions is not None
    assert record.agent_versions["trip_schema_sha256"] == schema.sha256
    assert [(r["is_error"], result_text(r)) for r in tool_results(fake)] == [
        (False, PLAN_ACCEPTED_TEXT)
    ]
    assert (record.status, record.submit_attempts, record.failure_reason) == ("ready", 1, None)
    assert record.plan is not None
    assert record.trip is not None
    assert trip["title"] == record.plan["title"]
    assert fake.archived == [fake.session_id]  # archived once ready

    # GET /plans/{id} and GET /plans: what the plan page and the home page show.
    tracker = browser.settings.triptracker_origin
    assert detail["status"] == "ready"
    assert detail["title"] == record.plan["title"]
    assert detail["import_url"] == f"{tracker}/import?plan={plan_id}"
    assert detail["plan"] == record.plan
    assert (detail["cost_cents"], detail["budget_cents"]) == (record.cost_cents, 60)
    assert len(detail["booking_links"]) == len(record.plan["bookings"])
    assert all(check is None or check["allowed"] for check in detail["booking_links"])
    assert [(p["id"], p["status"], p["title"]) for p in listed] == [
        (str(plan_id), "ready", record.plan["title"])
    ]


async def test_a_rejected_plan_goes_back_to_the_agent_then_is_accepted(
    open_browser: OpenBrowser, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    fake = scenario("rejected_then_accepted")
    try:
        async with open_browser(fake) as browser:
            plan_id = await browser.create_plan(fake.meta["request"])
            async with browser.events(plan_id) as connection:
                events, final = await connection.until_end()
            await browser.wait_for_consumer_exit(plan_id)
            await fake.wait_until_done()
            fake.assert_script_done()
            record = await load_plan(db_session_factory, plan_id)
            await assert_trip_served_to_triptracker(browser, plan_id, record)
    finally:
        await fake.shutdown()

    assert final == "ready"
    assert_contiguous(events)
    assert events == await stored_events(db_session_factory, plan_id)
    rejected, accepted = tool_results(fake)
    assert rejected["is_error"] is True
    assert result_text(rejected).startswith("Plan rejected: ")
    assert "book_by" in result_text(rejected)
    assert (accepted["is_error"], result_text(accepted)) == (False, PLAN_ACCEPTED_TEXT)
    plan_titles = [event.title for event in events if event.kind is EventKind.PLAN]
    assert any(title.startswith("Piano respinto: ") for title in plan_titles)
    assert plan_titles[-1] == TITLE_PLAN_ACCEPTED
    assert (record.status, record.submit_attempts) == ("ready", 2)


async def test_three_rejections_fail_the_plan_and_keep_the_session(
    open_browser: OpenBrowser, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    fake = scenario("three_rejections_failed")
    try:
        async with open_browser(fake) as browser:
            plan_id = await browser.create_plan(fake.meta["request"])
            async with browser.events(plan_id) as connection:
                events, final = await connection.until_end()
            await browser.wait_for_consumer_exit(plan_id)
            await fake.wait_until_done()
            fake.assert_script_done()
            detail = await browser.detail(plan_id)
            trip = await browser.http.get(f"/plans/{plan_id}/trip")
    finally:
        await fake.shutdown()

    assert final == "failed"
    assert_contiguous(events)
    assert events == await stored_events(db_session_factory, plan_id)
    assert [r["is_error"] for r in tool_results(fake)] == [True, True, True]
    assert fake.sent[-1].payload["type"] == "user.interrupt"
    assert (detail["status"], detail["submit_attempts"]) == ("failed", 3)
    assert detail["failure_reason"] == REASON_TOO_MANY_REJECTIONS
    assert (detail["plan"], detail["import_url"]) == (None, None)
    assert trip.status_code == 409
    assert fake.archived == []  # failed sessions are kept for inspection


# --- budget, interrupt ------------------------------------------------------------------------


async def test_budget_reached_pauses_and_continue_raises_the_budget(
    open_browser: OpenBrowser,
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fake session resumes by itself after the budget update [INFERRED, P9]: no nudge.
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    fake = scenario("budget_reached")
    try:
        async with open_browser(fake) as browser:
            plan_id = await browser.create_plan(fake.meta["request"])
            async with browser.events(plan_id) as connection:
                paused = await browser.wait_for_status(plan_id, PlanStatus.BUDGET_PAUSED)
                await browser.wait_for_consumer_exit(plan_id)
                assert (paused["cost_cents"], paused["budget_cents"]) == (61, 60)
                assert paused["import_url"] is None

                refused = await browser.http.post(
                    f"/plans/{plan_id}/continue", headers={"Origin": EVIL_ORIGIN}
                )
                assert refused.status_code == 403
                assert refused.json()["detail"]["code"] == "bad_origin"
                assert fake.budget_updates == []

                continued = await browser.http.post(
                    f"/plans/{plan_id}/continue", headers=browser.frontend
                )
                assert continued.status_code == 202, continued.text
                assert continued.json() == {
                    "id": str(plan_id),
                    "status": "running",
                    "budget_cents": 261,  # max(cap 60, consumed 61) + 200
                }
                again = await browser.http.post(
                    f"/plans/{plan_id}/continue", headers=browser.frontend
                )
                assert again.status_code == 409
                assert again.json()["detail"]["code"] == "invalid_plan_state"

                # budget_paused is not terminal: the same SSE connection goes on to the end.
                events, final = await connection.until_end()
            await browser.wait_for_consumer_exit(plan_id)
            await fake.wait_until_done()
            fake.assert_script_done()
            detail = await browser.detail(plan_id)
            record = await load_plan(db_session_factory, plan_id)
            await assert_trip_served_to_triptracker(browser, plan_id, record)
    finally:
        await fake.shutdown()

    assert final == "ready"
    assert fake.budget_updates == [(fake.session_id, 261)]
    assert (detail["status"], detail["budget_cents"]) == ("ready", 261)
    assert_contiguous(events)
    assert events == await stored_events(db_session_factory, plan_id)
    titles = [event.title for event in events]
    assert titles.count(sessions.TITLE_CONTINUED) == 1
    assert titles.index(sessions.TITLE_CONTINUED) < titles.index(TITLE_PLAN_ACCEPTED)


async def test_interrupt_from_the_browser_stops_the_plan(
    open_browser: OpenBrowser, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    fake = scenario("interrupt")
    try:
        async with open_browser(fake) as browser:
            plan_id = await browser.create_plan(fake.meta["request"])
            async with browser.events(plan_id) as connection:
                await fake.reached("working")
                refused = await browser.http.post(f"/plans/{plan_id}/interrupt")  # no Origin
                assert refused.status_code == 403
                response = await browser.http.post(
                    f"/plans/{plan_id}/interrupt", headers=browser.frontend
                )
                assert response.status_code == 202, response.text
                assert response.json() == {"id": str(plan_id), "status": "running"}
                fake.release("working")
                events, final = await connection.until_end()
            await browser.wait_for_consumer_exit(plan_id)
            await fake.wait_until_done()
            fake.assert_script_done()

            detail = await browser.detail(plan_id)
            trip = await browser.http.get(f"/plans/{plan_id}/trip")
            again = await browser.http.post(f"/plans/{plan_id}/interrupt", headers=browser.frontend)
    finally:
        await fake.shutdown()

    assert final == "interrupted"
    assert (detail["status"], detail["import_url"]) == ("interrupted", None)
    assert detail["failure_reason"]
    assert trip.status_code == 409
    assert trip.json()["detail"]["code"] == "plan_not_ready"
    assert again.status_code == 409
    assert again.json()["detail"] == {
        "code": "invalid_plan_state",
        "message": "Il piano non è in uno stato che lo permette.",
        "data": {"status": "interrupted"},
    }
    assert [s.payload["type"] for s in fake.sent].count("user.interrupt") == 1
    assert fake.archived == [fake.session_id]
    assert_contiguous(events)
    assert events == await stored_events(db_session_factory, plan_id)
    assert sessions.TITLE_INTERRUPT_REQUESTED in [event.title for event in events]
    record = await load_plan(db_session_factory, plan_id)
    assert record.interrupt_requested_at is not None
    assert record.trip is None


# --- restart --------------------------------------------------------------------------------------

RESTART_TOOL_USE = "sevt_011CZv95QMnpRSTerY4jSH9y"


async def test_a_restart_resumes_the_plan_in_a_new_app_instance(
    open_browser: OpenBrowser, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Process 1 stores the submit_plan outcome, then dies while its answer is on the wire.
    Process 2 (a new app on the same database and the same remote session) resumes the plan
    at startup, answers from the stored outcome, and the browser's EventSource picks up where
    it was with Last-Event-ID."""
    fake = scenario("restart_resume", page_size=10)
    try:
        async with open_browser(fake) as first_process:
            plan_id = await first_process.create_plan(fake.meta["request"])
            async with first_process.events(plan_id) as connection:
                first = await connection.take(5)
                await fake.reached("crash")
                hung = await fake.called("send_custom_tool_result")
                assert hung.args["tool_use_id"] == RESTART_TOOL_USE
            # The process dies: lifespan shutdown cancels the consumer mid-call.

        crashed = await load_plan(db_session_factory, plan_id)
        assert (crashed.status, crashed.submit_attempts) == ("running", 1)
        assert crashed.plan is not None  # the outcome was committed before the answer
        assert tool_results(fake) == []  # the answer never left
        stored_before = await stored_events(db_session_factory, plan_id)

        async with open_browser(fake) as second_process:
            registry = second_process.planner.registry
            assert registry is not None
            assert registry.active_plan_ids() == [plan_id]  # resumed at startup
            async with second_process.events(plan_id, last_event_id=first[-1].seq) as connection:
                fake.release("crash")
                rest, final = await connection.until_end()
            await second_process.wait_for_consumer_exit(plan_id)
            await fake.wait_until_done()
            fake.assert_script_done()
            record = await load_plan(db_session_factory, plan_id)
            await assert_trip_served_to_triptracker(second_process, plan_id, record)
    finally:
        await fake.shutdown()

    assert final == "ready"
    delivered = first + rest
    assert_contiguous(delivered)
    stored = await stored_events(db_session_factory, plan_id)
    assert delivered == stored
    assert stored[: len(stored_before)] == stored_before  # process 2 continued the sequence
    keys = await stored_keys(db_session_factory, plan_id)
    assert None not in keys
    assert len(set(keys)) == len(keys)
    # Answered once, from the stored outcome: never evaluated a second time.
    assert [(r["custom_tool_use_id"], r["is_error"]) for r in tool_results(fake)] == [
        (RESTART_TOOL_USE, False)
    ]
    assert (record.status, record.submit_attempts) == ("ready", 1)
    assert fake.archived == [fake.session_id]


# --- refusals -----------------------------------------------------------------------------------


async def test_the_monthly_limit_refuses_a_new_plan_before_spending(
    open_browser: OpenBrowser,
    plan_rows: PlanRows,
    db_session_factory: async_sessionmaker[AsyncSession],
    e2e_settings: Settings,
) -> None:
    assert e2e_settings.monthly_limit_cents == 5000
    fake = scenario("happy_path")
    try:
        async with open_browser(fake) as browser:
            # Last month's spend doesn't count; this month's sits exactly at the limit.
            await plan_rows.add_plan(
                status=PlanStatus.READY,
                cost_cents=9000,
                created_at=FROZEN_NOW - dt.timedelta(days=31),
            )
            await plan_rows.add_plan(
                status=PlanStatus.READY,
                cost_cents=5000,
                created_at=FROZEN_NOW,
                user_email="someone-else@example.com",  # the limit is the organization's
            )
            response = await browser.http.post(
                "/plans", json=dict(fake.meta["request"]), headers=browser.frontend
            )
    finally:
        await fake.shutdown()

    assert response.status_code == 429
    assert response.json()["detail"] == {
        "code": "monthly_limit_reached",
        "message": (
            "Questo mese il planner ha già impegnato 50,00 $ su 50,00 $: il prossimo piano si "
            "potrà creare il mese prossimo."
        ),
        "data": {"spent_cents": 5000, "limit_cents": 5000},
    }
    assert fake.created == []  # nothing was spent
    assert fake.sent == []
    assert await count_plans(db_session_factory) == 2


async def test_state_changing_requests_from_another_origin_are_refused(
    open_browser: OpenBrowser,
    plan_rows: PlanRows,
    db_session_factory: async_sessionmaker[AsyncSession],
    e2e_settings: Settings,
) -> None:
    fake = scenario("happy_path")
    try:
        async with open_browser(fake) as browser:
            paused = await plan_rows.add_plan(status=PlanStatus.BUDGET_PAUSED)
            request = dict(fake.meta["request"])
            refusals: list[httpx.Response] = []
            for headers in (
                {"Origin": EVIL_ORIGIN},
                {"Origin": "null"},
                {},
                {"Origin": e2e_settings.triptracker_origin},  # read-only, /trip only
            ):
                refusals.append(await browser.http.post("/plans", json=request, headers=headers))
            for action in ("interrupt", "continue"):
                refusals.append(
                    await browser.http.post(
                        f"/plans/{paused.id}/{action}", headers={"Origin": EVIL_ORIGIN}
                    )
                )
            preflight = await browser.http.options(
                "/plans",
                headers={"Origin": EVIL_ORIGIN, "Access-Control-Request-Method": "POST"},
            )
            trip_preflight = await browser.http.options(
                f"/plans/{paused.id}/trip",
                headers={"Origin": EVIL_ORIGIN, "Access-Control-Request-Method": "GET"},
            )
    finally:
        await fake.shutdown()

    for response in refusals:
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == {
            "code": "bad_origin",
            "message": "Richiesta rifiutata: arriva da un'origine non consentita.",
            "data": None,
        }
        assert "access-control-allow-origin" not in response.headers
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert trip_preflight.status_code == 400
    assert fake.created == []
    assert fake.sent == []
    assert fake.budget_updates == []
    assert await count_plans(db_session_factory) == 1
    assert (await load_plan(db_session_factory, paused.id)).status == "budget_paused"
