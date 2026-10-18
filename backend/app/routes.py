"""HTTP and SSE endpoints of the planner API (everything except GET /health, in main.py).

Spec: "Backend FastAPI" -> "Endpoint" table, "SSE verso il browser", "Autenticazione e domini"
(CORS, Origin check), "Integrazione con TripTracker" (GET /plans/{id}/trip for /import) and
"Interfaccia e design" (`budget_paused`: "Continua con 2 $ in piu'").

| Method and path              | Auth                     | What                                   |
|------------------------------|--------------------------|----------------------------------------|
| POST /plans                  | user + Origin            | validate PlanRequest, start the plan   |
| POST /plans?demo_scenario=   | user + Origin            | DEMO_MODE only: replay a scenario      |
| GET /me                      | user                     | who is signed in, and the admin flag   |
| GET /plans                   | user                     | the user's last 20 plans               |
| GET /plans/{id}              | user                     | status, plan, link checks, import URL  |
| GET /plans/{id}/events       | user                     | SSE: replay after Last-Event-ID, live  |
| GET /plans/{id}/trip         | user (+ CORS TripTracker)| the stored Trip, for /import           |
| GET /plans/{id}/cover        | user                     | the destination's Wikimedia photo      |
| POST /plans/{id}/interrupt   | user + Origin            | send user.interrupt                    |
| POST /plans/{id}/continue    | user + Origin            | raise the budget by $2 and resume      |
| POST /evals/runs             | Bearer EVALS_INGEST_TOKEN| CI uploads an eval run (no Origin/CORS)|
| GET /evals/runs              | admin                    | the eval history, newest first         |
| GET /evals/runs/{id}         | admin                    | one run with its results and comparison|

"user" is `auth.current_user` (the plans it lists and opens are the user's own,
`sessions.plan_owner_filter`); "admin" adds `auth.require_admin` (ADMIN_EMAILS; 403
`admin_only` for anyone else).

Errors: `HTTPException(detail=ErrorBody)` -> `{"detail": {"code", "message", "data"}}` with an
Italian `message`; auth errors use the same envelope (`auth.AuthErrorCode`). Request-body
validation errors keep FastAPI's 422 shape (`detail[].type` is a `RequestErrorCode` or a
pydantic type, `loc` starts with "body"), which the web form maps to its fields. A body over
`MAX_REQUEST_BODY_BYTES` is 413 `request_too_large` before routing (`RequestBodyLimitMiddleware`).

SSE wire format (`plan_events`): every UIEvent is a default `message` event with `id: <seq>`
and `data: <UIEvent JSON>`; a `: ping` comment every `PING_SECONDS`; when the plan reaches a
terminal status (ready, failed, blocked, interrupted) one `event: end` with `data:
{"status": ...}` and the stream closes, so EventSource doesn't reconnect forever. On
reconnection the browser sends `Last-Event-ID`; the `after` query parameter does the same for
a first connection (header wins). Replay comes from Postgres, then the live hub (see hub.py).

CORS (`install_routes`): `FRONTEND_ORIGIN` only, with credentials, no wildcard; the single
exception is GET (and its preflight) on /plans/{id}/trip, which also allows
`TRIPTRACKER_ORIGIN`, read-only.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import hmac
import re
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, cast

import structlog
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import EventSourceResponse, ServerSentEvent
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import clock, consumer, evals_store, quota, ratelimit, sessions
from app.auth import (
    AuthErrorCode,
    CurrentUser,
    CurrentUserDep,
    RequireAdmin,
    RequireOrigin,
    auth_error,
    auth_messages,
    user_is_admin,
)
from app.config import AgentProfile, Settings
from app.covers import Cover, CoverErrorCode, CoverResolver
from app.db import DbSession, PlanRecord, PlanStatus
from app.events import UIEvent, one_line
from app.hub import PlanEnded, SubscriptionLaggedError
from app.links import LinkVerdict, check_link
from app.ma_client import ManagedAgentsError
from app.request import PlanRequest
from app.sessions import PlannerServices
from app.triptracker_schema import TripSchemaUnavailableError

PLAN_LIST_LIMIT = 20
PING_SECONDS = 15
END_EVENT = "end"
TERMINAL_STATUSES: frozenset[PlanStatus] = frozenset(
    {PlanStatus.READY, PlanStatus.FAILED, PlanStatus.BLOCKED, PlanStatus.INTERRUPTED}
)
IMPORT_PATH = "/import"
"""TripTracker's import page: `{TRIPTRACKER_ORIGIN}/import?plan=<id>`."""

REPLAY_PAGE_SIZE = 500
"""Events read from Postgres per query during an SSE replay (each page in its own session)."""
SEND_TIMEOUT_SECONDS = 30.0
"""An SSE write (event or ping) that blocks longer than this closes the stream: the client is
gone or stuck, and EventSource reconnects with Last-Event-ID if it is still there."""
END_SETTLE_SECONDS = 10.0
"""Before `event: end`, how long the SSE stream waits for the plan's live consumer to store the
events its streams had already delivered (`consumer.PlanConsumer.wait_settled`)."""
MAX_SEQ = 2**31 - 1
"""`events.seq` is a Postgres `integer`: a larger resume point is not a seq."""

MAX_REQUEST_BODY_BYTES = 64 * 1024
"""Largest request body the API accepts (`RequestBodyLimitMiddleware`). The biggest valid
PlanRequest is about 2,900 characters of capped fields, under 35 KB even with every character
JSON-escaped; no other route takes a body, except POST /evals/runs (`EVALS_INGEST_PATH`)."""

EVALS_INGEST_PATH = "/evals/runs"
"""The machine endpoint CI uploads eval results to: its body cap is
`evals_store.MAX_INGEST_BYTES` (5 MB), not `MAX_REQUEST_BODY_BYTES`."""

TRIP_PATH = re.compile(r"/plans/[^/]+/trip/?")
"""The one path whose GET (and preflight) also admits TRIPTRACKER_ORIGIN in CORS."""

log = structlog.get_logger(__name__)


# --- errors -------------------------------------------------------------------------------------


class PlanErrorCode(StrEnum):
    """Stable `detail.code` values of plan endpoints (auth codes live in auth.AuthErrorCode)."""

    PLAN_NOT_FOUND = "plan_not_found"  # 404: missing or another user's
    PLAN_NOT_READY = "plan_not_ready"  # 409: GET /trip before `ready`
    INVALID_PLAN_STATE = "invalid_plan_state"  # 409: interrupt/continue in the wrong status
    MONTHLY_LIMIT_REACHED = "monthly_limit_reached"  # 429: data {spent_cents, limit_cents}
    QUOTA_PLANS_REACHED = "quota_plans_reached"  # 429: data = quota.UserQuota.as_data()
    QUOTA_CENTS_REACHED = "quota_cents_reached"  # 429: data = quota.UserQuota.as_data()
    TOO_MANY_REQUESTS = "too_many_requests"  # 429: data {retry_after_seconds}; Retry-After
    PLANNER_BUSY = "planner_busy"  # 503: data {running, limit, retry_after_seconds}; Retry-After
    CONTINUE_LIMIT_REACHED = "continue_limit_reached"  # 409: data {continues, limit}
    PLANNER_UNAVAILABLE = "planner_unavailable"  # 503: no key, lockfile or trip.json
    AGENTS_UNAVAILABLE = "agents_unavailable"  # 502: the Managed Agents API failed
    REQUEST_TOO_LARGE = "request_too_large"  # 413: body over MAX_REQUEST_BODY_BYTES
    DEMO_UNAVAILABLE = "demo_unavailable"  # 404: ?demo_scenario= without DEMO_MODE
    EVAL_RUN_NOT_FOUND = "eval_run_not_found"  # 404: GET /evals/runs/{id}
    EVALS_INGEST_DISABLED = "evals_ingest_disabled"  # 404: POST /evals/runs without a token set
    INVALID_INGEST_TOKEN = "invalid_ingest_token"  # 401: wrong or missing bearer
    INVALID_EVAL_RESULTS = "invalid_eval_results"  # 422: data {errors: [{field, reason}]}


