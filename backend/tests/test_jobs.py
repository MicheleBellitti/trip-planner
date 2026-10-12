"""app.jobs: the nightly cleanup (retention, ordering, orphan sweep) and the stuck-plan check."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
import structlog
import time_machine
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import jobs
from app.config import Settings, get_settings
from app.consumer import StatusChange, set_plan_status
from app.db import EventRecord, FxRateRecord, PlanRecord, PlanStatus
from app.jobs import (
    REASON_STUCK,
    TITLE_STUCK,
    TITLE_STUCK_REQUESTED,
    check_stuck_plans,
    nightly_cleanup,
    start_stuck_plan_checker,
)
from app.ma_client import SessionInfo, SessionUsage
from app.sessions import TITLE_INTERRUPTED
from tests.conftest import truncate_all
from tests.fakes import FakeManagedAgentsClient
from tests.test_sessions import (
    FROZEN_NOW,
    SCHEMA_URL,
    Planner,
    insert_plan,
    load_events,
    load_plan,
    open_planner,
    planner_settings,
)

NOW = FROZEN_NOW
OLD = NOW - dt.timedelta(days=100)
YOUNG = NOW - dt.timedelta(days=10)


def workspace_session(
    session_id: str,
    plan_id: uuid.UUID | str | None,
    *,
    app: str = "trip-planner",
    status: Any = "idle",
    created_at: dt.datetime = OLD,
) -> SessionInfo:
    metadata = {"agent_profile": "development", "app": app}
    if plan_id is not None:
        metadata["plan_id"] = str(plan_id)
    return SessionInfo(
        id=session_id,
        status=status,
        usage=SessionUsage(list_cost_cents=40),
        budget_cents=60,
        archived=True,
        metadata=metadata,
        created_at=created_at,
    )


class OrderingClient(FakeManagedAgentsClient):
    """Records, for every `delete_session`, whether the plan row still existed at that moment."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.session_factory = session_factory
        self.row_present: dict[str, bool] = {}

    async def delete_session(self, session_id: str) -> None:
        async with self.session_factory() as db:
            found = await db.scalar(
                select(PlanRecord.id).where(PlanRecord.session_id == session_id)
            )
        self.row_present[session_id] = found is not None
        await super().delete_session(session_id)


async def add_event(session_factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID) -> None:
    async with session_factory() as db:
        db.add(
            EventRecord(
                plan_id=plan_id,
                seq=0,
                agent="coordinator",
                kind="status",
                title="Piano avviato",
                ma_event_id=f"backend:{plan_id}:status:created",
            )
        )
        await db.commit()


async def count(session_factory: async_sessionmaker[AsyncSession], model: Any) -> int:
    async with session_factory() as db:
        return int(await db.scalar(select(func.count()).select_from(model)) or 0)


# --- nightly cleanup -----------------------------------------------------------------------------


