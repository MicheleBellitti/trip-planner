"""The Managed Agents seam: the only module that imports the Anthropic SDK.

Spec: "Backend FastAPI" (the consumer's six steps, POST /plans/{id}/interrupt), "Costi e
controlli di spesa" (per-session budget), "Log e resilienza" (429/5xx retries,
`session.status_rescheduled`) and "Sicurezza e privacy" (archive when the plan is ready, delete
after 90 days). API facts and their sources: docs/managed-agents-notes.md §2d-§2g and §2j.

Everything above this module (consumer, sessions, jobs, cli) talks to the `ManagedAgentsClient`
Protocol and never to `anthropic` types. Two implementations exist:

- `SdkManagedAgentsClient` (here): `anthropic==1.13.0`, `client.beta.sessions.*`, real money.
- `tests.fakes.FakeManagedAgentsClient`: replays scripted JSONL event sequences offline and
  records what the backend sent (design in backend/tests/fakes/README.md).

Raw events
----------
Events cross the seam as plain JSON dicts (`RawEvent`) holding the server's JSON as sent: the
`data:` payload of an SSE message (`json.loads(sse.data)`, plus `type` from the SSE `event:`
name when the payload lacks one), or one item of a listing's `data` array read from the raw
HTTP body (`with_raw_response.list(...)` then `http_response.json()`). Never
`event.model_dump()` of an SDK model: it adds every unset optional key as null, rewrites
timestamps (`...00.123Z` becomes `...00.123000Z`) and parses an unknown type as the union's
first variant (`BetaManagedAgentsUserMessageEvent`, with a spurious `content: null`) [SDK
_models.py:644-649; offline]. The fake replays JSON fixtures as they are written. Every event
has `id` (`sevt_...`, may be empty for `user.interrupt` [SKILL]), `type` and `processed_at`; the
other keys depend on the type (catalog: notes §2g). Optional keys may be absent or null, so
readers use `.get()`. Timestamps are compared as parsed datetimes, never as strings.

Streams deliver only events emitted after they open and never replay (notes §2f). That is why
`stream_session()` / `stream_thread()` return async context managers: entering one returns once
the HTTP stream is open, so the caller can open first and send the first message second.

Money
-----
Every amount here is **US cents of list cost** (`budget_cents`, `SessionUsage.list_cost_cents`),
the unit of `SESSION_BUDGET_CENTS`, `MONTHLY_LIMIT_CENTS` and `plans.cost_cents`. It is never
the EUR `costCents` of a TripTracker booking.

Retries
-------
`SdkManagedAgentsClient` builds `AsyncAnthropic(max_retries=MAX_RETRIES)`. The SDK's
`max_retries` counts retries AFTER the first attempt (`for retries_taken in range(max_retries +
1)` [SDK _base_client.py:1159]), so `MAX_RETRIES = 4` gives the spec's "massimo 5 tentativi":
one attempt plus four retries. The SDK retries 408, 409, 429, every status >= 500 (529
included) and connection errors, with backoff `min(0.5 * 2**n, 8) s * U(0.75, 1)`; a
`retry-after-ms` or `retry-after` header wins and is capped only at ~49.7 days [SDK
_base_client.py:812-850], and the per-request `timeout` does not bound the sleeps between
attempts. Every non-stream call is therefore wrapped in `asyncio.timeout(CALL_DEADLINE_SECONDS)`
and a deadline hit is an `ApiUnavailableError`.

Errors are classified by HTTP status, not by exception class (the SDK raises a plain
`APIStatusError` for a 408 and `ConflictError` for a 409): what the SDK treats as transient and
still fails after the retries (408, 409, 429, >= 500, connection errors, timeouts) is
`ApiUnavailableError`; 404 is `SessionNotFoundError`; any other 4xx is `ApiRejectedError`
(`_RETRYABLE_4XX` / `is_fatal_status_error` [SDK lib/_retry.py:29-48] draw the same line).
Three calls run with `max_retries=0`: `send_user_message`, because a retried `user.message` may
be enqueued twice [INFERRED] and the caller decides; and `archive_session` / `delete_session`,
called after `wait_until_not_running`, so a 400/409 for a still running session becomes
`SessionBusyError` at once instead of after five attempts and up to 7.5 s of backoff.

Streams are never retried by the SDK once open. A mid-stream network drop does NOT raise
`APIConnectionError`: the SDK no longer wraps transport errors at that point, so it surfaces as
a raw `httpx2.HTTPError` subclass (`ReadError`, `ReadTimeout`, `RemoteProtocolError`) [SDK
lib/_retry.py:24 `TRANSIENT_ERRORS = (httpx2.HTTPError, APIError)`; offline]. Stream iteration
catches `httpx2.HTTPError` and `anthropic.APIError` and raises `StreamDisconnectedError` from
them; the consumer reconnects (stream first, then list, skip seen ids). An `event: error` SSE
message mid-stream (e.g. `overloaded_error`) is handled the same way (see `stream_session`).

Test seam
---------
anthropic 1.13.0 is built on `httpx2`, not `httpx`: an `httpx.AsyncClient` passed as
`http_client` raises TypeError [SDK _base_client.py:145-152], and respx (which patches `httpx`)
never sees SDK traffic. SDK-level tests build `AsyncAnthropic(api_key="test", base_url=
"http://ma.test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))`.
respx only covers the backend's own `httpx` code (fx, auth, triptracker_schema).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast, get_args

import anthropic
import httpx2
import structlog
from anthropic import AsyncAnthropic, AsyncStream, omit

if TYPE_CHECKING:
    from app.config import Settings

_log = structlog.get_logger(__name__)

RawEvent = dict[str, Any]
"""One Managed Agents event as plain JSON (see the module docstring)."""

EventStream = AsyncIterator[RawEvent]
"""The events of one open stream, in arrival order."""

SessionStatus = Literal["rescheduling", "running", "idle", "terminated"]
ThreadStatus = Literal["rescheduling", "running", "idle", "terminated"]

MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"
"""Beta header the SDK adds by itself to every `client.beta.sessions.*` call [SDK]."""

MAX_RETRIES = 4
"""SDK `max_retries` (retries after the first attempt) for every call except
`send_user_message`, `archive_session` and `delete_session`: 1 + 4 = the spec's "massimo 5
tentativi"."""