PLAN_ERROR_STATUS: dict[PlanErrorCode, int] = {
    PlanErrorCode.PLAN_NOT_FOUND: 404,
    PlanErrorCode.PLAN_NOT_READY: 409,
    PlanErrorCode.INVALID_PLAN_STATE: 409,
    PlanErrorCode.MONTHLY_LIMIT_REACHED: 429,
    PlanErrorCode.QUOTA_PLANS_REACHED: 429,
    PlanErrorCode.QUOTA_CENTS_REACHED: 429,
    PlanErrorCode.TOO_MANY_REQUESTS: 429,
    PlanErrorCode.PLANNER_BUSY: 503,
    PlanErrorCode.CONTINUE_LIMIT_REACHED: 409,
    PlanErrorCode.PLANNER_UNAVAILABLE: 503,
    PlanErrorCode.AGENTS_UNAVAILABLE: 502,
    PlanErrorCode.REQUEST_TOO_LARGE: 413,
    PlanErrorCode.DEMO_UNAVAILABLE: 404,
    PlanErrorCode.EVAL_RUN_NOT_FOUND: 404,
    PlanErrorCode.EVALS_INGEST_DISABLED: 404,
    PlanErrorCode.INVALID_INGEST_TOKEN: 401,
    PlanErrorCode.INVALID_EVAL_RESULTS: 422,
}

PLAN_ERROR_MESSAGES: dict[PlanErrorCode, str] = {
    PlanErrorCode.PLAN_NOT_FOUND: "Questo piano non c'è.",
    PlanErrorCode.PLAN_NOT_READY: "Il piano è ancora in preparazione.",
    PlanErrorCode.INVALID_PLAN_STATE: "Il piano non è in uno stato che lo permette.",
    PlanErrorCode.MONTHLY_LIMIT_REACHED: (
        "Questo mese il planner ha già impegnato {spent} su {limit}: il prossimo piano si potrà "
        "creare il mese prossimo."
    ),
    PlanErrorCode.QUOTA_PLANS_REACHED: (
        "Questo mese hai già creato tutti i piani previsti ({plans_used} su {plans_limit}): il "
        "prossimo si potrà creare il mese prossimo."
    ),
    PlanErrorCode.QUOTA_CENTS_REACHED: (
        "Questo mese i tuoi piani hanno già impegnato {cents_used} su {cents_limit}: il "
        "prossimo si potrà creare il mese prossimo."
    ),
    PlanErrorCode.TOO_MANY_REQUESTS: (
        "Troppe richieste in poco tempo: riprova tra {retry_after_seconds} s."
    ),
    PlanErrorCode.PLANNER_BUSY: (
        "Il planner è al completo in questo momento: riprova tra qualche minuto. Nessun costo "
        "è stato addebitato."
    ),
    PlanErrorCode.CONTINUE_LIMIT_REACHED: (
        "Questo piano ha già avuto tutti gli aumenti di budget previsti ({continues} su "
        "{limit}): il budget non si può aumentare ancora. Puoi interromperlo, o creare un "
        "nuovo piano."
    ),
    PlanErrorCode.PLANNER_UNAVAILABLE: (
        "Il planner non è pronto in questo momento: nessun costo è stato addebitato. Riprova "
        "più tardi."
    ),
    PlanErrorCode.AGENTS_UNAVAILABLE: (
        "Gli agenti non rispondono: il piano non è partito. Riprova tra qualche minuto."
    ),
    PlanErrorCode.REQUEST_TOO_LARGE: "La richiesta è troppo grande: accorcia i testi e riprova.",
    PlanErrorCode.DEMO_UNAVAILABLE: "La modalità demo non è attiva su questo server.",
    PlanErrorCode.EVAL_RUN_NOT_FOUND: "Questa esecuzione delle eval non c'è.",
    PlanErrorCode.EVALS_INGEST_DISABLED: (
        "Il caricamento dei risultati delle eval non è attivo su questo server."
    ),
    PlanErrorCode.INVALID_INGEST_TOKEN: "Il token di caricamento non è valido.",
    PlanErrorCode.INVALID_EVAL_RESULTS: "I risultati delle eval non sono nel formato atteso.",
}
"""Italian user-facing messages; `{spent}`/`{limit}` are formatted with `format_usd`."""


class ErrorBody(BaseModel):
    """The API error envelope, under `detail`."""

    code: str = Field(description="Stable machine code (PlanErrorCode or AuthErrorCode).")
    message: str = Field(description="What happened and what to do, in Italian.")
    data: dict[str, Any] | None = Field(default=None, description="Code-specific figures.")


class ErrorResponse(BaseModel):
    detail: ErrorBody


def plan_error(
    code: PlanErrorCode,
    *,
    data: dict[str, Any] | None = None,
    retry_after_seconds: int | None = None,
) -> HTTPException:
    """The `HTTPException` for `code` (status from the PlanErrorCode comments), with
    `PLAN_ERROR_MESSAGES[code]` formatted from `data`: every integer whose key ends with `_cents`
    or starts with `cents_` fills `{<key>}` as `format_usd(value)` (a `<name>_cents` key fills
    `{<name>}` too), every other integer fills `{<key>}` as is. `retry_after_seconds` becomes
    the `Retry-After` header and, when absent from `data`, its `retry_after_seconds` key."""
    if retry_after_seconds is not None:
        data = {"retry_after_seconds": retry_after_seconds, **(data or {})}
    message = PLAN_ERROR_MESSAGES[code]
    if data and "{" in message:
        figures: dict[str, str] = {}
        for key, value in data.items():
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            if key.endswith("_cents"):
                figures[key] = figures[key.removesuffix("_cents")] = format_usd(value)
            elif key.startswith("cents_"):
                figures[key] = format_usd(value)
            else:
                figures[key] = str(value)
        try:
            message = message.format(**figures)
        except (KeyError, IndexError, ValueError):
            log.error("plan_error_format_failed", code=code.value)
    body = ErrorBody(code=code.value, message=message, data=data)
    headers = {"Retry-After": str(retry_after_seconds)} if retry_after_seconds is not None else None
    return HTTPException(
        status_code=PLAN_ERROR_STATUS[code], detail=body.model_dump(mode="json"), headers=headers
    )


def format_usd(cents: int) -> str:
    """US cents as Italian copy: 4820 -> "48,20 $" (thousands with a dot: "1.234,56 $")."""
    sign = "-" if cents < 0 else ""
    units, rest = divmod(abs(cents), 100)
    return f"{sign}{units:,}".replace(",", ".") + f",{rest:02d} $"


# --- models -------------------------------------------------------------------------------------


class CreatePlanResponse(BaseModel):
    id: uuid.UUID


