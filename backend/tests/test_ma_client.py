"""`SdkManagedAgentsClient` and the module helpers of `app.ma_client`, fully offline.

The real SDK client (`anthropic==1.13.0`) runs on `httpx2`, so every test builds it on an
`httpx2.MockTransport` (respx never sees SDK traffic; tests/fakes/README.md, "Not the fake's
job"). Each test checks what goes on the wire (method, path, query, JSON body, beta header) and
what comes back through the seam: raw SSE (pings, empty data, `event: error`, payloads without
`type`, `session.usage`, unknown types, mid-stream drops), listings read from the raw body,
pagination, the error mapping by status, 1 + `MAX_RETRIES` attempts, the calls sent once
(`send_user_message`, `archive_session`, `delete_session`) and the call deadline.

SDK retry sleeps are made instant by the `no_backoff` fixture, except in the `retry-after`
deadline test, which needs the SDK's real (almost uncapped) delay.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx2
import pytest
from anthropic import AsyncAnthropic

from app import ma_client
from app.config import Settings
from app.ma_client import (
    DEFAULT_LIST_LIMIT,
    MANAGED_AGENTS_BETA,
    MAX_RETRIES,
    AgentPin,
    ApiRejectedError,
    ApiUnavailableError,
    EventPage,
    EventStream,
    ManagedAgentsError,
    RawEvent,
    SdkManagedAgentsClient,
    SessionBusyError,
    SessionInfo,
    SessionNotFoundError,
    SessionUsage,
    StreamDisconnectedError,
    ThreadInfo,
    archive_when_idle,
    budget_param,
    iter_session_history,
    iter_thread_history,
    parse_list_cost_cents,
    usage_from_event,
    wait_until_not_running,
)

BASE_URL = "http://ma.test"
SID = "sesn_011CZtest000000000000"
TID = "sthr_011CZflights00000000"
PRIMARY = "sthr_011CZprimary00000000"
PIN = AgentPin(id="agent_011CZcoordinator", version=3)
ATTEMPTS = 1 + MAX_RETRIES

Responder = Callable[[httpx2.Request], httpx2.Response | Awaitable[httpx2.Response]]


class Api:
    """The MockTransport handler: records every request, answers with `responder`."""

    def __init__(self, responder: Responder) -> None:
        self.responder = responder
        self.requests: list[httpx2.Request] = []

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        result = self.responder(request)
        if inspect.isawaitable(result):
            result = await result
        return result

    @property
    def request(self) -> httpx2.Request:
        assert len(self.requests) == 1, [str(r.url) for r in self.requests]
        return self.requests[0]


MakeClient = Callable[[Responder], tuple[SdkManagedAgentsClient, Api]]


@pytest.fixture
async def make_client() -> AsyncIterator[MakeClient]:
    """Build `SdkManagedAgentsClient` over a recording `httpx2.MockTransport`; closes them all."""
    clients: list[SdkManagedAgentsClient] = []

    def factory(responder: Responder) -> tuple[SdkManagedAgentsClient, Api]:
        api = Api(responder)
        sdk = AsyncAnthropic(
            api_key="test",
            base_url=BASE_URL,
            max_retries=MAX_RETRIES,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api)),
        )
        client = SdkManagedAgentsClient(sdk)
        clients.append(client)
        return client, api

    yield factory
    for client in clients:
        await client.aclose()


@pytest.fixture
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK retries without sleeping (the attempts themselves are unchanged)."""
    monkeypatch.setattr(AsyncAnthropic, "_calculate_retry_timeout", lambda *_args, **_kwargs: 0.0)


@pytest.fixture
def short_deadline(monkeypatch: pytest.MonkeyPatch) -> float:
    monkeypatch.setattr(ma_client, "CALL_DEADLINE_SECONDS", 0.2)
    return 0.2


# --- builders ---------------------------------------------------------------------------------


def json_response(
    body: Any, status: int = 200, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return httpx2.Response(status, json=body, headers=headers)


def api_error(status: int, error_type: str, message: str = "nope") -> httpx2.Response:
    return httpx2.Response(
        status, json={"type": "error", "error": {"type": error_type, "message": message}}
    )


def sse_response(body: str) -> httpx2.Response:
    return httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=body.encode()
    )


def sse(data: dict[str, Any] | str, event: str | None = None) -> str:
    """One SSE message: optional `event:` line, one `data:` line, blank line."""
    payload = data if isinstance(data, str) else json.dumps(data)
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {payload}\n\n"


def usage_json(cents: int | None = 12) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cache_read_input_tokens": 50,
        "cache_creation": {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 0},
        "server_tool_use": {"web_search_requests": 3, "web_fetch_requests": 0},
        "active_seconds": 42.5,
    }
    if cents is not None:
        usage["list_cost"] = {"amount": str(cents), "currency": "USD"}
    return usage


def session_json(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": SID,
        "type": "session",
        "status": "idle",
        "agent": {"type": "agent", "id": PIN.id, "version": PIN.version, "name": "coordinator"},
        "archived_at": None,
        "budget": {"type": "limit", "max_list_cost": {"amount": "60", "currency": "USD"}},
        "created_at": "2026-10-12T10:00:00.123456789Z",
        "updated_at": "2026-10-12T10:00:01Z",
        "environment_id": "env_011CZcloud",
        "metadata": {"plan_id": "7f3c", "agent_profile": "development"},
        "outcome_evaluations": [],
        "resources": [],
        "stats": {},
        "title": "plan 7f3c",
        "usage": usage_json(),
        "vault_ids": [],
    }
    body.update(overrides)
    return body


