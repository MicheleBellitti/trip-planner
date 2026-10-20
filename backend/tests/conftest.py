"""Shared test fixtures.

Everything runs offline: no Anthropic key, no Managed Agents session, no travel MCP.

- The backend's own `httpx` traffic (fx, auth, triptracker_schema) is mocked with respx.
- respx does NOT cover the Anthropic SDK: anthropic 1.13.0 runs on `httpx2`. Managed Agents
  code is tested with `tests.fakes.FakeManagedAgentsClient`, and the SDK client itself with an
  `httpx2.MockTransport` (tests/fakes/README.md, "Not the fake's job").
- As a safety net, `OFFLINE_ANTHROPIC_ENV` is applied at import and again before every test
  (`_offline_anthropic_sdk`): every credential variable the SDK reads is blanked or removed and
  `ANTHROPIC_BASE_URL` points at a closed local port, so an SDK client built by mistake without
  a mock transport fails at once (connection refused) instead of reaching the network with a
  key found on the machine.

Database: tests that touch Postgres request `db_engine`, `db_session` or `db_session_factory`.
The test database (TEST_DATABASE_URL, default postgresql+asyncpg://localhost:5432/trip_planner_test)
is created if missing and rebuilt from the Alembic migrations once per run; every test that
requests a database fixture starts from empty tables. Tests that don't need Postgres never
connect to it.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import Connection, make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/trip_planner_test"
)

# The environment every test runs with. Applied before any `app` module is imported, so that
# `app.main.app` (built at import time) never sees a developer's backend/.env values for these.
TEST_ENV: dict[str, str] = {
    "ENVIRONMENT": "development",
    "AUTH_MODE": "local",
    "PLANNER_ALLOWED_EMAILS": "test@example.com",
    "FRONTEND_ORIGIN": "https://atlas.bellittim.com",
    "TRIPTRACKER_ORIGIN": "https://viaggi.bellittim.com",
    "TRIP_SCHEMA_URL": "https://viaggi.bellittim.com/schema/trip.json",
    "DATABASE_URL": TEST_DATABASE_URL,
    "AGENT_PROFILE": "development",
    # No test builds a real link checker by accident; a test that wants one sets it itself.
    "LINK_CHECK_ENABLED": "false",
    # No test looks up Wikimedia photos for choice cards by accident.
    "CHOICE_PHOTOS_ENABLED": "false",
    # Never a real key in tests. Blank rather than unset: an unset variable would let Settings
    # read a developer's backend/.env.
    "ANTHROPIC_API_KEY": "",
    # Same for federation: Settings must not read a developer's backend/.env for these.
    "ANTHROPIC_FEDERATION_RULE_ID": "",
    "ANTHROPIC_ORGANIZATION_ID": "",
    "ANTHROPIC_IDENTITY_TOKEN_FILE": "",
    "ANTHROPIC_WORKSPACE_ID": "",
    "SESSION_BUDGET_CENTS": "60",
    "MONTHLY_LIMIT_CENTS": "5000",
    "LOCKFILE_PATH": "",  # backend/claude-lock.<AGENT_PROFILE>.json (absent in tests)
    "LOG_LEVEL": "WARNING",
}

OFFLINE_ANTHROPIC_ENV: dict[str, str | None] = {
    "ANTHROPIC_API_KEY": "",  # the SDK treats an empty value as unset
    "ANTHROPIC_AUTH_TOKEN": "",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:9",  # discard port: connection refused, no traffic
    # No on-disk profile: a client built without explicit credentials raises CredentialsError.
    "ANTHROPIC_CONFIG_DIR": "/nonexistent/trip-planner-tests/anthropic",
    "ANTHROPIC_PROFILE": None,
    "ANTHROPIC_IDENTITY_TOKEN": None,
    "ANTHROPIC_IDENTITY_TOKEN_FILE": None,
    "ANTHROPIC_FEDERATION_RULE_ID": None,
    "ANTHROPIC_ORGANIZATION_ID": None,
    "ANTHROPIC_WEBHOOK_SIGNING_KEY": None,
}
"""What the Anthropic SDK may read from the environment during tests: None removes the
variable. Credential order and variables: SDK _client.py:187-235."""


def _apply_offline_anthropic_env(
    setenv: Callable[[str, str], None], delenv: Callable[[str], None]
) -> None:
    for key, value in OFFLINE_ANTHROPIC_ENV.items():
        if value is None:
            delenv(key)
        else:
            setenv(key, value)


os.environ.update(TEST_ENV)


def _remove_from_environ(key: str) -> None:
    os.environ.pop(key, None)


_apply_offline_anthropic_env(os.environ.__setitem__, _remove_from_environ)

from app.config import Settings, get_settings  # noqa: E402
from app.db import Base, UserRecord, create_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


# --- offline guard ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _offline_anthropic_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-apply `OFFLINE_ANTHROPIC_ENV` before every test (a previous test may have changed the
    environment), so no test can reach the Anthropic API with real credentials."""
    _apply_offline_anthropic_env(
        monkeypatch.setenv, lambda key: monkeypatch.delenv(key, raising=False)
    )