class QuotaView(BaseModel):
    """One user's month against their quota (quota.UserQuota): what the web app shows before
    the limit is hit, and what a 429 `quota_*_reached` carries as `data`."""

    plans_used: int = Field(description="Plans created this month (Europe/Rome), any status.")
    plans_limit: int = Field(description="USER_MONTHLY_PLANS.")
    cents_used: int = Field(
        description=(
            "US cents: the month's recorded cost plus the unspent budget of the plans still "
            "running."
        )
    )
    cents_limit: int = Field(description="USER_MONTHLY_CENTS.")
    resets_at: AwareDatetime = Field(description="The first instant of the next month.")
    next_plan_cents: int = Field(
        description=(
            "US cents a new plan reserves (the session budget): a start is refused when "
            "cents_used + next_plan_cents > cents_limit."
        )
    )
    continue_cents: int = Field(
        description=(
            "US cents a 'Continua' adds: it is refused when cents_used + continue_cents > "
            "cents_limit."
        )
    )

    @classmethod
    def from_quota(cls, allowance: quota.UserQuota) -> QuotaView:
        return cls(
            plans_used=allowance.plans_used,
            plans_limit=allowance.plans_limit,
            cents_used=allowance.cents_used,
            cents_limit=allowance.cents_limit,
            resets_at=allowance.resets_at,
            next_plan_cents=allowance.next_plan_cents,
            continue_cents=allowance.continue_cents,
        )


class MeResponse(BaseModel):
    """Answer of GET /me: who the cookie belongs to, for the web app's header."""

    email: str = Field(description="The signed-in address, trimmed and lower-cased.")
    is_admin: bool = Field(
        description="May read the eval history (one of ADMIN_EMAILS, `Settings.admins`)."
    )
    quota: QuotaView | None = Field(
        default=None,
        description=(
            "The user's month against the per-user quota; null for the users exempt from it "
            "(admins)."
        ),
    )


class PlanSummary(BaseModel):
    """One row of the home page list."""

    id: uuid.UUID
    title: str = Field(description="The plan's title once accepted, else built from the request.")
    status: PlanStatus
    cost_cents: int = Field(description="Cumulative Managed Agents list cost, US cents.")
    created_at: AwareDatetime


class PlanListResponse(BaseModel):
    plans: list[PlanSummary] = Field(description="Newest first, at most 20.")


class LinkCheck(BaseModel):
    """Whether a booking link may be shown as a "Prenota su <label>" button."""

    allowed: bool
    provider: str | None = None
    label: str | None = None
    host: str | None = None

    @classmethod
    def from_verdict(cls, verdict: LinkVerdict) -> LinkCheck:
        return cls(
            allowed=verdict.allowed,
            provider=verdict.provider,
            label=verdict.label,
            host=verdict.host,
        )


class PlanDetail(BaseModel):
    """Everything the plan page needs besides the event stream."""

    id: uuid.UUID
    status: PlanStatus
    title: str
    agent_profile: AgentProfile
    created_at: AwareDatetime
    updated_at: AwareDatetime
    cost_cents: int = Field(description="Cumulative Managed Agents list cost, US cents.")
    budget_cents: int | None = Field(
        default=None,
        description=(
            "The session's current budget cap in US cents (plans.budget_cents), the end of the "
            "cost bar; raised by 'Continua'. None until the session exists."
        ),
    )
    failure_reason: str | None = Field(default=None, description="Italian, for failed/blocked.")
    submit_attempts: int
    continues: int = Field(
        default=0, description="How many times 'Continua' raised the budget (plans.continues)."
    )
    continues_limit: int = Field(
        default=0,
        description=(
            "MAX_CONTINUES_PER_PLAN: at `continues` equal to it the web app offers no "
            "'Continua' and says why."
        ),
    )
    request: dict[str, Any] = Field(description="The PlanRequest as submitted.")
    plan: dict[str, Any] | None = Field(
        default=None, description="The accepted Plan (schema/plan.json), once submitted."
    )
    booking_links: list[LinkCheck | None] = Field(
        default_factory=list[LinkCheck | None],
        description="Aligned with plan.bookings: the check of each link, None without link.",
    )
    alternative_links: list[LinkCheck | None] = Field(
        default_factory=list[LinkCheck | None],
        description="Aligned with plan.alternatives.",
    )
    import_url: str | None = Field(
        default=None, description="TripTracker's /import?plan=<id>, only when ready."
    )


class StatusResponse(BaseModel):
    """Answer of POST /plans/{id}/interrupt."""

    id: uuid.UUID
    status: PlanStatus = Field(
        description="`running` while the interrupt is on its way, `interrupted` when immediate."
    )


class ContinueResponse(BaseModel):
    """Answer of POST /plans/{id}/continue."""

    id: uuid.UUID
    status: PlanStatus
    budget_cents: int = Field(description="The new session budget, US cents.")


# --- dependencies and helpers -------------------------------------------------------------------


def get_planner(request: Request) -> PlannerServices:
    """`request.app.state.planner`, set by main.py's lifespan (`sessions.start_planner`); 503
    `planner_unavailable` when the lifespan did not set it."""
    planner: PlannerServices | None = getattr(request.app.state, "planner", None)
    if planner is None:
        log.error("planner_missing")
        raise plan_error(PlanErrorCode.PLANNER_UNAVAILABLE)
    return planner


def get_app_settings(request: Request) -> Settings:
    """`request.app.state.settings` (the instance the app was built with, not get_settings())."""
    return request.app.state.settings


PlannerDep = Annotated[PlannerServices, Depends(get_planner)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]

COVER_CACHE_CONTROL = "private, max-age=3600"
COVER_UNAVAILABLE_MESSAGE = "Per questa destinazione non c'è una foto."


def cover_unavailable() -> HTTPException:
    """404 `cover_unavailable` (the envelope of `plan_error`; its code lives in covers.py)."""
    body = ErrorBody(code=CoverErrorCode.COVER_UNAVAILABLE.value, message=COVER_UNAVAILABLE_MESSAGE)
    return HTTPException(status_code=404, detail=body.model_dump(mode="json"))


def cover_destination(record: PlanRecord) -> str | None:
    """The destination whose photo to show: the accepted plan's (`Plan.destination`, e.g.
    'Lisbona, Portogallo') when the plan is ready, else the request's; None for a request that
    asked the planner to suggest a destination and has no plan yet."""
    if record.status == PlanStatus.READY and record.plan is not None:
        planned = record.plan.get("destination")
        if isinstance(planned, str) and planned.strip():
            return planned.strip()
    requested = record.request.get("destination")
    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    return None


def get_cover_resolver(
    request: Request, planner: PlannerDep, settings: SettingsDep
) -> CoverResolver:
    """The process-wide `CoverResolver` (`app.state.cover_resolver`), built on first use from the
    planner's database sessions and shared HTTP client; tests may set it beforehand."""
    resolver: CoverResolver | None = getattr(request.app.state, "cover_resolver", None)
    if resolver is None:
        resolver = CoverResolver(
            session_factory=planner.session_factory,
            http=planner.http,
            user_agent=settings.wikimedia_user_agent,
        )
        request.app.state.cover_resolver = resolver
    return resolver


CoverResolverDep = Annotated[CoverResolver, Depends(get_cover_resolver)]

_MONTHS = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)  # fmt: skip
_MONTHS_SHORT = (
    "gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic",
)  # fmt: skip
_MONTH_PATTERN = re.compile(r"([0-9]{4})-([0-9]{2})")
UNKNOWN_DESTINATION_TITLE = "Destinazione da scegliere"
UNTITLED_PLAN = "Piano senza titolo"


def _as_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _day_month(day: dt.date) -> str:
    return f"{day.day} {_MONTHS_SHORT[day.month - 1]}"


def format_date_range(start: dt.date, end: dt.date) -> str:
    """Italian copy for a trip's dates: "14 nov", "14–18 nov", "28 nov – 2 dic",
    "30 dic 2026 – 2 gen 2027"."""
    if start == end:
        return _day_month(start)
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{_day_month(end)}"
    if start.year == end.year:
        return f"{_day_month(start)} – {_day_month(end)}"
    return f"{_day_month(start)} {start.year} – {_day_month(end)} {end.year}"