def thread_json(
    thread_id: str, name: str | None, parent: str | None, status: str, archived: bool = False
) -> dict[str, Any]:
    agent: dict[str, Any] = {"type": "agent", "id": "agent_x", "version": 1}
    if name is not None:
        agent["name"] = name
    return {
        "id": thread_id,
        "type": "session_thread",
        "agent": agent,
        "archived_at": "2026-10-12T10:05:00Z" if archived else None,
        "created_at": "2026-10-12T10:00:00Z",
        "updated_at": "2026-10-12T10:00:00Z",
        "parent_thread_id": parent,
        "session_id": SID,
        "status": status,
    }


def refuse(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused", request=request)


def body_of(request: httpx2.Request) -> Any:
    return json.loads(request.content)


def query_of(request: httpx2.Request) -> dict[str, str]:
    return dict(request.url.params)


def assert_beta(request: httpx2.Request) -> None:
    assert request.headers["anthropic-beta"] == MANAGED_AGENTS_BETA
    assert request.url.params["beta"] == "true"
    assert request.headers["x-api-key"] == "test"


def retry_counts(api: Api) -> list[str]:
    return [r.headers["x-stainless-retry-count"] for r in api.requests]


async def collect(stream: AsyncIterator[RawEvent]) -> list[RawEvent]:
    return [raw async for raw in stream]


async def drain(stream: AbstractAsyncContextManager[EventStream], into: list[RawEvent]) -> None:
    """Open `stream` and append every event to `into` until it ends or raises."""
    async with stream as events:
        async for raw in events:
            into.append(raw)


async def guarded[T](call: Awaitable[T]) -> T:
    """`call` under an outer 5 s bound: a broken deadline fails the test (with TimeoutError,
    not the expected `ApiUnavailableError`) instead of hanging it."""
    async with asyncio.timeout(5):
        return await call


async def drain_history(history: AsyncIterator[RawEvent], into: list[RawEvent]) -> None:
    async for raw in history:
        into.append(raw)


# --- pure helpers -----------------------------------------------------------------------------


def test_budget_param_is_the_api_shape() -> None:
    assert budget_param(400) == {
        "type": "limit",
        "max_list_cost": {"amount": "400", "currency": "USD"},
    }


@pytest.mark.parametrize("bad", [0, -60, True, 1.5, "60", None])
def test_budget_param_rejects_anything_but_a_positive_int(bad: Any) -> None:
    with pytest.raises(ValueError, match="positive int"):
        budget_param(bad)


@pytest.mark.parametrize(
    ("list_cost", "cents"),
    [
        ({"amount": "123", "currency": "USD"}, 123),
        ({"amount": "0", "currency": "USD"}, 0),
        ({"amount": 45, "currency": "USD"}, 45),
        (None, None),
        ({"currency": "USD"}, None),
        ({"amount": "123", "currency": "EUR"}, None),
        ({"amount": "123"}, None),
        ({"amount": "12.50", "currency": "USD"}, None),
        ({"amount": "-5", "currency": "USD"}, None),
    ],
)
def test_parse_list_cost_cents(list_cost: dict[str, Any] | None, cents: int | None) -> None:
    assert parse_list_cost_cents(list_cost) == cents


def test_usage_from_event_reads_the_snapshot() -> None:
    raw = {
        "id": "sevt_9",
        "type": "session.usage",
        "processed_at": "2026-10-12T10:00:00Z",
        "usage": usage_json(37),
        "budget": {"type": "limit", "max_list_cost": {"amount": "60", "currency": "USD"}},
    }
    assert usage_from_event(raw) == SessionUsage(
        list_cost_cents=37,
        input_tokens=1200,
        output_tokens=300,
        cache_read_input_tokens=50,
        web_search_requests=3,
        active_seconds=42.5,
    )


def test_usage_from_event_without_cost_or_usage() -> None:
    assert usage_from_event({"type": "session.usage", "usage": {"input_tokens": 5}}) == (
        SessionUsage(input_tokens=5)
    )
    assert usage_from_event({"type": "session.usage"}) == SessionUsage()
    assert usage_from_event({"type": "session.status_idle", "usage": usage_json()}) is None
    assert usage_from_event({"id": "sevt_1"}) is None


# --- construction -----------------------------------------------------------------------------


def test_from_settings_passes_the_key_retries_and_timeout(
    make_settings: Callable[..., Settings],
) -> None:
    client = SdkManagedAgentsClient.from_settings(
        make_settings(anthropic_api_key="sk-ant-test-not-a-real-key")
    )
    sdk = client._sdk
    assert sdk.api_key == "sk-ant-test-not-a-real-key"
    assert sdk.max_retries == MAX_RETRIES == 4
    assert sdk.timeout == ma_client.REQUEST_TIMEOUT_SECONDS
    once = client._sdk_once
    assert once.max_retries == 0
    assert once.api_key == sdk.api_key


def test_from_settings_without_a_key_raises(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        SdkManagedAgentsClient.from_settings(make_settings(anthropic_api_key=""))
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        SdkManagedAgentsClient.from_settings(make_settings())


async def test_aclose_closes_the_http_client() -> None:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _r: httpx2.Response(200)))
    sdk = AsyncAnthropic(api_key="test", base_url=BASE_URL, http_client=http)
    client = SdkManagedAgentsClient(sdk)
    await client.aclose()
    assert http.is_closed


# --- sessions ---------------------------------------------------------------------------------


