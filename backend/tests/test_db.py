import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import Connection, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db import (
    AuthAccountRecord,
    AuthSessionRecord,
    AuthVerificationRecord,
    Base,
    DbSession,
    EventRecord,
    FxRateRecord,
    PlanRecord,
    PlanStatus,
    UserRecord,
)
from tests.conftest import run_alembic

REQUEST: dict[str, Any] = {
    "origin": "MXP",
    "destination": "Lisbona",
    "dates": {"exact_start": "2026-11-14", "exact_end": "2026-11-18"},
    "travelers": [{"kind": "adult"}, {"kind": "adult"}],
    "budget_eur": 1500,
}


def make_plan(**overrides: Any) -> PlanRecord:
    values: dict[str, Any] = {
        "user_email": "test@example.com",
        "agent_profile": "development",
        "request": REQUEST,
    }
    values.update(overrides)
    return PlanRecord(**values)


def make_event(plan_id: uuid.UUID, seq: int, **overrides: Any) -> EventRecord:
    values: dict[str, Any] = {
        "plan_id": plan_id,
        "seq": seq,
        "agent": "coordinator",
        "kind": "status",
        "title": "Al lavoro",
    }
    values.update(overrides)
    return EventRecord(**values)


async def test_plan_round_trip_with_defaults(db_session: AsyncSession) -> None:
    plan = make_plan()
    db_session.add(plan)
    await db_session.commit()
    db_session.expunge_all()

    stored = await db_session.get_one(PlanRecord, plan.id)

    assert isinstance(stored.id, uuid.UUID)
    assert stored.status == PlanStatus.RUNNING
    assert stored.request == REQUEST
    assert stored.session_id is None
    assert stored.plan is None
    assert stored.trip is None
    assert stored.agent_versions is None
    assert stored.failure_reason is None
    assert stored.cost_cents == 0
    assert stored.budget_cents is None
    assert stored.submit_attempts == 0
    assert stored.interrupt_requested_at is None
    assert stored.created_at.tzinfo is not None
    assert stored.updated_at.tzinfo is not None
    assert stored.running_since == stored.created_at


async def test_plan_json_columns_and_updated_at(db_session: AsyncSession) -> None:
    plan = make_plan(session_id="sesn_123")
    db_session.add(plan)
    await db_session.commit()
    created_at = plan.created_at

    plan.status = PlanStatus.READY
    plan.plan = {"title": "Lisbona in autunno", "days": []}
    plan.trip = {"id": str(uuid.uuid4()), "title": "Lisbona in autunno"}
    plan.agent_versions = {"coordinator": 3, "git_sha": "abc1234"}
    plan.cost_cents = 47
    plan.budget_cents = 260
    asked = dt.datetime(2026, 10, 12, 10, 30, tzinfo=dt.UTC)
    plan.interrupt_requested_at = asked
    await db_session.commit()
    db_session.expunge_all()

    stored = await db_session.get_one(PlanRecord, plan.id)
    assert stored.status == "ready"
    assert stored.plan == {"title": "Lisbona in autunno", "days": []}
    assert stored.trip is not None
    assert stored.trip["title"] == "Lisbona in autunno"
    assert stored.agent_versions == {"coordinator": 3, "git_sha": "abc1234"}
    assert stored.cost_cents == 47
    assert stored.budget_cents == 260
    assert stored.interrupt_requested_at == asked
    assert stored.created_at == created_at
    assert stored.updated_at >= created_at


async def test_none_is_stored_as_sql_null_not_json_null(db_session: AsyncSession) -> None:
    plan = make_plan(plan=None, trip=None, agent_versions=None)
    db_session.add(plan)
    await db_session.commit()

    nulls = await db_session.scalar(
        select(func.count())
        .select_from(PlanRecord)
        .where(
            PlanRecord.id == plan.id,
            PlanRecord.plan.is_(None),
            PlanRecord.trip.is_(None),
            PlanRecord.agent_versions.is_(None),
        )
    )
    assert nulls == 1


@pytest.mark.parametrize("status", list(PlanStatus))
async def test_every_plan_status_is_accepted(db_session: AsyncSession, status: PlanStatus) -> None:
    db_session.add(make_plan(status=status.value))
    await db_session.commit()


async def test_unknown_plan_status_is_rejected(db_session: AsyncSession) -> None:
    db_session.add(make_plan(status="done"))

    with pytest.raises(IntegrityError, match="ck_plans_status"):
        await db_session.commit()


