"""Per-user and global economics: the month's usage, the quota, the caps (roadmap phase 1,
"per-user economics").

Money is US cents of Managed Agents list cost, like everywhere in the backend (never euro).

- A **month** is the calendar month in Europe/Rome (`month_bounds`, shared with the global
  ceiling `MONTHLY_LIMIT_CENTS`).
- **Usage** counts the plans created in the month (not those whose start failed before a
  session existed, `never_started`) and the cents they used: the cost already recorded
  (`plans.cost_cents`) plus the **reservation** of the plans still `running`, whichever month
  created them, the budget they may still spend (`budget_cents - cost_cents`, never negative; a
  running plan whose session does not exist yet reserves the profile's session budget). Without
  the reservation N requests sent together would all pass a check that only knows cost already
  recorded.
- The **per-user quota** (`USER_MONTHLY_PLANS`, `USER_MONTHLY_CENTS`) is checked before every
  plan start and every "Continua" for the plans of the signed-in user
  (`sessions.plan_owner_filter`); admins (`auth.user_is_admin`) are exempt from it, never from the
  global ceiling, the running cap or the rate limits.
- The **global ceiling** gets the same reservation, and a start is refused when the new plan's
  own budget would not fit under it (`usage.cents + session_budget > limit`).
- The **running cap** (`MAX_RUNNING_PLANS`) counts the plans `running` for everyone: past it a
  start is refused with 503 `planner_busy`, nothing spent, retry in a minute.
- The **continue cap** (`MAX_CONTINUES_PER_PLAN`) counts `plans.continues`, raised by every
  "Continua".

The checks and the insert of the new plan run in one transaction that first takes a
transaction-level advisory lock (`lock_checks`), so two requests cannot both pass a check that
the other one's insert would have failed: `pg_advisory_xact_lock` is released with the commit.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app import clock
from app.config import Settings
from app.db import PlanRecord, PlanStatus

QUOTA_LOCK_KEY = 0x41544C53
"""The advisory lock key of the quota checks ("ATLS"), distinct from the plan leases'."""

CONTINUE_INCREMENT_CENTS = 200
""""Continua con 2 $ in piu'": the budget grows by $2 over what was consumed (and the quota
counts these 200 cents, `UserQuota.continue_cents`)."""

PLANNER_BUSY_RETRY_SECONDS = 60
"""What the 503 `planner_busy` answer suggests as `Retry-After`: a plan takes minutes."""

QuotaKind = Literal["plans", "cents"]


@dataclass(frozen=True)
class Usage:
    """The month's plans and cents of one owner, or of everyone."""

    plans: int
    cost_cents: int
    reserved_cents: int

    @property
    def cents(self) -> int:
        """Recorded cost plus the unspent budget of the running plans."""
        return self.cost_cents + self.reserved_cents


@dataclass(frozen=True)
class UserQuota:
    """One user's month against their limits: what GET /me shows and a refusal carries."""

    plans_used: int
    plans_limit: int
    cents_used: int
    cents_limit: int
    resets_at: dt.datetime
    """The first instant of the next month (Europe/Rome), when the counters start again."""
    next_plan_cents: int
    """What a new plan reserves (the profile's session budget): a start needs
    `cents_used + next_plan_cents <= cents_limit`."""
    continue_cents: int
    """What a "Continua" adds (`CONTINUE_INCREMENT_CENTS`): it needs `cents_used +
    continue_cents <= cents_limit`."""

    def exceeded_by(self, *, plans: int = 0, cents: int = 0) -> QuotaKind | None:
        """Which limit `plans` more plans and `cents` more cents would break, plans first."""
        if self.plans_used + plans > self.plans_limit:
            return "plans"
        if self.cents_used + cents > self.cents_limit:
            return "cents"
        return None

    def as_data(self) -> dict[str, int | str]:
        """The error envelope's `data` (and GET /me's `quota`), JSON-ready."""
        return {
            "plans_used": self.plans_used,
            "plans_limit": self.plans_limit,
            "cents_used": self.cents_used,
            "cents_limit": self.cents_limit,
            "resets_at": self.resets_at.isoformat(),
            "next_plan_cents": self.next_plan_cents,
            "continue_cents": self.continue_cents,
        }


class QuotaReachedError(Exception):
    """The user's monthly quota does not allow this start or "Continua"."""

    def __init__(self, kind: QuotaKind, quota: UserQuota) -> None:
        self.kind: QuotaKind = kind
        self.quota = quota
        super().__init__(f"user quota reached: {kind} ({quota.as_data()})")


