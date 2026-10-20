"""The local demo (DEMO_MODE, development only): the settings guard, the paced scenarios of
`tests/fakes/demo.py`, POST /plans?demo_scenario= and whole demo runs through the real app.

Demo runs go through `create_app` with DEMO_MODE and no client override, so `start_planner`
builds the demo client, the synthetic roster and the vendored trip.json by itself; every
outgoing httpx request fails (respx), the clock ticks from the scenarios' day, and DEMO_PACE is
tiny so a run takes about a second.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import sessions
from app.cli import REPLAY_LOCKFILE_DIR
from app.config import Settings
from app.consumer import ConsumerRegistry
from app.db import PlanRecord, PlanStatus
from app.ma_client import AgentPin, ApiRejectedError, SessionNotFoundError
from app.triptracker_schema import DEV_FALLBACK_SCHEMA_PATH
from tests.conftest import TEST_ENV, AppFactory, PlanRows, StubPlanner
from tests.fakes import FIXTURES_DIR, FakeManagedAgentsClient, load_jsonl
from tests.fakes.demo import (
    EXCLUDED_SCENARIOS,
    MAX_GAP_SECONDS,
    DemoManagedAgentsClient,
    PacedFakeClient,
    demo_scenarios,
)
from tests.test_consumer import SID, HarnessFactory, harness  # noqa: F401 (fixture)
from tests.test_e2e_offline import (  # noqa: F401 (fixture)
    FROZEN_NOW,
    Browser,
    assert_contiguous,
    assert_valid_trip,
    frozen_clock,
    stored_events,
)

DEMO_PACE = 0.01
FRONTEND = "https://atlas.bellittim.com"
REQUEST: dict[str, Any] = {
    "origin": "Milano",
    "destination": "Lisbona",
    "dates": {"exact_start": "2027-04-14", "exact_end": "2027-04-18"},
    "travelers": [{"kind": "adult"}, {"kind": "adult"}, {"kind": "child", "age": 9}],
    "budget_eur": 2800,
}
SHIPPED_STATES = {
    "happy_path": "ready",
    "rejected_then_accepted": "ready",
    "three_rejections_failed": "failed",
    "requires_action_blocked": "blocked",
    "end_turn_without_plan": "failed",
    "mcp_failure": "ready",
}
"""Scenarios that run to their end state without the user, and that state."""


# --- settings guard -----------------------------------------------------------------------------


def production(make_settings: Callable[..., Settings], **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "production",
        "auth_mode": "triptracker",
        "anthropic_api_key": "sk-ant-test-not-real",
        "agent_profile": "production",
    }
    return make_settings(**{**values, **overrides})


def test_demo_mode_is_off_by_default_and_refused_outside_development(
    make_settings: Callable[..., Settings],
) -> None:
    assert make_settings().demo_mode is False
    assert production(make_settings).demo_mode is False
    assert make_settings(demo_mode="true").demo_mode is True

    with pytest.raises(ValidationError, match="only allowed when ENVIRONMENT=development"):
        production(make_settings, demo_mode="true")
    with pytest.raises(ValidationError, match="only allowed when ENVIRONMENT=development"):
        production(make_settings, demo_pace="2")
    assert production(make_settings, demo_mode="false", demo_pace="").demo_pace == 1.0


@pytest.mark.parametrize(
    ("raw", "pace"), [("", 1.0), ("1", 1.0), ("2.5", 2.5), ("0.05", 0.05), (" ", 1.0)]
)
def test_demo_pace_reads_a_positive_factor(
    make_settings: Callable[..., Settings], raw: str, pace: float
) -> None:
    assert make_settings(demo_mode="true", demo_pace=raw).demo_pace == pace


@pytest.mark.parametrize("raw", ["0", "-1", "inf", "nan", "101", "fast"])
def test_demo_pace_refuses_nonsense(make_settings: Callable[..., Settings], raw: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(demo_mode="true", demo_pace=raw)


def test_a_blank_demo_mode_means_off(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(demo_mode="").demo_mode is False


def test_env_example_documents_the_demo(bare_env: pytest.MonkeyPatch) -> None:
    example = Path(__file__).resolve().parents[1] / ".env.example"
    settings = Settings(_env_file=example)  # pyright: ignore[reportCallIssue]
    assert (settings.demo_mode, settings.demo_pace) == (False, 1.0)
    text = example.read_text(encoding="utf-8")
    assert "DEMO_MODE=true" in text  # the one-line start command
    assert "demo_scenario" in text


@pytest.fixture
def bare_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """No settings in the environment: Settings reads only the file it is given."""
    for key in (*TEST_ENV, "DEMO_MODE", "DEMO_PACE"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# --- the scenarios and their pace ---------------------------------------------------------------


def test_every_shipped_scenario_but_the_excluded_ones_are_offered() -> None:
    shipped = {path.stem for path in FIXTURES_DIR.glob("*.jsonl")}
    assert set(demo_scenarios()) == shipped - EXCLUDED_SCENARIOS
    assert list(demo_scenarios()) == sorted(demo_scenarios())
    assert {"restart_resume", "choice_interrupt"} == EXCLUDED_SCENARIOS
    assert "choices" in demo_scenarios()
    assert sessions.DEFAULT_DEMO_SCENARIO == "happy_path"
    assert {*SHIPPED_STATES, "budget_reached", "interrupt"} <= set(demo_scenarios())
    assert sessions.DEFAULT_DEMO_SCENARIO in demo_scenarios()


def recorded_gaps(name: str) -> float:
    """What pace 1.0 should wait in total: the capped gaps between scripted stamps, the pause
    after a user action excluded."""
    steps, _ = load_jsonl(FIXTURES_DIR / f"{name}.jsonl")
    total, last = 0.0, None
    for step in steps:
        if step["op"] in ("await_call", "checkpoint"):
            last = None
            continue
        if step["op"] not in ("emit", "usage"):
            continue
        stamp = (step.get("event") or step).get("processed_at")
        if stamp is None:
            continue
        instant = dt.datetime.fromisoformat(stamp)
        if last is not None:
            total += min(max((instant - last).total_seconds(), 0.0), MAX_GAP_SECONDS)
        last = instant
    return total


@pytest.mark.parametrize("pace", [1.0, 2.0])
async def test_happy_path_lasts_about_a_minute_and_a_quarter_at_pace_one(
    harness: HarnessFactory,  # noqa: F811
    pace: float,
) -> None:
    """At DEMO_PACE=1 the recorded gaps (capped at MAX_GAP_SECONDS) add up to 60-90 s, so the
    live screen can be watched; DEMO_PACE scales them. Events carry wall-clock instants."""
    delays: list[float] = []

    async def record(seconds: float) -> None:
        delays.append(seconds)
        await asyncio.sleep(0)

    started = dt.datetime(2026, 10, 12, 14, 0, tzinfo=dt.UTC)
    ticks = iter(range(10_000))
    steps, _ = load_jsonl(FIXTURES_DIR / "happy_path.jsonl")
    fake = PacedFakeClient(
        steps,
        pace=pace,
        sleep=record,
        now=lambda: started + dt.timedelta(seconds=next(ticks)),
        await_timeout=10,
    )
    h = harness(fake)
    plan_id = await h.create_plan()

    assert await h.run(plan_id) is PlanStatus.READY

    fake.assert_script_done()
    assert 60 <= recorded_gaps("happy_path") <= 90
    assert sum(delays) == pytest.approx(recorded_gaps("happy_path") * pace)
    assert max(delays) <= MAX_GAP_SECONDS * pace
    rows = await h.events(plan_id)
    api_rows = [row for row in rows if not (row.ma_event_id or "").startswith("backend:")]
    assert len(api_rows) > 90
    # Re-stamped from the demo's clock, not the 10:00 of the recording.
    assert all(row.ts >= started for row in api_rows)
    assert all(raw["processed_at"] >= "2026-10-12T14:00" for raw in fake.history)


async def test_an_interrupt_stops_any_scenario_like_the_api_would(
    harness: HarnessFactory,  # noqa: F811
) -> None:
    """Outside the `interrupt` scenario the script has no step for the user's interrupt: the
    demo stops it and idles the working threads and the session with `end_turn`."""
    steps, _ = load_jsonl(FIXTURES_DIR / "happy_path.jsonl")
    fake = PacedFakeClient(steps, pace=0.02, await_timeout=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    consumer = h.consumer(plan_id)
    task = asyncio.create_task(consumer.run())
    try:
        async with asyncio.timeout(10):
            while len(fake.calls_of("stream_thread")) < 2:  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        consumer.request_interrupt()  # what sessions.request_interrupt does
        await fake.send_interrupt(SID)
        async with asyncio.timeout(10):
            status = await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await fake.shutdown()

    assert status is PlanStatus.INTERRUPTED
    assert fake.wound_down
    assert fake.mismatches == []
    assert all(thread.status != "running" for thread in fake.threads())
    assert fake.archived == [SID]


# --- the demo client ----------------------------------------------------------------------------


PIN = AgentPin(id="agent_demo_coordinator", version=1)


async def test_the_demo_client_plays_one_scenario_per_session() -> None:
    client = DemoManagedAgentsClient(pace=DEMO_PACE)
    metadata = {"plan_id": str(uuid.uuid4()), "app": "trip-planner"}
    try:
        first = await client.create_session(
            agent=PIN, environment_id="env_demo", budget_cents=60, metadata=metadata
        )
        second = await client.create_session(
            agent=PIN,
            environment_id="env_demo",
            budget_cents=60,
            metadata={**metadata, sessions.DEMO_SCENARIO_METADATA: "budget_reached"},
        )
        assert first.id != second.id
        assert first.id.startswith(sessions.DEMO_SESSION_PREFIX)
        assert second.id.startswith(sessions.DEMO_SESSION_PREFIX)
        assert client.scenarios == {first.id: "happy_path", second.id: "budget_reached"}
        assert (await client.retrieve_session(second.id)).id == second.id

        with pytest.raises(ApiRejectedError):
            await client.create_session(
                agent=PIN,
                environment_id="env_demo",
                budget_cents=60,
                metadata={**metadata, sessions.DEMO_SCENARIO_METADATA: "restart_resume"},
            )
        with pytest.raises(SessionNotFoundError):
            await client.retrieve_session("sesn_demo_unknown")
        with pytest.raises(SessionNotFoundError):
            async with client.stream_session("sesn_real_one"):
                pass
        assert await client.list_sessions(created_before=FROZEN_NOW) == []
    finally:
        await client.aclose()
    assert client.closed


# --- through the app ----------------------------------------------------------------------------


@pytest.fixture
def demo_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(demo_mode=True, demo_pace=DEMO_PACE)


@pytest.fixture
def offline_edges() -> Iterator[None]:
    """No outgoing httpx request at all: the demo needs no network (trip.json is vendored)."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True):
        yield


