"""app.sessions: the plan lifecycle (start, interrupt, continue, resume) and its helpers.

The Managed Agents side is `tests.fakes.FakeManagedAgentsClient`; the consumer side is a fake
`ConsumerRegistry` (the real consumer is exercised by the consumer's own tests and by
test_cli.py's replay). Events and status changes go through the real `EventSink` /
`set_plan_status` into Postgres.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import clock, sessions
from app import consumer as consumer_module
from app.auth import CurrentUser, SessionVerifier
from app.config import Settings
from app.consumer import (
    ConsumerAlreadyRunningError,
    ConsumerDeps,
    ConsumerRegistry,
    PlanNotFoundError,
)
from app.db import EventRecord, PlanRecord, PlanStatus, UserRecord
from app.fx import FxConverter
from app.hub import PlanHub
from app.lockfile import load_roster
from app.ma_client import ApiRejectedError, ApiUnavailableError, ManagedAgentsError
from app.quota import ContinueLimitReachedError, PlannerBusyError, QuotaReachedError
from app.request import PlanRequest
from app.sessions import (
    CONTINUE_MESSAGE,
    REASON_INTERRUPTED,
    REASON_NO_SESSION,
    REASON_SESSION_START_FAILED,
    TITLE_CONTINUED,
    TITLE_INTERRUPT_REQUESTED,
    TITLE_INTERRUPTED,
    TITLE_PLAN_CREATED,
    MonthlyLimitReachedError,
    PlannerServices,
    PlannerUnavailableError,
    PlanStateError,
    UserGoneError,
    build_brief,
    continue_plan,
    get_user_plan,
    interrupt_plan,
    month_bounds,
    monthly_spend_cents,
    resume_running_plans,
    session_metadata,
    start_plan,
    start_planner,
    stop_planner,
)
from app.triptracker_schema import (
    DEV_FALLBACK_SCHEMA_PATH,
    TripSchemaStore,
    TripSchemaUnavailableError,
)
from tests.fakes import FakeManagedAgentsClient

ROME = clock.HOME_TIMEZONE
FROZEN_NOW = dt.datetime(2026, 10, 12, 10, 0, tzinfo=ROME)
SCHEMA_URL = DEV_FALLBACK_SCHEMA_PATH.as_uri()
LOCKFILE = Path(__file__).parent / "fixtures" / "lockfile" / "claude-lock.development.json"
USER = CurrentUser(email="test@example.com")
OTHER_USER = CurrentUser(email="other@example.com")

REQUEST_JSON: dict[str, Any] = {
    "origin": "Milano",
    "destination": "Lisbona",
    "dates": {"exact_start": "2027-04-14", "exact_end": "2027-04-18"},
    "travelers": [{"kind": "adult"}, {"kind": "adult"}, {"kind": "child", "age": 9}],
    "budget_eur": 2800,
    "preferences": "Niente voli prima delle 8.",
}
REQUEST = PlanRequest.model_validate(REQUEST_JSON)


# --- fakes of the consumer side ------------------------------------------------------------------


class FakeConsumer:
    """Stands in for `PlanConsumer`: `wait_started` succeeds, raises or hangs on demand."""

    def __init__(
        self, plan_id: uuid.UUID, session_id: str, first_message: str | None, start: Any
    ) -> None:
        self.plan_id = plan_id
        self.session_id = session_id
        self.first_message = first_message
        self.start = start
        self.interrupts = 0
        self.finished = False

    async def wait_started(self) -> None:
        if self.start == "hang":
            await asyncio.Event().wait()
        if isinstance(self.start, BaseException):
            raise self.start

    def request_interrupt(self) -> None:
        self.interrupts += 1

    @property
    def done(self) -> bool:
        return self.finished


class FakeRegistry:
    """Stands in for `ConsumerRegistry` (same methods), recording what sessions asked."""

    def __init__(self, deps: ConsumerDeps) -> None:
        self._deps = deps
        self.consumers: dict[uuid.UUID, FakeConsumer] = {}
        self.started: list[tuple[uuid.UUID, str, str | None]] = []
        self.stopped: list[uuid.UUID] = []
        self.closed = False
        self.start_behaviour: Any = None

    @property
    def deps(self) -> ConsumerDeps:
        return self._deps

    def start(
        self, plan_id: uuid.UUID, session_id: str, *, first_message: str | None = None
    ) -> FakeConsumer:
        if plan_id in self.consumers:
            raise ConsumerAlreadyRunningError(str(plan_id))
        consumer = FakeConsumer(plan_id, session_id, first_message, self.start_behaviour)
        self.consumers[plan_id] = consumer
        self.started.append((plan_id, session_id, first_message))
        return consumer

    def get(self, plan_id: uuid.UUID) -> FakeConsumer | None:
        return self.consumers.get(plan_id)

    async def stop(self, plan_id: uuid.UUID, *, grace_seconds: float = 10.0) -> None:
        self.stopped.append(plan_id)
        self.consumers.pop(plan_id, None)

    def active_plan_ids(self) -> list[uuid.UUID]:
        return list(self.consumers)

    async def aclose(self) -> None:
        self.closed = True
        self.consumers.clear()


@dataclass
class Planner:
    services: PlannerServices
    fake: FakeManagedAgentsClient
    registry: FakeRegistry
    session_factory: async_sessionmaker[AsyncSession]

    @property
    def settings(self) -> Settings:
        return self.services.settings


def planner_settings(make_settings: Callable[..., Settings], **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "trip_schema_url": SCHEMA_URL,
        "lockfile_path": LOCKFILE,
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
    }
    values.update(overrides)
    return make_settings(**values)


@asynccontextmanager
async def open_planner(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[Planner]:
    """`PlannerServices` over the fake client and a `FakeRegistry`, with the real hub,
    trip.json store (fixture file) and an offline FX converter. Also used by test_jobs.py."""
    async with httpx.AsyncClient() as http:
        hub = PlanHub()
        store = TripSchemaStore(settings, http)
        assert await store.load() is not None
        fx = FxConverter(session_factory=session_factory, http=http, offline=True)
        fake = FakeManagedAgentsClient(await_timeout=2.0)
        deps = ConsumerDeps(
            settings=settings,
            session_factory=session_factory,
            client=fake,
            hub=hub,
            trip_schema=store,
            fx=fx,
            now=lambda: FROZEN_NOW,
        )
        registry = FakeRegistry(deps)
        services = PlannerServices(
            settings=settings,
            http=http,
            session_factory=session_factory,
            hub=hub,
            trip_schema=store,
            fx=fx,
            session_verifier=SessionVerifier(settings, http),
            client=fake,
            roster=load_roster(settings),
            registry=cast(ConsumerRegistry, registry),
        )
        try:
            yield Planner(services, fake, registry, session_factory)
        finally:
            for task in services.background_tasks:
                task.cancel()
            await asyncio.gather(*services.background_tasks, return_exceptions=True)
            await fake.shutdown()


@pytest.fixture
async def planner(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Planner]:
    async with open_planner(planner_settings(make_settings), db_session_factory) as opened:
        yield opened


def budget_object(cents: int) -> dict[str, Any]:
    return {"type": "limit", "max_list_cost": {"amount": str(cents), "currency": "USD"}}


async def insert_plan(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: PlanStatus = PlanStatus.RUNNING,
    session_id: str | None = "sesn_fake_0001",
    user_email: str = USER.email,
    user_id: str | None = None,
    cost_cents: int = 0,
    budget_cents: int | None = 60,
    created_at: dt.datetime | None = None,
    running_since: dt.datetime | None = None,
    continues: int = 0,
) -> uuid.UUID:
    plan_id = uuid.uuid4()
    values: dict[str, Any] = {"user_id": user_id, "continues": continues}
    if created_at is not None:
        values["created_at"] = created_at
    if running_since is not None:
        values["running_since"] = running_since
    async with session_factory() as db:
        db.add(
            PlanRecord(
                id=plan_id,
                user_email=user_email,
                session_id=session_id,
                agent_profile="development",
                status=status.value,
                request=REQUEST.model_dump(mode="json"),
                cost_cents=cost_cents,
                budget_cents=budget_cents,
                **values,
            )
        )
        await db.commit()
    return plan_id


async def load_plan(
    session_factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID
) -> PlanRecord:
    async with session_factory() as db:
        plan = await db.get(PlanRecord, plan_id)
    assert plan is not None
    return plan


async def load_events(
    session_factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID
) -> list[EventRecord]:
    async with session_factory() as db:
        rows = await db.scalars(
            select(EventRecord).where(EventRecord.plan_id == plan_id).order_by(EventRecord.seq)
        )
        return list(rows)


# --- start_plan ----------------------------------------------------------------------------------


async def test_start_plan_creates_the_session_with_budget_pins_and_metadata(
    planner: Planner,
) -> None:
    plan_id = await start_plan(REQUEST, USER, services=planner.services)

    roster = planner.services.roster
    assert roster is not None
    [created] = planner.fake.created
    assert created.agent == roster.coordinator  # pinned version from the lockfile
    assert created.environment_id == roster.environment_id
    assert created.budget_cents == 60  # SESSION_BUDGET_CENTS of the development profile
    assert created.metadata == {
        "plan_id": str(plan_id),
        "agent_profile": "development",
        "app": "trip-planner",
    }
    assert created.title == f"plan {plan_id}"
    sent_to_platform = json.dumps([created.metadata, created.title])
    assert USER.email not in sent_to_platform

    plan = await load_plan(planner.session_factory, plan_id)
    assert plan.status == PlanStatus.RUNNING
    assert plan.user_email == USER.email
    assert plan.agent_profile == "development"
    assert plan.session_id == created.session_id
    assert plan.budget_cents == 60
    assert plan.request == REQUEST.model_dump(mode="json")
    assert plan.agent_versions is not None
    trip_schema = planner.services.trip_schema.current()
    assert trip_schema is not None
    assert plan.agent_versions == roster.agent_versions(
        git_sha=planner.settings.git_sha, trip_schema_sha256=trip_schema.sha256
    )
    assert plan.agent_versions["coordinator"] == {"id": "agent_devcoordinator01", "version": 4}

    [(started_id, session_id, first_message)] = planner.registry.started
    assert (started_id, session_id) == (plan_id, created.session_id)
    assert first_message == build_brief(REQUEST, today=dt.date(2026, 10, 12))
    assert first_message is not None
    assert USER.email not in first_message

    events = await load_events(planner.session_factory, plan_id)
    assert [(event.seq, event.kind, event.title) for event in events] == [
        (0, "status", TITLE_PLAN_CREATED)
    ]
    assert events[0].ma_event_id == f"backend:{plan_id}:status:created"


async def test_start_plan_stores_the_users_id_only_with_the_apps_own_accounts(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # AUTH_MODE=atlas: the provider's user id is one of this backend's users.id, so it is kept.
    atlas_settings = planner_settings(make_settings, auth_mode="atlas")
    async with open_planner(atlas_settings, db_session_factory) as atlas:
        async with db_session_factory() as db:
            db.add(UserRecord(id="usr_atlas_1", email=USER.email))
            await db.commit()
        plan_id = await start_plan(
            REQUEST, CurrentUser(USER.email, "usr_atlas_1"), services=atlas.services
        )
        plan = await load_plan(atlas.session_factory, plan_id)
        assert plan.user_id == "usr_atlas_1"
        assert plan.user_email == USER.email

    # AUTH_MODE=triptracker: TripTracker's user id is not a users.id and never goes there.
    triptracker_settings = planner_settings(make_settings, auth_mode="triptracker")
    async with open_planner(triptracker_settings, db_session_factory) as triptracker:
        plan_id = await start_plan(
            REQUEST, CurrentUser(USER.email, "tt_usr_9"), services=triptracker.services
        )
        plan = await load_plan(triptracker.session_factory, plan_id)
        assert plan.user_id is None
        assert plan.user_email == USER.email


async def test_start_plan_for_a_deleted_account_is_user_gone_not_a_crash(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # The session cache can keep a verified user for up to 15 minutes after the account (and its
    # users row) is gone: the plans.user_id foreign key refuses the insert.
    settings = planner_settings(make_settings, auth_mode="atlas")
    async with open_planner(settings, db_session_factory) as atlas:
        with pytest.raises(UserGoneError):
            await start_plan(
                REQUEST, CurrentUser(USER.email, "usr_deleted"), services=atlas.services
            )
        assert atlas.fake.created == []  # nothing spent
        assert atlas.registry.started == []
        async with atlas.session_factory() as db:
            assert list(await db.scalars(select(PlanRecord.id))) == []
            assert list(await db.scalars(select(EventRecord.plan_id))) == []


class _FakeAsyncpgError(Exception):
    """asyncpg's error: it names the constraint."""

    def __init__(self, constraint_name: str | None) -> None:
        super().__init__("fake")
        self.constraint_name = constraint_name