CALL_DEADLINE_SECONDS = 120.0
"""Upper bound on one non-stream call, retries and `retry-after` sleeps included
(`asyncio.timeout`); hitting it raises `ApiUnavailableError`."""

REQUEST_TIMEOUT_SECONDS = 30.0
"""SDK `timeout` of one non-stream HTTP attempt (the SDK default is 600 s)."""

STREAM_READ_TIMEOUT_SECONDS = 120.0
"""Read timeout of an open SSE stream: well above the server's heartbeat interval, so only a
dead connection trips it (it then surfaces as `StreamDisconnectedError`) [INFERRED, P7]."""

TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({408, 409, 429})
"""4xx statuses the SDK retries [SDK lib/_retry.py:29]; with every status >= 500 they map to
`ApiUnavailableError` once the retries are spent."""

BUDGET_CURRENCY = "USD"
"""The only currency Managed Agents budgets and list costs use [SDK BetaMonetaryAmount]."""

DEFAULT_LIST_LIMIT = 1000
"""Page size for event listings (the API default and maximum per the skill)."""

PRIMARY_SCOPE = "session"
"""Stream scope name of the session (primary-thread) stream; thread streams use the thread id."""

ARCHIVE_POLL_ATTEMPTS = 10
ARCHIVE_POLL_DELAY_SECONDS = 0.2
"""`session.status_idle` arrives slightly before the queryable status leaves `running`; poll
`retrieve_session` this many times before archiving or deleting (notes §2d, I24)."""

SESSION_STREAM_END_TYPES: frozenset[str] = frozenset(
    {"session.status_terminated", "session.deleted"}
)
"""Event types after which a stream ends normally: iteration stops right after yielding one."""

THREAD_TERMINATED_TYPE = "session.thread_status_terminated"
"""Also ends a thread stream, when it is that thread's own (`session_thread_id` absent or equal)."""

BUSY_STATUS_CODES: frozenset[int] = frozenset({400, 409})
"""Statuses that mean "still running" on `archive_session` / `delete_session` [INFERRED, P10]."""

REJECTION_REASONS: tuple[str, ...] = (
    "budget_not_raised",
    "budget_create_only",
    "model_not_budgetable",
)
"""Rejection reasons the SDK documents for `sessions.create/update` [SDK
resources/beta/sessions/sessions.py]. Where they sit in the error body is not documented
[INFERRED, P9]: `error_type` takes `error.reason` when present, else a known reason named in
`error.message`, else `error.type`."""


# --- value types ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentPin:
    """An agent at an exact version: `{type: "agent", id, version}` in `sessions.create`."""

    id: str
    version: int


@dataclass(frozen=True, slots=True)
class SessionUsage:
    """Cumulative usage of a session (`session.usage`), in the units the API reports.

    `list_cost_cents` is `usage.list_cost.amount` parsed to int (US cents); `None` until cost
    tracking is available for the session ("Absent until cost tracking is available" [SDK]).
    The token figures are informational (logs, evals): session usage sums every thread and
    model, so no cost can be derived from them, and the backend has no token-based fallback
    (notes §2d, "Usage and cost"); `cache_creation` is therefore not carried.
    """

    list_cost_cents: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    web_search_requests: int | None = None
    active_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """What the backend needs from `BetaManagedAgentsSession` (`sessions.retrieve/create`)."""

    id: str
    status: SessionStatus
    usage: SessionUsage
    budget_cents: int | None
    """The current `budget.max_list_cost.amount` in US cents; None when uncapped."""
    archived: bool
    metadata: Mapping[str, str] = field(default_factory=dict[str, str])
    """`plan_id`, `agent_profile` and `app` as set by `sessions.session_metadata`."""
    created_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class ThreadInfo:
    """One session thread (`sessions.threads.list`). The primary thread is included."""

    id: str
    agent_name: str | None
    parent_thread_id: str | None
    status: ThreadStatus
    archived: bool = False
    """`archived_at` is set: the thread takes no new work and no longer counts against the
    session's 25 concurrent child threads (notes §2a)."""

    @property
    def is_primary(self) -> bool:
        """True for the coordinator's (primary) thread: it has no parent."""
        return self.parent_thread_id is None


@dataclass(frozen=True, slots=True)
class EventPage:
    """One page of an event listing, oldest first. `next_page` is the opaque cursor to pass
    back as `page=`, or None on the last page."""

    events: list[RawEvent]
    next_page: str | None


# --- errors -----------------------------------------------------------------------------------


