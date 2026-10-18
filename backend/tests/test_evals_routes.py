"""POST /evals/runs (machine endpoint, bearer token), GET /evals/runs and GET /evals/runs/{id}."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import evals_store
from app.config import Settings
from app.db import EvalRunRecord
from app.routes import MAX_REQUEST_BODY_BYTES, PLAN_ERROR_MESSAGES, PlanErrorCode
from tests.conftest import AppFactory, StubPlanner
from tests.test_evals_store import comparison, entry, make_results, real_results

TOKEN = "t0ken-for-tests-" + "x" * 24
BEARER = {"Authorization": f"Bearer {TOKEN}"}
FRONTEND = "https://atlas.bellittim.com"


@dataclass
class EvalsApi:
    client: httpx.AsyncClient
    db: async_sessionmaker[AsyncSession]


@pytest.fixture
async def evals_api(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[EvalsApi]:
    """An app with EVALS_INGEST_TOKEN set (the local user reads the history)."""
    async with make_app(settings=make_settings(evals_ingest_token=TOKEN)) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield EvalsApi(client=client, db=db_session_factory)


def payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "results": make_results(requests=[entry()]),
        "comparison": comparison(),
        "workflow_run_url": "https://github.com/o/r/actions/runs/7",
    }
    body.update(overrides)
    return body


def detail(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message", "data"}
    return body["detail"]


async def count(db: async_sessionmaker[AsyncSession]) -> int:
    async with db() as session:
        return await session.scalar(select(func.count()).select_from(EvalRunRecord)) or 0


# --- POST /evals/runs: access -------------------------------------------------------------------


async def test_ingest_is_disabled_without_a_token(
    make_app: AppFactory,
    stub_planner: StubPlanner,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with make_app() as app:  # the test settings leave EVALS_INGEST_TOKEN empty
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            for headers in ({}, BEARER, {"Authorization": "Bearer "}):
                response = await http.post("/evals/runs", json=payload(), headers=headers)
                assert response.status_code == 404
                body = detail(response)
                assert body["code"] == "evals_ingest_disabled"
                assert body["message"] == PLAN_ERROR_MESSAGES[PlanErrorCode.EVALS_INGEST_DISABLED]
    assert await count(db_session_factory) == 0


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"Authorization": f"Bearer {TOKEN[:-1]}"},
        {"Authorization": TOKEN},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
    ],
)
async def test_a_missing_or_wrong_token_is_401(
    evals_api: EvalsApi, headers: dict[str, str]
) -> None:
    response = await evals_api.client.post("/evals/runs", json=payload(), headers=headers)

    assert response.status_code == 401
    assert detail(response)["code"] == "invalid_ingest_token"
    assert response.headers["www-authenticate"] == "Bearer"
    assert TOKEN not in response.text
    assert await count(evals_api.db) == 0


async def test_the_bearer_scheme_is_case_insensitive(evals_api: EvalsApi) -> None:
    response = await evals_api.client.post(
        "/evals/runs", json=payload(), headers={"Authorization": f"bearer {TOKEN}"}
    )

    assert response.status_code == 201


async def test_the_token_is_compared_in_constant_time(
    evals_api: EvalsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hmac

    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)

    await evals_api.client.post("/evals/runs", json=payload(), headers=BEARER)

    assert len(calls) == 1
    assert all(len(value) == 32 for value in calls[0])  # sha256 digests, whatever the token


async def test_the_machine_endpoint_needs_neither_a_cookie_nor_an_origin(
    evals_api: EvalsApi,
) -> None:
    ok = await evals_api.client.post("/evals/runs", json=payload(), headers=BEARER)
    assert ok.status_code == 201

    # A browser from another origin is still not given CORS headers.
    foreign = await evals_api.client.post(
        "/evals/runs",
        json=payload(),
        headers={**BEARER, "Origin": "https://evil.example"},
    )
    assert foreign.status_code == 200
    assert "access-control-allow-origin" not in foreign.headers


# --- POST /evals/runs: storing ------------------------------------------------------------------


async def test_ingest_stores_a_run_and_repeating_it_is_a_200(evals_api: EvalsApi) -> None:
    first = await evals_api.client.post("/evals/runs", json=payload(), headers=BEARER)
    again = await evals_api.client.post("/evals/runs", json=payload(), headers=BEARER)

    assert first.status_code == 201
    assert set(first.json()) == {"id"}
    uuid.UUID(first.json()["id"])
    assert again.status_code == 200
    assert again.json() == first.json()
    assert await count(evals_api.db) == 1


async def test_ingest_without_comparison_or_link(evals_api: EvalsApi) -> None:
    response = await evals_api.client.post(
        "/evals/runs",
        json={"results": make_results(), "comparison": None, "workflow_run_url": None},
        headers=BEARER,
    )
    assert response.status_code == 201

    only_results = await evals_api.client.post(
        "/evals/runs",
        json={"results": make_results(started_at="2026-10-14T09:00:00+02:00")},
        headers=BEARER,
    )
    assert only_results.status_code == 201


async def test_a_repeat_with_the_comparison_updates_the_run(evals_api: EvalsApi) -> None:
    results = make_results(requests=[entry()])
    first = await evals_api.client.post("/evals/runs", json={"results": results}, headers=BEARER)
    await evals_api.client.post(
        "/evals/runs",
        json={
            "results": results,
            "comparison": comparison(status="blocked", blocked=True),
            "workflow_run_url": "https://github.com/o/r/actions/runs/3",
        },
        headers=BEARER,
    )

    async with evals_api.db() as session:
        record = await session.get_one(EvalRunRecord, uuid.UUID(first.json()["id"]))
    assert record.summary["compare_status"] == "blocked"
    assert record.workflow_run_url == "https://github.com/o/r/actions/runs/3"


async def test_the_real_results_file_can_be_uploaded(evals_api: EvalsApi) -> None:
    response = await evals_api.client.post(
        "/evals/runs", json={"results": real_results()}, headers=BEARER
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"results": {**make_results(), "kind": "other"}}, "results.kind"),
        ({"results": {**make_results(), "format": 99}}, "results.format"),
        (
            {"results": {**make_results(), "started_at": "2026-10-13T09:00:00"}},
            "results.started_at",
        ),
        ({"results": {**make_results(), "requests": "x"}}, "results.requests"),
        ({"results": make_results(), "comparison": {"kind": "other"}}, "comparison.kind"),
        ({"results": make_results(), "workflow_run_url": "javascript:x"}, "workflow_run_url"),
        ({"results": make_results(), "comparison": 5}, "comparison"),
        ({"results": []}, "results"),
        ({}, "results"),
    ],
)
async def test_an_invalid_document_is_422_with_the_envelope(
    evals_api: EvalsApi, body: dict[str, Any], field: str
) -> None:
    response = await evals_api.client.post("/evals/runs", json=body, headers=BEARER)

    assert response.status_code == 422
    error = detail(response)
    assert error["code"] == "invalid_eval_results"
    assert error["message"] == PLAN_ERROR_MESSAGES[PlanErrorCode.INVALID_EVAL_RESULTS]
    assert field in [e["field"] for e in error["data"]["errors"]]
    assert await count(evals_api.db) == 0


@pytest.mark.parametrize("raw", [b"", b"{", b"[1]", b"null", b'{"results": NaN}', b"\xff\xfe"])
async def test_a_body_that_is_not_a_json_object_is_422(evals_api: EvalsApi, raw: bytes) -> None:
    response = await evals_api.client.post(
        "/evals/runs", content=raw, headers={**BEARER, "Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert detail(response)["code"] == "invalid_eval_results"


# --- POST /evals/runs: size ---------------------------------------------------------------------


async def test_a_body_over_the_plan_cap_but_under_5_mb_is_accepted(evals_api: EvalsApi) -> None:
    results = make_results(requests=[entry(plan={"padding": "x" * (MAX_REQUEST_BODY_BYTES * 4)})])
    body = json.dumps({"results": results}).encode()
    assert MAX_REQUEST_BODY_BYTES < len(body) < evals_store.MAX_INGEST_BYTES

    response = await evals_api.client.post(
        "/evals/runs", content=body, headers={**BEARER, "Content-Type": "application/json"}
    )

    assert response.status_code == 201


async def test_a_body_over_5_mb_is_413_by_length_or_while_streaming(evals_api: EvalsApi) -> None:
    results = make_results(requests=[entry(plan={"padding": "x" * evals_store.MAX_INGEST_BYTES})])
    body = json.dumps({"results": results}).encode()
    headers = {**BEARER, "Content-Type": "application/json"}

    declared = await evals_api.client.post("/evals/runs", content=body, headers=headers)
    assert declared.status_code == 413
    assert detail(declared)["code"] == "request_too_large"

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(body), 65536):
            yield body[start : start + 65536]

    streamed = await evals_api.client.post("/evals/runs", content=chunks(), headers=headers)
    assert streamed.status_code == 413
    assert await count(evals_api.db) == 0


async def test_the_bigger_cap_is_only_for_the_upload_path(evals_api: EvalsApi) -> None:
    body = b"x" * (MAX_REQUEST_BODY_BYTES + 1)

    response = await evals_api.client.post(
        "/plans",
        content=body,
        headers={"Origin": FRONTEND, "Content-Type": "application/json"},
    )

    assert response.status_code == 413


async def test_an_unauthenticated_large_body_is_never_read(evals_api: EvalsApi) -> None:
    chunks_read = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal chunks_read
        for _ in range(40):
            chunks_read += 1
            yield b"x" * 65536

    response = await evals_api.client.post(
        "/evals/runs", content=chunks(), headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code == 401
    assert chunks_read <= 2  # the transport may buffer a little, the handler reads nothing


# --- GET /evals/runs ----------------------------------------------------------------------------


async def test_list_returns_the_runs_newest_first(evals_api: EvalsApi) -> None:
    for day in (11, 13, 12):
        await evals_api.client.post(
            "/evals/runs",
            json={"results": make_results(started_at=f"2026-10-{day}T09:00:00+02:00")},
            headers=BEARER,
        )

    response = await evals_api.client.get("/evals/runs", headers={"Origin": FRONTEND})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    runs = response.json()["runs"]
    assert [run["started_at"][:10] for run in runs] == ["2026-10-13", "2026-10-12", "2026-10-11"]
    limited = await evals_api.client.get("/evals/runs", params={"limit": 2})
    assert len(limited.json()["runs"]) == 2


async def test_list_pages_with_offset_and_says_how_many_runs_there_are(
    evals_api: EvalsApi,
) -> None:
    for day in (11, 13, 12):
        await evals_api.client.post(
            "/evals/runs",
            json={"results": make_results(started_at=f"2026-10-{day}T09:00:00+02:00")},
            headers=BEARER,
        )

    response = await evals_api.client.get("/evals/runs", params={"limit": 2, "offset": 2})

    assert response.status_code == 200
    body = response.json()
    assert [run["started_at"][:10] for run in body["runs"]] == ["2026-10-11"]
    assert body["total"] == 3


async def test_list_items_have_exactly_the_contract_fields(evals_api: EvalsApi) -> None:
    await evals_api.client.post(
        "/evals/runs",
        json={
            "results": real_results(),
            "comparison": comparison(status="report_only", report_only=True),
            "workflow_run_url": "https://github.com/o/r/actions/runs/5",
        },
        headers=BEARER,
    )

    [run] = (await evals_api.client.get("/evals/runs")).json()["runs"]

    assert set(run) == {
        "id",
        "started_at",
        "finished_at",
        "git_sha",
        "profile",
        "aborted",
        "requests_total",
        "requests_accepted",
        "checks_passed",
        "blocking_failures_count",
        "total_cost_cents",
        "web_search_requests",
        "judge_mean",
        "compare_status",
        "reference_judge_mean",
        "reference_cost_per_plan_cents",
        "blocking_findings",
        "workflow_run_url",
    }
    assert run["requests_total"] == 5
    assert run["total_cost_cents"] == 309
    assert run["compare_status"] == "report_only"
    assert run["judge_mean"] is None


async def test_list_is_empty_before_any_upload(evals_api: EvalsApi) -> None:
    response = await evals_api.client.get("/evals/runs")

    assert response.status_code == 200
    assert response.json() == {"runs": [], "total": 0}


@pytest.mark.parametrize("limit", ["0", "-1", "201", "abc"])
async def test_list_limit_is_bounded(evals_api: EvalsApi, limit: str) -> None:
    response = await evals_api.client.get("/evals/runs", params={"limit": limit})

    assert response.status_code == 422


@pytest.mark.parametrize("offset", ["-1", "abc", "1000001"])
async def test_list_offset_is_bounded(evals_api: EvalsApi, offset: str) -> None:
    response = await evals_api.client.get("/evals/runs", params={"offset": offset})

    assert response.status_code == 422


async def test_the_history_needs_a_signed_in_user(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    production_like = make_settings(auth_mode="triptracker", evals_ingest_token=TOKEN)
    async with make_app(settings=production_like) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            posted = await http.post("/evals/runs", json=payload(), headers=BEARER)
            listed = await http.get("/evals/runs")
            opened = await http.get(f"/evals/runs/{uuid.uuid4()}")
            # The bearer token is not a user: it opens nothing on the read side.
            with_token = await http.get("/evals/runs", headers=BEARER)

    assert posted.status_code == 201
    for response in (listed, opened, with_token):
        assert response.status_code == 401
        assert detail(response)["code"] == "not_authenticated"


async def test_the_history_is_for_admins_only(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    stub_planner: StubPlanner,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ADMIN_EMAILS names someone else: the signed-in local user may plan but not read the evals;
    the machine upload is unaffected."""
    not_an_admin = make_settings(evals_ingest_token=TOKEN, admin_emails="boss@example.com")
    async with make_app(settings=not_an_admin) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            posted = await http.post("/evals/runs", json=payload(), headers=BEARER)
            run_id = posted.json()["id"]
            listed = await http.get("/evals/runs")
            opened = await http.get(f"/evals/runs/{run_id}")
            me = await http.get("/me")
            plans = await http.get("/plans")

    assert posted.status_code == 201
    for response in (listed, opened):
        assert response.status_code == 403
        assert detail(response) == {
            "code": "admin_only",
            "message": "Questa sezione è riservata a chi gestisce il planner.",
            "data": None,
        }
    assert me.status_code == 200
    assert me.json() == {"email": "test@example.com", "is_admin": False}
    assert plans.status_code == 200