class _FakeAdaptedError(Exception):
    """SQLAlchemy's asyncpg adapter error: the SQLSTATE, raised from asyncpg's error."""

    def __init__(self, sqlstate: str, constraint_name: str | None) -> None:
        super().__init__("fake")
        self.sqlstate = sqlstate
        self.__cause__ = _FakeAsyncpgError(constraint_name)


@pytest.mark.parametrize(
    ("sqlstate", "constraint", "expected"),
    [
        ("23503", "fk_plans_user_id_users", True),
        ("23503", "fk_events_plan_id_plans", False),  # another foreign key
        ("23505", "fk_plans_user_id_users", False),  # not a foreign key violation
        ("23503", None, False),
    ],
)
def test_only_the_plans_user_foreign_key_is_user_gone(
    sqlstate: str, constraint: str | None, expected: bool
) -> None:
    error = IntegrityError("INSERT INTO plans ...", {}, _FakeAdaptedError(sqlstate, constraint))
    assert sessions.is_plans_user_fk_violation(error) is expected


async def test_start_plan_uses_the_brief_date_in_rome(planner: Planner) -> None:
    late_evening_utc = dt.datetime(2026, 10, 12, 22, 30, tzinfo=dt.UTC)  # 00:30 in Rome
    deps = dataclasses.replace(planner.registry.deps, now=lambda: late_evening_utc)
    planner.services.registry = cast(ConsumerRegistry, FakeRegistry(deps))
    await start_plan(REQUEST, USER, services=planner.services)
    registry = cast(FakeRegistry, planner.services.registry)
    [(_, _, first_message)] = registry.started
    assert first_message is not None
    assert first_message.startswith("Today is 2026-10-13 (Europe/Rome).")


# The new plan's own budget (60 cents in the test settings) must fit under the ceiling too.
@pytest.mark.parametrize(("spent", "refused"), [(4940, False), (4941, True), (5300, True)])
async def test_monthly_limit_refuses_when_the_new_budget_would_not_fit(
    planner: Planner, spent: int, refused: bool
) -> None:
    october = dt.datetime(2026, 10, 3, 12, 0, tzinfo=ROME)
    await insert_plan(
        planner.session_factory,
        status=PlanStatus.READY,
        cost_cents=spent - 1000,
        created_at=october,
        user_email="someone-else@example.com",  # the limit counts every user
    )
    await insert_plan(
        planner.session_factory, status=PlanStatus.FAILED, cost_cents=1000, created_at=october
    )
    await insert_plan(  # September does not count
        planner.session_factory,
        status=PlanStatus.READY,
        cost_cents=4000,
        created_at=dt.datetime(2026, 9, 30, 23, 30, tzinfo=ROME),
    )
    if not refused:
        await start_plan(REQUEST, USER, services=planner.services)
        assert len(planner.fake.created) == 1
        return
    with pytest.raises(MonthlyLimitReachedError) as caught:
        await start_plan(REQUEST, USER, services=planner.services)
    assert (caught.value.spent_cents, caught.value.limit_cents) == (spent, 5000)
    assert planner.fake.created == []  # nothing spent
    async with planner.session_factory() as db:
        count = len(list(await db.scalars(select(PlanRecord.id))))
    assert count == 3  # no plan row was added


async def test_unavailable_planner_refuses_before_anything(planner: Planner) -> None:
    planner.services.client = None
    planner.services.unavailable_reasons = ["ANTHROPIC_API_KEY is not set"]
    with pytest.raises(PlannerUnavailableError) as caught:
        await start_plan(REQUEST, USER, services=planner.services)
    assert caught.value.reasons == ["ANTHROPIC_API_KEY is not set"]
    async with planner.session_factory() as db:
        assert list(await db.scalars(select(PlanRecord.id))) == []