async def test_create_session_request_and_parsed_session(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response(session_json()))
    info = await client.create_session(
        agent=PIN,
        environment_id="env_011CZcloud",
        budget_cents=60,
        metadata={"plan_id": "7f3c", "agent_profile": "development"},
        title="plan 7f3c",
    )

    request = api.request
    assert request.method == "POST"
    assert request.url.path == "/v1/sessions"
    assert_beta(request)
    assert body_of(request) == {
        "agent": {"type": "agent", "id": PIN.id, "version": 3},
        "environment_id": "env_011CZcloud",
        "budget": {"type": "limit", "max_list_cost": {"amount": "60", "currency": "USD"}},
        "metadata": {"plan_id": "7f3c", "agent_profile": "development"},
        "title": "plan 7f3c",
    }
    assert info == SessionInfo(
        id=SID,
        status="idle",
        usage=SessionUsage(
            list_cost_cents=12,
            input_tokens=1200,
            output_tokens=300,
            cache_read_input_tokens=50,
            web_search_requests=3,
            active_seconds=42.5,
        ),
        budget_cents=60,
        archived=False,
        metadata={"plan_id": "7f3c", "agent_profile": "development"},
        created_at=dt.datetime(2026, 10, 12, 10, 0, 0, 123456, tzinfo=dt.UTC),
    )


async def test_create_session_omits_a_missing_title(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response(session_json(title=None)))
    await client.create_session(
        agent=PIN, environment_id="env_1", budget_cents=400, metadata={"plan_id": "x"}
    )
    body = body_of(api.request)
    assert "title" not in body
    assert body["budget"]["max_list_cost"] == {"amount": "400", "currency": "USD"}


@pytest.mark.parametrize("bad", [0, -1, True])
async def test_a_bad_budget_is_rejected_before_any_request(
    make_client: MakeClient, bad: Any
) -> None:
    client, api = make_client(lambda _r: json_response(session_json()))
    with pytest.raises(ApiRejectedError) as create_error:
        await client.create_session(
            agent=PIN, environment_id="env_1", budget_cents=bad, metadata={}
        )
    with pytest.raises(ApiRejectedError) as update_error:
        await client.update_budget(SID, bad)
    assert create_error.value.error_type == update_error.value.error_type == "invalid_budget"
    assert api.requests == []


async def test_retrieve_session_reads_status_cost_budget_and_archive(
    make_client: MakeClient,
) -> None:
    usage = usage_json(cents=None)
    client, api = make_client(
        lambda _r: json_response(
            session_json(
                status="terminated",
                budget=None,
                usage=usage,
                archived_at="2026-10-12T11:00:00Z",
                created_at="2026-10-12T12:00:00+02:00",
            )
        )
    )
    info = await client.retrieve_session(SID)

    request = api.request
    assert request.method == "GET"
    assert request.url.path == f"/v1/sessions/{SID}"
    assert_beta(request)
    assert info.status == "terminated"
    assert info.budget_cents is None
    assert info.usage.list_cost_cents is None
    assert info.usage.input_tokens == 1200
    assert info.archived is True
    assert info.created_at == dt.datetime(2026, 10, 12, 10, 0, tzinfo=dt.UTC)


async def test_update_budget_request(make_client: MakeClient) -> None:
    budget = {"type": "limit", "max_list_cost": {"amount": "260", "currency": "USD"}}
    client, api = make_client(lambda _r: json_response(session_json(budget=budget)))
    info = await client.update_budget(SID, 260)

    request = api.request
    assert request.method == "POST"
    assert request.url.path == f"/v1/sessions/{SID}"
    assert_beta(request)
    assert body_of(request) == {"budget": budget}
    assert info.budget_cents == 260


@pytest.mark.parametrize(
    "error",
    [
        {
            "type": "invalid_request_error",
            "message": "budget_not_raised: max_list_cost must exceed the consumed list cost",
        },
        {"type": "invalid_request_error", "reason": "budget_not_raised", "message": "no"},
    ],
)
async def test_update_budget_not_raised(make_client: MakeClient, error: dict[str, Any]) -> None:
    client, api = make_client(
        lambda _r: httpx2.Response(400, json={"type": "error", "error": error})
    )
    with pytest.raises(ApiRejectedError) as raised:
        await client.update_budget(SID, 12)
    assert raised.value.error_type == "budget_not_raised"
    assert raised.value.status_code == 400
    assert len(api.requests) == 1


async def test_archive_session_request(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response(session_json(status="terminated")))
    await client.archive_session(SID)
    request = api.request
    assert request.method == "POST"
    assert request.url.path == f"/v1/sessions/{SID}/archive"
    assert_beta(request)


async def test_delete_session_request(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response({"id": SID, "type": "session_deleted"}))
    await client.delete_session(SID)
    request = api.request
    assert request.method == "DELETE"
    assert request.url.path == f"/v1/sessions/{SID}"
    assert_beta(request)


@pytest.mark.parametrize("method", ["archive_session", "delete_session"])
@pytest.mark.parametrize(
    ("status", "error_cls"),
    [
        (400, SessionBusyError),
        (409, SessionBusyError),
        (404, SessionNotFoundError),
        (429, ApiUnavailableError),
        (500, ApiUnavailableError),
        (403, ApiRejectedError),
    ],
)
async def test_archive_and_delete_are_sent_once(
    make_client: MakeClient,
    no_backoff: None,
    method: str,
    status: int,
    error_cls: type[ManagedAgentsError],
) -> None:
    client, api = make_client(lambda _r: api_error(status, "invalid_request_error"))
    with pytest.raises(error_cls) as raised:
        await getattr(client, method)(SID)
    assert type(raised.value) is error_cls
    assert raised.value.status_code == status
    assert len(api.requests) == 1