# --- GET /evals/runs/{id} -----------------------------------------------------------------------


async def test_get_returns_the_list_fields_results_and_comparison(evals_api: EvalsApi) -> None:
    created = await evals_api.client.post(
        "/evals/runs",
        json={"results": real_results(), "comparison": comparison()},
        headers=BEARER,
    )
    run_id = created.json()["id"]

    response = await evals_api.client.get(f"/evals/runs/{run_id}")

    assert response.status_code == 200
    run = response.json()
    assert run["id"] == run_id
    assert run["results"] == real_results()
    assert run["comparison"] == comparison()
    listed = (await evals_api.client.get("/evals/runs")).json()["runs"][0]
    assert {key: run[key] for key in listed} == listed
    # Alone in the history: no run before it, none after.
    assert run["previous_run"] is None
    assert run["next_run"] is None


async def test_get_gives_the_neighbouring_runs_as_list_rows(evals_api: EvalsApi) -> None:
    ids = {}
    for day in (11, 12):
        created = await evals_api.client.post(
            "/evals/runs",
            json={"results": make_results(started_at=f"2026-10-{day}T09:00:00+02:00")},
            headers=BEARER,
        )
        ids[day] = created.json()["id"]

    newest = (await evals_api.client.get(f"/evals/runs/{ids[12]}")).json()

    listed = (await evals_api.client.get("/evals/runs")).json()["runs"]
    assert newest["previous_run"] == listed[1]
    assert newest["next_run"] is None