def test_require_ready_names_what_is_missing() -> None:
    services = PlannerServices(
        settings=cast(Settings, None),
        http=cast(httpx.AsyncClient, None),
        session_factory=cast(async_sessionmaker[AsyncSession], None),
        hub=PlanHub(),
        trip_schema=cast(TripSchemaStore, None),
        fx=cast(FxConverter, None),
        session_verifier=cast(SessionVerifier, None),
        client=None,
        roster=None,
        registry=None,
    )
    with pytest.raises(PlannerUnavailableError) as caught:
        services.require_ready()
    assert len(caught.value.reasons) == 2
    assert "ANTHROPIC_API_KEY" in caught.value.reasons[0]


async def test_missing_trip_schema_refuses_before_spending(
    make_settings: Callable[..., Settings], planner: Planner, tmp_path: Path
) -> None:
    production = planner_settings(
        make_settings,
        environment="production",
        auth_mode="triptracker",
        anthropic_api_key="sk-test-not-a-real-key",
        trip_schema_url=(tmp_path / "missing.json").as_uri(),
    )
    async with httpx.AsyncClient() as http:
        store = TripSchemaStore(production, http)
        assert await store.load() is None  # production never falls back
        planner.services.trip_schema = store
        with pytest.raises(TripSchemaUnavailableError):
            await start_plan(REQUEST, USER, services=planner.services)
    assert planner.fake.created == []


async def test_session_creation_failure_fails_the_plan(planner: Planner) -> None:
    planner.fake.fail_next("create_session", "api_unavailable")
    with pytest.raises(ApiUnavailableError):
        await start_plan(REQUEST, USER, services=planner.services)
    async with planner.session_factory() as db:
        [plan] = list(await db.scalars(select(PlanRecord)))
    assert plan.status == PlanStatus.FAILED
    assert plan.failure_reason == REASON_SESSION_START_FAILED
    assert plan.session_id is None
    titles = [event.title for event in await load_events(planner.session_factory, plan.id)]
    assert titles[0] == TITLE_PLAN_CREATED
    assert len(titles) == 2
    assert planner.registry.started == []


async def finish_background(services: PlannerServices) -> None:
    """Wait for the planner's background tasks (cleanups, nudges) to end."""
    async with asyncio.timeout(10):
        while services.background_tasks:
            await asyncio.gather(*list(services.background_tasks))


async def test_start_timeout_stops_the_consumer_and_fails_the_plan(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consumer_module, "START_TIMEOUT_SECONDS", 0.05)
    planner.registry.start_behaviour = "hang"
    with pytest.raises(TimeoutError):
        await start_plan(REQUEST, USER, services=planner.services)
    async with planner.session_factory() as db:
        [plan] = list(await db.scalars(select(PlanRecord)))
    assert plan.status == PlanStatus.FAILED
    assert plan.failure_reason == REASON_SESSION_START_FAILED
    assert planner.registry.stopped == [plan.id]
    # The session may have got the brief and nobody follows it: stopped in the background.
    await finish_background(planner.services)
    assert [sent.payload for sent in planner.fake.sent] == [{"type": "user.interrupt"}]
    assert planner.fake.archived == ["sesn_fake_0001"]