# --- settings ---------------------------------------------------------------------------------


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Settings for the test environment, also returned by `get_settings()` during the test."""
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Build Settings from TEST_ENV plus keyword overrides (field names), ignoring backend/.env."""

    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {key.lower(): value for key, value in TEST_ENV.items()}
        values.update(overrides)
        return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]

    return factory


# --- application ------------------------------------------------------------------------------


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    """A fresh app with its lifespan running (httpx's ASGITransport doesn't run lifespans)."""
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


# --- database ---------------------------------------------------------------------------------


def _alembic_config(connection: Connection) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def run_alembic(connection: Connection, action: str, revision: str) -> None:
    """Run `alembic upgrade|downgrade <revision>` on an open (sync) connection."""
    getattr(command, action)(_alembic_config(connection), revision)


async def _ensure_database_exists(url: str) -> None:
    target = make_url(url)
    database = target.database
    if not database or "test" not in database:
        msg = f"refusing to use {database!r} as the test database: its name must contain 'test'"
        raise RuntimeError(msg)
    admin = create_async_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}
            )
            if not exists:
                quoted = conn.dialect.identifier_preparer.quote(database)
                await conn.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        await admin.dispose()


async def _rebuild_schema(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(run_alembic, "upgrade", "head")
    finally:
        await engine.dispose()


async def _prepare_test_database(url: str) -> None:
    try:
        await _ensure_database_exists(url)
    except OSError as exc:
        pytest.fail(
            f"PostgreSQL is not reachable at {url} ({exc}); start it or set TEST_DATABASE_URL"
        )
    await _rebuild_schema(url)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Create the test database if needed and migrate a fresh schema to head, once per run.

    Sync on purpose: it runs on its own short-lived event loop, so no connection outlives it.
    """
    asyncio.run(_prepare_test_database(TEST_DATABASE_URL))
    return TEST_DATABASE_URL


async def truncate_all(engine: AsyncEngine) -> None:
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine on the test database, with every table emptied before the test."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        await truncate_all(engine)
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


@pytest.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with db_session_factory() as session:
        yield session


# --- API tests: app factory, planner stand-in, plan rows (owner F) ----------------------------
#
# `make_app(client=...)` is THE hook for running the real wiring against the fake Managed Agents
# client: main.py's lifespan reads `app.state.planner_client_override` and passes it to
# `sessions.start_planner(client=...)`.
#
# `stub_planner` replaces `sessions.start_planner` / `stop_planner` and
# `jobs.start_stuck_plan_checker` for one test, so the lifespan builds a minimal
# `PlannerServices` (a real `PlanHub` and `SessionVerifier`, no Managed Agents client, trip.json
# store or FX converter). API tests use it to stay independent of the lifecycle's
# implementation and of the network; they drive POST routes by monkeypatching
# `sessions.start_plan` & co.

import datetime as dt  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from contextlib import AbstractAsyncContextManager, asynccontextmanager  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import cast  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app import consumer, jobs, sessions  # noqa: E402
from app.auth import SessionCache, SessionVerifier  # noqa: E402
from app.db import EventRecord, PlanRecord, PlanStatus  # noqa: E402
from app.events import AgentName, EventKind, UIEvent  # noqa: E402
from app.fx import FxConverter  # noqa: E402
from app.hub import DEFAULT_QUEUE_SIZE, PlanHub  # noqa: E402
from app.ma_client import ManagedAgentsClient  # noqa: E402
from app.triptracker_schema import TripSchemaStore  # noqa: E402

AppFactory = Callable[..., AbstractAsyncContextManager[FastAPI]]


@pytest.fixture
def make_app(settings: Settings) -> AppFactory:
    """Factory of apps with their lifespan running (httpx's ASGITransport doesn't run it):

        async with make_app(client=FakeManagedAgentsClient.from_scenario("happy_path")) as app:
            ...

    `client` is passed to `sessions.start_planner(client=...)` through
    `app.state.planner_client_override`; `settings` replaces the test settings."""

    @asynccontextmanager
    async def factory(
        *, settings: Settings = settings, client: ManagedAgentsClient | None = None
    ) -> AsyncIterator[FastAPI]:
        application = create_app(settings)
        if client is not None:
            application.state.planner_client_override = client
        async with application.router.lifespan_context(application):
            yield application

    return factory


@dataclass(slots=True)
class StubPlanner:
    """Knobs and record of `stub_planner`; set the knobs before the app starts."""

    cache_clock: Callable[[], float] = time.monotonic
    """Clock of the `SessionVerifier`'s cache (time.time under time-machine, or a fake)."""
    queue_size: int = DEFAULT_QUEUE_SIZE
    """Per-subscriber buffer of the `PlanHub`."""
    started: list[sessions.PlannerServices] = field(default_factory=list[sessions.PlannerServices])
    stopped: list[sessions.PlannerServices] = field(default_factory=list[sessions.PlannerServices])

    @property
    def planner(self) -> sessions.PlannerServices:
        """The services of the app started last."""
        return self.started[-1]


@pytest.fixture
def stub_planner(monkeypatch: pytest.MonkeyPatch) -> StubPlanner:
    """Make the lifespan build a minimal `PlannerServices` (see the section comment)."""
    stub = StubPlanner()

    async def start_planner(
        settings: Settings,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        http: httpx.AsyncClient,
        client: ManagedAgentsClient | None = None,
        **_: Any,
    ) -> sessions.PlannerServices:
        services = sessions.PlannerServices(
            settings=settings,
            http=http,
            session_factory=session_factory,
            hub=PlanHub(queue_size=stub.queue_size),
            trip_schema=cast(TripSchemaStore, None),
            fx=cast(FxConverter, None),
            session_verifier=SessionVerifier(
                settings, http, cache=SessionCache(clock=stub.cache_clock)
            ),
            client=client,
            roster=None,
            registry=None,
            unavailable_reasons=["stub planner (tests)"],
        )
        stub.started.append(services)
        return services

    async def stop_planner(services: sessions.PlannerServices) -> None:
        for task in services.background_tasks:
            task.cancel()
        await asyncio.gather(*services.background_tasks, return_exceptions=True)
        stub.stopped.append(services)

    async def idle() -> None:
        await asyncio.Event().wait()

    def start_stuck_plan_checker(
        services: sessions.PlannerServices, **_: Any
    ) -> asyncio.Task[None]:
        return asyncio.create_task(idle(), name="stub-stuck-plan-checker")

    monkeypatch.setattr(sessions, "start_planner", start_planner)
    monkeypatch.setattr(sessions, "stop_planner", stop_planner)
    monkeypatch.setattr(jobs, "start_stuck_plan_checker", start_stuck_plan_checker)
    return stub


async def reference_load_events_after(
    db: AsyncSession, plan_id: uuid.UUID, after_seq: int | None, *, limit: int = 1000
) -> list[UIEvent]:
    """`consumer.load_events_after`'s contract as a plain query (`stub_event_replay`)."""
    query = select(EventRecord).where(EventRecord.plan_id == plan_id)
    if after_seq is not None:
        query = query.where(EventRecord.seq > after_seq)
    rows = await db.scalars(query.order_by(EventRecord.seq).limit(limit))
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


@pytest.fixture
def stub_event_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace `consumer.load_events_after` (the SSE replay's reader) with
    `reference_load_events_after`, so SSE tests don't depend on the consumer's implementation."""
    monkeypatch.setattr(consumer, "load_events_after", reference_load_events_after)


TEST_USER_EMAIL = TEST_ENV["PLANNER_ALLOWED_EMAILS"].split(",")[0]
"""The signed-in user under AUTH_MODE=local."""

SAMPLE_REQUEST: dict[str, Any] = {
    "origin": "Milano",
    "destination": "Lisbona",
    "suggest_destination": False,
    "dates": {"exact_start": "2027-11-14", "exact_end": "2027-11-18"},
    "travelers": [{"kind": "adult"}, {"kind": "adult"}],
    "budget_eur": 1500,
}
"""A stored PlanRequest (JSON) for rows inserted by `plan_rows`."""


@dataclass(slots=True)
class PlanRows:
    """Inserts `plans` and `events` rows directly (no consumer), for API tests."""

    session_factory: async_sessionmaker[AsyncSession]

    async def add_user(self, user_id: str, email: str, *, email_verified: bool = True) -> None:
        """Insert a `users` row (the web app's own accounts), for plans that carry `user_id`;
        verified unless told otherwise, as a magic-link sign-in leaves it."""
        async with self.session_factory() as db:
            db.add(UserRecord(id=user_id, email=email, email_verified=email_verified))
            await db.commit()

    async def add_plan(
        self,
        *,
        user_email: str = TEST_USER_EMAIL,
        user_id: str | None = None,
        status: PlanStatus = PlanStatus.RUNNING,
        request: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
        trip: dict[str, Any] | None = None,
        cost_cents: int = 0,
        budget_cents: int | None = 60,
        created_at: dt.datetime | None = None,
        failure_reason: str | None = None,
        session_id: str | None = "sesn_test",
        link_health: dict[str, Any] | None = None,
    ) -> PlanRecord:
        record = PlanRecord(
            user_email=user_email,
            user_id=user_id,
            session_id=session_id,
            agent_profile="development",
            status=status.value,
            request=request if request is not None else dict(SAMPLE_REQUEST),
            plan=plan,
            trip=trip,
            cost_cents=cost_cents,
            budget_cents=budget_cents,
            failure_reason=failure_reason,
            link_health=link_health,
        )
        if created_at is not None:
            record.created_at = created_at
        async with self.session_factory() as db:
            db.add(record)
            await db.commit()
            await db.refresh(record)
        return record

    async def set_status(self, plan_id: uuid.UUID, status: PlanStatus) -> None:
        async with self.session_factory() as db:
            record = await db.get(PlanRecord, plan_id)
            assert record is not None
            record.status = status.value
            await db.commit()

    async def add_event(
        self,
        plan_id: uuid.UUID,
        seq: int,
        *,
        title: str | None = None,
        kind: EventKind = EventKind.STATUS,
        agent: AgentName = AgentName.COORDINATOR,
    ) -> UIEvent:
        """Store event `seq` and return it as the consumer would publish it."""
        event = UIEvent(
            seq=seq,
            ts=dt.datetime(2026, 10, 12, 10, 0, seq % 60, tzinfo=dt.UTC),
            agent=agent,
            kind=kind,
            title=title or f"Evento {seq}",
            detail={"n": seq},
            cost_cents=seq,
        )
        async with self.session_factory() as db:
            db.add(
                EventRecord(
                    plan_id=plan_id,
                    seq=event.seq,
                    ts=event.ts,
                    agent=event.agent.value,
                    kind=event.kind.value,
                    title=event.title,
                    detail=event.detail,
                    cost_cents=event.cost_cents,
                    ma_event_id=f"test:{plan_id}:{seq}",
                )
            )
            await db.commit()
        return event


@pytest.fixture
def plan_rows(db_session_factory: async_sessionmaker[AsyncSession]) -> PlanRows:
    """`PlanRows` on the (emptied) test database."""
    return PlanRows(db_session_factory)