class ManagedAgentsError(Exception):
    """Base of every error raised through the seam. Never wraps the API key or event content.

    `status_code` is the HTTP status when there was one; `error_type` is the API's
    `error.type` (`invalid_request_error`, ...) or a reason such as `budget_not_raised`.
    """

    def __init__(
        self, message: str, *, status_code: int | None = None, error_type: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class ApiUnavailableError(ManagedAgentsError):
    """Transient failure that outlived the SDK retries (1 + `MAX_RETRIES` attempts): status
    408, 409, 429, >= 500 (529 included), a connection error or timeout, or
    `CALL_DEADLINE_SECONDS` exceeded. The consumer marks the plan `failed` with the reason
    (spec "Log e resilienza")."""


class ApiRejectedError(ManagedAgentsError):
    """Any other 4xx except 404 (400/401/403/413/422, ...): a bad body, a bad key, a
    `user.message` sent while the budget is reached, `budget_not_raised`, ... Not retryable."""


class SessionNotFoundError(ManagedAgentsError):
    """404: the session (or thread) does not exist any more, e.g. deleted by the nightly job."""


class SessionBusyError(ManagedAgentsError):
    """Archive or delete refused because the session is still `running` [DOCS
    session-operations]: a 400 or 409 on `archive_session` / `delete_session`, which are sent
    with `max_retries=0`. The exact status code is [INFERRED]; probe P10."""


class StreamDisconnectedError(ManagedAgentsError):
    """A stream dropped (`httpx2.HTTPError` or `anthropic.APIError` while iterating), sent an
    `event: error` SSE message (`error_type` = its `error.type`, e.g. `overloaded_error`), sent a
    payload that is not a JSON object, or ended without `session.status_terminated` /
    `session.deleted`. The caller reconnects: open the stream again, list the history, skip
    seen ids."""


# --- the seam ---------------------------------------------------------------------------------


class ManagedAgentsClient(Protocol):
    """Exactly the Managed Agents operations the backend uses. Implementations must be safe to
    share between the plan consumers of one process (one event loop)."""

    async def create_session(
        self,
        *,
        agent: AgentPin,
        environment_id: str,
        budget_cents: int,
        metadata: Mapping[str, str],
        title: str | None = None,
    ) -> SessionInfo:
        """Create a session for the coordinator at `agent` (pinned version) in `environment_id`
        with a list-cost cap of `budget_cents` US cents.

        Sends `budget={"type": "limit", "max_list_cost": {"amount": str(budget_cents),
        "currency": "USD"}}` (a budget can only be set at creation). `metadata` (at most 16
        pairs, keys <= 64 chars, values <= 512 chars) carries `plan_id` and `agent_profile`,
        never personal data. No `initial_events`: the caller opens the stream, then sends the
        first message. The new session is `idle`.

        Raises `ApiRejectedError` (bad id, `model_not_budgetable`, ...) or
        `ApiUnavailableError`.
        """
        ...

    async def send_user_message(self, session_id: str, text: str) -> None:
        """Send one `user.message` with a single text block.

        Not retried (`max_retries=0`): on `ApiUnavailableError` the message may or may not have
        been enqueued, so the caller lists events (type `user.message`) before resending.
        Raises `ApiRejectedError` when the session is at its budget (400) or terminated.
        """
        ...

    async def send_custom_tool_result(
        self, session_id: str, tool_use_id: str, content: str, is_error: bool
    ) -> None:
        """Answer an `agent.custom_tool_use` (here: `submit_plan`).

        `tool_use_id` is the `id` of the `agent.custom_tool_use` event (`sevt_...`); the body is
        `{"type": "user.custom_tool_result", "custom_tool_use_id": tool_use_id, "content":
        [{"type": "text", "text": content}], "is_error": is_error}`. No `session_thread_id`: the
        server routes it [SDK]. Idempotent ("a second result for the same call is accepted and
        has no effect" [DOCS]), so it is retried like any other call.
        """
        ...

    async def send_interrupt(self, session_id: str, thread_id: str | None = None) -> None:
        """Send `user.interrupt`. With `thread_id=None` it interrupts every non-archived thread,
        the primary included; it jumps the event queue. The session then goes idle with
        `stop_reason: end_turn`. Accepted even when the budget is reached."""
        ...

    def stream_session(self, session_id: str) -> AbstractAsyncContextManager[EventStream]:
        """Open the session (primary-thread) stream, `GET /v1/sessions/{id}/events/stream`.

        `async with client.stream_session(sid) as events:` returns once the stream is open;
        `async for raw in events:` then yields every session event in arrival order, including
        `session.usage` and types this code does not know. Stream-only previews
        (`event_start`/`event_delta`) are never requested. Iteration stops after
        `session.status_terminated` or `session.deleted`; any other end raises
        `StreamDisconnectedError`. Opening raises `SessionNotFoundError`, `ApiUnavailableError`,
        or `ApiRejectedError` for a fatal 4xx (401/403/...: reconnecting will not fix it, the
        same split as `is_fatal_status_error` [SDK lib/_retry.py:42-48]).

        The SDK client reads raw SSE (`AsyncStream.raw_events`), which does none of the typed
        iterator's housekeeping [SDK _streaming.py:214-221, 289-311], so every message goes
        through this loop:

            for sse in raw_events:
                if sse.event == "ping" or not sse.data.strip():
                    continue                       # heartbeats and empty messages
                if sse.event == "error":           # an API error mid-stream
                    raise StreamDisconnectedError(..., error_type=<error.type or None>)
                data = json.loads(sse.data)        # invalid JSON or not an object:
                                                   #   StreamDisconnectedError, never dropped
                if sse.event:
                    data.setdefault("type", sse.event)
                yield data                         # callers dispatch on data["type"], never
                                                   #   on sse.event (it may be absent)

        and `httpx2.HTTPError` / `anthropic.APIError` raised while iterating become
        `StreamDisconnectedError` (module docstring, "Retries"). The consumer reconnects and
        backfills from the listing in every one of these cases, so nothing is lost.
        """
        ...

    def stream_thread(
        self, session_id: str, thread_id: str
    ) -> AbstractAsyncContextManager[EventStream]:
        """Open one subagent thread's stream, `GET /v1/sessions/{sid}/threads/{tid}/stream`.

        Same contract as `stream_session`. The thread stream carries that agent's full activity
        (`agent.tool_use`/`agent.tool_result`, `agent.mcp_*`, messages, spans); iteration also
        stops after the thread's `session.thread_status_terminated`.
        """
        ...

    async def list_events(
        self,
        session_id: str,
        *,
        since: dt.datetime | None = None,
        page: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> EventPage:
        """One page of the session's persisted history, oldest first (`order="asc"`, ordered by
        `processed_at`), each event the server's JSON as sent (module docstring). `since` maps to
        `created_at_gte` (inclusive): a hint to shorten a resume, never a substitute for
        de-duplicating by id. Pass `next_page` back as `page`.
        """
        ...

    async def list_thread_events(
        self,
        session_id: str,
        thread_id: str,
        *,
        page: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> EventPage:
        """One page of a thread's history (no order/type/time filters exist for threads [SDK]).
        Used right after opening a thread stream, because thread streams don't replay."""
        ...

    async def list_threads(self, session_id: str) -> list[ThreadInfo]:
        """Every thread of the session, the primary included, all pages. Used on resume to
        reopen the subagents' thread streams."""
        ...

    async def archive_thread(self, session_id: str, thread_id: str) -> None:
        """Archive one child thread (`POST /v1/sessions/{sid}/threads/{tid}/archive` [SDK
        resources/beta/sessions/threads/threads.py:434-497]): it takes no new work and stops
        counting against the 25 concurrent child threads (notes §2a). Used by the consumer only
        for an idle thread superseded by a newer thread of the same agent (consumer
        `superseded_threads`). Raises `SessionNotFoundError` or `ApiRejectedError`."""
        ...

    async def retrieve_session(self, session_id: str) -> SessionInfo:
        """The session's status, cumulative usage (list cost) and current budget."""
        ...

    async def update_budget(self, session_id: str, budget_cents: int) -> SessionInfo:
        """Replace the session's cap with `budget_cents` US cents (`sessions.update(budget=...)`).

        Used by "Continua con 2 $ in piu'": `budget_cents` must be strictly greater than the
        consumed list cost, else `ApiRejectedError(error_type="budget_not_raised")`. Allowed in
        any non-terminated status. Per the docs only a budget update lets a `budget_reached`
        session continue; whether it resumes by itself or needs a new `user.message` is
        [INFERRED], probe P9.
        """
        ...

    async def archive_session(self, session_id: str) -> None:
        """Archive: history kept, no new events, status `terminated` (the stream sees
        `session.status_terminated`). Sent once (`max_retries=0`): raises `SessionBusyError`
        while running, so call `wait_until_not_running()` first. Archiving an archived session
        is a no-op."""
        ...

    async def delete_session(self, session_id: str) -> None:
        """Delete the session, its events, sandbox and files, permanently. Sent once
        (`max_retries=0`): raises `SessionBusyError` while running; `SessionNotFoundError` when
        already gone (the nightly job treats that as success)."""
        ...

    async def list_sessions(
        self, *, created_before: dt.datetime, include_archived: bool = True
    ) -> list[SessionInfo]:
        """Every session of the workspace created before `created_before`, all pages
        (`beta.sessions.list(created_at_lt=..., include_archived=..., order="asc")`; the API
        excludes archived sessions unless asked [SDK resources/beta/sessions/sessions.py:853-940]).
        Used by the nightly job to find sessions older than the retention whose plan row is gone
        (or was never committed), so no transcript outlives the 90 days."""
        ...

    async def aclose(self) -> None:
        """Release the HTTP connection pool (application shutdown)."""
        ...


# --- helpers over the Protocol ----------------------------------------------------------------


def budget_param(budget_cents: int) -> dict[str, Any]:
    """`{"type": "limit", "max_list_cost": {"amount": str(budget_cents), "currency": "USD"}}`.

    Raises ValueError unless `budget_cents` is a positive int (the API wants an integer-cents
    string with no decimals; "25.00" is rejected [DOCS budgets]).
    """
    if isinstance(budget_cents, bool) or not isinstance(budget_cents, int) or budget_cents <= 0:
        raise ValueError(f"budget_cents must be a positive int, got {budget_cents!r}")
    return {
        "type": "limit",
        "max_list_cost": {"amount": str(budget_cents), "currency": BUDGET_CURRENCY},
    }


def parse_list_cost_cents(list_cost: Mapping[str, Any] | None) -> int | None:
    """`{"amount": "123", "currency": "USD"}` -> 123; None for None, a missing amount or a
    currency other than USD (logged, never guessed)."""
    if list_cost is None:
        return None
    currency = list_cost.get("currency")
    if currency != BUDGET_CURRENCY:
        _log.warning("ma_list_cost_currency_unexpected", currency=str(currency)[:16])
        return None
    amount = list_cost.get("amount")
    if amount is None:
        return None
    if isinstance(amount, str) and amount.isascii() and amount.isdigit():
        return int(amount)
    if isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
        return amount
    _log.warning("ma_list_cost_amount_invalid", amount=str(amount)[:32])
    return None


def usage_from_event(raw: Mapping[str, Any]) -> SessionUsage | None:
    """The `SessionUsage` carried by a `session.usage` event (`raw["usage"]`), or None for any
    other event type. Pure; used by the consumer to track `plans.cost_cents` live."""
    if raw.get("type") != "session.usage":
        return None
    usage = raw.get("usage")
    return _usage_from_json(usage if isinstance(usage, Mapping) else None)


async def iter_session_history(
    client: ManagedAgentsClient, session_id: str, *, since: dt.datetime | None = None
) -> AsyncIterator[RawEvent]:
    """Every persisted session event, oldest first, following `next_page` cursors.
    Implemented as an async generator: `async for raw in iter_session_history(client, sid)`."""
    page: str | None = None
    while True:
        result = await client.list_events(session_id, since=since, page=page)
        for raw in result.events:
            yield raw
        if result.next_page is None:
            return
        page = _advance_cursor(page, result.next_page)


async def iter_thread_history(
    client: ManagedAgentsClient, session_id: str, thread_id: str
) -> AsyncIterator[RawEvent]:
    """Every persisted event of one thread, oldest first, following `next_page` cursors.
    Implemented as an async generator, like `iter_session_history`."""
    page: str | None = None
    while True:
        result = await client.list_thread_events(session_id, thread_id, page=page)
        for raw in result.events:
            yield raw
        if result.next_page is None:
            return
        page = _advance_cursor(page, result.next_page)


def _advance_cursor(current: str | None, next_page: str) -> str:
    """`next_page`, unless it repeats the cursor just used (a listing that would never end)."""
    if next_page == current:
        raise ManagedAgentsError("listing cursor did not advance", error_type="malformed_response")
    return next_page


async def wait_until_not_running(
    client: ManagedAgentsClient,
    session_id: str,
    *,
    attempts: int = ARCHIVE_POLL_ATTEMPTS,
    delay_seconds: float = ARCHIVE_POLL_DELAY_SECONDS,
) -> SessionInfo:
    """Poll `retrieve_session` until the status is not `running` (the post-idle race, notes
    §2d) and return the last `SessionInfo`. Raises `SessionBusyError` if it is still running
    after `attempts` polls. Sleeps with `asyncio.sleep` (tests patch `delay_seconds=0`)."""
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1, got {attempts}")
    for attempt in range(attempts):
        info = await client.retrieve_session(session_id)
        if info.status != "running":
            return info
        if attempt + 1 < attempts:
            await asyncio.sleep(delay_seconds)
    raise SessionBusyError(f"session still running after {attempts} status polls")


async def archive_when_idle(client: ManagedAgentsClient, session_id: str) -> None:
    """`wait_until_not_running` then `archive_session`; used when a plan becomes `ready` or
    `interrupted`. Errors propagate; the caller logs them and never fails the plan for them."""
    await wait_until_not_running(client, session_id)
    await client.archive_session(session_id)


# --- parsing the server's JSON ----------------------------------------------------------------

_SESSION_STATUSES: frozenset[str] = frozenset(get_args(SessionStatus))
_EXCESS_FRACTION = re.compile(r"(\.\d{6})\d+")


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_instant(value: object) -> dt.datetime | None:
    """An RFC 3339 timestamp as an aware datetime (fractions beyond microseconds dropped);
    None when absent, malformed or naive."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(_EXCESS_FRACTION.sub(r"\1", value, count=1))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _usage_from_json(usage: Mapping[str, Any] | None) -> SessionUsage:
    """`SessionUsage` from a session's `usage` object (`sessions.retrieve`) or a `session.usage`
    event's `usage` snapshot: the same keys [SDK beta_managed_agents_session_usage*.py]."""
    if usage is None:
        return SessionUsage()
    list_cost = usage.get("list_cost")
    server_tools = usage.get("server_tool_use")
    return SessionUsage(
        list_cost_cents=parse_list_cost_cents(
            list_cost if isinstance(list_cost, Mapping) else None
        ),
        input_tokens=_int_or_none(usage.get("input_tokens")),
        output_tokens=_int_or_none(usage.get("output_tokens")),
        cache_read_input_tokens=_int_or_none(usage.get("cache_read_input_tokens")),
        web_search_requests=(
            _int_or_none(server_tools.get("web_search_requests"))
            if isinstance(server_tools, Mapping)
            else None
        ),
        active_seconds=_float_or_none(usage.get("active_seconds")),
    )


def _malformed(what: str, problem: str) -> ManagedAgentsError:
    return ManagedAgentsError(f"{what}: {problem}", error_type="malformed_response")


def _json_object(response: httpx2.Response, what: str) -> Mapping[str, Any]:
    """The response body as a JSON object (never an SDK model: module docstring)."""
    try:
        body = response.json()
    except ValueError:
        raise _malformed(what, "response body is not JSON") from None
    if not isinstance(body, dict):
        raise _malformed(what, "response body is not a JSON object")
    return cast(dict[str, Any], body)


def _page_items(body: Mapping[str, Any], what: str) -> tuple[list[dict[str, Any]], str | None]:
    """`body["data"]` (each item a JSON object, as sent) and `body["next_page"]` (None at the
    end) of one page of a cursor listing."""
    data = body.get("data")
    if not isinstance(data, list):
        raise _malformed(what, "listing without a data array")
    items = cast(list[object], data)
    if not all(isinstance(item, dict) for item in items):
        raise _malformed(what, "listing item is not a JSON object")
    next_page = body.get("next_page")
    if next_page is not None and not isinstance(next_page, str):
        raise _malformed(what, "next_page is not a string")
    return cast(list[dict[str, Any]], items), next_page or None


def _session_info(body: Mapping[str, Any], what: str) -> SessionInfo:
    """`SessionInfo` from a `BetaManagedAgentsSession` JSON object."""
    session_id = body.get("id")
    status = body.get("status")
    if not isinstance(session_id, str) or not session_id or not isinstance(status, str):
        raise _malformed(what, "session without id or status")
    if status not in _SESSION_STATUSES:
        _log.warning("ma_session_status_unknown", session_id=session_id, status=status[:64])
    usage = body.get("usage")
    budget = body.get("budget")
    max_list_cost = budget.get("max_list_cost") if isinstance(budget, Mapping) else None
    metadata = body.get("metadata")
    return SessionInfo(
        id=session_id,
        status=cast(SessionStatus, status),
        usage=_usage_from_json(usage if isinstance(usage, Mapping) else None),
        budget_cents=parse_list_cost_cents(
            max_list_cost if isinstance(max_list_cost, Mapping) else None
        ),
        archived=body.get("archived_at") is not None,
        metadata=(
            {k: v for k, v in metadata.items() if isinstance(k, str) and isinstance(v, str)}
            if isinstance(metadata, Mapping)
            else {}
        ),
        created_at=_parse_instant(body.get("created_at")),
    )


def _thread_info(body: Mapping[str, Any], what: str) -> ThreadInfo:
    """`ThreadInfo` from a `BetaManagedAgentsSessionThread` JSON object; `agent_name` is the
    thread's `agent.name` (an advisor has none)."""
    thread_id = body.get("id")
    status = body.get("status")
    if not isinstance(thread_id, str) or not thread_id or not isinstance(status, str):
        raise _malformed(what, "thread without id or status")
    agent = body.get("agent")
    return ThreadInfo(
        id=thread_id,
        agent_name=_str_or_none(agent.get("name")) if isinstance(agent, Mapping) else None,
        parent_thread_id=_str_or_none(body.get("parent_thread_id")),
        status=cast(ThreadStatus, status),
        archived=body.get("archived_at") is not None,
    )


# --- errors and streams -----------------------------------------------------------------------


def _api_error_type(body: object) -> str | None:
    """The reason or `error.type` of an API error body `{"type": "error", "error": {...}}`."""
    if not isinstance(body, Mapping):
        return None
    error = cast(Mapping[str, Any], body).get("error")
    if not isinstance(error, Mapping):
        return None
    error = cast(Mapping[str, Any], error)
    reason = error.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    message = error.get("message")
    if isinstance(message, str):
        for known in REJECTION_REASONS:
            if known in message:
                return known
    return _str_or_none(error.get("type"))


def _map_api_error(exc: anthropic.APIError, what: str, *, busy: bool = False) -> ManagedAgentsError:
    """The seam's error for an SDK error that outlived the SDK's retries (module docstring,
    "Retries"). The message carries the call, the status, the error type and the request id,
    never a request or response body."""
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        error_type = _api_error_type(exc.body)
        message = f"{what}: HTTP {status}"
        if error_type:
            message += f" {error_type}"
        if exc.request_id:
            message += f" (request-id {exc.request_id})"
        if busy and status in BUSY_STATUS_CODES:
            return SessionBusyError(message, status_code=status, error_type=error_type)
        if status == 404:
            return SessionNotFoundError(message, status_code=status, error_type=error_type)
        if status in TRANSIENT_STATUS_CODES or status >= 500:
            return ApiUnavailableError(message, status_code=status, error_type=error_type)
        return ApiRejectedError(message, status_code=status, error_type=error_type)
    if isinstance(exc, anthropic.APITimeoutError):
        return ApiUnavailableError(f"{what}: request timed out", error_type="timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return ApiUnavailableError(f"{what}: connection error", error_type="connection_error")
    return ApiUnavailableError(f"{what}: {type(exc).__name__}")


def _sse_error_type(data: str) -> str | None:
    """`error.type` of an `event: error` SSE payload (`{"type": "error", "error": {...}}`)."""
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    return _api_error_type(payload)


def _sse_payload(data: str, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except ValueError:
        raise StreamDisconnectedError(f"{what}: SSE payload is not JSON") from None
    if not isinstance(payload, dict):
        raise StreamDisconnectedError(f"{what}: SSE payload is not a JSON object")
    return cast(dict[str, Any], payload)


def _ends_session_stream(raw: RawEvent) -> bool:
    return raw.get("type") in SESSION_STREAM_END_TYPES


def _thread_stream_end(thread_id: str) -> Callable[[RawEvent], bool]:
    def ends(raw: RawEvent) -> bool:
        if raw.get("type") == THREAD_TERMINATED_TYPE:
            return raw.get("session_thread_id") in (None, thread_id)
        return _ends_session_stream(raw)

    return ends


async def _sse_events(
    response: httpx2.Response, *, what: str, ends: Callable[[RawEvent], bool]
) -> AsyncGenerator[RawEvent]:
    """The raw SSE loop of `ManagedAgentsClient.stream_session` over an open response."""
    raw_events = AsyncStream.raw_events(response)
    try:
        async for sse in raw_events:
            if sse.event == "ping" or not sse.data.strip():
                continue
            if sse.event == "error":
                raise StreamDisconnectedError(
                    f"{what}: error event", error_type=_sse_error_type(sse.data)
                )
            data = _sse_payload(sse.data, what)
            if sse.event:
                data.setdefault("type", sse.event)
            yield data
            if ends(data):
                return
    except (httpx2.HTTPError, anthropic.APIError, UnicodeDecodeError) as exc:
        status = exc.status_code if isinstance(exc, anthropic.APIStatusError) else None
        raise StreamDisconnectedError(
            f"{what}: stream dropped ({type(exc).__name__})", status_code=status
        ) from exc
    finally:
        aclose = getattr(raw_events, "aclose", None)
        if aclose is not None:
            await aclose()
    raise StreamDisconnectedError(f"{what}: stream ended without a terminal event")


# --- credentials ------------------------------------------------------------------------------


def anthropic_client_kwargs(
    settings: Settings, *, max_retries: int, timeout: float | None = None
) -> dict[str, Any]:
    """The one rule for building an Anthropic client (the backend and `evals/`).

    - `settings.anthropic_auth_mode == "api_key"`: `api_key=<the key>` is passed explicitly, so
      the SDK never falls back to other credentials (ANTHROPIC_PROFILE, an on-disk profile).
    - `"federation"` (development only, no key): NO `api_key`. Omitting it (or passing None, which
      the SDK treats the same) lets the SDK resolve credentials itself: with no explicit
      credential it reads ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN (both empty here) and then
      `default_credentials()`, whose env-var federation step needs ANTHROPIC_FEDERATION_RULE_ID,
      ANTHROPIC_ORGANIZATION_ID and ANTHROPIC_IDENTITY_TOKEN[_FILE] (+ the optional
      ANTHROPIC_WORKSPACE_ID) in the process environment [SDK _client.py:213-275,
      lib/credentials/_chain.py:76-136]. The token is exchanged lazily at the first request
      and renewed by the SDK; nothing here reads or logs it. An explicit profile
      (ANTHROPIC_PROFILE, ANTHROPIC_CONFIG_DIR, an `active_config` pointer file) ranks above
      env-var federation in the SDK, so none of them may be set where federation is meant.
    - no credentials: ValueError.

    `max_retries` and `timeout` behave as before; `base_url` is left to ANTHROPIC_BASE_URL.
    """
    mode = settings.anthropic_auth_mode
    if mode is None:
        raise ValueError(
            "no Anthropic credentials: ANTHROPIC_API_KEY is not set (in development, "
            "ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_ORGANIZATION_ID and "
            "ANTHROPIC_IDENTITY_TOKEN_FILE enable Workload Identity Federation instead)"
        )
    kwargs: dict[str, Any] = {"max_retries": max_retries}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if mode == "api_key":
        secret = settings.anthropic_api_key
        assert secret is not None  # anthropic_auth_mode == "api_key" implies a key
        kwargs["api_key"] = secret.get_secret_value().strip()
    return kwargs


def build_async_anthropic(
    settings: Settings, *, max_retries: int, timeout: float | None = None
) -> AsyncAnthropic:
    """`AsyncAnthropic(**anthropic_client_kwargs(...))`; the judge in evals/ uses it too."""
    return AsyncAnthropic(
        **anthropic_client_kwargs(settings, max_retries=max_retries, timeout=timeout)
    )


# --- the real client --------------------------------------------------------------------------


class SdkManagedAgentsClient:
    """`ManagedAgentsClient` over `anthropic==1.13.0` (`AsyncAnthropic().beta.sessions`).

    Mapping, method by method (all paths get `?beta=true` and the beta header from the SDK).
    Every non-stream call goes through `with_raw_response` and reads the server's JSON, never
    an SDK model (module docstring):

    - `create_session` -> `beta.sessions.create(agent={"type": "agent", "id", "version"},
      environment_id, budget=budget_param(...), metadata, title)`; `title` is omitted when None.
    - `send_user_message` / `send_custom_tool_result` / `send_interrupt` ->
      `beta.sessions.events.send(sid, events=[...])` (`with_options(max_retries=0)` for the
      user message).
    - `stream_session` -> `beta.sessions.events.with_streaming_response.stream(sid)`, iterated
      with `AsyncStream.raw_events(resp.http_response)` through the loop in
      `ManagedAgentsClient.stream_session` (ping/empty skipped, `event: error` raised, `type`
      filled from the SSE event name). The typed iterator is NOT used: in 1.13.0 it silently
      drops `session.usage` and every event type missing from its whitelist (notes §2f).
    - `stream_thread` -> `beta.sessions.threads.events.with_streaming_response.stream(tid,
      session_id=sid)`, same raw iteration.
    - `list_events` -> `beta.sessions.events.with_raw_response.list(sid, order="asc", limit,
      page, created_at_gte)`, then `body = resp.http_response.json()`: `events = body["data"]`,
      `next_page = body.get("next_page")` (the server's JSON, not `model_dump()`; module
      docstring). `list_thread_events` -> `beta.sessions.threads.events.with_raw_response.list(
      tid, session_id=sid, limit, page)`, read the same way.
    - `list_threads` -> `beta.sessions.threads.with_raw_response.list(sid, page)`, every page;
      `archive_thread` -> `beta.sessions.threads.archive(tid, session_id=sid)`.
    - `retrieve_session` -> `beta.sessions.retrieve(sid)`; `update_budget` ->
      `beta.sessions.update(sid, budget=budget_param(...))`; `list_sessions` ->
      `beta.sessions.with_raw_response.list(created_at_lt, include_archived, order="asc",
      page)`, every page.
    - `archive_session` / `delete_session` -> `with_options(max_retries=0)` then
      `beta.sessions.archive(sid)` / `beta.sessions.delete(sid)`.

    Every non-stream call (all pages of a listing included) runs inside
    `asyncio.timeout(CALL_DEADLINE_SECONDS)`, and so does opening a stream; a deadline hit is
    `ApiUnavailableError`. Streams are opened with `timeout=httpx2.Timeout(
    REQUEST_TIMEOUT_SECONDS, read=STREAM_READ_TIMEOUT_SECONDS)`.

    SDK exceptions are mapped by HTTP status (module docstring, "Retries"): `APIStatusError`
    with status 408, 409, 429 or >= 500, `APIConnectionError` and `APITimeoutError` ->
    `ApiUnavailableError`; 404 -> `SessionNotFoundError`; a 400/409 on archive/delete ->
    `SessionBusyError`; any other 4xx -> `ApiRejectedError`. While a stream is being iterated,
    `httpx2.HTTPError` and `anthropic.APIError` -> `StreamDisconnectedError`. Messages carry the
    status and the API error type only, never request bodies. A body that is not the expected
    JSON is a plain `ManagedAgentsError(error_type="malformed_response")`; a budget that is not
    a positive int is `ApiRejectedError(error_type="invalid_budget")`, sent nowhere.
    """

    def __init__(self, sdk: AsyncAnthropic) -> None:
        """Wrap an already configured SDK client. Use `from_settings()` in the application.

        Tests pass one built on `httpx2` (the SDK's HTTP library; an `httpx` client raises
        TypeError and respx never sees SDK traffic): `AsyncAnthropic(api_key="test",
        base_url="http://ma.test", max_retries=MAX_RETRIES,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))`."""
        self._sdk = sdk
        # Same HTTP pool and credentials; used for the three calls that must not be retried.
        self._sdk_once = sdk.with_options(max_retries=0)

    @classmethod
    def from_settings(cls, settings: Settings) -> SdkManagedAgentsClient:
        """`build_async_anthropic(settings, max_retries=MAX_RETRIES,
        timeout=REQUEST_TIMEOUT_SECONDS)`: the API key when set (passed explicitly, so the SDK
        never falls back to other credentials), else Workload Identity Federation in development
        (see `anthropic_client_kwargs`). Raises ValueError without credentials (tests and local
        runs without a key use the fake instead)."""
        return cls(
            build_async_anthropic(
                settings, max_retries=MAX_RETRIES, timeout=REQUEST_TIMEOUT_SECONDS
            )
        )

    async def create_session(
        self,
        *,
        agent: AgentPin,
        environment_id: str,
        budget_cents: int,
        metadata: Mapping[str, str],
        title: str | None = None,
    ) -> SessionInfo:
        what = "create_session"
        budget = _checked_budget(budget_cents)

        async def call() -> SessionInfo:
            resp = await self._sdk.beta.sessions.with_raw_response.create(
                agent={"type": "agent", "id": agent.id, "version": agent.version},
                environment_id=environment_id,
                budget=cast(Any, budget),
                metadata=dict(metadata),
                title=title if title is not None else omit,
            )
            return _session_info(_json_object(resp.http_response, what), what)

        return await self._call(what, call)

    async def send_user_message(self, session_id: str, text: str) -> None:
        event = {"type": "user.message", "content": [{"type": "text", "text": text}]}
        await self._send("send_user_message", session_id, event, retry=False)

    async def send_custom_tool_result(
        self, session_id: str, tool_use_id: str, content: str, is_error: bool
    ) -> None:
        event = {
            "type": "user.custom_tool_result",
            "custom_tool_use_id": tool_use_id,
            "content": [{"type": "text", "text": content}],
            "is_error": is_error,
        }
        await self._send("send_custom_tool_result", session_id, event)

    async def send_interrupt(self, session_id: str, thread_id: str | None = None) -> None:
        event: dict[str, Any] = {"type": "user.interrupt"}
        if thread_id is not None:
            event["session_thread_id"] = thread_id
        await self._send("send_interrupt", session_id, event)

    def stream_session(self, session_id: str) -> AbstractAsyncContextManager[EventStream]:
        return self._stream(
            "stream_session",
            lambda: self._sdk.beta.sessions.events.with_streaming_response.stream(
                session_id, timeout=_stream_timeout()
            ),
            ends=_ends_session_stream,
        )

    def stream_thread(
        self, session_id: str, thread_id: str
    ) -> AbstractAsyncContextManager[EventStream]:
        return self._stream(
            "stream_thread",
            lambda: self._sdk.beta.sessions.threads.events.with_streaming_response.stream(
                thread_id, session_id=session_id, timeout=_stream_timeout()
            ),
            ends=_thread_stream_end(thread_id),
        )

    async def list_events(
        self,
        session_id: str,
        *,
        since: dt.datetime | None = None,
        page: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> EventPage:
        what = "list_events"
        created_at_gte = _utc(since, "since") if since is not None else None

        async def call() -> EventPage:
            resp = await self._sdk.beta.sessions.events.with_raw_response.list(
                session_id,
                order="asc",
                limit=limit,
                page=page if page is not None else omit,
                created_at_gte=created_at_gte if created_at_gte is not None else omit,
            )
            events, next_page = _page_items(_json_object(resp.http_response, what), what)
            return EventPage(events=events, next_page=next_page)

        return await self._call(what, call)

    async def list_thread_events(
        self,
        session_id: str,
        thread_id: str,
        *,
        page: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> EventPage:
        what = "list_thread_events"

        async def call() -> EventPage:
            resp = await self._sdk.beta.sessions.threads.events.with_raw_response.list(
                thread_id,
                session_id=session_id,
                limit=limit,
                page=page if page is not None else omit,
            )
            events, next_page = _page_items(_json_object(resp.http_response, what), what)
            return EventPage(events=events, next_page=next_page)

        return await self._call(what, call)

    async def list_threads(self, session_id: str) -> list[ThreadInfo]:
        what = "list_threads"

        async def call() -> list[ThreadInfo]:
            threads: list[ThreadInfo] = []
            page: str | None = None
            while True:
                resp = await self._sdk.beta.sessions.threads.with_raw_response.list(
                    session_id, page=page if page is not None else omit
                )
                items, next_page = _page_items(_json_object(resp.http_response, what), what)
                threads.extend(_thread_info(item, what) for item in items)
                if next_page is None:
                    return threads
                page = _advance_cursor(page, next_page)

        return await self._call(what, call)

    async def archive_thread(self, session_id: str, thread_id: str) -> None:
        async def call() -> None:
            await self._sdk.beta.sessions.threads.with_raw_response.archive(
                thread_id, session_id=session_id
            )

        await self._call("archive_thread", call)

    async def retrieve_session(self, session_id: str) -> SessionInfo:
        what = "retrieve_session"

        async def call() -> SessionInfo:
            resp = await self._sdk.beta.sessions.with_raw_response.retrieve(session_id)
            return _session_info(_json_object(resp.http_response, what), what)

        return await self._call(what, call)

    async def update_budget(self, session_id: str, budget_cents: int) -> SessionInfo:
        what = "update_budget"
        budget = _checked_budget(budget_cents)

        async def call() -> SessionInfo:
            resp = await self._sdk.beta.sessions.with_raw_response.update(
                session_id, budget=cast(Any, budget)
            )
            return _session_info(_json_object(resp.http_response, what), what)

        return await self._call(what, call)

    async def archive_session(self, session_id: str) -> None:
        async def call() -> None:
            await self._sdk_once.beta.sessions.with_raw_response.archive(session_id)

        await self._call("archive_session", call, busy=True)

    async def delete_session(self, session_id: str) -> None:
        async def call() -> None:
            await self._sdk_once.beta.sessions.with_raw_response.delete(session_id)

        await self._call("delete_session", call, busy=True)

    async def list_sessions(
        self, *, created_before: dt.datetime, include_archived: bool = True
    ) -> list[SessionInfo]:
        what = "list_sessions"
        created_at_lt = _utc(created_before, "created_before")

        async def call() -> list[SessionInfo]:
            sessions: list[SessionInfo] = []
            page: str | None = None
            while True:
                resp = await self._sdk.beta.sessions.with_raw_response.list(
                    created_at_lt=created_at_lt,
                    include_archived=include_archived,
                    order="asc",
                    page=page if page is not None else omit,
                )
                items, next_page = _page_items(_json_object(resp.http_response, what), what)
                sessions.extend(_session_info(item, what) for item in items)
                if next_page is None:
                    return sessions
                page = _advance_cursor(page, next_page)

        return await self._call(what, call)

    async def aclose(self) -> None:
        await self._sdk.close()

    # --- internals ----------------------------------------------------------------------------

    async def _call[T](
        self, what: str, call: Callable[[], Awaitable[T]], *, busy: bool = False
    ) -> T:
        """Run one non-stream call under the deadline and map SDK errors to the seam's."""
        try:
            async with asyncio.timeout(CALL_DEADLINE_SECONDS):
                return await call()
        except TimeoutError:
            raise ApiUnavailableError(
                f"{what}: no answer within {CALL_DEADLINE_SECONDS:g} s", error_type="deadline"
            ) from None
        except anthropic.APIStatusError as exc:
            # No chaining: the SDK's message embeds the response body.
            raise _map_api_error(exc, what, busy=busy) from None
        except anthropic.APIError as exc:
            raise _map_api_error(exc, what, busy=busy) from exc

    async def _send(
        self, what: str, session_id: str, event: Mapping[str, Any], *, retry: bool = True
    ) -> None:
        sdk = self._sdk if retry else self._sdk_once

        async def call() -> None:
            await sdk.beta.sessions.events.with_raw_response.send(
                session_id, events=[cast(Any, dict(event))]
            )

        await self._call(what, call)

    @asynccontextmanager
    async def _stream(
        self,
        what: str,
        open_response: Callable[[], AbstractAsyncContextManager[Any]],
        *,
        ends: Callable[[RawEvent], bool],
    ) -> AsyncIterator[EventStream]:
        """Open the HTTP stream (under the deadline, SDK retries included), then hand out the
        raw SSE iterator; on exit, close the iterator and the response."""
        async with AsyncExitStack() as stack:
            try:
                async with asyncio.timeout(CALL_DEADLINE_SECONDS):
                    response = await stack.enter_async_context(open_response())
            except TimeoutError:
                raise ApiUnavailableError(
                    f"{what}: not open within {CALL_DEADLINE_SECONDS:g} s", error_type="deadline"
                ) from None
            except anthropic.APIStatusError as exc:
                raise _map_api_error(exc, what) from None
            except anthropic.APIError as exc:
                raise _map_api_error(exc, what) from exc
            events = _sse_events(response.http_response, what=what, ends=ends)
            try:
                yield events
            finally:
                await events.aclose()


def _checked_budget(budget_cents: int) -> dict[str, Any]:
    """`budget_param`, with a bad value refused like the API would refuse it."""
    try:
        return budget_param(budget_cents)
    except ValueError as exc:
        raise ApiRejectedError(str(exc), error_type="invalid_budget") from None


def _utc(instant: dt.datetime, name: str) -> dt.datetime:
    """`instant` in UTC; a naive datetime is a bug (CLAUDE.md, contract rule 2)."""
    if instant.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return instant.astimezone(dt.UTC)


def _stream_timeout() -> httpx2.Timeout:
    return httpx2.Timeout(REQUEST_TIMEOUT_SECONDS, read=STREAM_READ_TIMEOUT_SECONDS)


def _conforms(client: SdkManagedAgentsClient) -> ManagedAgentsClient:
    """Static check only: pyright fails here if the SDK client drifts from the Protocol."""
    return client