async def test_events_round_trip_in_seq_order(db_session: AsyncSession) -> None:
    plan = make_plan()
    db_session.add(plan)
    await db_session.flush()
    ts = dt.datetime(2026, 11, 14, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=1)))
    db_session.add_all(
        [
            make_event(plan.id, 2, agent="flights", kind="tool", title="Expedia · voli MXP→LIS"),
            make_event(
                plan.id,
                1,
                ts=ts,
                detail={"tool": "search_flights", "params": {"from": "MXP", "to": "LIS"}},
                cost_cents=12,
                ma_event_id="sevt_1",
            ),
        ]
    )
    await db_session.commit()
    db_session.expunge_all()

    events = (
        await db_session.scalars(
            select(EventRecord).where(EventRecord.plan_id == plan.id).order_by(EventRecord.seq)
        )
    ).all()

    assert [event.seq for event in events] == [1, 2]
    first, second = events
    assert first.ts == ts
    assert first.detail == {"tool": "search_flights", "params": {"from": "MXP", "to": "LIS"}}
    assert first.cost_cents == 12
    assert first.ma_event_id == "sevt_1"
    assert second.title == "Expedia · voli MXP→LIS"
    assert second.detail is None
    assert second.cost_cents is None
    assert second.ma_event_id is None
    assert second.ts.tzinfo is not None


async def test_ma_event_id_is_unique(db_session: AsyncSession) -> None:
    first_plan, second_plan = make_plan(), make_plan()
    db_session.add_all([first_plan, second_plan])
    await db_session.flush()
    db_session.add(make_event(first_plan.id, 1, ma_event_id="sevt_dup"))
    await db_session.commit()

    db_session.add(make_event(second_plan.id, 1, ma_event_id="sevt_dup"))
    with pytest.raises(IntegrityError, match="uq_events_ma_event_id"):
        await db_session.commit()


async def test_events_without_ma_event_id_do_not_collide(db_session: AsyncSession) -> None:
    plan = make_plan()
    db_session.add(plan)
    await db_session.flush()
    db_session.add_all([make_event(plan.id, seq) for seq in (1, 2, 3)])
    await db_session.commit()

    count = await db_session.scalar(
        select(func.count()).select_from(EventRecord).where(EventRecord.plan_id == plan.id)
    )
    assert count == 3


async def test_seq_is_unique_per_plan(db_session: AsyncSession) -> None:
    plan = make_plan()
    db_session.add(plan)
    await db_session.flush()
    db_session.add(make_event(plan.id, 1))
    await db_session.commit()

    db_session.add(make_event(plan.id, 1))
    with pytest.raises(IntegrityError, match="pk_events"):
        await db_session.commit()


async def test_event_needs_an_existing_plan(db_session: AsyncSession) -> None:
    db_session.add(make_event(uuid.uuid4(), 1))

    with pytest.raises(IntegrityError, match="fk_events_plan_id_plans"):
        await db_session.commit()


async def test_deleting_a_plan_deletes_its_events(db_session: AsyncSession) -> None:
    plan = make_plan()
    db_session.add(plan)
    await db_session.flush()
    db_session.add_all([make_event(plan.id, 1), make_event(plan.id, 2, ma_event_id="sevt_9")])
    await db_session.commit()

    await db_session.execute(delete(PlanRecord).where(PlanRecord.id == plan.id))
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(EventRecord)) == 0


async def test_fx_rate_round_trip_keeps_precision(db_session: AsyncSession) -> None:
    day = dt.date(2026, 10, 9)
    db_session.add(
        FxRateRecord(date=day, currency="USD", rate=Decimal("1.0876"), source="bdi_daily")
    )
    await db_session.commit()
    db_session.expunge_all()

    stored = await db_session.get_one(FxRateRecord, (day, "USD", "bdi_daily"))
    assert stored.rate == Decimal("1.0876")
    assert stored.source == "bdi_daily"


async def test_one_fx_rate_per_currency_per_day_per_source(db_session: AsyncSession) -> None:
    day = dt.date(2026, 10, 9)
    db_session.add(FxRateRecord(date=day, currency="GBP", rate=Decimal("0.86"), source="bdi_daily"))
    await db_session.commit()

    db_session.add(FxRateRecord(date=day, currency="GBP", rate=Decimal("0.87"), source="bdi_daily"))
    with pytest.raises(IntegrityError, match="pk_fx_rates"):
        await db_session.commit()


async def test_a_daily_and_a_monthly_rate_can_share_a_date(db_session: AsyncSession) -> None:
    """The 1st of a month holds both a Banca d'Italia daily rate and the InforEuro rate."""
    first = dt.date(2026, 10, 1)
    db_session.add_all(
        [
            FxRateRecord(date=first, currency="USD", rate=Decimal("1.17"), source="bdi_daily"),
            FxRateRecord(
                date=first, currency="USD", rate=Decimal("1.1712"), source="inforeuro_monthly"
            ),
        ]
    )
    await db_session.commit()

    count = await db_session.scalar(select(func.count()).select_from(FxRateRecord))
    assert count == 2


async def test_tables_start_empty_in_every_test(db_session: AsyncSession) -> None:
    for model in (PlanRecord, EventRecord, FxRateRecord):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