async def test_list_sessions_request_and_pages(make_client: MakeClient) -> None:
    pages = {
        None: {"data": [session_json(id="sesn_a")], "next_page": "c1", "prev_page": None},
        "c1": {
            "data": [session_json(id="sesn_b", archived_at="2026-07-01T00:00:00Z")],
            "next_page": None,
        },
    }
    client, api = make_client(lambda r: json_response(pages[r.url.params.get("page")]))
    cutoff = dt.datetime(2026, 7, 14, 2, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    sessions = await client.list_sessions(created_before=cutoff)

    assert [s.id for s in sessions] == ["sesn_a", "sesn_b"]
    assert [s.archived for s in sessions] == [False, True]
    assert sessions[0].metadata == {"plan_id": "7f3c", "agent_profile": "development"}
    first, second = api.requests
    for request in api.requests:
        assert request.method == "GET"
        assert request.url.path == "/v1/sessions"
        assert_beta(request)
    assert query_of(first) == {
        "beta": "true",
        "created_at[lt]": "2026-07-14T00:00:00+00:00",
        "include_archived": "true",
        "order": "asc",
    }
    assert query_of(second) == {**query_of(first), "page": "c1"}


async def test_list_sessions_can_exclude_archived(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response({"data": [], "next_page": None}))
    assert (
        await client.list_sessions(
            created_before=dt.datetime(2026, 7, 14, tzinfo=dt.UTC), include_archived=False
        )
        == []
    )
    assert api.request.url.params["include_archived"] == "false"


async def test_naive_datetimes_are_refused_before_any_request(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response({"data": [], "next_page": None}))
    naive = dt.datetime(2026, 7, 14)  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="timezone-aware"):
        await client.list_sessions(created_before=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        await client.list_events(SID, since=naive)
    assert api.requests == []


# --- sending events ---------------------------------------------------------------------------


async def test_send_user_message_body(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response({"data": []}))
    await client.send_user_message(SID, "Today is 2026-10-12 (Europe/Rome).")
    request = api.request
    assert request.method == "POST"
    assert request.url.path == f"/v1/sessions/{SID}/events"
    assert_beta(request)
    assert body_of(request) == {
        "events": [
            {
                "type": "user.message",
                "content": [{"type": "text", "text": "Today is 2026-10-12 (Europe/Rome)."}],
            }
        ]
    }


async def test_send_custom_tool_result_body(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response({"data": []}))
    await client.send_custom_tool_result(SID, "sevt_42", "Plan accepted.", False)
    await client.send_custom_tool_result(SID, "sevt_43", "book_by == scheduled_for", True)
    first, second = api.requests
    assert first.url.path == second.url.path == f"/v1/sessions/{SID}/events"
    assert body_of(first) == {
        "events": [
            {
                "type": "user.custom_tool_result",
                "custom_tool_use_id": "sevt_42",
                "content": [{"type": "text", "text": "Plan accepted."}],
                "is_error": False,
            }
        ]
    }
    assert body_of(second)["events"][0]["is_error"] is True
    assert "session_thread_id" not in body_of(second)["events"][0]


async def test_send_interrupt_body(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response({"data": []}))
    await client.send_interrupt(SID)
    await client.send_interrupt(SID, TID)
    first, second = api.requests
    assert_beta(first)
    assert body_of(first) == {"events": [{"type": "user.interrupt"}]}
    assert body_of(second) == {"events": [{"type": "user.interrupt", "session_thread_id": TID}]}


@pytest.mark.parametrize(
    "fail",
    [
        lambda _r: api_error(500, "api_error"),
        lambda _r: api_error(429, "rate_limit_error"),
        lambda _r: api_error(409, "invalid_request_error"),
        lambda r: refuse(r),
    ],
    ids=["500", "429", "409", "connect"],
)
async def test_send_user_message_is_never_retried(
    make_client: MakeClient, no_backoff: None, fail: Responder
) -> None:
    client, api = make_client(fail)
    with pytest.raises(ApiUnavailableError):
        await client.send_user_message(SID, "hello")
    assert len(api.requests) == 1


async def test_send_user_message_at_the_budget_is_rejected(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: api_error(400, "invalid_request_error"))
    with pytest.raises(ApiRejectedError) as raised:
        await client.send_user_message(SID, "hello")
    assert raised.value.status_code == 400
    assert raised.value.error_type == "invalid_request_error"
    assert len(api.requests) == 1


async def test_custom_tool_results_and_interrupts_are_retried(
    make_client: MakeClient, no_backoff: None
) -> None:
    answers = iter([api_error(500, "api_error"), api_error(529, "overloaded_error")])
    client, api = make_client(lambda _r: next(answers, json_response({"data": []})))
    await client.send_custom_tool_result(SID, "sevt_42", "Plan accepted.", False)
    assert retry_counts(api) == ["0", "1", "2"]
    assert body_of(api.requests[0]) == body_of(api.requests[2])

    answers = iter([api_error(503, "api_error")])
    await client.send_interrupt(SID)
    assert len(api.requests) == 5


# --- streams ----------------------------------------------------------------------------------

USAGE_EVENT_DATA = {
    "id": "sevt_3",
    "processed_at": "2026-10-12T10:00:00.300Z",
    "usage": usage_json(21),
    "budget": {"type": "limit", "max_list_cost": {"amount": "60", "currency": "USD"}},
}


def happy_stream() -> str:
    return "".join(
        [
            ": heartbeat comment\n\n",
            sse({}, event="ping"),
            sse(
                {
                    "id": "sevt_1",
                    "type": "session.status_running",
                    "processed_at": "2026-10-12T10:00:00.100Z",
                },
                event="session.status_running",
            ),
            # No `event:` line: the payload's own type is used.
            sse(
                {
                    "id": "sevt_2",
                    "type": "agent.message",
                    "processed_at": "2026-10-12T10:00:00.200Z",
                    "content": [{"type": "text", "text": "Cerco i voli."}],
                }
            ),
            # No `type` in the payload: taken from the event name. Dropped by the SDK's typed
            # iterator in 1.13.0, yielded here.
            sse(USAGE_EVENT_DATA, event="session.usage"),
            sse("", event="agent.message"),  # empty data: skipped
            "event: ping\ndata: \n\n",
            # A type the SDK doesn't know.
            sse(
                {
                    "id": "sevt_4",
                    "type": "session.checkpoint_created",
                    "processed_at": "2026-10-12T10:00:00.400Z",
                    "checkpoint": {"n": 1},
                },
                event="session.checkpoint_created",
            ),
            # The payload's type wins over the event name.
            sse(
                {"id": "sevt_5", "type": "agent.thinking", "processed_at": "2026-10-12T10:00:01Z"},
                event="agent.message",
            ),
            sse(
                {
                    "id": "sevt_6",
                    "type": "session.status_terminated",
                    "processed_at": "2026-10-12T10:00:02Z",
                },
                event="session.status_terminated",
            ),
            sse({"id": "sevt_7", "type": "agent.message"}, event="agent.message"),
        ]
    )


async def test_stream_session_yields_raw_events_including_usage_and_unknown_types(
    make_client: MakeClient,
) -> None:
    client, api = make_client(lambda _r: sse_response(happy_stream()))
    async with client.stream_session(SID) as events:
        # Entering returns once the HTTP stream is open: the request is already sent.
        assert len(api.requests) == 1
        received = await collect(events)

    request = api.request
    assert request.method == "GET"
    assert request.url.path == f"/v1/sessions/{SID}/events/stream"
    assert_beta(request)
    assert query_of(request) == {"beta": "true"}  # no event_deltas previews
    assert request.extensions["timeout"] == {
        "connect": ma_client.REQUEST_TIMEOUT_SECONDS,
        "read": ma_client.STREAM_READ_TIMEOUT_SECONDS,
        "write": ma_client.REQUEST_TIMEOUT_SECONDS,
        "pool": ma_client.REQUEST_TIMEOUT_SECONDS,
    }
    assert received == [
        {
            "id": "sevt_1",
            "type": "session.status_running",
            "processed_at": "2026-10-12T10:00:00.100Z",
        },
        {
            "id": "sevt_2",
            "type": "agent.message",
            "processed_at": "2026-10-12T10:00:00.200Z",
            "content": [{"type": "text", "text": "Cerco i voli."}],
        },
        {**USAGE_EVENT_DATA, "type": "session.usage"},
        {
            "id": "sevt_4",
            "type": "session.checkpoint_created",
            "processed_at": "2026-10-12T10:00:00.400Z",
            "checkpoint": {"n": 1},
        },
        {"id": "sevt_5", "type": "agent.thinking", "processed_at": "2026-10-12T10:00:01Z"},
        {
            "id": "sevt_6",
            "type": "session.status_terminated",
            "processed_at": "2026-10-12T10:00:02Z",
        },
    ]
    usage = usage_from_event(received[2])
    assert usage is not None
    assert usage.list_cost_cents == 21


async def test_stream_session_ends_on_session_deleted(make_client: MakeClient) -> None:
    body = sse({"id": "sevt_1", "type": "session.deleted"}, event="session.deleted") + sse(
        {"id": "sevt_2", "type": "agent.message"}
    )
    client, _api = make_client(lambda _r: sse_response(body))
    async with client.stream_session(SID) as events:
        assert [raw["id"] for raw in await collect(events)] == ["sevt_1"]


async def test_session_stream_is_not_ended_by_a_thread_terminating(
    make_client: MakeClient,
) -> None:
    body = sse(
        {"id": "sevt_1", "type": "session.thread_status_terminated", "session_thread_id": TID}
    )
    client, _api = make_client(lambda _r: sse_response(body))
    received: list[RawEvent] = []
    with pytest.raises(StreamDisconnectedError, match="without a terminal event"):
        await drain(client.stream_session(SID), received)
    assert [raw["id"] for raw in received] == ["sevt_1"]


async def test_stream_thread_path_and_end(make_client: MakeClient) -> None:
    body = "".join(
        [
            sse({}, event="ping"),
            sse(
                {"id": "sevt_1", "type": "agent.tool_progress", "session_thread_id": TID},
                event="agent.tool_progress",
            ),
            # Another thread terminating does not end this thread's stream.
            sse(
                {
                    "id": "sevt_2",
                    "type": "session.thread_status_terminated",
                    "session_thread_id": "sthr_other",
                }
            ),
            sse(
                {
                    "id": "sevt_3",
                    "type": "session.thread_status_terminated",
                    "session_thread_id": TID,
                    "agent_name": "flights",
                }
            ),
            sse({"id": "sevt_4", "type": "agent.message"}),
        ]
    )
    client, api = make_client(lambda _r: sse_response(body))
    async with client.stream_thread(SID, TID) as events:
        received = await collect(events)

    request = api.request
    assert request.method == "GET"
    assert request.url.path == f"/v1/sessions/{SID}/threads/{TID}/stream"
    assert_beta(request)
    assert query_of(request) == {"beta": "true"}
    assert [raw["id"] for raw in received] == ["sevt_1", "sevt_2", "sevt_3"]
    assert received[0]["type"] == "agent.tool_progress"


async def test_stream_error_event_raises_with_its_type(make_client: MakeClient) -> None:
    body = sse({"id": "sevt_1", "type": "agent.message"}) + sse(
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
        event="error",
    )
    client, _api = make_client(lambda _r: sse_response(body))
    received: list[RawEvent] = []
    with pytest.raises(StreamDisconnectedError) as raised:
        await drain(client.stream_session(SID), received)
    assert raised.value.error_type == "overloaded_error"
    assert "Overloaded" not in str(raised.value)
    assert [raw["id"] for raw in received] == ["sevt_1"]


async def test_stream_error_event_with_a_bad_payload(make_client: MakeClient) -> None:
    client, _api = make_client(lambda _r: sse_response(sse("not json", event="error")))
    with pytest.raises(StreamDisconnectedError) as raised:
        async with client.stream_session(SID) as events:
            await collect(events)
    assert raised.value.error_type is None


@pytest.mark.parametrize("payload", ["[1, 2]", '"text"', "{not json", "42"])
async def test_stream_payload_that_is_not_an_object_disconnects(
    make_client: MakeClient, payload: str
) -> None:
    client, _api = make_client(lambda _r: sse_response(sse(payload, event="agent.message")))
    with pytest.raises(StreamDisconnectedError, match="SSE payload"):
        async with client.stream_session(SID) as events:
            await collect(events)


async def test_stream_that_just_ends_disconnects(make_client: MakeClient) -> None:
    body = sse({"id": "sevt_1", "type": "session.status_idle"}, event="session.status_idle")
    client, _api = make_client(lambda _r: sse_response(body))
    with pytest.raises(StreamDisconnectedError, match="without a terminal event"):
        async with client.stream_session(SID) as events:
            await collect(events)


class DroppingBody(httpx2.AsyncByteStream):
    """An SSE body that sends `chunks`, then fails like a dropped connection."""

    def __init__(self, chunks: list[bytes], error: Exception | None) -> None:
        self.chunks = chunks
        self.error = error
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "error",
    [
        httpx2.ReadError("connection reset by peer"),
        httpx2.ReadTimeout("read timed out"),
        httpx2.RemoteProtocolError("peer closed connection without sending complete message"),
    ],
    ids=["ReadError", "ReadTimeout", "RemoteProtocolError"],
)
async def test_mid_stream_transport_error_disconnects(
    make_client: MakeClient, error: Exception
) -> None:
    first = sse({"id": "sevt_1", "type": "agent.message"}, event="agent.message").encode()
    body = DroppingBody([first], error)
    client, _api = make_client(
        lambda _r: httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=body)
    )
    received: list[RawEvent] = []
    with pytest.raises(StreamDisconnectedError) as raised:
        await drain(client.stream_session(SID), received)
    assert [raw["id"] for raw in received] == ["sevt_1"]
    assert raised.value.__cause__ is error
    assert body.closed