DemoApp = Callable[..., AbstractAsyncContextManager[Browser]]


@pytest.fixture
def demo_app(
    make_app: AppFactory,
    demo_settings: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    offline_edges: None,
    frozen_clock: None,  # noqa: F811
) -> DemoApp:
    """`async with demo_app() as browser:` a fresh app in DEMO_MODE on the emptied database."""
    del db_session_factory

    @asynccontextmanager
    async def factory(*, settings: Settings = demo_settings) -> AsyncIterator[Browser]:
        async with make_app(settings=settings) as app:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                yield Browser(app=app, http=http, settings=settings)

    return factory


def demo_client(browser: Browser) -> DemoManagedAgentsClient:
    client = browser.planner.client
    assert isinstance(client, DemoManagedAgentsClient)
    return client


async def create(browser: Browser, scenario: str | None = None) -> httpx.Response:
    params = {"demo_scenario": scenario} if scenario is not None else None
    return await browser.http.post("/plans", json=REQUEST, params=params, headers=browser.frontend)


async def create_plan(browser: Browser, scenario: str | None = None) -> uuid.UUID:
    response = await create(browser, scenario)
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


async def run_to_end(browser: Browser, plan_id: uuid.UUID) -> str:
    async with browser.events(plan_id) as connection:
        events, final = await connection.until_end()
    assert_contiguous(events)
    await browser.wait_for_consumer_exit(plan_id)
    return final