def _request_dates(dates: Any) -> str | None:
    if not isinstance(dates, Mapping):
        return None
    window = cast(Mapping[str, Any], dates)
    start, end = _as_date(window.get("exact_start")), _as_date(window.get("exact_end"))
    if start is not None and end is not None:
        return format_date_range(start, end)
    month = window.get("month")
    match = _MONTH_PATTERN.fullmatch(month) if isinstance(month, str) else None
    if match is not None and 1 <= int(match[2]) <= 12:
        return f"{_MONTHS[int(match[2]) - 1]} {match[1]}"
    return None


def _title_from(plan_title_value: Any, request: Any) -> str:
    """The accepted plan's title when there is one, else "<destination>, <dates>" from the
    stored request (read defensively: an old or odd row never breaks the list)."""
    if isinstance(plan_title_value, str) and plan_title_value.strip():
        return one_line(plan_title_value)
    fields = cast(Mapping[str, Any], request) if isinstance(request, Mapping) else {}
    destination = fields.get("destination")
    if fields.get("suggest_destination") or not isinstance(destination, str):
        destination = UNKNOWN_DESTINATION_TITLE
    destination = destination.strip() or UNKNOWN_DESTINATION_TITLE
    dates = _request_dates(fields.get("dates"))
    title = f"{destination}, {dates}" if dates else destination
    return one_line(title) or UNTITLED_PLAN


def plan_title(record: PlanRecord) -> str:
    """`plan.title` once accepted; before that an Italian title from the request:
    "<destination>, <dates>" or "Destinazione da scegliere, <dates>" (e.g. "Lisbona, 14–18
    nov", "Destinazione da scegliere, novembre 2026")."""
    plan_value = record.plan.get("title") if record.plan else None
    return _title_from(plan_value, record.request)


def import_url(record: PlanRecord, *, settings: Settings) -> str | None:
    """`{TRIPTRACKER_ORIGIN}/import?plan=<id>` for a ready plan with a stored Trip, else None."""
    if record.status != PlanStatus.READY or record.trip is None:
        return None
    return f"{settings.triptracker_origin}{IMPORT_PATH}?plan={record.id}"


def _link_checks(plan: Mapping[str, Any] | None, field: str) -> list[LinkCheck | None]:
    items = plan.get(field) if plan else None
    if not isinstance(items, list):
        return []
    checks: list[LinkCheck | None] = []
    for item in cast(list[Any], items):
        link = cast(Mapping[str, Any], item).get("link") if isinstance(item, Mapping) else None
        if isinstance(link, str) and link:
            checks.append(LinkCheck.from_verdict(check_link(link)))
        else:
            checks.append(None)
    return checks


def plan_detail(record: PlanRecord, *, settings: Settings) -> PlanDetail:
    """Build the GET /plans/{id} answer: link checks from `links.check_link` for every booking
    and alternative of the stored plan, `import_url` only when `ready`. Pure."""
    return PlanDetail(
        id=record.id,
        status=PlanStatus(record.status),
        title=plan_title(record),
        agent_profile=cast(AgentProfile, record.agent_profile),
        created_at=record.created_at,
        updated_at=record.updated_at,
        cost_cents=record.cost_cents,
        budget_cents=record.budget_cents,
        failure_reason=record.failure_reason,
        submit_attempts=record.submit_attempts,
        continues=record.continues,
        continues_limit=settings.max_continues_per_plan,
        request=dict(record.request),
        plan=dict(record.plan) if record.plan is not None else None,
        booking_links=_link_checks(record.plan, "bookings"),
        alternative_links=_link_checks(record.plan, "alternatives"),
        import_url=import_url(record, settings=settings),
    )


class StreamLease:
    """One slot of `ratelimit.StreamCounter`, given back exactly once (`release` is
    idempotent): by the stream when it ends and by the response however it ends, so a slot is
    never kept by a stream that was cancelled before it started."""

    def __init__(self, release: Callable[[], None]) -> None:
        self._release: Callable[[], None] | None = release

    def release(self) -> None:
        release, self._release = self._release, None
        if release is not None:
            release()

    @property
    def released(self) -> bool:
        return self._release is None


class CountedEventSourceResponse(EventSourceResponse):
    """`EventSourceResponse` that gives its `StreamLease` back once the response is over, sent
    or not: a client gone (or a task cancelled) before the first event never starts the body's
    generator, whose own `finally` would then never run."""

    def __init__(self, content: Any, *, lease: StreamLease, **kwargs: Any) -> None:
        super().__init__(content, **kwargs)
        self.lease = lease

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.lease.release()


async def _counted(
    stream: AsyncGenerator[ServerSentEvent], *, lease: StreamLease
) -> AsyncGenerator[ServerSentEvent]:
    """`stream`, closed with this wrapper (so its hub subscription ends at once, not when the
    garbage collector finds it), with `lease` given back once it ends, however it ends (the
    client went away, the plan finished, an error)."""
    try:
        async with contextlib.aclosing(stream) as inner:
            async for item in inner:
                yield item
    finally:
        lease.release()


def sse_message(event: UIEvent) -> ServerSentEvent:
    """`ServerSentEvent(id=str(event.seq), data=event.model_dump_json())`: a default `message`
    event, so `EventSource.onmessage` gets it."""
    return ServerSentEvent(id=str(event.seq), data=event.model_dump_json())


def sse_end(status: PlanStatus) -> ServerSentEvent:
    """`ServerSentEvent(event=END_EVENT, data='{"status": "<status>"}')`."""
    return ServerSentEvent(event=END_EVENT, data=f'{{"status": "{status.value}"}}')


def ping_comment() -> ServerSentEvent:
    """`ServerSentEvent(comment="ping")`, sent every `PING_SECONDS` (`: ping`)."""
    return ServerSentEvent(comment="ping")


_SEQ_PATTERN = re.compile(r"[0-9]{1,10}")


def parse_last_event_id(header: str | None, after: int | None) -> int | None:
    """The `seq` to resume after: the `Last-Event-ID` header when it is a non-negative integer
    (at most `MAX_SEQ`), else `after`, else None (send everything). A malformed header is
    ignored, not an error."""
    if header is not None:
        text = header.strip()
        if _SEQ_PATTERN.fullmatch(text) and int(text) <= MAX_SEQ:
            return int(text)
    return after


async def _read_status(planner: PlannerServices, plan_id: uuid.UUID) -> PlanStatus | None:
    """The plan's current status from Postgres; None when the row is gone."""
    async with planner.session_factory() as db:
        value = await db.scalar(select(PlanRecord.status).where(PlanRecord.id == plan_id))
    return PlanStatus(value) if value is not None else None


async def _read_events(
    planner: PlannerServices, plan_id: uuid.UUID, after_seq: int | None
) -> AsyncIterator[list[UIEvent]]:
    """The stored events after `after_seq`, page by page; no connection is held while the
    caller sends a page."""
    while True:
        async with planner.session_factory() as db:
            page = await consumer.load_events_after(db, plan_id, after_seq, limit=REPLAY_PAGE_SIZE)
        if page:
            yield page
            after_seq = page[-1].seq
        if len(page) < REPLAY_PAGE_SIZE:
            return


async def _consumer_settled(planner: PlannerServices, plan_id: uuid.UUID) -> None:
    """Wait, at most `END_SETTLE_SECONDS`, until the plan's live consumer (if any) stores no
    more events. A consumer winding down after a terminal decision still stores what its streams
    had already delivered; `end` must come after those events, or the browser never sees them
    (EventSource does not reconnect after `end`)."""
    registry = planner.registry
    live = registry.get(plan_id) if registry is not None else None
    if live is None:
        return
    try:
        async with asyncio.timeout(END_SETTLE_SECONDS):
            await live.wait_settled()
    except TimeoutError:
        log.warning("sse_end_before_consumer_settled", plan_id=str(plan_id))