async def test_leaving_a_stream_early_closes_it(make_client: MakeClient) -> None:
    chunks = [
        sse({"id": f"sevt_{n}", "type": "agent.message"}, event="agent.message").encode()
        for n in range(3)
    ]
    body = DroppingBody(chunks, None)
    client, _api = make_client(
        lambda _r: httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=body)
    )
    async with client.stream_session(SID) as events:
        async for raw in events:
            assert raw["id"] == "sevt_0"
            break
    assert body.closed


@pytest.mark.parametrize(
    ("status", "error_cls", "attempts"),
    [
        (404, SessionNotFoundError, 1),
        (401, ApiRejectedError, 1),
        (403, ApiRejectedError, 1),
        (400, ApiRejectedError, 1),
        (429, ApiUnavailableError, ATTEMPTS),
        (503, ApiUnavailableError, ATTEMPTS),
        (529, ApiUnavailableError, ATTEMPTS),
    ],
)
async def test_opening_a_stream_maps_errors(
    make_client: MakeClient,
    no_backoff: None,
    status: int,
    error_cls: type[ManagedAgentsError],
    attempts: int,
) -> None:
    client, api = make_client(lambda _r: api_error(status, "some_error"))
    with pytest.raises(error_cls) as raised:
        async with client.stream_thread(SID, TID):
            pytest.fail("the stream must not open")
    assert type(raised.value) is error_cls
    assert raised.value.status_code == status
    assert len(api.requests) == attempts


