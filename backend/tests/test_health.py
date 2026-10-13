"""main.py: GET /health, the docs switch, the structlog chain and the error envelope of the
errors no route raises itself (404, 405, 400, 413, 500), CORS headers included."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
import structlog
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from structlog.testing import LogCapture
from structlog.typing import EventDict

from app import main, routes
from app.config import PLAN_LOG_KEYS, LogLevel, Settings

FRONTEND = "https://atlas.bellittim.com"  # conftest's FRONTEND_ORIGIN
TRIPTRACKER = "https://viaggi.bellittim.com"  # conftest's TRIPTRACKER_ORIGIN


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_needs_no_credentials(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200


def test_module_level_app_is_served_by_uvicorn() -> None:
    assert isinstance(main.app, FastAPI)
    assert any(getattr(route, "path", None) == "/health" for route in main.app.routes)


async def test_lifespan_opens_the_database_engine(app: FastAPI) -> None:
    assert app.state.engine is not None
    assert app.state.session_factory is not None


def _asgi_client(application: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    )


async def test_production_serves_no_docs_or_openapi(make_settings: Callable[..., Settings]) -> None:
    production = make_settings(
        environment="production",
        auth_mode="triptracker",
        anthropic_api_key="sk-test-not-a-real-key",
        agent_profile="production",
    )
    async with _asgi_client(main.create_app(production)) as http:
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert (await http.get(path)).status_code == 404, path
        assert (await http.get("/health")).status_code == 200


async def test_development_serves_the_openapi_document(
    make_settings: Callable[..., Settings],
) -> None:
    async with _asgi_client(main.create_app(make_settings())) as http:
        response = await http.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Trip Planner API"


@contextmanager
def app_logging(level: LogLevel) -> Iterator[None]:
    """`main.configure_logging(level)` for one test, then the previous structlog configuration
    back. Without the logger cache: configure_logging turns on `cache_logger_on_first_use`,
    and a logger first used under it would keep this chain (and this test's captured stdout)
    for every later test, out of reach of `structlog.testing.capture_logs`."""
    saved = structlog.get_config()
    main.configure_logging(level)
    structlog.configure(cache_logger_on_first_use=False)
    try:
        yield
    finally:
        structlog.configure(**saved)


def test_app_logging_restores_the_previous_structlog_configuration() -> None:
    before = structlog.get_config()
    with app_logging("WARNING"):
        during = structlog.get_config()
        assert during["cache_logger_on_first_use"] is False
        assert during["processors"] is not before["processors"]
    assert structlog.get_config() == before


async def test_every_log_line_carries_the_plan_keys(capsys: pytest.CaptureFixture[str]) -> None:
    """Spec "Log e resilienza": plan_id, session_id, agent and event_type on every line; None
    outside a plan, the bound values inside one (tasks created there inherit them), and a
    call's own keywords win."""
    with app_logging("WARNING"):  # the test environment's level, so nothing else changes
        await _log_inside_and_outside_a_plan()

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    keys = {line["event"]: {key: line[key] for key in PLAN_LOG_KEYS} for line in lines}
    assert keys == {
        "outside_any_plan": dict.fromkeys(PLAN_LOG_KEYS),
        "in_the_plan": {
            "plan_id": "p-1",
            "session_id": "sesn_1",
            "agent": "coordinator",
            "event_type": None,
        },
        "in_a_task_of_the_plan": {
            "plan_id": "p-1",
            "session_id": "sesn_1",
            "agent": "flights",
            "event_type": None,
        },
        "after_the_plan": {
            "plan_id": "p-2",
            "session_id": None,
            "agent": None,
            "event_type": None,
        },
    }


async def _log_inside_and_outside_a_plan() -> None:
    logger = structlog.get_logger("tests.test_health")

    async def thread_loop() -> None:
        logger.warning("in_a_task_of_the_plan", agent="flights")

    logger.warning("outside_any_plan")
    with structlog.contextvars.bound_contextvars(
        plan_id="p-1", session_id="sesn_1", agent="coordinator", event_type=None
    ):
        logger.warning("in_the_plan")
        await asyncio.create_task(thread_loop())
    logger.warning("after_the_plan", plan_id="p-2")


# --- the error envelope everywhere --------------------------------------------------------------


def envelope(code: str, message: str) -> dict[str, Any]:
    return {"detail": {"code": code, "message": message, "data": None}}


@pytest.fixture
def main_logs(monkeypatch: pytest.MonkeyPatch) -> list[EventDict]:
    """main.py's log entries, independent of the global structlog configuration."""
    capture = LogCapture()
    logger = structlog.wrap_logger(
        None,
        processors=[capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    monkeypatch.setattr(main, "log", logger)
    return capture.entries


@pytest.fixture
def error_app(make_settings: Callable[..., Settings]) -> FastAPI:
    """The real app (no lifespan: none of these paths touches the planner) plus test routes
    that fail in each way the framework, not a route, has to answer."""
    application = main.create_app(make_settings())

    async def crash() -> None:
        raise RuntimeError("boom: secret-looking detail")

    async def framework_error(status: int) -> None:
        raise StarletteHTTPException(status_code=status, detail="Framework text")

    async def route_error() -> None:
        raise routes.plan_error(routes.PlanErrorCode.PLAN_NOT_FOUND)

    async def broken_stream() -> StreamingResponse:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"first chunk"
            raise RuntimeError("after the response started")

        return StreamingResponse(chunks(), media_type="text/plain")

    application.add_api_route("/test/crash", crash, methods=["GET", "POST"])
    application.add_api_route("/test/framework/{status}", framework_error, methods=["GET"])
    application.add_api_route("/test/route-error", route_error, methods=["GET"])
    application.add_api_route("/test/stream", broken_stream, methods=["GET"])
    return application


async def test_an_unknown_path_is_a_404_envelope(error_app: FastAPI) -> None:
    async with _asgi_client(error_app) as http:
        response = await http.get("/nowhere", headers={"Origin": FRONTEND})

    assert response.status_code == 404
    assert response.json() == envelope("not_found", "Questo indirizzo non esiste.")
    assert response.headers["access-control-allow-origin"] == FRONTEND


async def test_a_wrong_method_is_a_405_envelope_with_allow(error_app: FastAPI) -> None:
    async with _asgi_client(error_app) as http:
        response = await http.post("/health", headers={"Origin": FRONTEND})

    assert response.status_code == 405
    assert response.json() == envelope(
        "method_not_allowed", "Questa operazione non è consentita qui."
    )
    assert response.headers["allow"] == "GET"
    assert response.headers["access-control-allow-origin"] == FRONTEND


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (400, "bad_request", "La richiesta non è valida: ricarica la pagina e riprova."),
        (
            413,
            "request_too_large",
            routes.PLAN_ERROR_MESSAGES[routes.PlanErrorCode.REQUEST_TOO_LARGE],
        ),
        (
            418,
            "http_error",
            "La richiesta non è andata a buon fine. Riprova tra qualche minuto.",
        ),
    ],
)
async def test_framework_errors_get_the_envelope_of_their_status(
    error_app: FastAPI, status: int, code: str, message: str
) -> None:
    async with _asgi_client(error_app) as http:
        response = await http.get(f"/test/framework/{status}")

    assert response.status_code == status
    assert response.json() == envelope(code, message)
    assert "Framework text" not in response.text


async def test_a_status_without_a_body_stays_empty(error_app: FastAPI) -> None:
    async with _asgi_client(error_app) as http:
        response = await http.get("/test/framework/304")

    assert response.status_code == 304
    assert response.content == b""


async def test_route_errors_keep_their_own_envelope(error_app: FastAPI) -> None:
    async with _asgi_client(error_app) as http:
        response = await http.get("/test/route-error")

    assert response.status_code == 404
    assert response.json() == envelope(
        "plan_not_found", routes.PLAN_ERROR_MESSAGES[routes.PlanErrorCode.PLAN_NOT_FOUND]
    )


async def test_request_validation_keeps_fastapis_422_shape(error_app: FastAPI) -> None:
    async with _asgi_client(error_app) as http:
        response = await http.get("/test/framework/not-a-number")

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


async def test_a_body_over_the_cap_is_a_413_envelope_with_cors(error_app: FastAPI) -> None:
    body = b"x" * (routes.MAX_REQUEST_BODY_BYTES + 1)
    async with _asgi_client(error_app) as http:
        response = await http.post("/nowhere", content=body, headers={"Origin": FRONTEND})

    assert response.status_code == 413
    assert response.json() == envelope(
        "request_too_large", routes.PLAN_ERROR_MESSAGES[routes.PlanErrorCode.REQUEST_TOO_LARGE]
    )
    assert response.headers["access-control-allow-origin"] == FRONTEND


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_an_unhandled_exception_is_a_500_envelope_the_browser_can_read(
    error_app: FastAPI, main_logs: list[EventDict], method: str
) -> None:
    async with _asgi_client(error_app) as http:
        response = await http.request(method, "/test/crash", headers={"Origin": FRONTEND})

    assert response.status_code == 500
    assert response.json() == envelope(
        "internal_error", "Qualcosa è andato storto da parte nostra. Riprova tra qualche minuto."
    )
    assert "boom" not in response.text
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert response.headers["access-control-allow-credentials"] == "true"
    [entry] = main_logs
    assert (entry["event"], entry["log_level"]) == ("unhandled_error", "error")
    assert (entry["error"], entry["method"], entry["path"]) == (
        "RuntimeError",
        method,
        "/test/crash",
    )


async def test_a_500_carries_no_cors_headers_for_other_origins(
    error_app: FastAPI, main_logs: list[EventDict]
) -> None:
    async with _asgi_client(error_app) as http:
        evil = await http.get("/test/crash", headers={"Origin": "https://evil.example"})
        # TRIPTRACKER_ORIGIN is allowed on GET /plans/{id}/trip only.
        triptracker = await http.get("/test/crash", headers={"Origin": TRIPTRACKER})

    for response in (evil, triptracker):
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "internal_error"
        assert "access-control-allow-origin" not in response.headers


async def test_an_error_after_the_response_started_goes_to_the_server(
    error_app: FastAPI, main_logs: list[EventDict]
) -> None:
    """A started response (an SSE stream) cannot be replaced by a 500: the exception goes on
    to Starlette and uvicorn, which close the connection."""
    async with _asgi_client(error_app) as http:
        with pytest.raises(RuntimeError, match="after the response started"):
            await http.get("/test/stream")
    assert main_logs == []


async def test_the_body_caps_http_exception_passes_through() -> None:
    """`RequestBodyTooLargeError` raised while a route streams its body escapes FastAPI's
    handlers on purpose: RequestBodyLimitMiddleware, outside, answers it with its 413."""

    async def reads_a_capped_body(scope: Any, receive: Any, send: Any) -> None:
        raise routes.RequestBodyTooLargeError

    middleware = main.UnhandledErrorMiddleware(reads_a_capped_body)
    scope = {"type": "http", "method": "POST", "path": "/plans", "headers": []}
    with pytest.raises(routes.RequestBodyTooLargeError):
        await middleware(scope, None, None)  # pyright: ignore[reportArgumentType]


async def test_starlettes_last_resort_answers_with_the_envelope(
    error_app: FastAPI,
) -> None:
    response = await main.envelope_server_error(None, RuntimeError("x"))  # pyright: ignore[reportArgumentType]
    assert response.status_code == 500
    assert json.loads(bytes(response.body)) == envelope(
        "internal_error", main.APP_ERROR_MESSAGES[main.AppErrorCode.INTERNAL_ERROR]
    )
    assert error_app.exception_handlers[Exception] is main.envelope_server_error