async def event_stream(
    plan_id: uuid.UUID, after_seq: int | None, *, planner: PlannerServices, request: Request
) -> AsyncGenerator[ServerSentEvent]:
    """The SSE body (an async generator): subscribe to the hub, replay `events` with
    `seq > after_seq` from Postgres (`consumer.load_events_after`, in pages), then the live
    subscription:

    - `seq <= last sent`: skip (already sent by the replay);
    - `seq == last + 1`: send;
    - `seq > last + 1`: a gap. Writers are not serialized across tasks (consumer, sessions and
      jobs all commit through `EventSink` and publish after their own commit), so seq N+1 can
      be published before seq N. Replay `load_events_after(db, plan_id, last)` from Postgres
      first (it holds everything committed, the live event included), then go on; the live
      copy, now `<= last`, is skipped. The browser never misses an event (spec: "non perde
      nulla").

    When the plan is already terminal, or the hub yields `PlanEnded`, first wait for the plan's
    live consumer to settle (`_consumer_settled`: a consumer winding down still stores the
    events its streams had already delivered), then do a final Postgres catch-up, then send
    `sse_end(status)` and stop: `end` is always the last thing the browser gets. On
    `SubscriptionLaggedError`, replay from Postgres again and resubscribe. The plan's status is
    read before its events, so an event committed together with a terminal status is always
    part of the replay that precedes `end`.

    Client disconnects: `EventSourceResponse` listens for `http.disconnect` and cancels this
    generator; the `with` block then closes and unregisters the subscription. `request` is not
    polled (`request.is_disconnected()` would compete with that listener for ASGI messages).
    """
    del request  # disconnects are handled by EventSourceResponse (see above)
    last = after_seq
    while True:
        with planner.hub.subscribe(plan_id) as live:
            status = await _read_status(planner, plan_id)
            if status is None:
                return
            if status in TERMINAL_STATUSES:
                await _consumer_settled(planner, plan_id)
            async for page in _read_events(planner, plan_id, last):
                for event in page:
                    yield sse_message(event)
                    last = event.seq
            if status in TERMINAL_STATUSES:
                yield sse_end(status)
                return
            try:
                async for item in live:
                    if isinstance(item, PlanEnded):
                        await _consumer_settled(planner, plan_id)
                        async for page in _read_events(planner, plan_id, last):
                            for event in page:
                                yield sse_message(event)
                                last = event.seq
                        yield sse_end(item.status)
                        return
                    if last is not None and item.seq <= last:
                        continue
                    if item.seq == (0 if last is None else last + 1):
                        yield sse_message(item)
                        last = item.seq
                        continue
                    async for page in _read_events(planner, plan_id, last):
                        for event in page:
                            yield sse_message(event)
                            last = event.seq
            except SubscriptionLaggedError:
                log.info("sse_subscription_lagged", plan_id=str(plan_id), last_seq=last)
                continue
        return  # the subscription closed without an end (e.g. the hub is shutting down)


# --- routes -------------------------------------------------------------------------------------

router = APIRouter(prefix="/plans", tags=["plans"])


@dataclass
class RateLimits:
    """The process's limiters (app/ratelimit.py), one set per app, built from its settings."""

    create_per_user: ratelimit.SlidingWindow
    create_per_ip: ratelimit.SlidingWindow
    streams: ratelimit.StreamCounter

    @classmethod
    def from_settings(cls, settings: Settings) -> RateLimits:
        window = float(settings.plan_create_window_seconds)
        return cls(
            create_per_user=ratelimit.SlidingWindow(
                settings.plan_create_limit_per_user, window, time.monotonic
            ),
            create_per_ip=ratelimit.SlidingWindow(
                settings.plan_create_limit_per_ip, window, time.monotonic
            ),
            streams=ratelimit.StreamCounter(settings.max_streams_per_user),
        )


def get_rate_limits(request: Request) -> RateLimits:
    """`request.app.state.rate_limits`, built on first use from the app's settings."""
    limits: RateLimits | None = getattr(request.app.state, "rate_limits", None)
    if limits is None:
        limits = RateLimits.from_settings(request.app.state.settings)
        request.app.state.rate_limits = limits
    return limits


RateLimitsDep = Annotated[RateLimits, Depends(get_rate_limits)]


def check_create_rate(
    request: Request, user: CurrentUser, *, settings: Settings, limits: RateLimits
) -> Callable[[], None]:
    """POST /plans: the user's and the client IP's sliding windows (`ratelimit`), called from
    the route's body once the request is one that may start a plan (validated, the demo
    parameter checked) and before any quota query; over either: 429 `too_many_requests` with
    `Retry-After`. The IP window is hit first, so a request the user's window refuses still
    counts against the address (a burst from one address is what it guards). Returns what
    gives both slots back (a 503 `planner_unavailable` is not a request the windows guard)."""
    ip = ratelimit.client_ip(request, trust_proxy=settings.trusts_proxy_headers)
    by_ip = limits.create_per_ip.hit(ip)
    by_user = limits.create_per_user.hit(user.email) if by_ip.allowed else by_ip
    if not by_user.allowed:
        log.info("plan_create_rate_limited", by="ip" if not by_ip.allowed else "user")
        raise plan_error(
            PlanErrorCode.TOO_MANY_REQUESTS, retry_after_seconds=by_user.retry_after_seconds
        )

    def give_back() -> None:
        limits.create_per_ip.undo(ip, by_ip)
        limits.create_per_user.undo(user.email, by_user)

    return give_back


_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


async def _user_plan(
    db: AsyncSession, plan_id: uuid.UUID, user: CurrentUser, settings: Settings
) -> PlanRecord:
    """`sessions.get_user_plan`, with a missing or foreign plan as 404 `plan_not_found`."""
    try:
        return await sessions.get_user_plan(db, plan_id, user, settings=settings)
    except consumer.PlanNotFoundError:
        raise plan_error(PlanErrorCode.PLAN_NOT_FOUND) from None


me_router = APIRouter(tags=["me"])


@me_router.get("/me", responses=_ERRORS)
async def me(user: CurrentUserDep, settings: SettingsDep, db: DbSession) -> MeResponse:
    """Who is signed in, whether they may read the eval history (`auth.user_is_admin`: the web
    app shows the "Collaudi" section only to admins) and, unless they are exempt, their month
    against the quota (`quota.month_usage` of their plans, read without the lock). No personal
    data beyond the email the cookie already stands for."""
    is_admin = user_is_admin(user, settings)
    allowance: QuotaView | None = None
    if not is_admin:
        now = clock.now()
        usage = await quota.month_usage(
            db,
            now=now,
            owner=sessions.plan_owner_filter(user, settings=settings),
            default_budget_cents=settings.session_budget_cents,
        )
        allowance = QuotaView.from_quota(quota.user_quota(usage, settings=settings, now=now))
    return MeResponse(email=user.email, is_admin=is_admin, quota=allowance)