async def test_a_shutdown_lets_the_start_cleanup_finish(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan failed at start is never resumed: a shutdown right after it (a redeploy, the end
    of `app.cli run`) gives the session's cleanup its grace instead of cancelling it."""
    monkeypatch.setattr(consumer_module, "START_TIMEOUT_SECONDS", 0.05)
    planner.registry.start_behaviour = "hang"
    planner.fake.set_latency("send_interrupt", 0.2)
    with pytest.raises(TimeoutError):
        await start_plan(REQUEST, USER, services=planner.services)
    assert len(planner.services.cleanup_tasks) == 1

    await stop_planner(planner.services)

    assert [sent.payload for sent in planner.fake.sent] == [{"type": "user.interrupt"}]
    assert planner.fake.archived == ["sesn_fake_0001"]
    assert planner.services.cleanup_tasks == set()
    assert planner.services.background_tasks == []


class SlowAnswerClient(FakeManagedAgentsClient):
    """The API accepts the brief at once but answers the HTTP request late."""

    async def send_user_message(self, session_id: str, text: str) -> None:
        await super().send_user_message(session_id, text)
        await asyncio.sleep(1.0)


async def test_a_start_timeout_after_the_brief_was_accepted_stops_the_session(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the brief reached the session but its answer came after the start
    timeout. The plan failed (502) while the agents ran a whole plan unwatched and their cost
    never reached the monthly limit. Now the session is interrupted, archived and its list
    cost recorded."""
    monkeypatch.setattr(consumer_module, "START_TIMEOUT_SECONDS", 0.2)
    fake = SlowAnswerClient(await_timeout=5.0, list_cost_cents=9)
    async with httpx.AsyncClient() as http:
        services = await start_planner(
            planner_settings(make_settings),
            session_factory=db_session_factory,
            http=http,
            client=fake,
            fx_offline=True,
        )
        try:
            with pytest.raises(TimeoutError):
                await start_plan(REQUEST, USER, services=services)
            await finish_background(services)
        finally:
            await stop_planner(services)
    async with db_session_factory() as db:
        [plan] = list(await db.scalars(select(PlanRecord)))
    assert (plan.status, plan.failure_reason) == (PlanStatus.FAILED, REASON_SESSION_START_FAILED)
    assert [sent.payload["type"] for sent in fake.sent] == ["user.message", "user.interrupt"]
    assert fake.archived == [fake.session_id]
    assert plan.cost_cents == 9  # counted by the monthly limit


async def test_start_error_from_the_consumer_propagates(planner: Planner) -> None:
    planner.registry.start_behaviour = ApiRejectedError("refused", status_code=400)
    with pytest.raises(ApiRejectedError):
        await start_plan(REQUEST, USER, services=planner.services)


# --- the brief -----------------------------------------------------------------------------------


def test_brief_follows_the_contract() -> None:
    brief = build_brief(REQUEST, today=dt.date(2026, 10, 12))
    parts = brief.split("\n\n")
    assert parts[0] == "Today is 2026-10-12 (Europe/Rome)."
    assert "Italian" in parts[1]
    assert all(word in parts[1] for word in ("titles", "notes", "summary", "warnings"))
    assert parts[2].startswith("```json\n")
    assert parts[2].endswith("\n```")
    embedded = json.loads(parts[2].removeprefix("```json\n").removesuffix("\n```"))
    assert embedded == REQUEST.model_dump(mode="json", exclude_none=True)
    assert (
        parts[3] == "Save this JSON verbatim to /workspace/shared/request.json before delegating."
    )
    assert len(parts) == 4
    order = [brief.index(part) for part in parts]
    assert order == sorted(order)


def test_brief_keeps_unicode_and_drops_nulls() -> None:
    request = PlanRequest.model_validate(
        {
            "origin": "Bolzano",
            "suggest_destination": True,
            "destination_idea": "mare a novembre, volo diretto, città più calda",
            "dates": {"month": "2026-11", "nights": 5},
            "travelers": [{"kind": "adult"}],
            "budget_eur": 900,
        }
    )
    brief = build_brief(request, today=dt.date(2026, 10, 12))
    assert "città più calda" in brief
    assert "null" not in brief
    assert '"destination"' not in brief
    assert '"suggest_destination": true' in brief


def test_session_metadata_has_no_personal_data() -> None:
    plan_id = uuid.uuid4()
    metadata = session_metadata(plan_id, "production")
    assert metadata == {
        "plan_id": str(plan_id),
        "agent_profile": "production",
        "app": "trip-planner",
    }


# --- months and spend ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "start", "end"),
    [
        (
            dt.datetime(2026, 10, 12, 10, 0, tzinfo=ROME),
            dt.datetime(2026, 10, 1, tzinfo=ROME),
            dt.datetime(2026, 11, 1, tzinfo=ROME),
        ),
        (  # 23:30 UTC on 31 October is already November in Rome
            dt.datetime(2026, 10, 31, 23, 30, tzinfo=dt.UTC),
            dt.datetime(2026, 11, 1, tzinfo=ROME),
            dt.datetime(2026, 12, 1, tzinfo=ROME),
        ),
        (
            dt.datetime(2026, 12, 31, 12, 0, tzinfo=ROME),
            dt.datetime(2026, 12, 1, tzinfo=ROME),
            dt.datetime(2027, 1, 1, tzinfo=ROME),
        ),
    ],
)
def test_month_bounds_in_rome(now: dt.datetime, start: dt.datetime, end: dt.datetime) -> None:
    assert month_bounds(now) == (start, end)


def test_month_bounds_across_daylight_saving() -> None:
    start, end = month_bounds(dt.datetime(2026, 10, 15, tzinfo=ROME))
    assert start.utcoffset() == dt.timedelta(hours=2)  # CEST
    assert end.utcoffset() == dt.timedelta(hours=1)  # CET


def test_month_bounds_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        month_bounds(dt.datetime(2026, 10, 12))  # noqa: DTZ001 - the point of the test


async def test_monthly_spend_counts_the_rome_month(
    db_session_factory: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    for created_at, cost in [
        (dt.datetime(2026, 9, 30, 21, 59, tzinfo=dt.UTC), 1),  # 23:59 Rome: September
        (dt.datetime(2026, 9, 30, 22, 0, tzinfo=dt.UTC), 10),  # 00:00 Rome: October
        (dt.datetime(2026, 10, 31, 22, 59, tzinfo=dt.UTC), 100),  # 23:59 Rome (CET)
        (dt.datetime(2026, 10, 31, 23, 0, tzinfo=dt.UTC), 1000),  # November
    ]:
        await insert_plan(db_session_factory, cost_cents=cost, created_at=created_at)
    assert await monthly_spend_cents(db_session, now=FROZEN_NOW) == 110
    assert await monthly_spend_cents(db_session, now=FROZEN_NOW.replace(month=12)) == 0


async def test_get_user_plan_hides_other_users_plans(
    db_session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    plan_id = await insert_plan(db_session_factory)
    assert (await get_user_plan(db_session, plan_id, USER, settings=settings)).id == plan_id
    with pytest.raises(PlanNotFoundError):
        await get_user_plan(db_session, plan_id, OTHER_USER, settings=settings)
    with pytest.raises(PlanNotFoundError):
        await get_user_plan(db_session, uuid.uuid4(), USER, settings=settings)


async def test_with_the_apps_own_accounts_ownership_goes_by_user_id_then_by_legacy_email(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    """AUTH_MODE=atlas: a plan is the user's when `plans.user_id` is their id, or when it has no
    id (a plan from before the switch) and carries their verified email. A plan with another
    user's id is never theirs, whatever its email says."""
    atlas = make_settings(auth_mode="atlas")
    me = CurrentUser(USER.email, "usr_me", email_verified=True)
    db_session.add_all(
        [
            UserRecord(id="usr_me", email=USER.email),
            UserRecord(id="usr_other", email="o@example.com"),
        ]
    )
    await db_session.commit()
    mine = await insert_plan(db_session_factory, user_id="usr_me", user_email="old@example.com")
    legacy = await insert_plan(db_session_factory, user_email=USER.email.upper())
    others = await insert_plan(db_session_factory, user_id="usr_other", user_email=USER.email)
    someone_elses_legacy = await insert_plan(db_session_factory, user_email=OTHER_USER.email)

    assert (await get_user_plan(db_session, mine, me, settings=atlas)).id == mine
    assert (await get_user_plan(db_session, legacy, me, settings=atlas)).id == legacy
    for hidden in (others, someone_elses_legacy):
        with pytest.raises(PlanNotFoundError):
            await get_user_plan(db_session, hidden, me, settings=atlas)
    listed = await db_session.scalars(
        select(PlanRecord.id).where(sessions.plan_owner_filter(me, settings=atlas))
    )
    assert set(listed) == {mine, legacy}

    # An account that never verified the address keeps its own plans, but the address alone
    # does not hand it the legacy plans stored by that email.
    unverified = CurrentUser(USER.email, "usr_me", email_verified=False)
    assert (await get_user_plan(db_session, mine, unverified, settings=atlas)).id == mine
    with pytest.raises(PlanNotFoundError):
        await get_user_plan(db_session, legacy, unverified, settings=atlas)
    listed = await db_session.scalars(
        select(PlanRecord.id).where(sessions.plan_owner_filter(unverified, settings=atlas))
    )
    assert set(listed) == {mine}

    # Outside atlas mode the id means nothing (TripTracker's ids are not rows of `users`):
    # the email alone decides, as before the switch.
    triptracker = make_settings(auth_mode="triptracker")
    tt_user = CurrentUser(USER.email, "tt_usr_9")
    listed = await db_session.scalars(
        select(PlanRecord.id).where(sessions.plan_owner_filter(tt_user, settings=triptracker))
    )
    assert set(listed) == {legacy, others}
    with pytest.raises(PlanNotFoundError):
        await get_user_plan(db_session, mine, tt_user, settings=triptracker)


# --- interrupt -----------------------------------------------------------------------------------


async def test_interrupt_running_plan_with_a_live_consumer(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory)
    consumer = planner.registry.start(plan_id, "sesn_fake_0001")

    status = await interrupt_plan(plan_id, USER, services=planner.services)

    assert status is PlanStatus.RUNNING  # the consumer closes it on the coming end_turn
    assert consumer.interrupts == 1
    assert [sent.payload for sent in planner.fake.sent] == [{"type": "user.interrupt"}]
    plan = await load_plan(planner.session_factory, plan_id)
    assert plan.status == PlanStatus.RUNNING
    assert plan.interrupt_requested_at == FROZEN_NOW
    [event] = await load_events(planner.session_factory, plan_id)
    assert event.title == TITLE_INTERRUPT_REQUESTED
    assert event.ma_event_id is not None
    assert event.ma_event_id.startswith(f"backend:{plan_id}:status:interrupt-requested:")
    assert planner.fake.archived == []


async def test_interrupt_twice_stores_two_requests(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory)
    planner.registry.start(plan_id, "sesn_fake_0001")
    await interrupt_plan(plan_id, USER, services=planner.services)
    await interrupt_plan(plan_id, USER, services=planner.services)
    events = await load_events(planner.session_factory, plan_id)
    assert [event.title for event in events] == [TITLE_INTERRUPT_REQUESTED] * 2
    assert len({event.ma_event_id for event in events}) == 2


async def test_interrupt_running_plan_without_consumer_ends_it(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory, cost_cents=20)
    planner.fake.emit(
        {"type": "session.usage", "usage": {"list_cost": {"amount": "33", "currency": "USD"}}}
    )

    status = await interrupt_plan(plan_id, USER, services=planner.services)

    assert status is PlanStatus.INTERRUPTED
    plan = await load_plan(planner.session_factory, plan_id)
    assert plan.status == PlanStatus.INTERRUPTED
    assert plan.failure_reason == REASON_INTERRUPTED
    assert plan.interrupt_requested_at is not None
    titles = [event.title for event in await load_events(planner.session_factory, plan_id)]
    assert titles == [TITLE_INTERRUPT_REQUESTED, TITLE_INTERRUPTED]
    assert planner.fake.archived == ["sesn_fake_0001"]
    assert plan.cost_cents == 33  # no consumer will read the final cost: read here


async def test_interrupt_budget_paused_plan_ends_it_at_once(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)

    status = await interrupt_plan(plan_id, USER, services=planner.services)

    assert status is PlanStatus.INTERRUPTED
    plan = await load_plan(planner.session_factory, plan_id)
    assert (plan.status, plan.failure_reason) == (PlanStatus.INTERRUPTED, REASON_INTERRUPTED)
    [event] = await load_events(planner.session_factory, plan_id)
    assert event.title == TITLE_INTERRUPTED
    assert planner.fake.archived == ["sesn_fake_0001"]
    assert planner.fake.sent == []  # nothing was running: no user.interrupt


async def test_interrupt_survives_a_failed_archive(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)
    planner.fake.fail_next("archive_session", "api_unavailable")
    assert await interrupt_plan(plan_id, USER, services=planner.services) is (
        PlanStatus.INTERRUPTED
    )


@pytest.mark.parametrize(
    "status", [PlanStatus.READY, PlanStatus.FAILED, PlanStatus.BLOCKED, PlanStatus.INTERRUPTED]
)
async def test_interrupt_refuses_finished_plans(planner: Planner, status: PlanStatus) -> None:
    plan_id = await insert_plan(planner.session_factory, status=status)
    with pytest.raises(PlanStateError) as caught:
        await interrupt_plan(plan_id, USER, services=planner.services)
    assert caught.value.status is status
    assert await load_events(planner.session_factory, plan_id) == []


async def test_interrupt_of_another_users_plan_is_not_found(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory)
    with pytest.raises(PlanNotFoundError):
        await interrupt_plan(plan_id, OTHER_USER, services=planner.services)
    assert (await load_plan(planner.session_factory, plan_id)).interrupt_requested_at is None


# --- continue ------------------------------------------------------------------------------------


async def test_continue_raises_the_budget_over_consumption_and_restarts(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    long_ago = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=2)  # the database clock
    plan_id = await insert_plan(
        planner.session_factory,
        status=PlanStatus.BUDGET_PAUSED,
        cost_cents=61,
        running_since=long_ago,
    )
    planner.fake.emit({"type": "session.updated", "budget": budget_object(60)})
    planner.fake.emit(
        {"type": "session.usage", "usage": {"list_cost": {"amount": "63", "currency": "USD"}}}
    )

    new_budget = await continue_plan(plan_id, USER, services=planner.services)

    assert new_budget == 263  # max(cap 60, consumed 63) + 200
    assert planner.fake.budget_updates == [("sesn_fake_0001", 263)]
    plan = await load_plan(planner.session_factory, plan_id)
    assert plan.status == PlanStatus.RUNNING
    assert plan.budget_cents == 263
    assert plan.running_since > long_ago
    [event] = await load_events(planner.session_factory, plan_id)
    assert event.title == TITLE_CONTINUED
    assert event.ma_event_id == f"backend:{plan_id}:status:continue:263"
    assert planner.registry.started == [(plan_id, "sesn_fake_0001", None)]  # resume mode


async def test_continue_twice_gives_two_status_events(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)
    planner.fake.emit(
        {"type": "session.usage", "usage": {"list_cost": {"amount": "60", "currency": "USD"}}}
    )
    first = await continue_plan(plan_id, USER, services=planner.services)
    first_running_since = (await load_plan(planner.session_factory, plan_id)).running_since

    # The consumer pauses the plan again at the new cap; the cost overshot it a little.
    await planner.registry.stop(plan_id)
    async with planner.session_factory() as db:
        await db.execute(
            update(PlanRecord)
            .where(PlanRecord.id == plan_id)
            .values(status=PlanStatus.BUDGET_PAUSED.value)
        )
        await db.commit()
    planner.fake.emit(
        {"type": "session.usage", "usage": {"list_cost": {"amount": "268", "currency": "USD"}}}
    )
    await asyncio.sleep(0.01)  # a distinct transaction time for running_since
    second = await continue_plan(plan_id, USER, services=planner.services)

    assert (first, second) == (260, 468)
    events = await load_events(planner.session_factory, plan_id)
    assert [event.title for event in events] == [TITLE_CONTINUED, TITLE_CONTINUED]
    assert [event.ma_event_id for event in events] == [
        f"backend:{plan_id}:status:continue:260",
        f"backend:{plan_id}:status:continue:468",
    ]
    plan = await load_plan(planner.session_factory, plan_id)
    assert plan.budget_cents == 468
    assert plan.status == PlanStatus.RUNNING
    assert plan.running_since > first_running_since
    assert [budget for _, budget in planner.fake.budget_updates] == [260, 468]


async def test_a_double_continue_raises_the_budget_once(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: two concurrent "Continua" (a double click, two tabs) both raised the
    session's budget before either moved the plan to `running`: the session could spend $4
    while the database and the monthly check counted $2."""
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)
    planner.fake.emit(
        {"type": "session.usage", "usage": {"list_cost": {"amount": "60", "currency": "USD"}}}
    )

    results = await asyncio.gather(
        continue_plan(plan_id, USER, services=planner.services),
        continue_plan(plan_id, USER, services=planner.services),
        return_exceptions=True,
    )

    assert 260 in results
    [refused] = [result for result in results if not isinstance(result, int)]
    assert isinstance(refused, PlanStateError)
    assert refused.status is PlanStatus.RUNNING
    assert planner.fake.budget_updates == [("sesn_fake_0001", 260)]
    plan = await load_plan(planner.session_factory, plan_id)
    assert (plan.status, plan.budget_cents) == (PlanStatus.RUNNING, 260)
    assert planner.fake.session_info().budget_cents == plan.budget_cents
    assert len(planner.services.plan_locks) == 0  # no lock outlives its requests


async def test_an_interrupt_racing_a_continue_never_raises_the_budget(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interrupt of a paused plan and a "Continua" sent at the same time: the second one
    waits for the first and sees its outcome, so a plan just interrupted never gets its
    session's budget raised (and resumed)."""
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)

    interrupted, continued = await asyncio.gather(
        interrupt_plan(plan_id, USER, services=planner.services),
        continue_plan(plan_id, USER, services=planner.services),
        return_exceptions=True,
    )

    assert interrupted is PlanStatus.INTERRUPTED
    assert isinstance(continued, PlanStateError)
    assert continued.status is PlanStatus.INTERRUPTED
    assert planner.fake.budget_updates == []
    assert planner.registry.started == []
    plan = await load_plan(planner.session_factory, plan_id)
    assert plan.status == PlanStatus.INTERRUPTED


async def test_plan_locks_serialize_one_plan_and_let_others_run() -> None:
    locks = sessions.PlanLocks()
    first, second = uuid.uuid4(), uuid.uuid4()
    order: list[str] = []

    async def hold(plan_id: uuid.UUID, name: str, seconds: float) -> None:
        async with locks.hold(plan_id):
            order.append(f"{name}+")
            await asyncio.sleep(seconds)
            order.append(f"{name}-")

    await asyncio.gather(hold(first, "a", 0.05), hold(first, "b", 0), hold(second, "c", 0))
    assert order.index("a-") < order.index("b+")  # same plan: one after the other
    assert order.index("c+") < order.index("a-")  # another plan: not blocked
    assert len(locks) == 0


async def test_continue_counts_the_extra_spend_against_the_monthly_limit(
    planner: Planner,
) -> None:
    october = dt.datetime(2026, 10, 2, tzinfo=ROME)
    await insert_plan(
        planner.session_factory, status=PlanStatus.READY, cost_cents=4801, created_at=october
    )
    plan_id = await insert_plan(
        planner.session_factory, status=PlanStatus.BUDGET_PAUSED, created_at=october
    )
    with pytest.raises(MonthlyLimitReachedError) as caught:
        await continue_plan(plan_id, USER, services=planner.services)
    assert caught.value.spent_cents == 4801
    assert planner.fake.budget_updates == []
    assert (await load_plan(planner.session_factory, plan_id)).status == PlanStatus.BUDGET_PAUSED


async def test_continue_at_exactly_the_limit_is_allowed(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    october = dt.datetime(2026, 10, 2, tzinfo=ROME)
    plan_id = await insert_plan(
        planner.session_factory,
        status=PlanStatus.BUDGET_PAUSED,
        cost_cents=4800,
        created_at=october,
    )
    # max(stored cap 60, consumed 0) + 200: allowed although spent + 200 == the limit.
    assert await continue_plan(plan_id, USER, services=planner.services) == 60 + 200


async def test_continue_falls_back_to_the_stored_cost(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    fake = FakeManagedAgentsClient(list_cost_cents=None, budget_cents=60)
    planner.services.client = fake
    plan_id = await insert_plan(
        planner.session_factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=75
    )
    assert await continue_plan(plan_id, USER, services=planner.services) == 275
    assert fake.budget_updates == [("sesn_fake_0001", 275)]


@pytest.mark.parametrize("status", [PlanStatus.RUNNING, PlanStatus.READY, PlanStatus.FAILED])
async def test_continue_only_from_budget_paused(planner: Planner, status: PlanStatus) -> None:
    plan_id = await insert_plan(planner.session_factory, status=status)
    with pytest.raises(PlanStateError) as caught:
        await continue_plan(plan_id, USER, services=planner.services)
    assert caught.value.allowed == (PlanStatus.BUDGET_PAUSED,)
    assert planner.fake.budget_updates == []


async def test_continue_rejected_budget_keeps_the_plan_paused(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)
    planner.fake.fail_next("update_budget", "api_rejected")
    with pytest.raises(ManagedAgentsError):
        await continue_plan(plan_id, USER, services=planner.services)
    plan = await load_plan(planner.session_factory, plan_id)
    assert plan.status == PlanStatus.BUDGET_PAUSED
    assert await load_events(planner.session_factory, plan_id) == []
    assert planner.registry.started == []


async def test_continue_sends_the_message_when_the_session_stays_idle(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 0.0)
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)
    await continue_plan(plan_id, USER, services=planner.services)
    await asyncio.gather(*planner.services.background_tasks)
    assert [sent.payload for sent in planner.fake.sent] == [
        {"type": "user.message", "content": [{"type": "text", "text": CONTINUE_MESSAGE}]}
    ]
    assert planner.services.background_tasks == []  # the nudge forgets itself


async def test_continue_does_not_nudge_a_session_that_resumed(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 0.05)
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)
    await continue_plan(plan_id, USER, services=planner.services)
    planner.fake.emit({"type": "session.status_running"})  # resumed by itself (P9)
    await asyncio.gather(*planner.services.background_tasks)
    assert planner.fake.sent == []


async def test_continue_of_another_users_plan_is_not_found(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED)
    with pytest.raises(PlanNotFoundError):
        await continue_plan(plan_id, OTHER_USER, services=planner.services)


# --- resume and the planner's life ---------------------------------------------------------------


async def test_resume_running_plans_at_startup(planner: Planner) -> None:
    with_session = await insert_plan(planner.session_factory, session_id="sesn_a")
    second = await insert_plan(planner.session_factory, session_id="sesn_b")
    without_session = await insert_plan(planner.session_factory, session_id=None)
    await insert_plan(planner.session_factory, status=PlanStatus.READY, session_id="sesn_c")
    await insert_plan(planner.session_factory, status=PlanStatus.BUDGET_PAUSED, session_id="sesn_d")

    resumed = await resume_running_plans(planner.services)

    assert set(resumed) == {with_session, second}
    assert {(plan_id, sid, message) for plan_id, sid, message in planner.registry.started} == {
        (with_session, "sesn_a", None),
        (second, "sesn_b", None),
    }
    orphan = await load_plan(planner.session_factory, without_session)
    assert (orphan.status, orphan.failure_reason) == (PlanStatus.FAILED, REASON_NO_SESSION)

    # A second pass (e.g. a reload) neither restarts live consumers nor fails twice.
    assert await resume_running_plans(planner.services) == []
    assert len(await load_events(planner.session_factory, without_session)) == 1


async def test_resume_without_a_ready_planner_leaves_plans_running(planner: Planner) -> None:
    plan_id = await insert_plan(planner.session_factory)
    planner.services.client = None
    assert await resume_running_plans(planner.services) == []
    assert (await load_plan(planner.session_factory, plan_id)).status == PlanStatus.RUNNING
    assert planner.registry.started == []


async def test_start_planner_without_key_or_lockfile_is_unavailable_not_broken(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    settings = planner_settings(make_settings, lockfile_path=tmp_path / "claude-lock.json")
    factory = cast(async_sessionmaker[AsyncSession], None)  # never touched: nothing to resume
    async with httpx.AsyncClient() as http:
        services = await start_planner(settings, session_factory=factory, http=http)
        try:
            assert services.client is None
            assert services.registry is None
            assert services.roster is None
            assert services.trip_schema.current() is not None
            assert services.unavailable_reasons[0] == "ANTHROPIC_API_KEY is not set"
            assert "does not exist" in services.unavailable_reasons[1]
            with pytest.raises(PlannerUnavailableError):
                services.require_ready()
        finally:
            await stop_planner(services)


async def test_start_planner_builds_its_client_under_federation(
    make_settings: Callable[..., Settings],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No API key but a federation config (development): the planner is not unavailable for
    lack of credentials. Nothing is exchanged: the token file is only a path here."""
    token_file = tmp_path / "identity-token"
    token_file.write_text("fake.identity.token-not-a-secret", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_CONFIG_DIR")  # a profile would outrank federation in the SDK
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_IDENTITY_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("ANTHROPIC_FEDERATION_RULE_ID", "fdrl_fake")
    monkeypatch.setenv("ANTHROPIC_ORGANIZATION_ID", "org-fake")
    settings = planner_settings(
        make_settings,
        lockfile_path=tmp_path / "claude-lock.json",
        anthropic_identity_token_file=str(token_file),
        anthropic_federation_rule_id="fdrl_fake",
        anthropic_organization_id="org-fake",
    )
    factory = cast(async_sessionmaker[AsyncSession], None)  # never touched: nothing to resume
    async with httpx.AsyncClient() as http:
        services = await start_planner(settings, session_factory=factory, http=http)
        try:
            assert services.client is not None
            assert not any("ANTHROPIC_API_KEY" in reason for reason in services.unavailable_reasons)
            assert (
                "does not exist" in services.unavailable_reasons[0]
            )  # only the lockfile is missing
        finally:
            await stop_planner(services)


async def test_start_planner_with_a_client_resolves_the_roster(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = planner_settings(make_settings)
    fake = FakeManagedAgentsClient()
    async with httpx.AsyncClient() as http:
        services = await start_planner(
            settings, session_factory=db_session_factory, http=http, client=fake
        )
        try:
            ready = services.require_ready()
            assert ready.client is fake
            assert ready.roster.coordinator.id == "agent_devcoordinator01"
            assert ready.deps.client is fake
            assert ready.deps.trip_schema is services.trip_schema
            assert services.unavailable_reasons == []
        finally:
            await stop_planner(services)
    assert fake.closed


async def test_start_planner_resumes_running_plans_with_the_real_registry(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    running = await insert_plan(db_session_factory, session_id="sesn_fake_0001")
    finished = await insert_plan(db_session_factory, status=PlanStatus.READY)
    fake = FakeManagedAgentsClient()
    async with httpx.AsyncClient() as http:
        services = await start_planner(
            planner_settings(make_settings),
            session_factory=db_session_factory,
            http=http,
            client=fake,
        )
        try:
            assert services.registry is not None
            assert services.registry.active_plan_ids() == [running]
            assert services.registry.get(finished) is None
        finally:
            await stop_planner(services)
    # Shutdown leaves the plan running: the next process resumes it.
    assert (await load_plan(db_session_factory, running)).status == PlanStatus.RUNNING


async def test_start_planner_retries_a_missing_trip_schema_in_the_background(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    production = planner_settings(
        make_settings,
        environment="production",
        auth_mode="triptracker",
        anthropic_api_key="sk-test-not-a-real-key",
        trip_schema_url=(tmp_path / "trip.json").as_uri(),
        lockfile_path=tmp_path / "claude-lock.json",
    )
    factory = cast(async_sessionmaker[AsyncSession], None)  # not ready: nothing touches it
    async with httpx.AsyncClient() as http:
        services = await start_planner(
            production, session_factory=factory, http=http, client=FakeManagedAgentsClient()
        )
        [retry] = services.background_tasks
        assert retry.get_name() == "trip-schema-retry"
        assert services.trip_schema.current() is None
        await stop_planner(services)
    assert retry.cancelled()


async def test_stop_planner_cancels_tasks_and_closes_everything(planner: Planner) -> None:
    async def forever() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(forever())
    planner.services.background_tasks.append(task)
    await stop_planner(planner.services)
    assert task.cancelled()
    assert planner.services.background_tasks == []
    assert planner.registry.closed
    assert planner.fake.closed


def test_backend_git_sha_prefers_the_setting(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert sessions.backend_git_sha(make_settings(git_sha="abc")) == "abc"
    monkeypatch.setattr(sessions, "_git_head", lambda: None)
    assert sessions.backend_git_sha(make_settings()) is None
    monkeypatch.setattr(sessions, "_git_head", lambda: "f" * 40)
    assert sessions.backend_git_sha(make_settings()) == "f" * 40


# --- with the real consumer ----------------------------------------------------------------------


async def wait_for_status(
    session_factory: async_sessionmaker[AsyncSession], plan_id: uuid.UUID, status: PlanStatus
) -> PlanRecord:
    """Poll the row (at most 10 s) until the consumer moved the plan to `status`."""
    for _ in range(500):
        plan = await load_plan(session_factory, plan_id)
        if plan.status == status:
            return plan
        await asyncio.sleep(0.02)
    raise AssertionError(f"plan {plan_id} never reached {status}")


async def wait_for_consumer_exit(services: PlannerServices, plan_id: uuid.UUID) -> None:
    assert services.registry is not None
    for _ in range(500):
        if services.registry.get(plan_id) is None:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"the consumer of {plan_id} never stopped")


async def test_budget_paused_then_continue_with_the_real_consumer(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)  # resumes by itself
    fake = FakeManagedAgentsClient.from_scenario("budget_reached")
    request = PlanRequest.from_stored(fake.meta["request"])
    async with httpx.AsyncClient() as http:
        services = await start_planner(
            planner_settings(make_settings),
            session_factory=db_session_factory,
            http=http,
            client=fake,
            fx_offline=True,
        )
        try:
            plan_id = await start_plan(request, USER, services=services)
            paused = await wait_for_status(db_session_factory, plan_id, PlanStatus.BUDGET_PAUSED)
            assert paused.cost_cents == 61
            await wait_for_consumer_exit(services, plan_id)

            new_budget = await continue_plan(plan_id, USER, services=services)

            assert new_budget == 261  # max(cap 60, consumed 61) + 200
            ready = await wait_for_status(db_session_factory, plan_id, PlanStatus.READY)
            await fake.wait_until_done()
            fake.assert_script_done()
        finally:
            await stop_planner(services)
    assert fake.budget_updates == [(fake.session_id, 261)]
    assert ready.budget_cents == 261
    assert ready.trip is not None
    titles = [event.title for event in await load_events(db_session_factory, plan_id)]
    assert titles.count(TITLE_CONTINUED) == 1
    assert titles[0] == TITLE_PLAN_CREATED


async def test_interrupt_with_the_real_consumer(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fake = FakeManagedAgentsClient.from_scenario("interrupt")
    request = PlanRequest.from_stored(fake.meta["request"])
    async with httpx.AsyncClient() as http:
        services = await start_planner(
            planner_settings(make_settings),
            session_factory=db_session_factory,
            http=http,
            client=fake,
            fx_offline=True,
        )
        try:
            plan_id = await start_plan(request, USER, services=services)
            await fake.reached("working")

            status = await interrupt_plan(plan_id, USER, services=services)
            assert status is PlanStatus.RUNNING
            fake.release("working")

            plan = await wait_for_status(db_session_factory, plan_id, PlanStatus.INTERRUPTED)
            await wait_for_consumer_exit(services, plan_id)
            await fake.wait_until_done()
            fake.assert_script_done()
        finally:
            await stop_planner(services)
    assert plan.interrupt_requested_at is not None
    assert fake.archived == [fake.session_id]
    titles = [event.title for event in await load_events(db_session_factory, plan_id)]
    assert TITLE_INTERRUPT_REQUESTED in titles


# --- the economics (app/quota.py) ----------------------------------------------------------------

OCTOBER = dt.datetime(2026, 10, 2, 9, 0, tzinfo=ROME)
ADMIN = CurrentUser(email="boss@example.com")


@pytest.fixture
async def quota_planner(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Planner]:
    """USER subject to the per-user quota (someone else is the admin), with small limits: 3
    plans and 300 cents a month, 1 "Continua" per plan, 3 plans running at once."""
    settings = planner_settings(
        make_settings,
        admin_emails=["boss@example.com"],
        user_monthly_plans=3,
        user_monthly_cents=300,
        max_continues_per_plan=1,
        max_running_plans=3,
    )
    async with open_planner(settings, db_session_factory) as opened:
        yield opened


async def count_plans(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as db:
        return len(list(await db.scalars(select(PlanRecord.id))))


async def test_quota_refuses_the_users_fourth_plan_of_the_month(quota_planner: Planner) -> None:
    factory = quota_planner.session_factory
    await insert_plan(factory, status=PlanStatus.READY, cost_cents=10, created_at=OCTOBER)
    await insert_plan(factory, status=PlanStatus.FAILED, cost_cents=0, created_at=OCTOBER)
    await insert_plan(factory, status=PlanStatus.INTERRUPTED, cost_cents=5, created_at=OCTOBER)
    await insert_plan(  # someone else's: not counted against USER
        factory, status=PlanStatus.READY, cost_cents=10, created_at=OCTOBER, user_email=ADMIN.email
    )
    await insert_plan(  # last month: not counted
        factory,
        status=PlanStatus.READY,
        created_at=dt.datetime(2026, 9, 30, 23, 30, tzinfo=ROME),
    )

    with pytest.raises(QuotaReachedError) as caught:
        await start_plan(REQUEST, USER, services=quota_planner.services)

    assert caught.value.kind == "plans"
    assert (caught.value.quota.plans_used, caught.value.quota.plans_limit) == (3, 3)
    assert caught.value.quota.resets_at == dt.datetime(2026, 11, 1, tzinfo=ROME)
    assert quota_planner.fake.created == []  # nothing spent
    assert await count_plans(factory) == 5  # no row added


# USER's month: a finished plan and a running one with 50 of its 60 cents unspent; the new plan's
# own 60 cents must fit under 300 too.
@pytest.mark.parametrize(("finished_cost", "refused"), [(180, False), (181, True)])
async def test_quota_counts_the_running_plans_unspent_budget_and_the_new_one(
    quota_planner: Planner, finished_cost: int, refused: bool
) -> None:
    factory = quota_planner.session_factory
    await insert_plan(
        factory, status=PlanStatus.READY, cost_cents=finished_cost, created_at=OCTOBER
    )
    await insert_plan(factory, status=PlanStatus.RUNNING, cost_cents=10, created_at=OCTOBER)

    if not refused:
        await start_plan(REQUEST, USER, services=quota_planner.services)
        assert len(quota_planner.fake.created) == 1
        return
    with pytest.raises(QuotaReachedError) as caught:
        await start_plan(REQUEST, USER, services=quota_planner.services)
    assert caught.value.kind == "cents"
    assert (caught.value.quota.cents_used, caught.value.quota.cents_limit) == (
        finished_cost + 10 + 50,
        300,
    )
    assert quota_planner.fake.created == []


async def test_admins_are_exempt_from_the_user_quota_but_not_from_the_ceiling(
    quota_planner: Planner,
) -> None:
    factory = quota_planner.session_factory
    for _ in range(4):  # over the 3-plan quota
        await insert_plan(
            factory,
            status=PlanStatus.READY,
            cost_cents=100,
            created_at=OCTOBER,
            user_email=ADMIN.email,
        )

    await start_plan(REQUEST, ADMIN, services=quota_planner.services)
    assert len(quota_planner.fake.created) == 1

    await insert_plan(  # the ceiling (5000) still counts everyone, the admin included
        factory,
        status=PlanStatus.READY,
        cost_cents=4700,
        created_at=OCTOBER,
        user_email="x@example.com",
    )
    with pytest.raises(MonthlyLimitReachedError):
        await start_plan(REQUEST, ADMIN, services=quota_planner.services)


async def test_the_running_cap_refuses_with_planner_busy_and_spends_nothing(
    quota_planner: Planner,
) -> None:
    factory = quota_planner.session_factory
    for owner in ("a@example.com", "b@example.com", ADMIN.email):
        await insert_plan(factory, status=PlanStatus.RUNNING, created_at=OCTOBER, user_email=owner)

    with pytest.raises(PlannerBusyError) as caught:
        await start_plan(REQUEST, ADMIN, services=quota_planner.services)

    assert (caught.value.running, caught.value.limit) == (3, 3)
    assert quota_planner.fake.created == []
    assert await count_plans(factory) == 3


async def test_the_continue_cap_refuses_before_touching_the_session(quota_planner: Planner) -> None:
    plan_id = await insert_plan(
        quota_planner.session_factory,
        status=PlanStatus.BUDGET_PAUSED,
        cost_cents=60,
        created_at=OCTOBER,
        continues=1,
    )

    with pytest.raises(ContinueLimitReachedError) as caught:
        await continue_plan(plan_id, USER, services=quota_planner.services)

    assert (caught.value.continues, caught.value.limit) == (1, 1)
    assert quota_planner.fake.budget_updates == []
    plan = await load_plan(quota_planner.session_factory, plan_id)
    assert (plan.status, plan.continues) == (PlanStatus.BUDGET_PAUSED, 1)


async def test_continue_checks_the_users_cents_with_the_extra_included(
    quota_planner: Planner,
) -> None:
    factory = quota_planner.session_factory
    await insert_plan(factory, status=PlanStatus.READY, cost_cents=101, created_at=OCTOBER)
    plan_id = await insert_plan(
        factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=0, created_at=OCTOBER
    )

    with pytest.raises(QuotaReachedError) as caught:  # 101 + 0 + 200 > 300
        await continue_plan(plan_id, USER, services=quota_planner.services)

    assert caught.value.kind == "cents"
    assert quota_planner.fake.budget_updates == []


async def test_continue_counts_itself_on_the_plan(
    planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    plan_id = await insert_plan(
        planner.session_factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=60, created_at=OCTOBER
    )

    assert await continue_plan(plan_id, USER, services=planner.services) == 260

    plan = await load_plan(planner.session_factory, plan_id)
    assert (plan.status, plan.budget_cents, plan.continues) == (PlanStatus.RUNNING, 260, 1)


# --- "Continua" reserves its extra before the session is touched -------------------------------


@pytest.fixture
async def ceiling_planner(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Planner]:
    """A 1500-cent month for everyone, no per-user limit in the way, 3 plans running at once."""
    settings = planner_settings(
        make_settings,
        monthly_limit_cents=1500,
        user_monthly_cents=100_000,
        user_monthly_plans=100,
        max_running_plans=3,
    )
    async with open_planner(settings, db_session_factory) as opened:
        yield opened


def hold_retrieve(planner: Planner, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Make the next `retrieve_session` (step 2 of "Continua") wait: returns (entered, release)."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = planner.fake.retrieve_session

    async def held(session_id: str) -> Any:
        if not entered.is_set():  # only the first call waits
            entered.set()
            await release.wait()
        return await original(session_id)

    monkeypatch.setattr(planner.fake, "retrieve_session", held)
    return entered, release


async def test_a_continue_in_flight_reserves_its_extra_against_a_new_start(
    ceiling_planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    factory = ceiling_planner.session_factory
    await insert_plan(
        factory, status=PlanStatus.READY, cost_cents=1200, created_at=OCTOBER, user_email="x@a.it"
    )
    paused = await insert_plan(
        factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=60, created_at=OCTOBER
    )
    entered, release = hold_retrieve(ceiling_planner, monkeypatch)

    continuing = asyncio.create_task(continue_plan(paused, USER, services=ceiling_planner.services))
    await asyncio.wait_for(entered.wait(), 5)
    # 1200 + 60 + the continue's 200 = 1460: a start's 60 would make 1520. Without the
    # reservation the start would see 1260 and pass.
    try:
        with pytest.raises(MonthlyLimitReachedError):
            await start_plan(REQUEST, USER, services=ceiling_planner.services)
    finally:
        release.set()
    assert await continuing == 260

    plan = await load_plan(factory, paused)
    assert (plan.status, plan.budget_cents, plan.continues) == (PlanStatus.RUNNING, 260, 1)
    assert ceiling_planner.fake.created == []


async def test_a_continue_in_flight_reserves_its_extra_against_another_continue(
    ceiling_planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    factory = ceiling_planner.session_factory
    await insert_plan(
        factory, status=PlanStatus.READY, cost_cents=1080, created_at=OCTOBER, user_email="x@a.it"
    )
    first = await insert_plan(
        factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=60, created_at=OCTOBER
    )
    second = await insert_plan(
        factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=60, created_at=OCTOBER
    )
    entered, release = hold_retrieve(ceiling_planner, monkeypatch)

    continuing = asyncio.create_task(continue_plan(first, USER, services=ceiling_planner.services))
    await asyncio.wait_for(entered.wait(), 5)
    # 1080 + 120 + 200 = 1400 with the first one's extra reserved: another 200 would make 1600.
    try:
        with pytest.raises(MonthlyLimitReachedError):
            await continue_plan(second, USER, services=ceiling_planner.services)
    finally:
        release.set()
    await continuing

    plan = await load_plan(factory, second)
    assert (plan.status, plan.budget_cents, plan.continues) == (PlanStatus.BUDGET_PAUSED, 60, 0)
    assert len(ceiling_planner.fake.budget_updates) == 1


async def test_a_continue_in_flight_counts_as_running_for_the_cap(
    ceiling_planner: Planner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    factory = ceiling_planner.session_factory
    for owner in ("a@example.com", "b@example.com"):
        await insert_plan(factory, status=PlanStatus.RUNNING, created_at=OCTOBER, user_email=owner)
    paused = await insert_plan(
        factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=60, created_at=OCTOBER
    )
    entered, release = hold_retrieve(ceiling_planner, monkeypatch)

    continuing = asyncio.create_task(continue_plan(paused, USER, services=ceiling_planner.services))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        with pytest.raises(PlannerBusyError) as caught:
            await start_plan(REQUEST, USER, services=ceiling_planner.services)
    finally:
        release.set()
    assert (caught.value.running, caught.value.limit) == (3, 3)
    await continuing


async def test_continue_respects_the_running_cap(ceiling_planner: Planner) -> None:
    factory = ceiling_planner.session_factory
    for owner in ("a@example.com", "b@example.com", "c@example.com"):
        await insert_plan(factory, status=PlanStatus.RUNNING, created_at=OCTOBER, user_email=owner)
    paused = await insert_plan(
        factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=60, created_at=OCTOBER
    )

    with pytest.raises(PlannerBusyError):
        await continue_plan(paused, USER, services=ceiling_planner.services)

    assert ceiling_planner.fake.calls_of("retrieve_session") == []
    assert ceiling_planner.fake.budget_updates == []
    plan = await load_plan(factory, paused)
    assert (plan.status, plan.budget_cents, plan.continues) == (PlanStatus.BUDGET_PAUSED, 60, 0)


@pytest.mark.parametrize("failing", ["retrieve_session", "update_budget"])
async def test_a_failed_continue_gives_its_reservation_back(
    ceiling_planner: Planner, failing: str
) -> None:
    factory = ceiling_planner.session_factory
    await insert_plan(
        factory, status=PlanStatus.READY, cost_cents=1200, created_at=OCTOBER, user_email="x@a.it"
    )
    paused = await insert_plan(
        factory, status=PlanStatus.BUDGET_PAUSED, cost_cents=60, created_at=OCTOBER
    )
    ceiling_planner.fake.fail_next(failing, ApiRejectedError("refused", status_code=400))

    with pytest.raises(ApiRejectedError):
        await continue_plan(paused, USER, services=ceiling_planner.services)

    plan = await load_plan(factory, paused)
    assert (plan.status, plan.budget_cents, plan.continues) == (PlanStatus.BUDGET_PAUSED, 60, 0)
    titles = [event.title for event in await load_events(factory, paused)]
    assert TITLE_CONTINUED not in titles
    # 1200 + 60 + a start's 60 = 1320: the released 200 no longer stands in the way.
    await start_plan(REQUEST, USER, services=ceiling_planner.services)
    assert len(ceiling_planner.fake.created) == 1


async def test_an_outage_does_not_eat_the_users_plans(quota_planner: Planner) -> None:
    """Michele, 2026-10-18: starts that failed before any session existed (502s) are not plans
    of the month; the next start after the outage is still admitted."""
    factory = quota_planner.session_factory
    await insert_plan(factory, status=PlanStatus.READY, cost_cents=10, created_at=OCTOBER)
    await insert_plan(factory, status=PlanStatus.FAILED, cost_cents=5, created_at=OCTOBER)
    for _ in range(4):  # more than the 3-plan quota
        quota_planner.fake.fail_next("create_session", "api_unavailable")
        with pytest.raises(ManagedAgentsError):
            await start_plan(REQUEST, USER, services=quota_planner.services)

    plan_id = await start_plan(REQUEST, USER, services=quota_planner.services)

    assert (await load_plan(factory, plan_id)).status == PlanStatus.RUNNING.value
    # Now 3 plans (the ready one, the one that failed with a session, this one): the next is one
    # too many.
    with pytest.raises(QuotaReachedError) as caught:
        await start_plan(REQUEST, USER, services=quota_planner.services)
    assert (caught.value.kind, caught.value.quota.plans_used) == ("plans", 3)


async def test_the_eval_runner_is_exempt_from_the_user_quota_not_from_the_ceiling(
    quota_planner: Planner,
) -> None:
    factory = quota_planner.session_factory
    for _ in range(3):  # USER's 3 plans of the month
        await insert_plan(factory, status=PlanStatus.READY, cost_cents=10, created_at=OCTOBER)
    with pytest.raises(QuotaReachedError):
        await start_plan(REQUEST, USER, services=quota_planner.services)

    await start_plan(REQUEST, USER, services=quota_planner.services, user_quota_applies=False)
    assert len(quota_planner.fake.created) == 1

    await insert_plan(  # the ceiling (5000) still holds
        factory, status=PlanStatus.READY, cost_cents=4900, created_at=OCTOBER, user_email="x@a.it"
    )
    with pytest.raises(MonthlyLimitReachedError):
        await start_plan(REQUEST, USER, services=quota_planner.services, user_quota_applies=False)