async def test_get_without_comparison_is_null(evals_api: EvalsApi) -> None:
    created = await evals_api.client.post(
        "/evals/runs", json={"results": make_results()}, headers=BEARER
    )

    run = (await evals_api.client.get(f"/evals/runs/{created.json()['id']}")).json()

    assert run["comparison"] is None
    assert run["workflow_run_url"] is None
    assert run["compare_status"] is None


async def test_an_unknown_run_is_404_in_the_envelope(evals_api: EvalsApi) -> None:
    response = await evals_api.client.get(f"/evals/runs/{uuid.uuid4()}")

    assert response.status_code == 404
    error = detail(response)
    assert error["code"] == "eval_run_not_found"
    assert error["message"] == PLAN_ERROR_MESSAGES[PlanErrorCode.EVAL_RUN_NOT_FOUND]
    assert error["data"] is None


async def test_a_malformed_run_id_is_422(evals_api: EvalsApi) -> None:
    response = await evals_api.client.get("/evals/runs/not-a-uuid")

    assert response.status_code == 422


async def test_eval_routes_are_documented_with_their_error_models(evals_api: EvalsApi) -> None:
    paths = (await evals_api.client.get("/openapi.json")).json()["paths"]

    post = paths["/evals/runs"]["post"]
    assert {"200", "201", "401", "404", "413", "422"} <= set(post["responses"])
    assert "results" in post["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "404" in paths["/evals/runs/{run_id}"]["get"]["responses"]
    assert "403" in paths["/evals/runs"]["get"]["responses"]  # admin_only
