"""FastAPI application factory.

`app` is what uvicorn serves (`uvicorn app.main:app`); tests build their own instance with
`create_app(settings)`. `create_app` adds GET /health and `routes.install_routes` (the plan
routes, the Origin check through their dependencies, the CORS policy); the lifespan builds the
process-wide services (docs/backend-interfaces.md §3).

Every error answer uses the API's envelope `{"detail": {"code", "message", "data"}}` with an
Italian message, also those no route raises itself (`AppErrorCode`): an unknown path (404
`not_found`), a method the path doesn't take (405 `method_not_allowed`, with `Allow`), a body
the framework can't parse (400 `bad_request`), an unexpected exception (500
`internal_error`). A 413 is `routes`' `request_too_large`. Request validation keeps FastAPI's
422 shape, which the web form maps to its fields (routes.py). The 500 is answered by
`UnhandledErrorMiddleware`, inside the CORS policy, so an allowed origin gets its
`Access-Control-Allow-Origin` and the browser reads the envelope instead of a network error;
Starlette's own last-resort 500 sits outside every user middleware and would have none.

Test hook: when `app.state.planner_client_override` is set before the lifespan starts, it is
passed to `sessions.start_planner(client=...)`, so a test runs the real wiring against
`tests.fakes.FakeManagedAgentsClient` (conftest's `make_app(client=...)`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any, Literal, cast

import httpx
import structlog
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from fastapi.utils import is_body_allowed_for_status_code
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import jobs, routes, sessions
from app.config import LogLevel, Settings, add_plan_log_keys, get_settings
from app.db import create_engine, create_session_factory

log = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


# --- errors no route raises itself --------------------------------------------------------------


class AppErrorCode(StrEnum):
    """`detail.code` of errors the framework raises (routes.PlanErrorCode and auth.AuthErrorCode
    are the routes' own). The web app falls back to the HTTP status for codes it doesn't know."""

    NOT_FOUND = "not_found"  # 404: no route has this path
    METHOD_NOT_ALLOWED = "method_not_allowed"  # 405: the path exists, the method doesn't
    BAD_REQUEST = "bad_request"  # 400: e.g. a body that cannot be parsed at all
    INTERNAL_ERROR = "internal_error"  # 500: an unhandled exception
    HTTP_ERROR = "http_error"  # any other status the framework raises


APP_ERROR_MESSAGES: dict[AppErrorCode, str] = {
    AppErrorCode.NOT_FOUND: "Questo indirizzo non esiste.",
    AppErrorCode.METHOD_NOT_ALLOWED: "Questa operazione non è consentita qui.",
    AppErrorCode.BAD_REQUEST: "La richiesta non è valida: ricarica la pagina e riprova.",
    AppErrorCode.INTERNAL_ERROR: (
        "Qualcosa è andato storto da parte nostra. Riprova tra qualche minuto."
    ),
    AppErrorCode.HTTP_ERROR: "La richiesta non è andata a buon fine. Riprova tra qualche minuto.",
}
"""Italian user-facing messages (sentence case, what happened and what to do)."""

_CODE_BY_STATUS: dict[int, AppErrorCode] = {
    400: AppErrorCode.BAD_REQUEST,
    404: AppErrorCode.NOT_FOUND,
    405: AppErrorCode.METHOD_NOT_ALLOWED,
    500: AppErrorCode.INTERNAL_ERROR,
}


def error_detail(status_code: int) -> dict[str, Any]:
    """The envelope body for a framework error of `status_code` (413 is routes' own code)."""
    if status_code == 413:
        return cast(
            dict[str, Any], routes.plan_error(routes.PlanErrorCode.REQUEST_TOO_LARGE).detail
        )
    code = _CODE_BY_STATUS.get(status_code, AppErrorCode.HTTP_ERROR)
    return {"code": code.value, "message": APP_ERROR_MESSAGES[code], "data": None}


def _is_envelope(detail: object) -> bool:
    if not isinstance(detail, Mapping):
        return False
    body = cast(Mapping[str, object], detail)
    return isinstance(body.get("code"), str) and isinstance(body.get("message"), str)


async def envelope_http_exception(request: Request, exc: Exception) -> Response:
    """Handler of every `HTTPException`: the routes' and auth's (already an envelope) answer
    as FastAPI answers them; the framework's own (`detail` "Not Found", "Method Not
    Allowed", ...) get the envelope of their status, keeping their headers (`Allow`)."""
    assert isinstance(exc, StarletteHTTPException)
    if _is_envelope(exc.detail):
        return await http_exception_handler(request, exc)
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=exc.headers)
    return JSONResponse(
        {"detail": error_detail(exc.status_code)}, status_code=exc.status_code, headers=exc.headers
    )


def internal_error_response() -> JSONResponse:
    return JSONResponse({"detail": error_detail(500)}, status_code=500)


async def envelope_server_error(request: Request, exc: Exception) -> Response:
    """Starlette's last resort (`ServerErrorMiddleware`), for an exception raised outside
    `UnhandledErrorMiddleware` (in the CORS or body-cap middleware): the envelope at least,
    though without CORS headers."""
    return internal_error_response()


class UnhandledErrorMiddleware:
    """Answer an unhandled exception with 500 `internal_error` in the envelope, from inside
    the CORS policy (module docstring). `create_app` adds it before `routes.install_routes`,
    so it is the innermost user middleware: CORS wraps the body cap, which wraps this.

    An `HTTPException` passes through: the only one that gets here is the body cap's
    `RequestBodyTooLargeError`, raised while reading a body outside FastAPI's parsing, which
    `RequestBodyLimitMiddleware` answers with its 413. Once a response has started (an SSE
    stream), nothing can be answered any more: the exception goes on to the server."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, tracked_send)
        except StarletteHTTPException:
            raise
        except Exception as exc:
            if response_started:
                raise
            log.exception(
                "unhandled_error",
                error=type(exc).__name__,
                method=scope.get("method"),
                path=scope.get("path"),
            )
            await internal_error_response()(scope, receive, send)


def configure_logging(level: LogLevel) -> None:
    """JSON logs through structlog, one object per line, ISO timestamps in UTC.

    Every line carries `plan_id`, `session_id`, `agent` and `event_type` (spec "Log e
    resilienza"): from the call's own keywords, else from `structlog.contextvars` (code that
    works for one plan binds them there, and tasks it creates inherit them), else None
    (`config.add_plan_log_keys`)."""
    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_plan_log_keys,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the process-wide services and tear them down in reverse order.

    The database engine and the shared httpx client belong to this function; everything else
    (hub, session verifier, trip.json store, FX, Managed Agents client, consumers, resumed
    plans) is `sessions.start_planner`'s, which never raises for a missing key, lockfile or
    schema, so /health stays up. The hourly stuck-plan checker is started here (sessions must
    not import jobs) and cancelled by `sessions.stop_planner`.
    """
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory
    http = httpx.AsyncClient(follow_redirects=False)
    try:
        planner = await sessions.start_planner(
            settings,
            session_factory=session_factory,
            http=http,
            client=getattr(app.state, "planner_client_override", None),
        )
        try:
            planner.background_tasks.append(jobs.start_stuck_plan_checker(planner))
            app.state.planner = planner  # routes.get_planner
            app.state.hub = planner.hub  # SSE
            app.state.session_verifier = planner.session_verifier  # auth.current_user
            yield
        finally:
            await sessions.stop_planner(planner)
    finally:
        await http.aclose()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    # The spec allows only /health without current_user(): in production the interactive docs
    # and the OpenAPI document are not served at all (locally they help development).
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Trip Planner API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.add_exception_handler(StarletteHTTPException, envelope_http_exception)
    app.add_exception_handler(Exception, envelope_server_error)

    @app.get("/health", tags=["ops"])
    async def health() -> HealthResponse:
        """Railway healthcheck; no authentication."""
        return HealthResponse()

    # Before install_routes: middleware added later wraps it, so the CORS policy and the body
    # cap that install_routes adds sit outside it and see its 500 (UnhandledErrorMiddleware).
    app.add_middleware(UnhandledErrorMiddleware)
    routes.install_routes(app, settings)
    return app


app = create_app()