@router.post(
    "",
    status_code=201,
    dependencies=[RequireOrigin],
    responses={
        **_ERRORS,
        413: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
async def create_plan(
    body: PlanRequest,
    request: Request,
    user: CurrentUserDep,
    planner: PlannerDep,
    settings: SettingsDep,
    limits: RateLimitsDep,
    demo_scenario: Annotated[
        str | None,
        Query(
            max_length=64,
            description=(
                "DEMO_MODE only (development): the scripted session to replay, one of the "
                "scenarios in backend/tests/fixtures/ma (default happy_path). 404 "
                "demo_unavailable without DEMO_MODE, 422 for an unknown scenario."
            ),
        ),
    ] = None,
) -> CreatePlanResponse:
    """Validate the request (422 on errors), then `sessions.start_plan`. Maps
    `QuotaReachedError` -> 429 `quota_plans_reached` or `quota_cents_reached` (data: the
    user's quota), `MonthlyLimitReachedError` -> 429 `monthly_limit_reached` (data:
    spent_cents, limit_cents), `PlannerBusyError` -> 503 `planner_busy` (Retry-After),
    `PlannerUnavailableError`/`TripSchemaUnavailableError` -> 503 `planner_unavailable`,
    `ManagedAgentsError` or a start `TimeoutError` -> 502 `agents_unavailable`,
    `UserGoneError` (the account was deleted while its session was still cached) -> 401
    `not_authenticated`. `demo_scenario`: `check_demo_scenario`. The rate limits
    (`check_create_rate`) count only the requests that get this far."""
    check_demo_scenario(demo_scenario, settings=settings, planner=planner)
    give_back = check_create_rate(request, user, settings=settings, limits=limits)
    try:
        plan_id = await sessions.start_plan(
            body, user, services=planner, demo_scenario=demo_scenario
        )
    except quota.QuotaReachedError as exc:
        raise quota_error(exc) from None
    except sessions.MonthlyLimitReachedError as exc:
        log.info("plan_refused_monthly_limit", spent_cents=exc.spent_cents)
        raise plan_error(
            PlanErrorCode.MONTHLY_LIMIT_REACHED,
            data={"spent_cents": exc.spent_cents, "limit_cents": exc.limit_cents},
        ) from None
    except quota.PlannerBusyError as exc:
        raise plan_error(
            PlanErrorCode.PLANNER_BUSY,
            data={"running": exc.running, "limit": exc.limit},
            retry_after_seconds=quota.PLANNER_BUSY_RETRY_SECONDS,
        ) from None
    except sessions.PlannerUnavailableError as exc:
        give_back()
        log.error("plan_refused_planner_unavailable", reasons=exc.reasons)
        raise plan_error(PlanErrorCode.PLANNER_UNAVAILABLE) from None
    except sessions.UserGoneError:
        raise auth_error(AuthErrorCode.NOT_AUTHENTICATED, auth_messages(settings)) from None
    except TripSchemaUnavailableError as exc:
        give_back()
        log.error("plan_refused_trip_schema_unavailable", error=str(exc))
        raise plan_error(PlanErrorCode.PLANNER_UNAVAILABLE) from None
    except (ManagedAgentsError, TimeoutError) as exc:
        log.error("plan_start_failed", error=type(exc).__name__)
        raise plan_error(PlanErrorCode.AGENTS_UNAVAILABLE) from None
    return CreatePlanResponse(id=plan_id)


def quota_error(exc: quota.QuotaReachedError) -> HTTPException:
    """429 `quota_plans_reached` or `quota_cents_reached`, `data` the user's quota."""
    code = (
        PlanErrorCode.QUOTA_PLANS_REACHED
        if exc.kind == "plans"
        else PlanErrorCode.QUOTA_CENTS_REACHED
    )
    return plan_error(code, data=dict(exc.quota.as_data()))


def check_demo_scenario(value: str | None, *, settings: Settings, planner: PlannerServices) -> None:
    """POST /plans?demo_scenario=: absent is always fine; without DEMO_MODE it is 404
    `demo_unavailable` (the parameter does not exist there); in DEMO_MODE a name outside
    `planner.demo_scenarios` is a FastAPI-shaped 422 on `("query", "demo_scenario")`."""
    if value is None:
        return
    if not settings.demo_mode:
        raise plan_error(PlanErrorCode.DEMO_UNAVAILABLE)
    if value not in planner.demo_scenarios:
        expected = ", ".join(planner.demo_scenarios)
        raise RequestValidationError(
            [
                {
                    "type": "literal_error",
                    "loc": ("query", "demo_scenario"),
                    "msg": f"Input should be one of: {expected}",
                    "input": value,
                    "ctx": {"expected": expected},
                }
            ]
        )


@router.get("", responses=_ERRORS)
async def list_plans(
    user: CurrentUserDep, db: DbSession, settings: SettingsDep
) -> PlanListResponse:
    """The user's `PLAN_LIST_LIMIT` most recent plans (`sessions.plan_owner_filter`), newest
    first: title, status, cost, date. Reads only the listed columns (never the stored plan or
    Trip documents)."""
    rows = await db.execute(
        select(
            PlanRecord.id,
            PlanRecord.status,
            PlanRecord.cost_cents,
            PlanRecord.created_at,
            PlanRecord.request,
            func.jsonb_extract_path_text(PlanRecord.plan, "title"),
        )
        .where(sessions.plan_owner_filter(user, settings=settings))
        .order_by(PlanRecord.created_at.desc(), PlanRecord.id.desc())
        .limit(PLAN_LIST_LIMIT)
    )
    plans = [
        PlanSummary(
            id=plan_id,
            title=_title_from(accepted_title, request),
            status=PlanStatus(status),
            cost_cents=cost_cents,
            created_at=created_at,
        )
        for plan_id, status, cost_cents, created_at, request, accepted_title in rows
    ]
    return PlanListResponse(plans=plans)


@router.get("/{plan_id}", responses=_ERRORS)
async def get_plan(
    plan_id: uuid.UUID, user: CurrentUserDep, db: DbSession, settings: SettingsDep
) -> PlanDetail:
    """`plan_detail()` of the user's plan (`budget_cents` from `plans.budget_cents`); 404
    `plan_not_found` otherwise."""
    record = await _user_plan(db, plan_id, user, settings)
    return plan_detail(record, settings=settings)


@router.get("/{plan_id}/events", response_class=EventSourceResponse, responses=_ERRORS)
async def plan_events(
    plan_id: uuid.UUID,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
    planner: PlannerDep,
    settings: SettingsDep,
    limits: RateLimitsDep,
    last_event_id: Annotated[str | None, Header()] = None,
    after: Annotated[int | None, Query(ge=0, le=MAX_SEQ)] = None,
) -> EventSourceResponse:
    """SSE of the plan's UI events (module docstring). Checks ownership first (404), then the
    user's open streams (`MAX_STREAMS_PER_USER`, 429 `too_many_requests` with `Retry-After`;
    the slot, a `StreamLease`, is given back when the stream or the response ends, whichever
    comes first), then returns `CountedEventSourceResponse(event_stream(...), ping=PING_SECONDS,
    ping_message_factory=ping_comment, send_timeout=SEND_TIMEOUT_SECONDS,
    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})`. The request's DB
    session is released before streaming (the stream opens its own short sessions)."""
    await _user_plan(db, plan_id, user, settings)
    await db.close()
    held = limits.streams.acquire(user.email)
    if not held.allowed:
        log.info("plan_events_rate_limited", plan_id=str(plan_id))
        raise plan_error(
            PlanErrorCode.TOO_MANY_REQUESTS, retry_after_seconds=held.retry_after_seconds
        )
    lease = StreamLease(lambda: limits.streams.release(user.email))
    return CountedEventSourceResponse(
        _counted(
            event_stream(
                plan_id,
                parse_last_event_id(last_event_id, after),
                planner=planner,
                request=request,
            ),
            lease=lease,
        ),
        lease=lease,
        ping=PING_SECONDS,
        ping_message_factory=ping_comment,
        send_timeout=SEND_TIMEOUT_SECONDS,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/{plan_id}/trip",
    response_class=JSONResponse,
    responses={**_ERRORS, 409: {"model": ErrorResponse}},
)
async def get_trip(
    plan_id: uuid.UUID, user: CurrentUserDep, db: DbSession, settings: SettingsDep
) -> JSONResponse:
    """The stored TripTracker Trip (`plans.trip`), byte-for-byte the same on every call (its
    ids never change, so /import deduplicates by id). 409 `plan_not_ready` unless `ready`;
    404 for another user's plan. `Cache-Control: no-store`. The only route that also allows
    `TRIPTRACKER_ORIGIN` in CORS."""
    record = await _user_plan(db, plan_id, user, settings)
    if record.status != PlanStatus.READY or record.trip is None:
        raise plan_error(PlanErrorCode.PLAN_NOT_READY, data={"status": record.status})
    return JSONResponse(record.trip, headers={"Cache-Control": "no-store"})


@router.get("/{plan_id}/cover", responses=_ERRORS)
async def get_cover(
    plan_id: uuid.UUID,
    response: Response,
    user: CurrentUserDep,
    db: DbSession,
    covers: CoverResolverDep,
    settings: SettingsDep,
) -> Cover:
    """A free-licensed Wikimedia photo of the plan's destination, with author, license and
    source (`covers.Cover`); `cover_destination` picks the name. 404 `cover_unavailable` when
    there is no destination, no usable free photo or Wikimedia can't be reached (the page then
    simply has no photo); 404 `plan_not_found` for another user's plan. The destination name
    is the only thing sent to Wikimedia; the answer is cached per destination (covers.py)."""
    record = await _user_plan(db, plan_id, user, settings)
    destination = cover_destination(record)
    await db.close()  # no connection held while Wikimedia answers
    if destination is None:
        raise cover_unavailable()
    cover = await covers.get(destination)
    if cover is None:
        raise cover_unavailable()
    response.headers["Cache-Control"] = COVER_CACHE_CONTROL
    return cover


@router.post(
    "/{plan_id}/interrupt",
    status_code=202,
    dependencies=[RequireOrigin],
    responses={**_ERRORS, 409: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
async def interrupt_plan(
    plan_id: uuid.UUID, user: CurrentUserDep, planner: PlannerDep
) -> StatusResponse:
    """`sessions.interrupt_plan`; `PlanStateError` -> 409 `invalid_plan_state` (data: the
    current status), a missing or foreign plan -> 404, an API failure -> 502."""
    try:
        status = await sessions.interrupt_plan(plan_id, user, services=planner)
    except consumer.PlanNotFoundError:
        raise plan_error(PlanErrorCode.PLAN_NOT_FOUND) from None
    except sessions.PlanStateError as exc:
        raise plan_error(
            PlanErrorCode.INVALID_PLAN_STATE, data={"status": exc.status.value}
        ) from None
    except sessions.PlannerUnavailableError as exc:
        log.error("interrupt_planner_unavailable", plan_id=str(plan_id), reasons=exc.reasons)
        raise plan_error(PlanErrorCode.PLANNER_UNAVAILABLE) from None
    except ManagedAgentsError as exc:
        log.error("interrupt_failed", plan_id=str(plan_id), error=type(exc).__name__)
        raise plan_error(PlanErrorCode.AGENTS_UNAVAILABLE) from None
    return StatusResponse(id=plan_id, status=status)


@router.post(
    "/{plan_id}/continue",
    status_code=202,
    dependencies=[RequireOrigin],
    responses={
        **_ERRORS,
        409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def continue_plan(
    plan_id: uuid.UUID, user: CurrentUserDep, planner: PlannerDep
) -> ContinueResponse:
    """The "Continua con 2 $ in piu'" button: `sessions.continue_plan` (only from
    `budget_paused`, else 409); the plan's cap on "Continua" -> 409 `continue_limit_reached`;
    the user's quota -> 429 `quota_cents_reached`; the monthly limit -> 429; the running cap
    (`MAX_RUNNING_PLANS`) -> 503 `planner_busy` with Retry-After; API failure -> 502 and the plan
    stays `budget_paused`."""
    try:
        budget_cents = await sessions.continue_plan(plan_id, user, services=planner)
    except consumer.PlanNotFoundError:
        raise plan_error(PlanErrorCode.PLAN_NOT_FOUND) from None
    except sessions.PlanStateError as exc:
        raise plan_error(
            PlanErrorCode.INVALID_PLAN_STATE, data={"status": exc.status.value}
        ) from None
    except quota.ContinueLimitReachedError as exc:
        raise plan_error(
            PlanErrorCode.CONTINUE_LIMIT_REACHED,
            data={"continues": exc.continues, "limit": exc.limit},
        ) from None
    except quota.QuotaReachedError as exc:
        raise quota_error(exc) from None
    except sessions.MonthlyLimitReachedError as exc:
        raise plan_error(
            PlanErrorCode.MONTHLY_LIMIT_REACHED,
            data={"spent_cents": exc.spent_cents, "limit_cents": exc.limit_cents},
        ) from None
    except quota.PlannerBusyError as exc:
        raise plan_error(
            PlanErrorCode.PLANNER_BUSY,
            data={"running": exc.running, "limit": exc.limit},
            retry_after_seconds=quota.PLANNER_BUSY_RETRY_SECONDS,
        ) from None
    except sessions.PlannerUnavailableError as exc:
        log.error("continue_planner_unavailable", plan_id=str(plan_id), reasons=exc.reasons)
        raise plan_error(PlanErrorCode.PLANNER_UNAVAILABLE) from None
    except ManagedAgentsError as exc:
        log.error("continue_failed", plan_id=str(plan_id), error=type(exc).__name__)
        raise plan_error(PlanErrorCode.AGENTS_UNAVAILABLE) from None
    return ContinueResponse(id=plan_id, status=PlanStatus.RUNNING, budget_cents=budget_cents)


# --- eval history -------------------------------------------------------------------------------

evals_router = APIRouter(prefix="/evals", tags=["evals"])


def _bearer_token(authorization: str | None) -> str | None:
    """The token of an `Authorization: Bearer <token>` header (scheme case-insensitive)."""
    if authorization is None:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


def _token_matches(presented: str | None, settings: Settings) -> bool:
    """Constant-time comparison of the presented bearer token with EVALS_INGEST_TOKEN (both
    hashed first, so neither the value nor its length shows in the timing)."""
    expected = settings.evals_ingest_token.get_secret_value()
    digest = hashlib.sha256((presented or "").encode()).digest()
    matches = hmac.compare_digest(digest, hashlib.sha256(expected.encode()).digest())
    return matches and presented is not None


def _invalid_eval_results(exc: evals_store.InvalidEvalResultsError) -> HTTPException:
    return plan_error(PlanErrorCode.INVALID_EVAL_RESULTS, data={"errors": exc.errors})


@evals_router.post(
    "/runs",
    status_code=201,
    responses={
        200: {"model": evals_store.EvalRunCreated, "description": "The run was already stored."},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": evals_store.IngestBody.model_json_schema(
                        ref_template="#/components/schemas/{model}"
                    )
                }
            },
        }
    },
)
async def ingest_eval_run(
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> evals_store.EvalRunCreated:
    """Machine endpoint for the CI eval job: `Authorization: Bearer <EVALS_INGEST_TOKEN>`,
    body `{"results", "comparison", "workflow_run_url"}` (`evals_store.IngestBody`). No cookie,
    no Origin check, no CORS. 404 `evals_ingest_disabled` while the token is unset, 401
    `invalid_ingest_token` for a wrong one, 422 `invalid_eval_results` for a document that is not
    an eval run; 201 for a new run, 200 (same body) when it already existed.

    The body is read only after the token is checked (a parameter of type PlanRequest-style would
    make FastAPI read all of it first), so an unauthenticated caller costs no memory."""
    if not settings.evals_ingest_enabled:
        raise plan_error(PlanErrorCode.EVALS_INGEST_DISABLED)
    if not _token_matches(_bearer_token(authorization), settings):
        error = plan_error(PlanErrorCode.INVALID_INGEST_TOKEN)
        error.headers = {"WWW-Authenticate": "Bearer"}
        raise error
    raw = await request.body()
    if len(raw) > evals_store.MAX_INGEST_BYTES:
        raise plan_error(PlanErrorCode.REQUEST_TOO_LARGE)
    try:
        document = evals_store.parse_json(raw)
        if not isinstance(document, dict):
            raise evals_store.InvalidEvalResultsError(
                [{"field": "(body)", "reason": "must be a JSON object"}]
            )
        try:
            body = evals_store.IngestBody.model_validate(document)
        except ValidationError as exc:
            raise evals_store.InvalidEvalResultsError(
                [
                    {"field": ".".join(str(p) for p in e["loc"]), "reason": e["msg"]}
                    for e in exc.errors(include_input=False, include_url=False)
                ]
            ) from None
        stored = await evals_store.store_eval_run(
            db,
            results=body.results,
            comparison=body.comparison,
            workflow_run_url=body.workflow_run_url,
        )
    except evals_store.InvalidEvalResultsError as exc:
        raise _invalid_eval_results(exc) from None
    if not stored.created:
        response.status_code = 200
    return evals_store.EvalRunCreated(id=stored.id)


@evals_router.get("/runs", dependencies=[RequireAdmin], responses=_ERRORS)
async def list_eval_runs(
    user: CurrentUserDep,
    db: DbSession,
    limit: Annotated[
        int, Query(ge=1, le=evals_store.MAX_LIST_LIMIT)
    ] = evals_store.DEFAULT_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0, le=evals_store.MAX_LIST_OFFSET)] = 0,
) -> evals_store.EvalRunListResponse:
    """The eval history, newest first: the counts and the verdict of each run, never its
    documents; `offset` skips the newest runs and `total` counts them all, for the list's pages.
    Admins only (`RequireAdmin`): the runs belong to the project, not to a user."""
    return evals_store.EvalRunListResponse(
        runs=await evals_store.list_eval_runs(db, limit=limit, offset=offset),
        total=await evals_store.count_eval_runs(db),
    )


@evals_router.get("/runs/{run_id}", dependencies=[RequireAdmin], responses=_ERRORS)
async def get_eval_run(
    run_id: uuid.UUID, user: CurrentUserDep, db: DbSession
) -> evals_store.EvalRunDetail:
    """One run with its stored results and comparison; 404 `eval_run_not_found`. Admins only."""
    run = await evals_store.get_eval_run(db, run_id)
    if run is None:
        raise plan_error(PlanErrorCode.EVAL_RUN_NOT_FOUND)
    return run


# --- request body cap ---------------------------------------------------------------------------


class RequestBodyTooLargeError(HTTPException):
    """Raised from the capped `receive` when a streamed body passes the cap. An HTTPException,
    so FastAPI re-raises it from its body reading and answers with the error envelope."""

    def __init__(self) -> None:
        error = plan_error(PlanErrorCode.REQUEST_TOO_LARGE)
        super().__init__(status_code=error.status_code, detail=error.detail)


class RequestBodyLimitMiddleware:
    """Refuse request bodies over `max_body_size` bytes with 413 `request_too_large`, before
    routing, authentication and body parsing.

    FastAPI reads and JSON-parses a route's whole body before it resolves the route's
    dependencies (the Origin check, `current_user`), and neither uvicorn nor FastAPI caps the
    body (FastAPI 0.143 ignores Starlette's `max_body_size`). Without this, anyone could make
    the one web process hold an arbitrarily large POST /plans body in memory. A `Content-Length`
    over the cap is answered at once, without reading anything and without calling the app; a
    body without one (chunked) is counted as the app reads it and refused as soon as it passes
    the cap. `install_routes` puts it inside the CORS policy, so the browser can read the 413.
    `path_limits` raises the cap for the POST paths it names (the eval upload).
    """

    def __init__(
        self, app: ASGIApp, *, max_body_size: int, path_limits: Mapping[str, int] | None = None
    ) -> None:
        self._app = app
        self._default_max = max_body_size
        self._path_limits = dict(path_limits or {})

    def _limit_for(self, scope: Scope) -> int:
        """`max_body_size`, or the larger cap of a POST path in `path_limits`."""
        if scope.get("method") == "POST":
            return self._path_limits.get(scope["path"].rstrip("/"), self._default_max)
        return self._default_max

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        limit = self._limit_for(scope)
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await _body_too_large_response()(scope, receive, send)
            return
        received = 0
        response_started = False

        async def capped_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestBodyTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, capped_receive, tracked_send)
        except RequestBodyTooLargeError:
            # Read outside FastAPI's body parsing (which answers it itself): answer here.
            if response_started:
                raise
            await _body_too_large_response()(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    """The request's declared Content-Length, or None when absent or unreadable."""
    value = Headers(scope=scope).get("content-length")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _body_too_large_response() -> JSONResponse:
    error = RequestBodyTooLargeError()
    return JSONResponse({"detail": error.detail}, status_code=error.status_code)


# --- CORS ---------------------------------------------------------------------------------------


class PlanCorsMiddleware:
    """The API's CORS policy (spec "Autenticazione e domini", decision 23).

    Everywhere: `FRONTEND_ORIGIN` only, with credentials, methods GET and POST, request headers
    Content-Type and Last-Event-ID. On `GET /plans/{id}/trip` (and its preflight) also
    `TRIPTRACKER_ORIGIN`, read-only (GET), for TripTracker's /import. Never a wildcard: an
    origin outside the list gets no `Access-Control-Allow-Origin`, and its preflight a 400.
    """

    def __init__(self, app: ASGIApp, *, frontend_origin: str, triptracker_origin: str) -> None:
        self._default = CORSMiddleware(
            app,
            allow_origins=[frontend_origin],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Last-Event-ID"],
        )
        self._trip = CORSMiddleware(
            app,
            allow_origins=list(dict.fromkeys([frontend_origin, triptracker_origin])),
            allow_credentials=True,
            allow_methods=["GET"],
            allow_headers=["Content-Type"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in ("GET", "HEAD", "OPTIONS")
            and TRIP_PATH.fullmatch(scope["path"])
        ):
            await self._trip(scope, receive, send)
        else:
            await self._default(scope, receive, send)


def install_routes(app: FastAPI, settings: Settings) -> None:
    """Called once by main.py's `create_app`: include `router`, cap request bodies for the
    whole app (`RequestBodyLimitMiddleware`, `MAX_REQUEST_BODY_BYTES`) and install the CORS
    policy of the module docstring (`PlanCorsMiddleware`: Starlette's CORSMiddleware for
    `FRONTEND_ORIGIN` with `allow_credentials=True`, methods GET/POST, headers Content-Type and
    Last-Event-ID; plus a path-scoped rule that also accepts `TRIPTRACKER_ORIGIN` for GET
    /plans/{id}/trip and its preflight). Never a wildcard. The last middleware added is the
    outermost: CORS wraps the body cap, which wraps routing."""
    app.include_router(me_router)
    app.include_router(router)
    app.include_router(evals_router)
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_size=MAX_REQUEST_BODY_BYTES,
        path_limits={EVALS_INGEST_PATH: evals_store.MAX_INGEST_BYTES},
    )
    app.add_middleware(
        PlanCorsMiddleware,
        frontend_origin=settings.frontend_origin,
        triptracker_origin=settings.triptracker_origin,
    )