async def test_cleanup_deletes_the_session_before_the_plan(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old_a = await insert_plan(db_session_factory, session_id="sesn_old_a", created_at=OLD)
    old_b = await insert_plan(db_session_factory, session_id="sesn_old_b", created_at=OLD)
    young = await insert_plan(db_session_factory, session_id="sesn_young", created_at=YOUNG)
    for plan_id in (old_a, old_b, young):
        await add_event(db_session_factory, plan_id)
    client = OrderingClient(
        db_session_factory,
        workspace_sessions=[
            workspace_session("sesn_old_a", old_a),
            workspace_session("sesn_old_b", old_b),
            workspace_session("sesn_young", young, created_at=YOUNG),
        ],
    )

    report = await nightly_cleanup(session_factory=db_session_factory, client=client, now=NOW)

    assert client.row_present == {"sesn_old_a": True, "sesn_old_b": True}  # session first
    assert sorted(client.deleted) == ["sesn_old_a", "sesn_old_b"]
    assert (report.plans_deleted, report.sessions_deleted) == (2, 2)
    assert report.orphan_sessions_deleted == 0
    assert report.failures == []
    async with db_session_factory() as db:
        remaining = list(await db.scalars(select(PlanRecord.id)))
        events = list(await db.scalars(select(EventRecord.plan_id)))
    assert remaining == [young]
    assert events == [young]  # the old plans' events went with them (cascade)

    again = await nightly_cleanup(session_factory=db_session_factory, client=client, now=NOW)
    assert again == jobs.CleanupReport()  # idempotent


async def test_session_already_gone_still_deletes_the_plan(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_plan(db_session_factory, session_id="sesn_gone", created_at=OLD)
    without_session = await insert_plan(db_session_factory, session_id=None, created_at=OLD)
    client = FakeManagedAgentsClient()
    report = await nightly_cleanup(session_factory=db_session_factory, client=client, now=NOW)
    assert report.sessions_already_gone == 1
    assert report.plans_deleted == 2
    assert await count(db_session_factory, PlanRecord) == 0
    assert without_session  # deleted without any API call for it
    assert [call.session_id for call in client.calls_of("delete_session")] == ["sesn_gone"]


async def test_running_session_is_interrupted_and_its_plan_kept(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    plan_id = await insert_plan(db_session_factory, session_id="sesn_busy", created_at=OLD)
    client = FakeManagedAgentsClient(
        workspace_sessions=[workspace_session("sesn_busy", plan_id, status="running")]
    )
    report = await nightly_cleanup(session_factory=db_session_factory, client=client, now=NOW)
    assert report.plans_deleted == 0
    assert len(report.failures) == 1
    assert str(plan_id) in report.failures[0]
    assert "interrupted" in report.failures[0]
    assert [call.session_id for call in client.calls_of("send_interrupt")] == ["sesn_busy"]
    assert (await load_plan(db_session_factory, plan_id)).id == plan_id
    assert client.deleted == []


async def test_failed_session_deletion_keeps_the_plan(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    kept = await insert_plan(
        db_session_factory, session_id="sesn_old_a", created_at=OLD - dt.timedelta(days=1)
    )
    deleted = await insert_plan(db_session_factory, session_id="sesn_old_b", created_at=OLD)
    client = FakeManagedAgentsClient(
        workspace_sessions=[
            workspace_session("sesn_old_a", kept),
            workspace_session("sesn_old_b", deleted),
        ]
    )
    client.fail_next("delete_session", "api_unavailable")
    report = await nightly_cleanup(session_factory=db_session_factory, client=client, now=NOW)
    assert report.plans_deleted == 1
    assert len(report.failures) == 1
    async with db_session_factory() as db:
        assert list(await db.scalars(select(PlanRecord.id))) == [kept]


async def test_without_a_client_plans_with_sessions_are_kept(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with_session = await insert_plan(db_session_factory, session_id="sesn_x", created_at=OLD)
    await insert_plan(db_session_factory, session_id=None, created_at=OLD)
    report = await nightly_cleanup(session_factory=db_session_factory, client=None, now=NOW)
    assert report.plans_deleted == 1
    assert report.sessions_deleted == 0
    assert len(report.failures) == 1
    assert "ANTHROPIC_API_KEY" in report.failures[0]
    async with db_session_factory() as db:
        assert list(await db.scalars(select(PlanRecord.id))) == [with_session]


async def test_orphan_sweep_deletes_only_our_sessions_without_a_plan(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # A plan whose old session could not be deleted keeps its row: its session is no orphan.
    survivor = await insert_plan(db_session_factory, session_id="sesn_kept", created_at=YOUNG)
    client = FakeManagedAgentsClient(
        workspace_sessions=[
            workspace_session("sesn_orphan", uuid.uuid4()),  # crash before session_id commit
            workspace_session("sesn_bad_id", "not-a-uuid"),
            workspace_session("sesn_kept", survivor),
            workspace_session("sesn_foreign", uuid.uuid4(), app="another-app"),
            workspace_session("sesn_no_metadata", None, app=""),
            workspace_session("sesn_recent_orphan", uuid.uuid4(), created_at=YOUNG),
        ]
    )
    report = await nightly_cleanup(session_factory=db_session_factory, client=client, now=NOW)
    assert sorted(client.deleted) == ["sesn_bad_id", "sesn_orphan"]
    assert report.orphan_sessions_deleted == 2
    assert report.failures == []
    [listing] = client.calls_of("list_sessions")
    assert listing.args == {"created_before": NOW - jobs.PLAN_RETENTION, "include_archived": True}


async def test_cleanup_deletes_fx_rates_older_than_a_year(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        for day in (dt.date(2025, 10, 11), dt.date(2025, 10, 12), dt.date(2026, 10, 9)):
            db.add(FxRateRecord(date=day, currency="USD", source="bdi_daily", rate=Decimal("1.1")))
        await db.commit()
    report = await nightly_cleanup(session_factory=db_session_factory, client=None, now=NOW)
    assert report.fx_rates_deleted == 1
    async with db_session_factory() as db:
        dates = sorted(await db.scalars(select(FxRateRecord.date)))
    assert dates == [dt.date(2025, 10, 12), dt.date(2026, 10, 9)]


async def test_cleanup_works_in_batches(
    db_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "CLEANUP_BATCH_SIZE", 2)
    for _ in range(5):
        await insert_plan(db_session_factory, session_id=None, created_at=OLD)
    stuck = await insert_plan(db_session_factory, session_id="sesn_busy", created_at=OLD)
    client = FakeManagedAgentsClient(
        workspace_sessions=[workspace_session("sesn_busy", stuck, status="running")]
    )
    report = await nightly_cleanup(session_factory=db_session_factory, client=client, now=NOW)
    assert report.plans_deleted == 5
    assert len(report.failures) == 1
    assert await count(db_session_factory, PlanRecord) == 1


async def test_cleanup_rejects_a_naive_now(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await nightly_cleanup(
            session_factory=db_session_factory,
            client=None,
            now=dt.datetime(2026, 10, 12),  # noqa: DTZ001 - the point of the test
        )


# --- stuck plans ---------------------------------------------------------------------------------


@pytest.fixture
async def planner(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Planner]:
    async with open_planner(planner_settings(make_settings), db_session_factory) as opened:
        yield opened


@pytest.fixture
def quick_stuck_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "STUCK_INTERRUPT_GRACE_SECONDS", 0.3)
    monkeypatch.setattr(jobs, "STUCK_POLL_SECONDS", 0.02)


@pytest.mark.usefixtures("quick_stuck_check")
async def test_stuck_plan_is_interrupted_then_forced(planner: Planner) -> None:
    running_since = NOW - dt.timedelta(minutes=46)
    plan_id = await insert_plan(planner.session_factory, running_since=running_since, cost_cents=12)
    consumer = planner.registry.start(plan_id, "sesn_fake_0001")
    # Spent after the last `session.usage` the consumer stored (no idle came to report it).
    planner.fake.emit(
        {"type": "session.usage", "usage": {"list_cost": {"amount": "57", "currency": "USD"}}}
    )

    handled = await check_stuck_plans(planner.services, now=NOW)

    assert handled == [plan_id]
    assert consumer.interrupts == 1
    assert [sent.payload for sent in planner.fake.sent] == [{"type": "user.interrupt"}]
    plan = await load_plan(planner.session_factory, plan_id)
    assert (plan.status, plan.failure_reason) == (PlanStatus.INTERRUPTED, REASON_STUCK)
    assert plan.interrupt_requested_at is not None
    events = await load_events(planner.session_factory, plan_id)
    assert [event.title for event in events] == [TITLE_STUCK_REQUESTED, TITLE_STUCK]
    assert events[1].ma_event_id == (
        f"backend:{plan_id}:status:stuck:{running_since.astimezone(dt.UTC).isoformat()}"
    )
    assert planner.registry.stopped == [plan_id]
    assert planner.fake.archived == ["sesn_fake_0001"]
    # The stopped consumer never read the final cost: the stuck check did (decision 11b).
    assert plan.cost_cents == 57


@pytest.mark.usefixtures("quick_stuck_check")
async def test_stuck_plan_closed_by_its_consumer_is_not_forced(planner: Planner) -> None:
    plan_id = await insert_plan(
        planner.session_factory, running_since=NOW - dt.timedelta(minutes=50)
    )
    planner.registry.start(plan_id, "sesn_fake_0001")

    async def consumer_sees_end_turn() -> None:
        await planner.fake.called("send_interrupt")
        await set_plan_status(
            planner.session_factory,
            planner.services.hub,
            plan_id,
            StatusChange(PlanStatus.INTERRUPTED, reason="Interrotto."),
            title=TITLE_INTERRUPTED,
            event_key="interrupted:by-consumer",
        )

    closer = asyncio.create_task(consumer_sees_end_turn())
    assert await check_stuck_plans(planner.services, now=NOW) == [plan_id]
    await closer
    titles = [event.title for event in await load_events(planner.session_factory, plan_id)]
    assert titles == [TITLE_STUCK_REQUESTED, TITLE_INTERRUPTED]
    assert planner.registry.stopped == []


async def test_stuck_plan_without_consumer_is_interrupted_at_once(planner: Planner) -> None:
    running_since = NOW - dt.timedelta(hours=3)
    plan_id = await insert_plan(planner.session_factory, running_since=running_since)
    planner.fake.emit(
        {"type": "session.usage", "usage": {"list_cost": {"amount": "41", "currency": "USD"}}}
    )
    assert await check_stuck_plans(planner.services, now=NOW) == [plan_id]
    plan = await load_plan(planner.session_factory, plan_id)
    assert (plan.status, plan.failure_reason) == (PlanStatus.INTERRUPTED, REASON_STUCK)
    assert plan.cost_cents == 41  # sessions.request_interrupt read it: no consumer will
    events = await load_events(planner.session_factory, plan_id)
    assert events[-1].ma_event_id == (
        f"backend:{plan_id}:status:stuck:{running_since.astimezone(dt.UTC).isoformat()}"
    )


async def test_only_plans_running_for_45_minutes_are_stuck(planner: Planner) -> None:
    fresh = await insert_plan(planner.session_factory, running_since=NOW - dt.timedelta(minutes=44))
    continued = await insert_plan(  # created hours ago, but "Continua" restarted the clock
        planner.session_factory,
        created_at=NOW - dt.timedelta(hours=5),
        running_since=NOW - dt.timedelta(minutes=10),
    )
    paused = await insert_plan(
        planner.session_factory,
        status=PlanStatus.BUDGET_PAUSED,
        running_since=NOW - dt.timedelta(hours=2),
    )
    assert await check_stuck_plans(planner.services, now=NOW) == []
    for plan_id in (fresh, continued):
        assert (await load_plan(planner.session_factory, plan_id)).status == PlanStatus.RUNNING
    assert (await load_plan(planner.session_factory, paused)).status == PlanStatus.BUDGET_PAUSED
    assert planner.fake.sent == []


async def test_stuck_check_does_nothing_without_a_client(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory, running_since=NOW - dt.timedelta(hours=2))
    planner.services.client = None
    assert await check_stuck_plans(planner.services, now=NOW) == []
    assert (await load_plan(planner.session_factory, plan_id)).status == PlanStatus.RUNNING


@pytest.mark.usefixtures("quick_stuck_check")
async def test_hourly_checker_uses_the_clock(planner: Planner) -> None:
    traveled_to = dt.datetime(2026, 10, 12, 15, 0, tzinfo=dt.UTC)
    stuck = await insert_plan(
        planner.session_factory, running_since=traveled_to - dt.timedelta(minutes=50)
    )
    recent = await insert_plan(
        planner.session_factory, running_since=traveled_to - dt.timedelta(minutes=30)
    )
    with time_machine.travel(traveled_to, tick=True):
        task = start_stuck_plan_checker(planner.services, interval_seconds=3600.0)
        assert task.get_name() == "stuck-plan-checker"
        try:
            for _ in range(200):
                if (await load_plan(planner.session_factory, stuck)).status != "running":
                    break
                await asyncio.sleep(0.02)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert (await load_plan(planner.session_factory, stuck)).status == PlanStatus.INTERRUPTED
    assert (await load_plan(planner.session_factory, recent)).status == PlanStatus.RUNNING


async def test_checker_survives_a_failing_round(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds: list[dt.datetime] = []

    async def flaky(services: Any, *, now: dt.datetime) -> list[uuid.UUID]:
        rounds.append(now)
        if len(rounds) == 1:
            raise RuntimeError("database went away")
        return []

    monkeypatch.setattr(jobs, "check_stuck_plans", flaky)
    task = start_stuck_plan_checker(planner.services, interval_seconds=0.01)
    try:
        for _ in range(200):
            if len(rounds) >= 3:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert len(rounds) >= 3
    assert all(now.tzinfo is not None for now in rounds)


# --- entry point ---------------------------------------------------------------------------------


async def _reset_database(url: str, *, old_plan_with_session: bool) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        await truncate_all(engine)
        if old_plan_with_session:
            from app.db import create_session_factory

            await insert_plan(
                create_session_factory(engine),
                session_id="sesn_old",
                created_at=dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=120),
            )
    finally:
        await engine.dispose()


@pytest.fixture
def uncached_structlog(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """For tests that run an entry point (`jobs.main`, `cli.main`): it configures structlog
    for the whole process with `cache_logger_on_first_use=True`. In the test process that
    leaks: every logger first used afterwards, in any later test, keeps that configuration and
    escapes `structlog.testing.capture_logs`. Configure without the cache, then restore the
    previous configuration."""
    saved = structlog.get_config()
    configure = structlog.configure

    def configure_uncached(**kwargs: Any) -> None:
        configure(**{**kwargs, "cache_logger_on_first_use": False})

    monkeypatch.setattr(structlog, "configure", configure_uncached)
    yield
    configure(**saved)


@pytest.fixture
def jobs_env(
    settings: Settings,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    uncached_structlog: None,
) -> Callable[[bool], None]:
    """`get_settings()` for `jobs.main`: the test environment, trip.json from the fixture."""
    monkeypatch.setenv("TRIP_SCHEMA_URL", SCHEMA_URL)
    get_settings.cache_clear()

    def reset(old_plan_with_session: bool) -> None:
        asyncio.run(_reset_database(test_database_url, old_plan_with_session=old_plan_with_session))

    return reset


def test_main_cleanup_exit_codes(jobs_env: Callable[[bool], None]) -> None:
    jobs_env(False)
    assert jobs.main(["cleanup"]) == 0
    jobs_env(True)  # a session to delete and no API key: kept, reported, exit 1
    assert jobs.main(["cleanup"]) == 1


def test_main_stuck_without_a_key(jobs_env: Callable[[bool], None]) -> None:
    jobs_env(False)
    assert jobs.main(["stuck"]) == 0


def test_main_requires_a_command() -> None:
    with pytest.raises(SystemExit) as caught:
        jobs.main([])
    assert caught.value.code == 2
