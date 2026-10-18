"""app/quota.py: the month's usage with the running plans' budgets reserved, the per-user
quota arithmetic, the running count. The checks themselves are driven in test_sessions.py."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.config import Settings
from app.db import PlanStatus
from app.quota import (
    QuotaReachedError,
    Usage,
    UserQuota,
    month_bounds,
    month_usage,
    running_plans,
    user_quota,
)
from app.sessions import plan_owner_filter
from tests.conftest import PlanRows

ROME = ZoneInfo("Europe/Rome")
NOW = dt.datetime(2026, 10, 13, 12, 0, tzinfo=ROME)
OCTOBER = dt.datetime(2026, 10, 2, 9, 0, tzinfo=ROME)
SEPTEMBER = dt.datetime(2026, 9, 30, 23, 30, tzinfo=ROME)
OTHER = "other@example.com"


async def seed(plan_rows: PlanRows) -> None:
    """Five October plans (one of them another user's) and one September plan."""
    await plan_rows.add_plan(
        status=PlanStatus.READY, cost_cents=120, budget_cents=60, created_at=OCTOBER
    )
    # Running, 50 cents of its 60 unspent: reserved.
    await plan_rows.add_plan(
        status=PlanStatus.RUNNING, cost_cents=10, budget_cents=60, created_at=OCTOBER
    )
    # Running before its session exists: the profile's budget stands in (60 here).
    await plan_rows.add_plan(
        status=PlanStatus.RUNNING, cost_cents=0, budget_cents=None, created_at=OCTOBER
    )
    # Paused: its cost reached its budget, nothing to reserve.
    await plan_rows.add_plan(
        status=PlanStatus.BUDGET_PAUSED, cost_cents=60, budget_cents=60, created_at=OCTOBER
    )
    # Another user's, running and over its budget by the overshoot of one request: never negative.
    await plan_rows.add_plan(
        status=PlanStatus.RUNNING,
        cost_cents=70,
        budget_cents=60,
        created_at=OCTOBER,
        user_email=OTHER,
    )
    await plan_rows.add_plan(
        status=PlanStatus.READY, cost_cents=500, budget_cents=60, created_at=SEPTEMBER
    )


async def test_month_usage_counts_cost_and_reserves_the_running_plans_unspent_budget(
    db_session: AsyncSession, plan_rows: PlanRows
) -> None:
    await seed(plan_rows)

    everyone = await month_usage(db_session, now=NOW, owner=None, default_budget_cents=60)

    assert everyone == Usage(plans=5, cost_cents=120 + 10 + 0 + 60 + 70, reserved_cents=50 + 60)
    assert everyone.cents == 260 + 110


async def test_month_usage_of_one_owner(
    db_session: AsyncSession, plan_rows: PlanRows, make_settings: Callable[..., Settings]
) -> None:
    await seed(plan_rows)
    owner = plan_owner_filter(CurrentUser(email=OTHER), settings=make_settings())

    mine = await month_usage(db_session, now=NOW, owner=owner, default_budget_cents=60)

    assert mine == Usage(plans=1, cost_cents=70, reserved_cents=0)


async def test_a_start_that_never_had_a_session_is_not_a_plan_but_its_cost_counts(
    db_session: AsyncSession, plan_rows: PlanRows
) -> None:
    # create_session refused: failed, no session, nothing spent. Not counted.
    await plan_rows.add_plan(
        status=PlanStatus.FAILED, cost_cents=0, created_at=OCTOBER, session_id=None
    )
    # A session existed (a start that timed out, a run that failed): a plan, with its cost.
    await plan_rows.add_plan(status=PlanStatus.FAILED, cost_cents=7, created_at=OCTOBER)
    # Whatever the row says, a recorded cost is never dropped.
    await plan_rows.add_plan(
        status=PlanStatus.FAILED, cost_cents=3, created_at=OCTOBER, session_id=None
    )

    usage = await month_usage(db_session, now=NOW, owner=None, default_budget_cents=60)

    assert usage == Usage(plans=1, cost_cents=10, reserved_cents=0)


async def test_last_months_plans_still_running_reserve_in_the_new_month(
    db_session: AsyncSession, plan_rows: PlanRows
) -> None:
    last_night = dt.datetime(2026, 10, 31, 23, 50, tzinfo=ROME)
    # Created in October, still running on 1 November with 50 of its 60 unspent.
    await plan_rows.add_plan(
        status=PlanStatus.RUNNING, cost_cents=10, budget_cents=60, created_at=last_night
    )
    # Created in October and finished: November knows nothing of it.
    await plan_rows.add_plan(status=PlanStatus.READY, cost_cents=90, created_at=last_night)
    # Paused in October: it reserves nothing until a "Continua" turns it running.
    await plan_rows.add_plan(
        status=PlanStatus.BUDGET_PAUSED, cost_cents=60, budget_cents=60, created_at=last_night
    )
    november = dt.datetime(2026, 11, 1, 0, 5, tzinfo=ROME)

    usage = await month_usage(db_session, now=november, owner=None, default_budget_cents=60)

    # Its cost stays October's (created_at accounting); only the reservation crosses over.
    assert usage == Usage(plans=0, cost_cents=0, reserved_cents=50)
    october = await month_usage(db_session, now=last_night, owner=None, default_budget_cents=60)
    assert october == Usage(plans=3, cost_cents=160, reserved_cents=50)


async def test_month_usage_of_an_empty_month_is_zero(db_session: AsyncSession) -> None:
    assert await month_usage(db_session, now=NOW, owner=None, default_budget_cents=60) == Usage(
        plans=0, cost_cents=0, reserved_cents=0
    )


async def test_running_plans_counts_every_users_running_plans(
    db_session: AsyncSession, plan_rows: PlanRows
) -> None:
    await seed(plan_rows)
    assert await running_plans(db_session) == 3


def test_user_quota_says_what_would_break_first(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(user_monthly_plans=3, user_monthly_cents=300)
    allowance = user_quota(
        Usage(plans=2, cost_cents=150, reserved_cents=90), settings=settings, now=NOW
    )

    assert allowance == UserQuota(
        plans_used=2,
        plans_limit=3,
        cents_used=240,
        cents_limit=300,
        resets_at=dt.datetime(2026, 11, 1, tzinfo=ROME),
        next_plan_cents=settings.session_budget_cents,
        continue_cents=200,
    )
    assert allowance.exceeded_by(plans=1, cents=60) is None  # 3 plans, 300 cents: at the limits
    assert allowance.exceeded_by(plans=1, cents=61) == "cents"
    assert allowance.exceeded_by(plans=2, cents=0) == "plans"
    assert allowance.exceeded_by(plans=2, cents=100) == "plans"  # plans first
    assert allowance.as_data() == {
        "plans_used": 2,
        "plans_limit": 3,
        "cents_used": 240,
        "cents_limit": 300,
        "resets_at": "2026-11-01T00:00:00+01:00",
        "next_plan_cents": settings.session_budget_cents,
        "continue_cents": 200,
    }


def test_quota_error_carries_the_kind_and_the_figures() -> None:
    allowance = UserQuota(
        plans_used=10,
        plans_limit=10,
        cents_used=100,
        cents_limit=1500,
        resets_at=NOW,
        next_plan_cents=400,
        continue_cents=200,
    )
    error = QuotaReachedError("plans", allowance)
    assert (error.kind, error.quota) == ("plans", allowance)
    assert "plans" in str(error)


@pytest.mark.parametrize(
    ("now", "start", "end"),
    [
        (
            dt.datetime(2026, 12, 31, 23, 30, tzinfo=ROME),
            dt.datetime(2026, 12, 1, tzinfo=ROME),
            dt.datetime(2027, 1, 1, tzinfo=ROME),
        ),
        (
            dt.datetime(2026, 10, 31, 23, 30, tzinfo=dt.UTC),  # already November in Rome (CET)
            dt.datetime(2026, 11, 1, tzinfo=ROME),
            dt.datetime(2026, 12, 1, tzinfo=ROME),
        ),
    ],
)
def test_month_bounds_follow_rome(now: dt.datetime, start: dt.datetime, end: dt.datetime) -> None:
    assert month_bounds(now) == (start, end)


def test_month_bounds_refuse_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        month_bounds(dt.datetime(2026, 10, 13, 12, 0))  # noqa: DTZ001  (the point of the test)
