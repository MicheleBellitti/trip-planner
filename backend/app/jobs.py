"""Scheduled work: the nightly cleanup and the hourly stuck-plan check.

Spec: "Ambiente locale" -> "Lavori pianificati" ("Un cron di Railway ogni notte alle 3: cancella
piani, eventi e sessioni Managed Agents piu' vecchi di 90 giorni e i tassi di cambio piu' vecchi
di un anno"), "Log e resilienza" ("Un controllo ogni ora sui piani running da piu' di 45 minuti
li segnala nei log e li interrompe"), "Sicurezza e privacy" (sessions are outside Zero Data
Retention: archived at ready, deleted after 90 days) and decision 2 of "Decisioni aperte".

Where each job runs (DECISION):

- Nightly cleanup: a Railway cron service running `python -m app.jobs cleanup` at 03:00
  Europe/Rome (Railway cron is UTC: `0 1 * * *` in summer time, `0 2 * * *` in winter; or run
  it hourly and let `cleanup` no-op outside 03:00-03:59 Rome). It needs only the database and
  the API key, not the web process.
- Stuck-plan check: inside the web process, every hour (`start_stuck_plan_checker`, started by
  main.py's lifespan after `sessions.start_planner`), because interrupting a plan goes through
  its live consumer, which only exists there. `python -m app.jobs stuck` runs one check by
  hand.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import logging
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import structlog
from pydantic import ValidationError
from sqlalchemy import delete, select

from app import clock, sessions
from app.config import LogLevel, Settings, add_plan_log_keys, get_settings
from app.consumer import EventSink, StatusChange, record_session_cost, set_plan_status
from app.db import (
    FxRateRecord,
    PlanRecord,
    PlanStatus,
    create_engine,
    create_session_factory,
)
from app.ma_client import (
    ManagedAgentsError,
    SdkManagedAgentsClient,
    SessionBusyError,
    SessionNotFoundError,
    archive_when_idle,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.ma_client import ManagedAgentsClient
    from app.sessions import PlannerServices

PLAN_RETENTION = dt.timedelta(days=90)
FX_RETENTION = dt.timedelta(days=365)
STUCK_AFTER = dt.timedelta(minutes=45)
STUCK_CHECK_INTERVAL_SECONDS = 3600.0
CLEANUP_BATCH_SIZE = 100

STUCK_INTERRUPT_GRACE_SECONDS = 60.0
"""After `user.interrupt`, how long the stuck check waits for the consumer to close the plan
(`end_turn` -> `interrupted`) before setting `interrupted` itself."""
STUCK_POLL_SECONDS = 2.0

REASON_STUCK = "Interrotto automaticamente: lavorava da più di 45 minuti."
"""`plans.failure_reason` of a plan stopped by the stuck check (Italian, user-facing)."""
TITLE_STUCK = "Piano interrotto automaticamente"
TITLE_STUCK_REQUESTED = "Interruzione automatica: lavorava da più di 45 minuti"

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class CleanupReport:
    """What one cleanup run did (logged as one structured line)."""

    plans_deleted: int = 0
    """Plan rows deleted; their events go with them (ON DELETE CASCADE)."""
    sessions_deleted: int = 0
    sessions_already_gone: int = 0
    orphan_sessions_deleted: int = 0
    """Sessions older than the retention with no plan row (step 2 of `nightly_cleanup`)."""
    fx_rates_deleted: int = 0
    failures: list[str] = field(default_factory=list[str])
    """Plan ids whose session could not be deleted (kept for the next night), with the reason."""


async def nightly_cleanup(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    client: ManagedAgentsClient | None,
    now: dt.datetime,
) -> CleanupReport:
    """Delete what is older than the retention, in batches of `CLEANUP_BATCH_SIZE`:

    1. Plans with `created_at < now - PLAN_RETENTION`: for each, first delete its Managed
       Agents session (`client.delete_session`; `SessionNotFoundError` counts as already gone;
       a `running` session is interrupted and skipped until next night), then the plan row in
       its own transaction (events cascade). A plan whose session deletion failed is kept, so
       nothing is orphaned on the platform. Without a client (no key) sessions are skipped and
       their plans kept, logged as an error.
    2. Orphan sweep: `client.list_sessions(created_before=now - PLAN_RETENTION)`; every session
       whose `metadata["app"] == "trip-planner"` and whose `metadata["plan_id"]` has no plan row
       (a crash between `sessions.create` and the commit of `plans.session_id`, or a row
       already deleted) is deleted the same way. Sessions without our metadata are never
       touched. This keeps the spec's promise that no transcript outlives 90 days even when the
       database lost track of it.
    3. `fx_rates` with `date < (now - FX_RETENTION).date()`.

    Idempotent; never raises for a single plan's failure (reported in `failures`).
    """
    if now.tzinfo is None:
        msg = "nightly_cleanup needs a timezone-aware `now`"
        raise ValueError(msg)
    report = CleanupReport()
    cutoff = now - PLAN_RETENTION

    # 1. Old plans: the session first, then the row.
    kept: set[uuid.UUID] = set()
    while True:
        query = (
            select(PlanRecord.id, PlanRecord.session_id)
            .where(PlanRecord.created_at < cutoff)
            .order_by(PlanRecord.created_at, PlanRecord.id)
            .limit(CLEANUP_BATCH_SIZE)
        )
        if kept:
            query = query.where(PlanRecord.id.not_in(kept))
        async with session_factory() as db:
            batch = (await db.execute(query)).all()
        if not batch:
            break
        for plan_id, session_id in batch:
            with structlog.contextvars.bound_contextvars(
                plan_id=str(plan_id), session_id=session_id
            ):
                if await _delete_old_plan(session_factory, client, plan_id, session_id, report):
                    report.plans_deleted += 1
                else:
                    kept.add(plan_id)

    # 2. Orphan sessions: ours, older than the retention, without a plan row.
    if client is not None:
        await _sweep_orphan_sessions(session_factory, client, cutoff, report)

    # 3. Exchange rates older than a year.
    fx_cutoff = (now.astimezone(clock.HOME_TIMEZONE) - FX_RETENTION).date()
    async with session_factory() as db:
        result = await db.execute(delete(FxRateRecord).where(FxRateRecord.date < fx_cutoff))
        await db.commit()
    report.fx_rates_deleted = max(getattr(result, "rowcount", 0) or 0, 0)
    return report


async def _delete_old_plan(
    session_factory: async_sessionmaker[AsyncSession],
    client: ManagedAgentsClient | None,
    plan_id: uuid.UUID,
    session_id: str | None,
    report: CleanupReport,
) -> bool:
    """Step 1 of `nightly_cleanup` for one plan: its session, then its row. True when the row
    was deleted, False when it is kept for the next night (reason in `report.failures`)."""
    if session_id is not None:
        if client is None:
            report.failures.append(
                f"{plan_id}: session {session_id} not deleted (no ANTHROPIC_API_KEY)"
            )
            log.error("cleanup_without_client", plan_id=str(plan_id), session_id=session_id)
            return False
        if not await _delete_session(client, session_id, report, label=str(plan_id)):
            return False
    async with session_factory() as db:
        await db.execute(delete(PlanRecord).where(PlanRecord.id == plan_id))
        await db.commit()
    return True


async def _delete_session(
    client: ManagedAgentsClient,
    session_id: str,
    report: CleanupReport,
    *,
    label: str,
    orphan: bool = False,
) -> bool:
    """Delete one session. True when it is gone (deleted now or before), False when it must be
    retried next night (reason appended to `report.failures`)."""
    bound = log.bind(session_id=session_id, subject=label)
    try:
        await client.delete_session(session_id)
    except SessionNotFoundError:
        report.sessions_already_gone += 1
        return True
    except SessionBusyError:
        try:
            await client.send_interrupt(session_id)
        except ManagedAgentsError as exc:
            bound.warning("cleanup_interrupt_failed", error_type=exc.error_type)
        report.failures.append(
            f"{label}: session {session_id} was running; interrupted, deleted next night"
        )
        bound.warning("cleanup_session_busy")
        return False
    except ManagedAgentsError as exc:
        report.failures.append(
            f"{label}: session {session_id} not deleted ({type(exc).__name__}, "
            f"status {exc.status_code})"
        )
        bound.error("cleanup_session_delete_failed", status_code=exc.status_code)
        return False
    if orphan:
        report.orphan_sessions_deleted += 1
    else:
        report.sessions_deleted += 1
    return True


async def _sweep_orphan_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    client: ManagedAgentsClient,
    cutoff: dt.datetime,
    report: CleanupReport,
) -> None:
    try:
        listed = await client.list_sessions(created_before=cutoff, include_archived=True)
    except ManagedAgentsError as exc:
        report.failures.append(f"orphan sweep: list_sessions failed ({type(exc).__name__})")
        log.error("cleanup_list_sessions_failed", status_code=exc.status_code)
        return
    ours = [info for info in listed if info.metadata.get("app") == sessions.APP_METADATA]
    plan_ids: dict[str, uuid.UUID | None] = {}
    for info in ours:
        try:
            plan_ids[info.id] = uuid.UUID(info.metadata.get("plan_id", ""))
        except ValueError:
            plan_ids[info.id] = None
    candidates = {plan_id for plan_id in plan_ids.values() if plan_id is not None}
    existing: set[uuid.UUID] = set()
    if candidates:
        async with session_factory() as db:
            existing = set(
                await db.scalars(select(PlanRecord.id).where(PlanRecord.id.in_(candidates)))
            )
    for info in ours:
        plan_id = plan_ids[info.id]
        if plan_id is not None and plan_id in existing:
            continue
        label = f"orphan {plan_id}" if plan_id is not None else "orphan (no plan_id)"
        with structlog.contextvars.bound_contextvars(
            plan_id=str(plan_id) if plan_id is not None else None, session_id=info.id
        ):
            if await _delete_session(client, info.id, report, label=label, orphan=True):
                log.info("cleanup_orphan_session", session_id=info.id, plan_id=str(plan_id))


async def check_stuck_plans(services: PlannerServices, *, now: dt.datetime) -> list[uuid.UUID]:
    """Find plans `running` with `plans.running_since < now - STUCK_AFTER`, log each one
    (plan_id, session_id, age), and stop it: the `sessions.interrupt_plan` path without a user
    (`plans.interrupt_requested_at` stored with its status event, live consumer told,
    `user.interrupt` sent); when the session doesn't reach idle the plan is set `interrupted`
    with `REASON_STUCK` (`set_plan_status(..., event_key=f"stuck:<running_since ISO>")`, unique
    per stuck episode), its consumer stopped (cancelled: it reads no final cost), the session
    archived, and the session's final list cost recorded (`consumer.record_session_cost`, so
    the monthly limit counts a plan that may have spent close to its whole budget). Returns
    the ids handled.

    `running_since` is the last time the plan entered `running` (the insert, then every
    "Continua", written by `EventSink` with the status change), so a plan resumed with
    "Continua" gets a fresh 45 minutes.

    Without a Managed Agents client nothing runs or spends, and the check does nothing (it does
    not even query the database, so a planner without a key starts without Postgres)."""
    if services.client is None:
        return []
    cutoff = now - STUCK_AFTER
    async with services.session_factory() as db:
        plans = list(
            await db.scalars(
                select(PlanRecord)
                .where(
                    PlanRecord.status == PlanStatus.RUNNING.value,
                    PlanRecord.running_since < cutoff,
                )
                .order_by(PlanRecord.running_since)
            )
        )
    handled: list[uuid.UUID] = []
    for plan in plans:
        with structlog.contextvars.bound_contextvars(
            plan_id=str(plan.id), session_id=plan.session_id
        ):
            bound = log.bind(plan_id=str(plan.id), session_id=plan.session_id)
            age = now - plan.running_since
            bound.warning(
                "plan_stuck",
                age_minutes=round(age.total_seconds() / 60, 1),
                running_since=plan.running_since.isoformat(),
            )
            try:
                await _stop_stuck_plan(services, plan)
            except Exception:
                bound.exception("stuck_plan_stop_failed")
                continue
            handled.append(plan.id)
    return handled


async def _stop_stuck_plan(services: PlannerServices, plan: PlanRecord) -> None:
    """Stop one stuck plan (`check_stuck_plans`), with its plan and session bound in the
    logging context for every line written on its behalf."""
    with structlog.contextvars.bound_contextvars(plan_id=str(plan.id), session_id=plan.session_id):
        await _stop_stuck_plan_bound(services, plan)


async def _stop_stuck_plan_bound(services: PlannerServices, plan: PlanRecord) -> None:
    bound = log.bind(plan_id=str(plan.id), session_id=plan.session_id)
    stuck_key = f"stuck:{plan.running_since.isoformat()}"
    try:
        status = await sessions.request_interrupt(
            services,
            plan,
            reason=REASON_STUCK,
            interrupted_key=stuck_key,
            request_title=TITLE_STUCK_REQUESTED,
        )
    except ManagedAgentsError as exc:
        # The request is stored; the session may not have heard it. Fall through to the wait.
        bound.warning("stuck_interrupt_send_failed", error_type=exc.error_type)
        status = PlanStatus.RUNNING
    if status is not PlanStatus.RUNNING:
        bound.info("stuck_plan_stopped", status=status.value)
        return

    loop = asyncio.get_running_loop()
    deadline = loop.time() + STUCK_INTERRUPT_GRACE_SECONDS
    while loop.time() < deadline:
        await asyncio.sleep(min(STUCK_POLL_SECONDS, max(deadline - loop.time(), 0.0)))
        async with services.session_factory() as db:
            current = await db.scalar(select(PlanRecord.status).where(PlanRecord.id == plan.id))
        if current != PlanStatus.RUNNING.value:
            bound.info("stuck_plan_stopped", status=current)
            return

    result = await set_plan_status(
        services.session_factory,
        services.hub,
        plan.id,
        StatusChange(PlanStatus.INTERRUPTED, reason=REASON_STUCK),
        title=TITLE_STUCK,
        event_key=stuck_key,
    )
    if services.registry is not None:
        await services.registry.stop(plan.id)
    if services.client is not None and plan.session_id is not None:
        if result.status_applied:
            try:
                await archive_when_idle(services.client, plan.session_id)
            except Exception as exc:
                bound.warning("session_archive_failed", error=type(exc).__name__)
        # The cancelled consumer never read the final cost (decision 11b): read it here.
        sink = EventSink(plan.id, session_factory=services.session_factory, hub=services.hub)
        await record_session_cost(
            services.client, sink, plan.session_id, known_cents=plan.cost_cents
        )
    bound.warning("stuck_plan_forced_interrupted", applied=result.status_applied)


def start_stuck_plan_checker(
    services: PlannerServices, *, interval_seconds: float = STUCK_CHECK_INTERVAL_SECONDS
) -> asyncio.Task[None]:
    """Start the hourly loop (`check_stuck_plans` then sleep), named `stuck-plan-checker`.
    Errors of one round are logged and never stop the loop; cancel the task to stop it."""

    async def run() -> None:
        while True:
            try:
                await check_stuck_plans(services, now=clock.now())
            except Exception:
                log.exception("stuck_plan_check_failed")
            await asyncio.sleep(interval_seconds)

    return asyncio.create_task(run(), name="stuck-plan-checker")


# --- entry point ----------------------------------------------------------------------------------


def _configure_logging(level: LogLevel) -> None:
    """One JSON object per line on stdout (what Railway's log view parses), with the plan keys
    on every line (`config.add_plan_log_keys`, as in main.configure_logging)."""
    logging.basicConfig(format="%(message)s", level=level, stream=sys.stdout)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_plan_log_keys,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


async def _run_cleanup(settings: Settings) -> int:
    engine = create_engine(settings)
    client: ManagedAgentsClient | None = None
    try:
        if settings.anthropic_credentials_available:
            client = SdkManagedAgentsClient.from_settings(settings)
        else:
            log.error("cleanup_without_client", reason="ANTHROPIC_API_KEY is not set")
        report = await nightly_cleanup(
            session_factory=create_session_factory(engine), client=client, now=clock.now()
        )
    except Exception:
        log.exception("nightly_cleanup_failed")
        return 1
    finally:
        if client is not None:
            await client.aclose()
        await engine.dispose()
    log.info("nightly_cleanup", **dataclasses.asdict(report))
    return 1 if report.failures else 0


async def _run_stuck_check(settings: Settings) -> int:
    engine = create_engine(settings)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as http:
            services = await sessions.start_planner(
                settings,
                session_factory=create_session_factory(engine),
                http=http,
                resume=False,
            )
            try:
                handled = await check_stuck_plans(services, now=clock.now())
            finally:
                await sessions.stop_planner(services)
    except Exception:
        log.exception("stuck_plan_check_failed")
        return 1
    finally:
        await engine.dispose()
    log.info("stuck_plan_check", plans=[str(plan_id) for plan_id in handled])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m app.jobs cleanup` (nightly, Railway cron) or `python -m app.jobs stuck` (one
    check by hand). Builds its own engine and client from `get_settings()`, runs, prints the
    report as one JSON log line, and returns 0, or 1 when anything failed.

    `stuck` from a separate process has no live consumer to tell, so `request_interrupt` sends
    `user.interrupt` and sets a stuck plan `interrupted` at once (`REASON_STUCK`); the web
    process's consumer then finds the plan no longer `running` and stops following it."""
    parser = argparse.ArgumentParser(prog="python -m app.jobs", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("cleanup", help="nightly retention cleanup (Railway cron)")
    commands.add_parser("stuck", help="one stuck-plan check")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except ValidationError as exc:
        print(f"invalid configuration: {exc}", file=sys.stderr)
        return 1
    _configure_logging(settings.log_level)
    if args.command == "cleanup":
        return asyncio.run(_run_cleanup(settings))
    return asyncio.run(_run_stuck_check(settings))


if __name__ == "__main__":
    raise SystemExit(main())