class PlannerBusyError(Exception):
    """`MAX_RUNNING_PLANS` plans are running: nothing was started."""

    def __init__(self, running: int, limit: int) -> None:
        self.running = running
        self.limit = limit
        super().__init__(f"{running} plans running, cap {limit}")


class ContinueLimitReachedError(Exception):
    """The plan had its `MAX_CONTINUES_PER_PLAN` budget raises."""

    def __init__(self, continues: int, limit: int) -> None:
        self.continues = continues
        self.limit = limit
        super().__init__(f"plan continued {continues} times, cap {limit}")


def month_bounds(now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """[first instant of the month, first instant of the next month) in Europe/Rome, aware."""
    if now.tzinfo is None or now.utcoffset() is None:
        msg = "month_bounds needs a timezone-aware datetime"
        raise ValueError(msg)
    local = now.astimezone(clock.HOME_TIMEZONE)
    start = dt.datetime(local.year, local.month, 1, tzinfo=clock.HOME_TIMEZONE)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    end = dt.datetime(year, month, 1, tzinfo=clock.HOME_TIMEZONE)
    return start, end


async def lock_checks(db: AsyncSession) -> None:
    """Take the quota checks' transaction-level advisory lock on `db`'s connection: the checks
    and the insert that follow run alone until the transaction ends."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": QUOTA_LOCK_KEY})


def never_started() -> ColumnElement[bool]:
    """SQL predicate: a plan whose start failed before any session existed (`failed` with no
    `session_id`: `create_session` refused, `sessions._mark_start_failed` without a session, or
    a crash before the session was created). Nothing could be spent on it, so it does not count
    against `USER_MONTHLY_PLANS` (Michele, 2026-10-18: an outage must not eat the month). A plan
    whose session existed counts even when it failed, and every plan's cost always counts."""
    return and_(PlanRecord.status == PlanStatus.FAILED.value, PlanRecord.session_id.is_(None))


async def month_usage(
    db: AsyncSession,
    *,
    now: dt.datetime,
    owner: ColumnElement[bool] | None,
    default_budget_cents: int,
) -> Usage:
    """`Usage` in `now`'s month of `owner`'s plans (a `plan_owner_filter` predicate) or
    everyone's (None): the plans created in the month except those that never started
    (`never_started`), their recorded cost, and the reservation of **every** plan still
    `running`, whatever month created it. `default_budget_cents` stands in for a running plan
    whose `budget_cents` is still NULL.

    Months follow `created_at`: a plan's whole cost belongs to the month it was created in. So a
    plan created on 31 October and still running on 1 November reserves its unspent budget in
    November's checks too (else November would start with nothing reserved), but what it then
    spends, a "Continua" included, is recorded on October; once it ends it leaves November's
    figures. A `budget_paused` plan reserves nothing: its "Continua" reserves through the row it
    turns `running` (`sessions._reserve_continue`)."""
    start, end = month_bounds(now)
    in_month = and_(PlanRecord.created_at >= start, PlanRecord.created_at < end)
    running = PlanRecord.status == PlanStatus.RUNNING.value
    unspent = func.greatest(
        func.coalesce(PlanRecord.budget_cents, default_budget_cents) - PlanRecord.cost_cents, 0
    )
    statement = select(
        func.count().filter(in_month, ~never_started()),
        func.coalesce(func.sum(PlanRecord.cost_cents).filter(in_month), 0),
        func.coalesce(func.sum(case((running, unspent), else_=0)), 0),
    ).where(or_(in_month, running))
    if owner is not None:
        statement = statement.where(owner)
    row = (await db.execute(statement)).one()
    return Usage(plans=int(row[0]), cost_cents=int(row[1]), reserved_cents=int(row[2]))


async def running_plans(db: AsyncSession) -> int:
    """How many plans are `running` right now, all users."""
    total = await db.scalar(
        select(func.count()).where(PlanRecord.status == PlanStatus.RUNNING.value)
    )
    return int(total or 0)


def user_quota(usage: Usage, *, settings: Settings, now: dt.datetime) -> UserQuota:
    """`usage` against the per-user limits, with when the month turns."""
    _, end = month_bounds(now)
    return UserQuota(
        plans_used=usage.plans,
        plans_limit=settings.user_monthly_plans,
        cents_used=usage.cents,
        cents_limit=settings.user_monthly_cents,
        resets_at=end,
        next_plan_cents=settings.session_budget_cents,
        continue_cents=CONTINUE_INCREMENT_CENTS,
    )