async def test_opening_a_stream_is_bounded_by_the_deadline(
    make_client: MakeClient, short_deadline: float
) -> None:
    async def hang(_request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    client, _api = make_client(hang)
    with pytest.raises(ApiUnavailableError) as raised:
        await guarded(drain(client.stream_session(SID), []))
    assert raised.value.error_type == "deadline"


async def test_an_error_in_the_callers_block_is_not_remapped(make_client: MakeClient) -> None:
    client, _api = make_client(lambda _r: sse_response(happy_stream()))

    async def fail_on_first_event() -> None:
        async with client.stream_session(SID) as events:
            async for raw in events:
                raise KeyError(raw["id"])

    with pytest.raises(KeyError):
        await fail_on_first_event()


# --- listings ---------------------------------------------------------------------------------

# Events exactly as the server sends them: an empty interrupt id, no optional keys, timestamps
# with milliseconds and an offset, a type the SDK doesn't know.
LISTED_EVENTS: list[dict[str, Any]] = [
    {"id": "", "type": "user.interrupt", "processed_at": "2026-10-12T10:00:00.120Z"},
    {
        "id": "sevt_2",
        "type": "agent.custom_tool_use",
        "processed_at": "2026-10-12T12:00:00.000+02:00",
        "name": "submit_plan",
        "input": {"title": "Lisbona"},
    },
    {"id": "sevt_3", "type": "session.checkpoint_created", "processed_at": "2026-10-12T10:00:01Z"},
]


async def test_list_events_returns_the_raw_body(make_client: MakeClient) -> None:
    client, api = make_client(
        lambda _r: json_response({"data": LISTED_EVENTS, "next_page": "cursor_2"})
    )
    since = dt.datetime(2026, 10, 12, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    page = await client.list_events(SID, since=since, page="cursor_1")

    request = api.request
    assert request.method == "GET"
    assert request.url.path == f"/v1/sessions/{SID}/events"
    assert_beta(request)
    assert query_of(request) == {
        "beta": "true",
        "order": "asc",
        "limit": str(DEFAULT_LIST_LIMIT),
        "page": "cursor_1",
        "created_at[gte]": "2026-10-12T08:00:00+00:00",
    }
    # No nulls added, timestamps untouched, unknown types kept as sent.
    assert page == EventPage(events=LISTED_EVENTS, next_page="cursor_2")


async def test_list_events_defaults(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response({"data": [], "next_page": ""}))
    assert await client.list_events(SID, limit=10) == EventPage(events=[], next_page=None)
    assert query_of(api.request) == {"beta": "true", "order": "asc", "limit": "10"}


async def test_list_thread_events_request(make_client: MakeClient) -> None:
    client, api = make_client(
        lambda _r: json_response({"data": LISTED_EVENTS[1:], "next_page": None})
    )
    page = await client.list_thread_events(SID, TID, page="c9")

    request = api.request
    assert request.method == "GET"
    assert request.url.path == f"/v1/sessions/{SID}/threads/{TID}/events"
    assert_beta(request)
    assert query_of(request) == {"beta": "true", "limit": str(DEFAULT_LIST_LIMIT), "page": "c9"}
    assert page == EventPage(events=LISTED_EVENTS[1:], next_page=None)


@pytest.mark.parametrize(
    "body",
    [
        {"next_page": None},
        {"data": "nope"},
        {"data": [1]},
        {"data": [], "next_page": 3},
        [],
    ],
)
async def test_malformed_listing_body(make_client: MakeClient, body: Any) -> None:
    client, _api = make_client(lambda _r: json_response(body))
    with pytest.raises(ManagedAgentsError) as raised:
        await client.list_events(SID)
    assert raised.value.error_type == "malformed_response"


def paged(pages: dict[str | None, dict[str, Any]]) -> Responder:
    return lambda r: json_response(pages[r.url.params.get("page")])


async def test_iter_session_history_follows_every_page(make_client: MakeClient) -> None:
    pages: dict[str | None, dict[str, Any]] = {
        None: {"data": LISTED_EVENTS[:2], "next_page": "c1"},
        "c1": {"data": [], "next_page": "c2"},
        "c2": {"data": LISTED_EVENTS[2:], "next_page": None},
    }
    client, api = make_client(paged(pages))
    since = dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.UTC)
    events = [raw async for raw in iter_session_history(client, SID, since=since)]

    assert events == LISTED_EVENTS
    assert [r.url.params.get("page") for r in api.requests] == [None, "c1", "c2"]
    assert {r.url.params["created_at[gte]"] for r in api.requests} == {"2026-10-12T09:00:00+00:00"}


async def test_iter_thread_history_follows_every_page(make_client: MakeClient) -> None:
    pages: dict[str | None, dict[str, Any]] = {
        None: {"data": LISTED_EVENTS[:1], "next_page": "t1"},
        "t1": {"data": LISTED_EVENTS[1:], "next_page": None},
    }
    client, api = make_client(paged(pages))
    events = [raw async for raw in iter_thread_history(client, SID, TID)]

    assert events == LISTED_EVENTS
    assert [r.url.path for r in api.requests] == [f"/v1/sessions/{SID}/threads/{TID}/events"] * 2
    assert [r.url.params.get("page") for r in api.requests] == [None, "t1"]


async def test_history_stops_on_a_cursor_that_does_not_advance(make_client: MakeClient) -> None:
    client, api = make_client(lambda _r: json_response({"data": [], "next_page": "same"}))
    with pytest.raises(ManagedAgentsError, match="did not advance"):
        _ = [raw async for raw in iter_session_history(client, SID)]
    assert len(api.requests) == 2


async def test_history_propagates_a_failing_page(make_client: MakeClient, no_backoff: None) -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.params.get("page") == "c1":
            return api_error(500, "api_error")
        return json_response({"data": LISTED_EVENTS[:1], "next_page": "c1"})

    client, api = make_client(respond)
    received: list[RawEvent] = []
    with pytest.raises(ApiUnavailableError):
        await drain_history(iter_session_history(client, SID), received)
    assert received == LISTED_EVENTS[:1]
    assert len(api.requests) == 1 + ATTEMPTS


async def test_list_threads_reads_every_page(make_client: MakeClient) -> None:
    pages: dict[str | None, dict[str, Any]] = {
        None: {"data": [thread_json(PRIMARY, "coordinator", None, "idle")], "next_page": "n1"},
        "n1": {
            "data": [
                thread_json(TID, "flights", PRIMARY, "running"),
                thread_json("sthr_old", "activities", PRIMARY, "idle", archived=True),
                thread_json("sthr_adv", None, PRIMARY, "idle"),
            ],
            "next_page": None,
        },
    }
    client, api = make_client(paged(pages))
    threads = await client.list_threads(SID)

    assert threads == [
        ThreadInfo(id=PRIMARY, agent_name="coordinator", parent_thread_id=None, status="idle"),
        ThreadInfo(id=TID, agent_name="flights", parent_thread_id=PRIMARY, status="running"),
        ThreadInfo(
            id="sthr_old",
            agent_name="activities",
            parent_thread_id=PRIMARY,
            status="idle",
            archived=True,
        ),
        ThreadInfo(id="sthr_adv", agent_name=None, parent_thread_id=PRIMARY, status="idle"),
    ]
    assert threads[0].is_primary
    for request in api.requests:
        assert request.method == "GET"
        assert request.url.path == f"/v1/sessions/{SID}/threads"
        assert_beta(request)
    assert [query_of(r) for r in api.requests] == [{"beta": "true"}, {"beta": "true", "page": "n1"}]


async def test_archive_thread_request(make_client: MakeClient) -> None:
    client, api = make_client(
        lambda _r: json_response(thread_json(TID, "flights", PRIMARY, "idle", archived=True))
    )
    await client.archive_thread(SID, TID)
    request = api.request
    assert request.method == "POST"
    assert request.url.path == f"/v1/sessions/{SID}/threads/{TID}/archive"
    assert_beta(request)


# --- error mapping, retries, deadline ---------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error_cls", "attempts"),
    [
        (400, ApiRejectedError, 1),
        (401, ApiRejectedError, 1),
        (403, ApiRejectedError, 1),
        (404, SessionNotFoundError, 1),
        (413, ApiRejectedError, 1),
        (422, ApiRejectedError, 1),
        (408, ApiUnavailableError, ATTEMPTS),
        (409, ApiUnavailableError, ATTEMPTS),
        (429, ApiUnavailableError, ATTEMPTS),
        (500, ApiUnavailableError, ATTEMPTS),
        (502, ApiUnavailableError, ATTEMPTS),
        (503, ApiUnavailableError, ATTEMPTS),
        (529, ApiUnavailableError, ATTEMPTS),
    ],
)
async def test_errors_are_mapped_by_status_after_the_retries(
    make_client: MakeClient,
    no_backoff: None,
    status: int,
    error_cls: type[ManagedAgentsError],
    attempts: int,
) -> None:
    client, api = make_client(
        lambda _r: api_error(status, "some_error", message="echo of SECRET-CONTENT")
    )
    with pytest.raises(error_cls) as raised:
        await client.retrieve_session(SID)

    error = raised.value
    assert type(error) is error_cls
    assert error.status_code == status
    assert error.error_type == "some_error"
    assert "SECRET-CONTENT" not in str(error)
    assert error.__cause__ is None  # the SDK error embeds the response body
    assert retry_counts(api) == [str(n) for n in range(attempts)]