# --- migrations -------------------------------------------------------------------------------


def _schema_diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    return list(compare_metadata(context, Base.metadata))


async def test_migrations_match_the_models(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        diff = await conn.run_sync(_schema_diff)

    assert diff == [], "app/db.py and migrations/ differ: add a migration"


async def test_migrations_downgrade_to_base_and_back(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(run_alembic, "downgrade", "base")
        remaining = await conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name IN ('plans', 'events', 'fx_rates')"
            )
        )
        assert remaining == 0
        await conn.run_sync(run_alembic, "upgrade", "head")

    async with db_engine.connect() as conn:
        assert await conn.run_sync(_schema_diff) == []


# --- get_db dependency ------------------------------------------------------------------------


async def test_get_db_yields_a_session_bound_to_the_app_engine(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    @app.post("/_test/plans")
    async def create_plan(session: DbSession) -> dict[str, str]:
        plan = make_plan()
        session.add(plan)
        await session.commit()
        return {"id": str(plan.id)}

    response = await client.post("/_test/plans")

    assert response.status_code == 200
    stored = await db_session.get(PlanRecord, uuid.UUID(response.json()["id"]))
    assert stored is not None
    assert stored.user_email == "test@example.com"


async def test_get_db_discards_uncommitted_work(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    @app.post("/_test/uncommitted")
    async def add_without_commit(session: DbSession) -> dict[str, bool]:
        session.add(make_plan())
        await session.flush()
        return {"ok": True}

    response = await client.post("/_test/uncommitted")

    assert response.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(PlanRecord)) == 0


# --- the web app's own accounts (Better Auth tables, AUTH_MODE=atlas) ----------------------------


def make_user(**overrides: Any) -> UserRecord:
    values: dict[str, Any] = {"id": "usr_test", "email": "test@example.com"}
    values.update(overrides)
    return UserRecord(**values)


def tomorrow() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(days=1)


async def test_user_round_trip_with_defaults(db_session: AsyncSession) -> None:
    db_session.add(make_user())
    await db_session.commit()
    db_session.expunge_all()

    stored = await db_session.get_one(UserRecord, "usr_test")

    assert stored.email == "test@example.com"
    assert stored.name == ""  # a magic-link sign-up has no display name
    assert stored.email_verified is False
    assert stored.image is None
    assert stored.created_at.tzinfo is not None
    assert stored.updated_at.tzinfo is not None


async def test_user_emails_are_unique(db_session: AsyncSession) -> None:
    db_session.add(make_user())
    await db_session.commit()
    db_session.add(make_user(id="usr_other"))

    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_a_plan_may_carry_its_owners_id_but_only_a_real_one(db_session: AsyncSession) -> None:
    db_session.add(make_user())
    await db_session.commit()
    db_session.add(make_plan())  # TripTracker's or the local mode's plan: no user id
    db_session.add(make_plan(user_id="usr_test"))
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(PlanRecord)) == 2

    db_session.add(make_plan(user_id="usr_missing"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_deleting_a_user_deletes_their_plans_sessions_and_accounts(
    db_session: AsyncSession,
) -> None:
    # No ORM relationships tie these models (the web app owns the rows), so the user is
    # committed first: the unit of work would not otherwise order the inserts by foreign key.
    db_session.add(make_user())
    await db_session.commit()
    db_session.add(make_plan(user_id="usr_test"))
    db_session.add(make_plan())  # another mode's plan, untouched by the deletion
    db_session.add(
        AuthSessionRecord(id="ses_1", user_id="usr_test", token="tok_1", expires_at=tomorrow())
    )
    db_session.add(
        AuthAccountRecord(id="acc_1", user_id="usr_test", account_id="g-1", provider_id="google")
    )
    await db_session.commit()

    await db_session.execute(delete(UserRecord).where(UserRecord.id == "usr_test"))
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(UserRecord)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AuthSessionRecord)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AuthAccountRecord)) == 0
    [remaining] = (await db_session.scalars(select(PlanRecord))).all()
    assert remaining.user_id is None


async def test_session_tokens_are_unique_and_verifications_round_trip(
    db_session: AsyncSession,
) -> None:
    db_session.add(make_user())
    await db_session.commit()
    db_session.add(
        AuthSessionRecord(id="ses_1", user_id="usr_test", token="tok_1", expires_at=tomorrow())
    )
    db_session.add(
        AuthVerificationRecord(
            id="ver_1", identifier="test@example.com", value="magic", expires_at=tomorrow()
        )
    )
    await db_session.commit()
    db_session.expunge_all()

    verification = await db_session.get_one(AuthVerificationRecord, "ver_1")
    assert verification.identifier == "test@example.com"
    assert verification.expires_at.tzinfo is not None

    db_session.add(
        AuthSessionRecord(id="ses_2", user_id="usr_test", token="tok_1", expires_at=tomorrow())
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
