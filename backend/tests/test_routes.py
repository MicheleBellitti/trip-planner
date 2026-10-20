"""HTTP API (app/routes.py, app/main.py wiring): endpoints, error envelope, ownership, CORS,
docs in production.

The lifespan runs with conftest's `stub_planner` (no Managed Agents client, no network);
`sessions.start_plan`, `interrupt_plan` and `continue_plan` are monkeypatched per test, so these
tests pin the HTTP contract, not the lifecycle (tests/test_sessions.py does that). Rows are
inserted directly with conftest's `plan_rows`.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from starlette.types import Message

from app import main, quota, routes, sessions
from app.auth import AuthErrorCode, CurrentUser, auth_messages
from app.config import Settings
from app.consumer import PlanNotFoundError
from app.db import AuthSessionRecord, PlanStatus
from app.events import AgentName, EventKind, UIEvent
from app.links import check_link
from app.ma_client import ApiRejectedError, ApiUnavailableError
from app.request import PlanRequest
from app.routes import (
    MAX_REQUEST_BODY_BYTES,
    PLAN_ERROR_MESSAGES,
    LinkCheck,
    PlanErrorCode,
    format_date_range,
    format_usd,
    parse_last_event_id,
    ping_comment,
    plan_error,
    sse_end,
    sse_message,
)
from app.sessions import PlannerServices
from app.triptracker_schema import TripSchemaUnavailableError
from tests.conftest import AppFactory, PlanRows, StubPlanner

FRONTEND = "https://atlas.bellittim.com"
TRIPTRACKER = "https://viaggi.bellittim.com"
USER = "test@example.com"
POST_HEADERS = {"Origin": FRONTEND}

VALID_BODY: dict[str, Any] = {
    "origin": "Milano",
    "destination": "Lisbona",
    "dates": {"exact_start": "2027-03-10", "exact_end": "2027-03-14"},
    "travelers": [{"kind": "adult"}, {"kind": "child", "age": 7}],
    "budget_eur": 1200,
}

ACCEPTED_PLAN: dict[str, Any] = {
    "title": "Lisbona, weekend lungo di novembre",
    "bookings": [
        {"title": "Hotel", "link": "https://www.booking.com/hotel/pt/alfama.it.html"},
        {"title": "Tour", "link": "https://evil.example/pay"},
        {"title": "Museo"},
    ],
    "alternatives": [{"title": "Volo", "link": "https://www.kiwi.com/it/booking?token=x"}],
}

STORED_TRIP: dict[str, Any] = {
    "id": "6f0c1e3a-1111-4222-8333-944455556666",
    "title": "Lisbona, weekend lungo di novembre",
    "days": [],
}


@dataclass
class Api:
    app: FastAPI
    client: httpx.AsyncClient
    planner: PlannerServices


@pytest.fixture
async def api(
    make_app: AppFactory,
    stub_planner: StubPlanner,
    db_session_factory: Any,  # prepares and empties the test database
) -> AsyncIterator[Api]:
    async with make_app() as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield Api(app=app, client=client, planner=stub_planner.planner)


@dataclass
class Calls:
    """Arguments of the monkeypatched sessions functions."""

    items: list[tuple[str, Any, CurrentUser, PlannerServices]] = field(default_factory=list)
    options: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    """The keyword arguments of each call besides `services` (e.g. `demo_scenario`)."""


def patch_sessions(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    *,
    result: Any = None,
    error: BaseException | None = None,
) -> Calls:
    calls = Calls()

    async def fake(
        subject: Any, user: CurrentUser, *, services: PlannerServices, **options: Any
    ) -> Any:
        calls.items.append((name, subject, user, services))
        calls.options.append(options)
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(sessions, name, fake)
    return calls


def detail(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message", "data"}
    return body["detail"]


# --- pure helpers -------------------------------------------------------------------------------


def test_format_usd_is_italian_copy() -> None:
    assert format_usd(4820) == "48,20 $"
    assert format_usd(5) == "0,05 $"
    assert format_usd(0) == "0,00 $"
    assert format_usd(123456) == "1.234,56 $"
    assert format_usd(-250) == "-2,50 $"


def test_plan_errors_carry_status_code_and_italian_message() -> None:
    expected = {
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
    assert set(expected) == set(PlanErrorCode)
    for code, status in expected.items():
        error = plan_error(code)
        assert error.status_code == status
        error_detail: Any = error.detail
        assert error_detail["code"] == code.value

    limit = plan_error(
        PlanErrorCode.MONTHLY_LIMIT_REACHED, data={"spent_cents": 5010, "limit_cents": 5000}
    )
    assert limit.detail == {
        "code": "monthly_limit_reached",
        "message": (
            "Questo mese il planner ha già impegnato 50,10 $ su 50,00 $: il prossimo piano si "
            "potrà creare il mese prossimo."
        ),
        "data": {"spent_cents": 5010, "limit_cents": 5000},
    }


def test_format_date_range() -> None:
    assert format_date_range(dt.date(2026, 11, 14), dt.date(2026, 11, 14)) == "14 nov"
    assert format_date_range(dt.date(2026, 11, 14), dt.date(2026, 11, 18)) == "14–18 nov"
    assert format_date_range(dt.date(2026, 11, 28), dt.date(2026, 12, 2)) == "28 nov – 2 dic"
    assert (
        format_date_range(dt.date(2026, 12, 30), dt.date(2027, 1, 2)) == "30 dic 2026 – 2 gen 2027"
    )


def test_parse_last_event_id_header_wins_and_garbage_is_ignored() -> None:
    assert parse_last_event_id("12", 3) == 12
    assert parse_last_event_id(" 0 ", None) == 0
    assert parse_last_event_id(None, 3) == 3
    assert parse_last_event_id(None, None) is None
    for malformed in ("", "-1", "abc", "1.5", "²", "99999999999"):
        assert parse_last_event_id(malformed, 4) == 4


def test_sse_wire_format() -> None:
    event = UIEvent(
        seq=7,
        ts=dt.datetime(2026, 10, 12, 8, 0, tzinfo=dt.UTC),
        agent=AgentName.FLIGHTS,
        kind=EventKind.TOOL,
        title="Kiwi · voli MXP→LIS",
    )

    assert sse_message(event).encode() == (
        f"id: 7\r\ndata: {event.model_dump_json()}\r\n\r\n".encode()
    )
    assert sse_end(PlanStatus.READY).encode() == b'event: end\r\ndata: {"status": "ready"}\r\n\r\n'
    assert ping_comment().encode() == b": ping\r\n\r\n"


def test_link_check_from_verdict() -> None:
    assert LinkCheck.from_verdict(check_link("https://www.booking.com/x")) == LinkCheck(
        allowed=True, provider="booking", label="Booking.com", host="www.booking.com"
    )
    assert LinkCheck.from_verdict(check_link("https://evil.example/x")) == LinkCheck(
        allowed=False, host="evil.example"
    )


# --- POST /plans ----------------------------------------------------------------------------------


async def test_create_plan_starts_the_plan_for_the_user(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = uuid.uuid4()
    calls = patch_sessions(monkeypatch, "start_plan", result=plan_id)

    response = await api.client.post("/plans", json=VALID_BODY, headers=POST_HEADERS)

    assert response.status_code == 201
    assert response.json() == {"id": str(plan_id)}
    [(_, request, user, services)] = calls.items
    assert isinstance(request, PlanRequest)
    assert request.destination == "Lisbona"
    assert user == CurrentUser(USER)
    assert services is api.planner
    assert calls.options == [{"demo_scenario": None}]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Origin": "https://evil.bellittim.com"}, {"Origin": TRIPTRACKER}, {"Origin": "null"}],
    ids=["missing", "sibling", "triptracker", "null"],
)
async def test_create_plan_needs_the_frontend_origin(
    api: Api, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    calls = patch_sessions(monkeypatch, "start_plan", result=uuid.uuid4())

    response = await api.client.post("/plans", json=VALID_BODY, headers=headers)

    assert response.status_code == 403
    assert detail(response)["code"] == "bad_origin"
    assert calls.items == []


async def test_create_plan_validation_errors_keep_fastapis_422_shape(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = patch_sessions(monkeypatch, "start_plan", result=uuid.uuid4())
    body = {**VALID_BODY, "destination": None, "travelers": [{"kind": "child", "age": 4}]}

    response = await api.client.post("/plans", json=body, headers=POST_HEADERS)

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert isinstance(errors, list)
    types = {error["type"] for error in errors}
    assert {"destination_required", "adult_required"} <= types
    assert all(error["loc"][0] == "body" for error in errors)
    assert calls.items == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (sessions.MonthlyLimitReachedError(5010, 5000), 429, "monthly_limit_reached"),
        (sessions.PlannerUnavailableError(["no key"]), 503, "planner_unavailable"),
        (TripSchemaUnavailableError("trip.json: 404"), 503, "planner_unavailable"),
        (ApiUnavailableError("down", status_code=503), 502, "agents_unavailable"),
        (ApiRejectedError("bad", status_code=400), 502, "agents_unavailable"),
        (TimeoutError(), 502, "agents_unavailable"),
    ],
)
async def test_create_plan_errors_use_the_envelope(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    status: int,
    code: str,
) -> None:
    patch_sessions(monkeypatch, "start_plan", error=error)

    response = await api.client.post("/plans", json=VALID_BODY, headers=POST_HEADERS)

    assert response.status_code == status
    body = detail(response)
    assert body["code"] == code
    if code == "monthly_limit_reached":
        assert body["data"] == {"spent_cents": 5010, "limit_cents": 5000}
        assert "50,10 $ su 50,00 $" in body["message"]
    else:
        assert body["message"] == PLAN_ERROR_MESSAGES[PlanErrorCode(code)]
        assert body["data"] is None


QUOTA = quota.UserQuota(
    plans_used=10,
    plans_limit=10,
    cents_used=1234,
    cents_limit=1500,
    resets_at=dt.datetime(2026, 11, 1, tzinfo=dt.timezone(dt.timedelta(hours=1))),
    next_plan_cents=400,
    continue_cents=200,
)


@pytest.mark.parametrize(
    ("error", "status", "code", "message_part", "retry_after"),
    [
        (
            quota.QuotaReachedError("plans", QUOTA),
            429,
            "quota_plans_reached",
            "hai già creato tutti i piani previsti (10 su 10)",
            None,
        ),
        (
            quota.QuotaReachedError("cents", QUOTA),
            429,
            "quota_cents_reached",
            "hanno già impegnato 12,34 $ su 15,00 $",
            None,
        ),
        (quota.PlannerBusyError(8, 8), 503, "planner_busy", "al completo", "60"),
    ],
)
async def test_create_plan_quota_and_busy_refusals(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    status: int,
    code: str,
    message_part: str,
    retry_after: str | None,
) -> None:
    patch_sessions(monkeypatch, "start_plan", error=error)

    response = await api.client.post("/plans", json=VALID_BODY, headers=POST_HEADERS)

    assert response.status_code == status
    body = detail(response)
    assert body["code"] == code
    assert message_part in body["message"]
    assert response.headers.get("Retry-After") == retry_after
    if code.startswith("quota_"):
        assert body["data"] == {
            "plans_used": 10,
            "plans_limit": 10,
            "cents_used": 1234,
            "cents_limit": 1500,
            "resets_at": "2026-11-01T00:00:00+01:00",
            "next_plan_cents": 400,
            "continue_cents": 200,
        }
    else:
        assert body["data"] == {"retry_after_seconds": 60, "running": 8, "limit": 8}


async def test_create_plan_is_rate_limited_per_user(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_sessions(monkeypatch, "start_plan", result=uuid.uuid4())
    settings = make_settings(plan_create_limit_per_user=2, plan_create_window_seconds=600)
    async with make_app(settings=settings) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            statuses = [
                (await client.post("/plans", json=VALID_BODY, headers=POST_HEADERS)).status_code
                for _ in range(3)
            ]
            third = await client.post("/plans", json=VALID_BODY, headers=POST_HEADERS)

    assert statuses == [201, 201, 429]
    body = detail(third)
    assert body["code"] == "too_many_requests"
    assert body["data"] == {"retry_after_seconds": 600}
    assert "riprova tra 600 s." in body["message"]
    assert third.headers["Retry-After"] == "600"


async def test_only_a_request_that_could_start_a_plan_counts_in_the_windows(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(plan_create_limit_per_user=1, plan_create_limit_per_ip=1)
    async with make_app(settings=settings) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:

            async def post(body: Any, query: str = "") -> int:
                response = await client.post(f"/plans{query}", json=body, headers=POST_HEADERS)
                return response.status_code

            invalid = [await post({"origin": ""}) for _ in range(3)]
            demo = [await post(VALID_BODY, "?demo_scenario=happy_path") for _ in range(3)]
            # The stub planner is not ready: a 503 gives its slot back.
            unavailable = [await post(VALID_BODY) for _ in range(3)]
            patch_sessions(monkeypatch, "start_plan", result=uuid.uuid4())
            started = await post(VALID_BODY)
            again = await post(VALID_BODY)

    assert invalid == [422, 422, 422]
    assert demo == [404, 404, 404]
    assert unavailable == [503, 503, 503]
    assert (started, again) == (201, 429)


async def test_create_plan_is_rate_limited_per_proxied_client_ip(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_sessions(monkeypatch, "start_plan", result=uuid.uuid4())
    settings = make_settings(plan_create_limit_per_ip=1, trust_proxy_headers=True)
    async with make_app(settings=settings) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first = await client.post(
                "/plans",
                json=VALID_BODY,
                headers={**POST_HEADERS, "X-Forwarded-For": "203.0.113.9"},
            )
            other = await client.post(
                "/plans",
                json=VALID_BODY,
                headers={**POST_HEADERS, "X-Forwarded-For": "198.51.100.2"},
            )
            # The client's own first value changes nothing: the proxy's last value is the key.
            again = await client.post(
                "/plans",
                json=VALID_BODY,
                headers={**POST_HEADERS, "X-Forwarded-For": "9.9.9.9, 203.0.113.9"},
            )

    assert (first.status_code, other.status_code, again.status_code) == (201, 201, 429)
    assert detail(again)["code"] == "too_many_requests"


async def test_create_plan_never_lifts_the_user_quota(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the eval runner (a CLI) passes user_quota_applies=False: the route never does.
    calls = patch_sessions(monkeypatch, "start_plan", result=uuid.uuid4())

    response = await api.client.post("/plans", json=VALID_BODY, headers=POST_HEADERS)

    assert response.status_code == 201
    assert "user_quota_applies" not in calls.options[0]


async def test_create_plan_for_a_deleted_account_is_401_not_authenticated(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_sessions(monkeypatch, "start_plan", error=sessions.UserGoneError())

    response = await api.client.post("/plans", json=VALID_BODY, headers=POST_HEADERS)

    assert response.status_code == 401
    assert detail(response) == {
        "code": "not_authenticated",
        "message": auth_messages(api.app.state.settings)[AuthErrorCode.NOT_AUTHENTICATED],
        "data": None,
    }
    assert response.headers["www-authenticate"] == "Cookie"


async def test_without_a_planner_post_plans_is_503(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    del api.app.state.planner

    response = await api.client.post("/plans", json=VALID_BODY, headers=POST_HEADERS)

    assert response.status_code == 503
    assert detail(response)["code"] == "planner_unavailable"


# --- GET /plans -----------------------------------------------------------------------------------


async def test_list_plans_shows_the_users_last_20_newest_first(
    api: Api, plan_rows: PlanRows
) -> None:
    base = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)
    for index in range(22):
        await plan_rows.add_plan(created_at=base + dt.timedelta(hours=index), cost_cents=index)
    await plan_rows.add_plan(user_email="other@example.com", created_at=base + dt.timedelta(days=9))

    response = await api.client.get("/plans")

    assert response.status_code == 200
    plans = response.json()["plans"]
    assert len(plans) == 20
    assert [plan["cost_cents"] for plan in plans] == list(range(21, 1, -1))
    created = [dt.datetime.fromisoformat(plan["created_at"]) for plan in plans]
    assert created == sorted(created, reverse=True)
    assert created[0] == base + dt.timedelta(hours=21)
    assert set(plans[0]) == {"id", "title", "status", "cost_cents", "created_at"}


async def test_list_plans_titles_come_from_the_plan_or_the_request(
    api: Api, plan_rows: PlanRows
) -> None:
    base = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)
    accepted = await plan_rows.add_plan(
        status=PlanStatus.READY, plan=ACCEPTED_PLAN, trip=STORED_TRIP, created_at=base
    )
    running = await plan_rows.add_plan(created_at=base + dt.timedelta(hours=1))
    suggested = await plan_rows.add_plan(
        request={
            "origin": "Milano",
            "suggest_destination": True,
            "destination_idea": "mare",
            "dates": {"month": "2027-11", "nights": 4},
            "travelers": [{"kind": "adult"}],
            "budget_eur": 900,
        },
        status=PlanStatus.BUDGET_PAUSED,
        created_at=base + dt.timedelta(hours=2),
    )

    plans = (await api.client.get("/plans")).json()["plans"]

    assert [(plan["id"], plan["title"], plan["status"]) for plan in plans] == [
        (str(suggested.id), "Destinazione da scegliere, novembre 2027", "budget_paused"),
        (str(running.id), "Lisbona, 14–18 nov", "running"),
        (str(accepted.id), "Lisbona, weekend lungo di novembre", "ready"),
    ]


async def test_list_plans_is_empty_for_a_new_user(api: Api) -> None:
    response = await api.client.get("/plans")

    assert response.status_code == 200
    assert response.json() == {"plans": []}


# --- GET /plans/{id} ------------------------------------------------------------------------------


async def test_get_plan_returns_status_plan_link_checks_and_import_link(
    api: Api, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(
        status=PlanStatus.READY,
        plan=ACCEPTED_PLAN,
        trip=STORED_TRIP,
        cost_cents=48,
        budget_cents=260,
    )

    response = await api.client.get(f"/plans/{record.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(record.id)
    assert body["status"] == "ready"
    assert body["title"] == "Lisbona, weekend lungo di novembre"
    assert body["agent_profile"] == "development"
    assert body["cost_cents"] == 48
    assert body["budget_cents"] == 260
    assert body["plan"] == ACCEPTED_PLAN
    assert body["request"]["destination"] == "Lisbona"
    assert body["import_url"] == f"{TRIPTRACKER}/import?plan={record.id}"
    assert body["booking_links"] == [
        {
            "allowed": True,
            "provider": "booking",
            "label": "Booking.com",
            "host": "www.booking.com",
        },
        {"allowed": False, "provider": None, "label": None, "host": "evil.example"},
        None,
    ]
    assert body["alternative_links"] == [
        {"allowed": True, "provider": "kiwi", "label": "Kiwi.com", "host": "www.kiwi.com"}
    ]


async def test_plan_detail_exposes_link_health(api: Api, plan_rows: PlanRows) -> None:
    record = await plan_rows.add_plan(
        status=PlanStatus.READY,
        plan=ACCEPTED_PLAN,
        trip=STORED_TRIP,
        link_health={
            "https://a.example/gone": {
                "status": "dead",
                "reason": "http_404",
                "http_status": 404,
                "fallback": "https://a.example/",
                "fallback_allowed": False,
                "checked_at": "2026-10-18T10:00:00+00:00",
            }
        },
    )

    response = await api.client.get(f"/plans/{record.id}")

    assert response.status_code == 200
    assert response.json()["link_health"] == {
        "https://a.example/gone": {
            "status": "dead",
            "fallback": "https://a.example/",
            "fallback_allowed": False,
        }
    }


async def test_plan_detail_fallback_allowed_asks_the_allowlist_as_it_is_now(
    api: Api, plan_rows: PlanRows
) -> None:
    """A stored `fallback_allowed: true` holds only while the link and its fallback both pass
    the allowlist: a link check_link refuses (the backslash) gets no homepage button."""

    def dead(fallback: str) -> dict[str, object]:
        return {
            "status": "dead",
            "reason": "http_404",
            "fallback": fallback,
            "fallback_allowed": True,
        }

    record = await plan_rows.add_plan(
        status=PlanStatus.READY,
        plan=ACCEPTED_PLAN,
        trip=STORED_TRIP,
        link_health={
            "https://www.booking.com/hotel/it/x.html": dead("https://www.booking.com/"),
            "https://www.booking.com/hotel\\it/x.html": dead("https://www.booking.com/"),
        },
    )

    response = await api.client.get(f"/plans/{record.id}")

    allowed = {
        url: entry["fallback_allowed"] for url, entry in response.json()["link_health"].items()
    }
    assert allowed == {
        "https://www.booking.com/hotel/it/x.html": True,
        "https://www.booking.com/hotel\\it/x.html": False,
    }


async def test_plan_detail_link_health_is_empty_for_older_plans(
    api: Api, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.READY, plan=ACCEPTED_PLAN, trip=STORED_TRIP)

    response = await api.client.get(f"/plans/{record.id}")

    assert response.status_code == 200
    assert response.json()["link_health"] == {}


async def test_get_plan_before_acceptance_has_no_plan_and_no_import_link(
    api: Api, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(budget_cents=None)

    body = (await api.client.get(f"/plans/{record.id}")).json()

    assert body["status"] == "running"
    assert body["title"] == "Lisbona, 14–18 nov"
    assert body["plan"] is None
    assert body["budget_cents"] is None
    assert body["booking_links"] == []
    assert body["alternative_links"] == []
    assert body["import_url"] is None


async def test_failed_plan_shows_its_reason_and_no_import_link(
    api: Api, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(
        status=PlanStatus.FAILED, failure_reason="Il coordinatore ha chiuso senza piano."
    )

    body = (await api.client.get(f"/plans/{record.id}")).json()

    assert body["failure_reason"] == "Il coordinatore ha chiuso senza piano."
    assert body["import_url"] is None


@pytest.mark.parametrize("path", ["", "/trip", "/events"])
async def test_another_users_plan_is_404(api: Api, plan_rows: PlanRows, path: str) -> None:
    record = await plan_rows.add_plan(
        user_email="other@example.com", status=PlanStatus.READY, trip=STORED_TRIP
    )

    response = await api.client.get(f"/plans/{record.id}{path}")

    assert response.status_code == 404
    assert detail(response) == {
        "code": "plan_not_found",
        "message": "Questo piano non c'è.",
        "data": None,
    }


async def test_unknown_plan_is_404(api: Api) -> None:
    response = await api.client.get(f"/plans/{uuid.uuid4()}")

    assert response.status_code == 404
    assert detail(response)["code"] == "plan_not_found"


# --- GET /plans/{id}/trip -------------------------------------------------------------------------


async def test_trip_is_served_unchanged_when_ready(api: Api, plan_rows: PlanRows) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.READY, plan=ACCEPTED_PLAN, trip=STORED_TRIP)

    first = await api.client.get(f"/plans/{record.id}/trip")
    second = await api.client.get(f"/plans/{record.id}/trip")

    assert first.status_code == 200
    assert first.json() == STORED_TRIP
    assert first.content == second.content
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "status",
    [PlanStatus.RUNNING, PlanStatus.BUDGET_PAUSED, PlanStatus.FAILED, PlanStatus.INTERRUPTED],
)
async def test_trip_is_409_until_ready(api: Api, plan_rows: PlanRows, status: PlanStatus) -> None:
    record = await plan_rows.add_plan(status=status)

    response = await api.client.get(f"/plans/{record.id}/trip")

    assert response.status_code == 409
    assert detail(response) == {
        "code": "plan_not_ready",
        "message": "Il piano è ancora in preparazione.",
        "data": {"status": status.value},
    }


# --- POST /plans/{id}/interrupt and /continue -----------------------------------------------------


async def test_interrupt_returns_the_status(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    plan_id = uuid.uuid4()
    calls = patch_sessions(monkeypatch, "interrupt_plan", result=PlanStatus.RUNNING)

    response = await api.client.post(f"/plans/{plan_id}/interrupt", headers=POST_HEADERS)

    assert response.status_code == 202
    assert response.json() == {"id": str(plan_id), "status": "running"}
    [(_, subject, user, services)] = calls.items
    assert (subject, user, services) == (plan_id, CurrentUser(USER), api.planner)


async def test_continue_returns_the_new_budget(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    plan_id = uuid.uuid4()
    patch_sessions(monkeypatch, "continue_plan", result=262)

    response = await api.client.post(f"/plans/{plan_id}/continue", headers=POST_HEADERS)

    assert response.status_code == 202
    assert response.json() == {"id": str(plan_id), "status": "running", "budget_cents": 262}


@pytest.mark.parametrize("action", ["interrupt", "continue"])
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (PlanNotFoundError(), 404, "plan_not_found"),
        (
            sessions.PlanStateError(uuid.uuid4(), PlanStatus.READY, (PlanStatus.BUDGET_PAUSED,)),
            409,
            "invalid_plan_state",
        ),
        (sessions.PlannerUnavailableError(["no key"]), 503, "planner_unavailable"),
        (ApiUnavailableError("down"), 502, "agents_unavailable"),
    ],
)
async def test_interrupt_and_continue_errors(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    error: BaseException,
    status: int,
    code: str,
) -> None:
    patch_sessions(monkeypatch, f"{action}_plan", error=error)

    response = await api.client.post(f"/plans/{uuid.uuid4()}/{action}", headers=POST_HEADERS)

    assert response.status_code == status
    body = detail(response)
    assert body["code"] == code
    if code == "invalid_plan_state":
        assert body["data"] == {"status": "ready"}


async def test_continue_at_its_cap_is_409(
    api: Api, plan_rows: PlanRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.BUDGET_PAUSED)
    patch_sessions(monkeypatch, "continue_plan", error=quota.ContinueLimitReachedError(2, 2))

    response = await api.client.post(f"/plans/{record.id}/continue", headers=POST_HEADERS)

    assert response.status_code == 409
    body = detail(response)
    assert body["code"] == "continue_limit_reached"
    assert body["data"] == {"continues": 2, "limit": 2}
    assert "(2 su 2)" in body["message"]


async def test_continue_over_the_users_quota_is_429(
    api: Api, plan_rows: PlanRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.BUDGET_PAUSED)
    patch_sessions(monkeypatch, "continue_plan", error=quota.QuotaReachedError("cents", QUOTA))

    response = await api.client.post(f"/plans/{record.id}/continue", headers=POST_HEADERS)

    assert response.status_code == 429
    assert detail(response)["code"] == "quota_cents_reached"


async def test_continue_over_the_monthly_limit_is_429(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_sessions(
        monkeypatch, "continue_plan", error=sessions.MonthlyLimitReachedError(4900, 5000)
    )

    response = await api.client.post(f"/plans/{uuid.uuid4()}/continue", headers=POST_HEADERS)

    assert response.status_code == 429
    assert detail(response)["data"] == {"spent_cents": 4900, "limit_cents": 5000}


async def test_continue_when_the_planner_is_full_is_503_planner_busy(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_sessions(monkeypatch, "continue_plan", error=quota.PlannerBusyError(8, 8))

    response = await api.client.post(f"/plans/{uuid.uuid4()}/continue", headers=POST_HEADERS)

    assert response.status_code == 503
    body = detail(response)
    assert body["code"] == "planner_busy"
    assert body["data"] == {"retry_after_seconds": 60, "running": 8, "limit": 8}
    assert response.headers["Retry-After"] == "60"


@pytest.mark.parametrize("action", ["interrupt", "continue"])
async def test_interrupt_and_continue_need_the_frontend_origin(
    api: Api, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    calls = patch_sessions(monkeypatch, f"{action}_plan", result=PlanStatus.RUNNING)

    response = await api.client.post(
        f"/plans/{uuid.uuid4()}/{action}", headers={"Origin": TRIPTRACKER}
    )

    assert response.status_code == 403
    assert detail(response)["code"] == "bad_origin"
    assert calls.items == []


# --- request body cap -----------------------------------------------------------------------------


@dataclass
class RawExchange:
    """One request driven straight through the ASGI app, recording what it read and sent."""

    chunks_read: int = 0
    bytes_read: int = 0
    sent: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @property
    def status(self) -> int:
        return self.sent[0]["status"]

    @property
    def headers(self) -> dict[str, str]:
        return {name.decode().lower(): value.decode() for name, value in self.sent[0]["headers"]}

    def json(self) -> Any:
        return json.loads(b"".join(m.get("body", b"") for m in self.sent[1:]))


async def raw_post(
    app: FastAPI,
    path: str,
    *,
    total: int,
    chunk: int,
    content_length: int | None,
    headers: dict[str, str] | None = None,
) -> RawExchange:
    """POST `total` bytes in `chunk`-sized `http.request` messages, without the lifespan and
    without httpx (which would buffer and measure the body itself)."""
    exchange = RawExchange()
    raw_headers = [(b"host", b"testserver"), (b"content-type", b"application/json")]
    if content_length is not None:
        raw_headers.append((b"content-length", str(content_length).encode()))
    raw_headers += [
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
    ]
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": ("203.0.113.7", 40000),
        "server": ("testserver", 80),
    }

    async def receive() -> Message:
        sent_so_far = exchange.bytes_read
        if sent_so_far >= total:
            return {"type": "http.disconnect"}
        size = min(chunk, total - sent_so_far)
        exchange.chunks_read += 1
        exchange.bytes_read += size
        return {
            "type": "http.request",
            "body": b" " * size,
            "more_body": sent_so_far + size < total,
        }

    async def send(message: Message) -> None:
        exchange.sent.append(dict(message))

    await app(scope, receive, send)
    return exchange


def too_large_detail() -> dict[str, Any]:
    return {
        "code": "request_too_large",
        "message": PLAN_ERROR_MESSAGES[PlanErrorCode.REQUEST_TOO_LARGE],
        "data": None,
    }


async def test_an_oversized_content_length_is_413_before_reading_anything(
    make_settings: Callable[..., Settings],
) -> None:
    """Reviewer's repro: no cookie, no Origin, 1 MiB declared. Nothing is read, no
    dependency runs (an Origin or auth check would answer 403/401 instead)."""
    app = main.create_app(make_settings(auth_mode="triptracker"))

    exchange = await raw_post(app, "/plans", total=1 << 20, chunk=1 << 16, content_length=1 << 20)

    assert exchange.status == 413
    assert exchange.chunks_read == 0
    assert exchange.json() == {"detail": too_large_detail()}


async def test_a_chunked_body_is_cut_off_once_it_passes_the_cap(
    make_settings: Callable[..., Settings],
) -> None:
    app = main.create_app(make_settings(auth_mode="triptracker"))
    chunk = 16 * 1024

    exchange = await raw_post(app, "/plans", total=1 << 20, chunk=chunk, content_length=None)

    assert exchange.status == 413
    assert exchange.bytes_read <= MAX_REQUEST_BODY_BYTES + chunk
    assert exchange.json() == {"detail": too_large_detail()}


async def test_the_413_carries_cors_headers_for_the_frontend(
    make_settings: Callable[..., Settings],
) -> None:
    app = main.create_app(make_settings())

    exchange = await raw_post(
        app,
        "/plans",
        total=1 << 20,
        chunk=1 << 16,
        content_length=1 << 20,
        headers={"Origin": FRONTEND},
    )

    assert exchange.status == 413
    assert exchange.headers["access-control-allow-origin"] == FRONTEND


async def test_a_body_at_the_cap_still_reaches_the_route(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = uuid.uuid4()
    calls = patch_sessions(monkeypatch, "start_plan", result=plan_id)
    compact = json.dumps(VALID_BODY).encode()
    padded = compact[:-1] + b" " * (MAX_REQUEST_BODY_BYTES - len(compact)) + b"}"
    assert len(padded) == MAX_REQUEST_BODY_BYTES

    response = await api.client.post(
        "/plans",
        content=padded,
        headers={**POST_HEADERS, "Content-Type": "application/json"},
    )
    too_big = await api.client.post(
        "/plans",
        content=padded + b" ",
        headers={**POST_HEADERS, "Content-Type": "application/json"},
    )
    no_origin = await api.client.post("/plans", json=VALID_BODY)

    assert response.status_code == 201
    assert response.json() == {"id": str(plan_id)}
    assert too_big.status_code == 413
    assert detail(too_big) == too_large_detail()
    assert no_origin.status_code == 403  # small bodies still meet the Origin check
    assert len(calls.items) == 1


# --- auth through the real routes (AUTH_MODE=triptracker) -----------------------------------------


@pytest.fixture
async def tt_api(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    db_session_factory: Any,
) -> AsyncIterator[httpx.AsyncClient]:
    async with make_app(settings=make_settings(auth_mode="triptracker")) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/plans"),
        ("GET", "/plans/00000000-0000-4000-8000-000000000000"),
        ("GET", "/plans/00000000-0000-4000-8000-000000000000/events"),
        ("GET", "/plans/00000000-0000-4000-8000-000000000000/trip"),
        ("POST", "/plans"),
        ("POST", "/plans/00000000-0000-4000-8000-000000000000/interrupt"),
        ("POST", "/plans/00000000-0000-4000-8000-000000000000/continue"),
    ],
)
async def test_every_plan_route_needs_a_session(
    tt_api: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await tt_api.request(method, path, headers=POST_HEADERS, json=VALID_BODY)

    assert response.status_code == 401
    assert detail(response)["code"] == "not_authenticated"


async def test_a_signed_in_allowed_user_sees_their_plans(
    tt_api: httpx.AsyncClient, plan_rows: PlanRows
) -> None:
    await plan_rows.add_plan(user_email=USER)
    with respx.mock(assert_all_mocked=True) as router:
        router.get(
            f"{TRIPTRACKER}/api/auth/get-session", params={"disableRefresh": "true"}
        ).respond(200, json={"session": {"token": "t"}, "user": {"id": "u1", "email": USER}})
        response = await tt_api.get(
            "/plans", headers={"Cookie": "__Secure-better-auth.session_token=abc.sig"}
        )

    assert response.status_code == 200
    assert len(response.json()["plans"]) == 1


# --- GET /me and ownership with the app's own accounts (AUTH_MODE=atlas) --------------------------


async def test_me_says_who_is_signed_in_and_whether_they_manage_the_evals(api: Api) -> None:
    # AUTH_MODE=local without ADMIN_EMAILS: the allowed user is the admin (the one-user setup).
    response = await api.client.get("/me")

    assert response.status_code == 200
    assert response.json() == {"email": USER, "is_admin": True, "quota": None}  # exempt


async def test_me_carries_the_month_against_the_quota_for_a_plain_user(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    plan_rows: PlanRows,
) -> None:
    settings = make_settings(
        admin_emails=["boss@example.com"], user_monthly_plans=10, user_monthly_cents=1500
    )
    await plan_rows.add_plan(
        status=PlanStatus.READY, cost_cents=80, created_at=dt.datetime.now(dt.UTC)
    )
    await plan_rows.add_plan(  # running: 60 budgeted, 10 spent, 50 reserved
        status=PlanStatus.RUNNING,
        cost_cents=10,
        budget_cents=60,
        created_at=dt.datetime.now(dt.UTC),
    )
    async with make_app(settings=settings) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/me")

    assert response.status_code == 200
    body = response.json()
    assert (body["email"], body["is_admin"]) == (USER, False)
    assert {
        key: body["quota"][key]
        for key in ("plans_used", "plans_limit", "cents_used", "cents_limit")
    } == {
        "plans_used": 2,
        "plans_limit": 10,
        "cents_used": 80 + 10 + 50,
        "cents_limit": 1500,
    }
    assert body["quota"]["resets_at"].startswith("20")
    # What the next start and a "Continua" need, so the web app applies the backend's own rule.
    assert (body["quota"]["next_plan_cents"], body["quota"]["continue_cents"]) == (
        settings.session_budget_cents,
        200,
    )


async def test_me_needs_a_session(tt_api: httpx.AsyncClient) -> None:
    response = await tt_api.get("/me")

    assert response.status_code == 401
    assert detail(response)["code"] == "not_authenticated"


ATLAS_COOKIE = "__Secure-atlas.session_token"


async def add_session(plan_rows: PlanRows, *, user_id: str, token: str, hours: float = 24) -> None:
    async with plan_rows.session_factory() as db:
        db.add(
            AuthSessionRecord(
                id=f"ses_{token}",
                user_id=user_id,
                token=token,
                expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=hours),
            )
        )
        await db.commit()


async def test_with_the_apps_own_accounts_the_cookie_is_the_session_table_and_plans_go_by_id(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    plan_rows: PlanRows,
) -> None:
    """AUTH_MODE=atlas end to end: the `atlas` cookie's token is looked up in `auth_sessions`
    (no HTTP call to anyone), PLANNER_ALLOWED_EMAILS plays no part, the list and the detail go by
    `plans.user_id` (plus the user's legacy rows without one), and `/me` says this user is no
    admin until ADMIN_EMAILS names them."""
    await plan_rows.add_user("usr_me", "Me@Example.com")
    await plan_rows.add_user("usr_other", "other@example.com")
    await add_session(plan_rows, user_id="usr_me", token="tok3nMe")
    await add_session(plan_rows, user_id="usr_other", token="tok3nOther", hours=-1)  # expired
    mine = await plan_rows.add_plan(user_email="me@example.com", user_id="usr_me")
    legacy = await plan_rows.add_plan(user_email="ME@example.com")  # before the switch: no id
    others = await plan_rows.add_plan(user_email="me@example.com", user_id="usr_other")
    strangers = await plan_rows.add_plan(user_email="other@example.com")

    atlas = make_settings(auth_mode="atlas", planner_allowed_emails="nobody@example.com")
    async with make_app(settings=atlas) as app:
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as http,
            respx.mock(assert_all_mocked=True),  # any HTTP call out of the app fails the test
        ):
            cookie = {"Cookie": f"{ATLAS_COOKIE}=tok3nMe.SiGnAtUrE%3D; theme=dark"}
            me = await http.get("/me", headers=cookie)
            listed = await http.get("/plans", headers=cookie)
            opened = [
                (await http.get(f"/plans/{plan.id}", headers=cookie)).status_code
                for plan in (mine, legacy, others, strangers)
            ]
            expired = await http.get("/plans", headers={"Cookie": f"{ATLAS_COOKIE}=tok3nOther.x"})
            unknown = await http.get("/plans", headers={"Cookie": f"{ATLAS_COOKIE}=nobody.x"})
            triptrackers = await http.get(
                "/plans", headers={"Cookie": "__Secure-better-auth.session_token=tok3nMe.x"}
            )

    assert me.status_code == 200
    identity = me.json()
    assert (identity["email"], identity["is_admin"]) == ("me@example.com", False)
    assert identity["quota"]["plans_limit"] == 10  # a plain user sees their month
    assert listed.status_code == 200
    assert {plan["id"] for plan in listed.json()["plans"]} == {str(mine.id), str(legacy.id)}
    assert opened == [200, 200, 404, 404]
    for response in (expired, unknown, triptrackers):
        assert response.status_code == 401
        assert detail(response) == {
            "code": "not_authenticated",
            "message": "Accedi per usare il planner.",
            "data": None,
        }


async def test_with_the_apps_own_accounts_an_unverified_email_owns_no_legacy_plan_nor_the_evals(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    plan_rows: PlanRows,
) -> None:
    """An account whose `users.email_verified` is false keeps the plans stored with its id, but
    the address alone gives it neither the legacy plans stored by that email nor the admin role,
    even when ADMIN_EMAILS names it."""
    await plan_rows.add_user("usr_me", "me@example.com", email_verified=False)
    await add_session(plan_rows, user_id="usr_me", token="tok3nMe")
    mine = await plan_rows.add_plan(user_email="me@example.com", user_id="usr_me")
    legacy = await plan_rows.add_plan(user_email="me@example.com")  # before the switch: no id

    atlas = make_settings(auth_mode="atlas", admin_emails="me@example.com")
    async with make_app(settings=atlas) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            cookie = {"Cookie": f"{ATLAS_COOKIE}=tok3nMe.SiGnAtUrE"}
            me = await http.get("/me", headers=cookie)
            listed = await http.get("/plans", headers=cookie)
            opened = [
                (await http.get(f"/plans/{plan.id}", headers=cookie)).status_code
                for plan in (mine, legacy)
            ]
            evals = await http.get("/evals/runs", headers=cookie)

    identity = me.json()
    assert (identity["email"], identity["is_admin"]) == ("me@example.com", False)
    # Not an admin, so not exempt from the quota, which counts only the plan stored with its id.
    assert identity["quota"]["plans_used"] == 1
    assert {plan["id"] for plan in listed.json()["plans"]} == {str(mine.id)}
    assert opened == [200, 404]
    assert evals.status_code == 403
    assert detail(evals)["code"] == "admin_only"


# --- CORS -----------------------------------------------------------------------------------------


def preflight(origin: str, method: str, headers: str | None = None) -> dict[str, str]:
    result = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers is not None:
        result["Access-Control-Request-Headers"] = headers
    return result


async def test_cors_frontend_preflight_for_post_plans(api: Api) -> None:
    response = await api.client.options(
        "/plans", headers=preflight(FRONTEND, "POST", "content-type")
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]


async def test_cors_frontend_preflight_for_events_with_last_event_id(api: Api) -> None:
    response = await api.client.options(
        f"/plans/{uuid.uuid4()}/events", headers=preflight(FRONTEND, "GET", "last-event-id")
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND


async def test_cors_frontend_simple_request_with_credentials(api: Api) -> None:
    response = await api.client.get("/plans", headers={"Origin": FRONTEND})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "Origin" in response.headers["vary"]


@pytest.mark.parametrize("origin", [TRIPTRACKER, "https://evil.example"])
async def test_cors_other_origins_get_nothing_outside_the_trip_route(
    api: Api, plan_rows: PlanRows, origin: str
) -> None:
    record = await plan_rows.add_plan()

    for path in ("/plans", f"/plans/{record.id}"):
        response = await api.client.get(path, headers={"Origin": origin})
        assert "access-control-allow-origin" not in response.headers, path

    refused = await api.client.options("/plans", headers=preflight(origin, "POST", "content-type"))
    assert refused.status_code == 400
    assert "access-control-allow-origin" not in refused.headers


async def test_cors_triptracker_may_read_the_trip(api: Api, plan_rows: PlanRows) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.READY, plan=ACCEPTED_PLAN, trip=STORED_TRIP)

    response = await api.client.get(f"/plans/{record.id}/trip", headers={"Origin": TRIPTRACKER})
    allowed = await api.client.options(
        f"/plans/{record.id}/trip", headers=preflight(TRIPTRACKER, "GET")
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == TRIPTRACKER
    assert response.headers["access-control-allow-credentials"] == "true"
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == TRIPTRACKER
    assert allowed.headers["access-control-allow-methods"] == "GET"


async def test_cors_trip_route_stays_read_only_and_closed_to_strangers(api: Api) -> None:
    path = f"/plans/{uuid.uuid4()}/trip"

    write = await api.client.options(path, headers=preflight(TRIPTRACKER, "POST"))
    stranger = await api.client.options(path, headers=preflight("https://evil.example", "GET"))
    frontend = await api.client.options(path, headers=preflight(FRONTEND, "GET"))

    assert write.status_code == 400
    assert stranger.status_code == 400
    assert "access-control-allow-origin" not in stranger.headers
    assert frontend.headers["access-control-allow-origin"] == FRONTEND


async def test_cors_never_answers_a_wildcard(api: Api, plan_rows: PlanRows) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.READY, trip=STORED_TRIP)
    for origin in (FRONTEND, TRIPTRACKER, "https://evil.example"):
        for path in ("/plans", f"/plans/{record.id}/trip", "/health"):
            response = await api.client.get(path, headers={"Origin": origin})
            assert response.headers.get("access-control-allow-origin") != "*"


# --- wiring and docs ------------------------------------------------------------------------------


async def test_lifespan_exposes_the_planner_hub_and_verifier(
    api: Api, stub_planner: StubPlanner
) -> None:
    state = api.app.state
    assert state.planner is stub_planner.planner
    assert state.hub is stub_planner.planner.hub
    assert state.session_verifier is stub_planner.planner.session_verifier
    assert len(stub_planner.planner.background_tasks) == 1  # the stuck-plan checker


async def test_lifespan_stops_the_planner_and_passes_the_client_override(
    make_app: AppFactory, stub_planner: StubPlanner, db_session_factory: Any
) -> None:
    marker: Any = object()
    async with make_app(client=marker):
        planner = stub_planner.planner
        assert planner.client is marker
        task = planner.background_tasks[0]
    assert stub_planner.stopped == [planner]
    assert task.cancelled()


async def test_development_documents_every_route(api: Api) -> None:
    paths = (await api.client.get("/openapi.json")).json()["paths"]

    assert set(paths) == {
        "/health",
        "/me",
        "/plans",
        "/plans/{plan_id}",
        "/plans/{plan_id}/events",
        "/plans/{plan_id}/trip",
        "/plans/{plan_id}/cover",
        "/plans/{plan_id}/interrupt",
        "/plans/{plan_id}/continue",
        "/evals/runs",
        "/evals/runs/{run_id}",
    }
    assert set(paths["/evals/runs"]) == {"get", "post"}
    assert set(paths["/plans"]) == {"get", "post"}


async def test_production_hides_the_docs_and_only_health_answers_without_a_user(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    db_session_factory: Any,
) -> None:
    production = make_settings(
        environment="production",
        auth_mode="triptracker",
        anthropic_api_key="sk-test-not-a-real-key",
        agent_profile="production",
    )
    async with make_app(settings=production) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
                assert (await client.get(path)).status_code == 404, path
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/plans")).status_code == 401
            assert (await client.get(f"/plans/{uuid.uuid4()}/trip")).status_code == 401


def test_routes_module_exposes_the_stream_settings() -> None:
    assert routes.PING_SECONDS == 15
    expected = {PlanStatus.READY, PlanStatus.FAILED, PlanStatus.BLOCKED, PlanStatus.INTERRUPTED}
    assert expected == routes.TERMINAL_STATUSES
    assert PlanStatus.BUDGET_PAUSED not in routes.TERMINAL_STATUSES