@pytest.mark.parametrize(
    ("exc", "error_type"),
    [
        (httpx2.ConnectError, "connection_error"),
        (httpx2.ReadError, "connection_error"),
        (httpx2.ConnectTimeout, "timeout"),
        (httpx2.ReadTimeout, "timeout"),
    ],
)
async def test_transport_errors_are_retried_then_unavailable(
    make_client: MakeClient,
    no_backoff: None,
    exc: type[httpx2.TransportError],
    error_type: str,
) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise exc("boom", request=request)

    client, api = make_client(fail)
    with pytest.raises(ApiUnavailableError) as raised:
        await client.list_threads(SID)
    assert raised.value.error_type == error_type
    assert raised.value.status_code is None
    assert len(api.requests) == ATTEMPTS


async def test_a_transient_error_then_success(make_client: MakeClient, no_backoff: None) -> None:
    answers = iter([api_error(429, "rate_limit_error"), api_error(529, "overloaded_error")])
    client, api = make_client(lambda _r: next(answers, json_response(session_json())))
    info = await client.retrieve_session(SID)
    assert info.id == SID
    assert retry_counts(api) == ["0", "1", "2"]


async def test_retry_after_beyond_the_deadline_is_unavailable(
    make_client: MakeClient, short_deadline: float
) -> None:
    # No `no_backoff`: the SDK honours `retry-after` with no useful cap; the deadline bounds it.
    client, api = make_client(
        lambda _r: httpx2.Response(
            429,
            headers={"retry-after": "100000"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
        )
    )
    with pytest.raises(ApiUnavailableError) as raised:
        await guarded(
            client.create_session(agent=PIN, environment_id="env_1", budget_cents=60, metadata={})
        )
    assert raised.value.error_type == "deadline"
    assert len(api.requests) == 1


async def test_a_hanging_call_hits_the_deadline(
    make_client: MakeClient, short_deadline: float
) -> None:
    async def hang(_request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    client, _api = make_client(hang)
    with pytest.raises(ApiUnavailableError) as raised:
        await guarded(client.list_events(SID))
    assert raised.value.error_type == "deadline"


async def test_a_body_that_is_not_json_is_malformed(make_client: MakeClient) -> None:
    client, _api = make_client(lambda _r: httpx2.Response(200, content=b"<html>oops</html>"))
    with pytest.raises(ManagedAgentsError) as raised:
        await client.retrieve_session(SID)
    assert type(raised.value) is ManagedAgentsError
    assert raised.value.error_type == "malformed_response"


# --- status polling and archive ---------------------------------------------------------------


def polling_api(sequence: list[str]) -> Responder:
    remaining = iter(sequence)
    last = sequence[-1]

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST" and request.url.path.endswith("/archive"):
            return json_response(session_json(status="terminated"))
        return json_response(session_json(status=next(remaining, last)))

    return respond


async def test_wait_until_not_running_polls_until_idle(make_client: MakeClient) -> None:
    client, api = make_client(polling_api(["running", "running", "idle"]))
    info = await wait_until_not_running(client, SID, attempts=5, delay_seconds=0)
    assert info.status == "idle"
    assert len(api.requests) == 3


async def test_wait_until_not_running_gives_up(make_client: MakeClient) -> None:
    client, api = make_client(polling_api(["running"]))
    with pytest.raises(SessionBusyError):
        await wait_until_not_running(client, SID, attempts=3, delay_seconds=0)
    assert len(api.requests) == 3
    with pytest.raises(ValueError, match="attempts"):
        await wait_until_not_running(client, SID, attempts=0)


async def test_archive_when_idle_polls_then_archives_once(make_client: MakeClient) -> None:
    client, api = make_client(polling_api(["running", "idle"]))
    await archive_when_idle(client, SID)
    assert [(r.method, r.url.path) for r in api.requests] == [
        ("GET", f"/v1/sessions/{SID}"),
        ("GET", f"/v1/sessions/{SID}"),
        ("POST", f"/v1/sessions/{SID}/archive"),
    ]


async def test_archive_when_idle_never_archives_a_running_session(
    make_client: MakeClient,
) -> None:
    client, api = make_client(polling_api(["running"]))  # ~1.8 s of real polling delays
    with pytest.raises(SessionBusyError):
        await archive_when_idle(client, SID)
    assert {r.method for r in api.requests} == {"GET"}
    assert len(api.requests) == ma_client.ARCHIVE_POLL_ATTEMPTS