async def test_a_demo_plan_runs_from_post_to_the_trip_without_key_lockfile_or_network(
    demo_app: DemoApp, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with demo_app() as browser:
        planner = browser.planner
        assert planner.unavailable_reasons == []
        assert planner.settings.anthropic_api_key is None
        assert planner.roster is not None
        assert planner.roster.lockfile_sha256 == "demo"
        assert planner.demo_scenarios == demo_scenarios()

        plan_id = await create_plan(browser)
        assert await run_to_end(browser, plan_id) == "ready"
        detail = await browser.detail(plan_id)
        trip = await browser.http.get(f"/plans/{plan_id}/trip")
        [session_id] = demo_client(browser).sessions

    assert detail["status"] == "ready"
    assert detail["import_url"] is not None
    assert trip.status_code == 200
    assert_valid_trip(trip.json())
    events = await stored_events(db_session_factory, plan_id)
    assert len(events) > 90
    assert session_id.startswith(sessions.DEMO_SESSION_PREFIX)


@pytest.mark.parametrize(("scenario", "state"), sorted(SHIPPED_STATES.items()))
async def test_every_automatic_scenario_reaches_its_state(
    demo_app: DemoApp, scenario: str, state: str
) -> None:
    async with demo_app() as browser:
        plan_id = await create_plan(browser, scenario)
        assert await run_to_end(browser, plan_id) == state
        fake = demo_client(browser).sessions[next(iter(demo_client(browser).sessions))]
        assert fake.mismatches == []


async def test_demo_choices_waits_for_the_answer(demo_app: DemoApp) -> None:
    """The PR's end-to-end test of the answer endpoint: the scripted session pauses twice, the
    traveller answers through POST /plans/{id}/choices/{choice_id} (a pick, then a skip)."""
    async with demo_app() as browser:
        plan_id = await create_plan(browser, "choices")

        async def open_choice(kind: str) -> dict[str, Any]:
            async with asyncio.timeout(10):
                while True:
                    pending = (await browser.detail(plan_id))["pending_choice"]
                    if pending is not None and pending["kind"] == kind:
                        return pending
                    await asyncio.sleep(0.02)

        activities = await open_choice("activities")
        await asyncio.sleep(0.2)  # the script waits for the traveller, however long it takes
        assert (await browser.detail(plan_id))["pending_choice"]["id"] == activities["id"]
        picked = await browser.http.post(
            f"/plans/{plan_id}/choices/{activities['id']}",
            json={"selected": [activities["options"][1]["id"]]},
            headers=browser.frontend,
        )
        assert picked.status_code == 200, picked.text

        food = await open_choice("food")
        assert food["id"] != activities["id"]
        skipped = await browser.http.post(
            f"/plans/{plan_id}/choices/{food['id']}", json={"skip": True}, headers=browser.frontend
        )
        assert skipped.status_code == 200, skipped.text

        assert await run_to_end(browser, plan_id) == "ready"
        detail = await browser.detail(plan_id)
        [fake] = demo_client(browser).sessions.values()

    assert detail["pending_choice"] is None
    assert fake.mismatches == []


def test_demo_offers_choices_but_not_choice_interrupt() -> None:
    assert "choices" in demo_scenarios()
    assert "choice_interrupt" not in demo_scenarios()
    assert sessions.DEFAULT_DEMO_SCENARIO == "happy_path"


async def test_budget_reached_waits_for_continue_on_the_real_endpoint(
    demo_app: DemoApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    async with demo_app() as browser:
        plan_id = await create_plan(browser, "budget_reached")
        paused = await browser.wait_for_status(plan_id, PlanStatus.BUDGET_PAUSED)
        await browser.wait_for_consumer_exit(plan_id)
        await asyncio.sleep(0.3)  # the script waits for the user, however long it takes
        assert (await browser.detail(plan_id))["status"] == "budget_paused"

        continued = await browser.http.post(f"/plans/{plan_id}/continue", headers=browser.frontend)
        assert continued.status_code == 202, continued.text
        assert await run_to_end(browser, plan_id) == "ready"
        detail = await browser.detail(plan_id)

    assert (paused["cost_cents"], paused["budget_cents"]) == (61, 60)
    assert (detail["status"], detail["budget_cents"]) == ("ready", 261)


async def test_the_interrupt_scenario_waits_for_the_real_interrupt(demo_app: DemoApp) -> None:
    async with demo_app() as browser:
        plan_id = await create_plan(browser, "interrupt")
        [fake] = demo_client(browser).sessions.values()
        await fake.reached("working")
        response = await browser.http.post(f"/plans/{plan_id}/interrupt", headers=browser.frontend)
        assert response.status_code == 202, response.text
        assert await run_to_end(browser, plan_id) == "interrupted"
        detail = await browser.detail(plan_id)

    fake.assert_script_done()
    assert not fake.wound_down  # the script's own end, not the generic one
    assert detail["failure_reason"]


async def test_interrupting_a_happy_path_demo_stops_it(demo_app: DemoApp) -> None:
    async with demo_app() as browser:
        plan_id = await create_plan(browser)
        [fake] = demo_client(browser).sessions.values()
        async with asyncio.timeout(10):
            while not fake.calls_of("stream_thread"):  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        response = await browser.http.post(f"/plans/{plan_id}/interrupt", headers=browser.frontend)
        assert response.status_code == 202, response.text
        assert await run_to_end(browser, plan_id) == "interrupted"
    assert fake.wound_down


@pytest.mark.parametrize("name", ["restart_resume", "nope", "HAPPY_PATH", ""])
async def test_an_unknown_demo_scenario_is_a_422_on_the_query(demo_app: DemoApp, name: str) -> None:
    async with demo_app() as browser:
        response = await create(browser, name)
        assert demo_client(browser).sessions == {}
    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["loc"] == ["query", "demo_scenario"]
    assert error["type"] == "literal_error"
    assert error["input"] == name
    assert "happy_path" in error["msg"]


async def test_demo_scenario_is_404_without_demo_mode(
    make_app: AppFactory,
    stub_planner: StubPlanner,
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del stub_planner, db_session_factory
    started: list[Any] = []

    async def start_plan(*args: Any, **kwargs: Any) -> uuid.UUID:
        started.append((args, kwargs))
        return uuid.uuid4()

    monkeypatch.setattr(sessions, "start_plan", start_plan)
    async with make_app() as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            response = await http.post(
                "/plans",
                json=REQUEST,
                params={"demo_scenario": "happy_path"},
                headers={"Origin": FRONTEND},
            )
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "demo_unavailable",
        "message": "La modalità demo non è attiva su questo server.",
        "data": None,
    }
    assert started == []


# --- restarts -----------------------------------------------------------------------------------


async def test_a_restart_closes_demo_plans_and_leaves_real_ones_alone(
    demo_app: DemoApp, plan_rows: PlanRows, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A demo session dies with its process: at the next start the plan is closed. In demo
    mode a real running plan is neither resumed (the demo client can't follow it) nor touched."""
    demo_plan = await plan_rows.add_plan()
    real_plan = await plan_rows.add_plan()
    await set_session(db_session_factory, demo_plan.id, f"{sessions.DEMO_SESSION_PREFIX}abc")

    async with demo_app() as browser:
        registry = cast(ConsumerRegistry, browser.planner.registry)
        assert registry.active_plan_ids() == []
        closed = await browser.detail(demo_plan.id)
        real = await browser.detail(real_plan.id)

    assert (closed["status"], closed["failure_reason"]) == (
        "interrupted",
        sessions.REASON_DEMO_ENDED,
    )
    assert real["status"] == "running"


async def test_a_start_without_demo_mode_closes_leftover_demo_plans(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    plan_rows: PlanRows,
    db_session_factory: async_sessionmaker[AsyncSession],
    offline_edges: None,
) -> None:
    leftover = await plan_rows.add_plan()
    await set_session(db_session_factory, leftover.id, f"{sessions.DEMO_SESSION_PREFIX}abc")
    settings = make_settings(
        lockfile_path=REPLAY_LOCKFILE_DIR / "claude-lock.development.json",
        trip_schema_url=DEV_FALLBACK_SCHEMA_PATH.as_uri(),
    )
    fake = FakeManagedAgentsClient()
    async with make_app(settings=settings, client=fake) as app:
        planner = app.state.planner
        assert planner.registry.active_plan_ids() == []
    assert await status_of(db_session_factory, leftover.id) == "interrupted"
    assert [call.method for call in fake.calls] == ["aclose"]  # never asked the API about it


async def set_session(
    factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID, session_id: str
) -> None:
    async with factory() as db:
        await db.execute(
            update(PlanRecord).where(PlanRecord.id == plan_id).values(session_id=session_id)
        )
        await db.commit()


async def status_of(factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID) -> str:
    async with factory() as db:
        record = await db.get(PlanRecord, plan_id)
    assert record is not None
    return record.status
