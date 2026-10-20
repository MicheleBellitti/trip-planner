"""`FakeManagedAgentsClient`: an offline, scripted `ManagedAgentsClient`.

The design (script format, stream semantics, recording, fault injection, the shipped scenarios)
is README.md in this directory. The fake never opens a socket and never spends money: it
replays JSONL scripts at the seam's level (`RawEvent` dicts) and records everything the backend
sends. `_conforms()` makes pyright check it against `app.ma_client.ManagedAgentsClient`.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import datetime as dt
import json
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NoReturn, cast, get_args

from app.ma_client import (
    BUDGET_CURRENCY,
    DEFAULT_LIST_LIMIT,
    PRIMARY_SCOPE,
    AgentPin,
    ApiRejectedError,
    ApiUnavailableError,
    EventPage,
    EventStream,
    ManagedAgentsClient,
    ManagedAgentsError,
    RawEvent,
    SessionBusyError,
    SessionInfo,
    SessionNotFoundError,
    SessionStatus,
    SessionUsage,
    StreamDisconnectedError,
    ThreadInfo,
    ThreadStatus,
)

ScriptStep = Mapping[str, Any]
"""One JSONL line of a script: `{"op": ..., ...}` (README.md, "Script format")."""

StepOp = Literal[
    "meta",
    "emit",
    "await",
    "await_call",
    "await_stream",
    "usage",
    "set",
    "disconnect",
    "fail_next",
    "checkpoint",
]
STEP_OPS: frozenset[str] = frozenset(get_args(StepOp))

FaultKind = Literal["api_unavailable", "api_rejected", "not_found", "busy", "disconnected", "hang"]
"""What `fail_next` makes a call do (README.md, "Fault injection")."""
FAULT_KINDS: frozenset[str] = frozenset(get_args(FaultKind))

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
"""backend/tests/fixtures: `{"$fixture": "<path>"}` values are resolved against it."""

FIXTURES_DIR = FIXTURES_ROOT / "ma"
"""Where scenario scripts live: backend/tests/fixtures/ma/<scenario>.jsonl."""

FAKE_EPOCH = dt.datetime(2026, 10, 12, 10, 0, tzinfo=dt.UTC)
"""`processed_at` of the first auto-stamped event of a session; every later auto-stamped event
is `AUTO_STAMP_STEP` after the latest `processed_at` the session has seen."""

INTERRUPTED_TOOL_TEXT = "Tool execution was interrupted before completion. Please retry."
"""What the platform answers a waiting custom tool call with on `user.interrupt` (probe P14)."""

AUTO_STAMP_STEP = dt.timedelta(milliseconds=1)
"""Small on purpose: an echo stamped while the driver is between two scripted events (with
explicit `processed_at`) still sorts between them, so the history stays ordered."""

DEFAULT_PRIMARY_THREAD_ID = "sthr_fake_primary"
"""Id of the coordinator's (primary) thread in `list_threads`; a script's `meta` can set
`primary_thread_id` so that it matches the ids its inter-agent messages use."""

COORDINATOR_AGENT_NAME = "coordinator"

PROTOCOL_METHODS: frozenset[str] = frozenset(
    {
        "create_session",
        "send_user_message",
        "send_custom_tool_result",
        "send_interrupt",
        "stream_session",
        "stream_thread",
        "list_events",
        "list_thread_events",
        "list_threads",
        "archive_thread",
        "retrieve_session",
        "update_budget",
        "archive_session",
        "delete_session",
        "list_sessions",
        "aclose",
    }
)
"""The `ManagedAgentsClient` methods `fail_next`, `await_call` and `called` accept."""

_SET_FIELDS = frozenset({"status", "status_lag", "budget_cents", "list_cost_cents", "page_size"})
_SESSION_STATUSES = frozenset(get_args(SessionStatus))
_THREAD_STATUS_BY_EVENT: dict[str, ThreadStatus] = {
    "session.thread_status_running": "running",
    "session.thread_status_idle": "idle",
    "session.thread_status_rescheduled": "rescheduling",
    "session.thread_status_terminated": "terminated",
}
_SESSION_STATUS_BY_EVENT: dict[str, SessionStatus] = {
    "session.status_running": "running",
    "session.status_idle": "idle",
    "session.status_rescheduled": "rescheduling",
    "session.status_terminated": "terminated",
}
_STREAM_ENDING_TYPES = frozenset({"session.status_terminated", "session.deleted"})


class ScriptMismatchError(AssertionError):
    """What the backend sent didn't match the script's next `await` step (or a blocking step
    timed out, or the script itself is inconsistent). Recorded and re-raised by
    `assert_script_done()`."""


class _ScriptStoppedError(Exception):
    """Internal: unwinds the driver after a mismatch was recorded."""


@dataclass(frozen=True, slots=True)
class CreatedSession:
    """One `create_session` call, as the real client would have sent it."""

    session_id: str
    agent: AgentPin
    environment_id: str
    budget_cents: int
    metadata: Mapping[str, str]
    title: str | None


@dataclass(frozen=True, slots=True)
class SentEvent:
    """One event the backend sent, as the JSON body item the real client would POST."""

    session_id: str
    payload: Mapping[str, Any]
    """E.g. `{"type": "user.custom_tool_result", "custom_tool_use_id": "sevt_1", "content":
    [{"type": "text", "text": "Plan accepted."}], "is_error": false}`."""
    open_streams: frozenset[str]
    """Stream scopes open at send time ("session", thread ids): lets a test assert that the
    session stream was open before the first `user.message`."""


@dataclass(slots=True)
class RecordedCall:
    """One call of a `ManagedAgentsClient` method, recorded when it starts (`calls`)."""

    method: str
    session_id: str | None
    args: Mapping[str, Any]
    error: ManagedAgentsError | None = None
    """What the call raised (an injected fault or the fake's API rules); None on success, or
    while a hung call is still pending."""


@dataclass(slots=True)
class _Fault:
    error: ManagedAgentsError | Literal["hang"]
    after: int


@dataclass(slots=True)
class _Thread:
    id: str
    agent_name: str | None
    parent_thread_id: str | None
    status: ThreadStatus = "running"
    archived: bool = False
    history: list[RawEvent] = field(default_factory=list[RawEvent])


_END = object()


class _Stream:
    """One open stream: an async iterator over a private queue (README, "Stream semantics")."""

    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.queue: asyncio.Queue[object] = asyncio.Queue()
        self.finished = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> RawEvent:
        if self.finished:
            raise StopAsyncIteration
        item = await self.queue.get()
        if item is _END:
            self.finished = True
            raise StopAsyncIteration
        if isinstance(item, BaseException):
            self.finished = True
            raise item
        return cast(RawEvent, item)


@dataclass(slots=True)
class _Session:
    id: str
    created_at: dt.datetime
    primary_thread_id: str
    scripted: bool
    status: SessionStatus = "idle"
    budget_cents: int | None = None
    usage: SessionUsage = field(default_factory=SessionUsage)
    metadata: dict[str, str] = field(default_factory=dict[str, str])
    title: str | None = None
    archived: bool = False
    deleted: bool = False
    history: list[RawEvent] = field(default_factory=list[RawEvent])
    threads: dict[str, _Thread] = field(default_factory=dict[str, _Thread])
    streams: dict[str, list[_Stream]] = field(default_factory=dict[str, list[_Stream]])
    budget_blocked: bool = False
    status_lag: int = 0
    lag_remaining: int = 0
    latest: dt.datetime | None = None
    custom_tool_use_ids: set[str] = field(default_factory=set[str])
    answered_tool_use_ids: set[str] = field(default_factory=set[str])

    def open_scopes(self) -> frozenset[str]:
        return frozenset(scope for scope, streams in self.streams.items() if streams)

    def reported_status(self, *, consume: bool) -> SessionStatus:
        """The status `retrieve_session` reports: `running` for `lag_remaining` more reads after
        an idle (README, "`session.status_idle` precedes the status write")."""
        if self.status != "running" and self.lag_remaining > 0:
            if consume:
                self.lag_remaining -= 1
            return "running"
        return self.status

    def info(self, *, consume_lag: bool) -> SessionInfo:
        return SessionInfo(
            id=self.id,
            status=self.reported_status(consume=consume_lag),
            usage=self.usage,
            budget_cents=self.budget_cents,
            archived=self.archived,
            metadata=dict(self.metadata),
            created_at=self.created_at,
        )


# --- helpers ----------------------------------------------------------------------------------


def _parse_instant(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def format_instant(value: dt.datetime) -> str:
    """The API's timestamp format: UTC, millisecond precision, `Z` suffix."""
    utc = value.astimezone(dt.UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def contains(actual: Any, expected: Any) -> bool:
    """Recursive subset match used by `await` steps: every key of `expected` is in `actual`
    with a matching value; lists match element-wise with equal length; booleans never equal
    integers."""
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return False
        actual_map = cast(Mapping[str, Any], actual)
        return all(
            key in actual_map and contains(actual_map[key], value)
            for key, value in cast(Mapping[str, Any], expected).items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        expected_list = cast(list[Any], expected)
        actual_list = cast(list[Any], actual)
        return len(actual_list) == len(expected_list) and all(
            contains(item, want) for item, want in zip(actual_list, expected_list, strict=True)
        )
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    return actual == expected


def resolve_fixtures(value: Any, *, root: Path = FIXTURES_ROOT) -> Any:
    """Replace every `{"$fixture": "<path>"}` with the JSON file at `root/<path>`."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, Any], value)
        if set(mapping) == {"$fixture"}:
            path = root / str(mapping["$fixture"])
            return resolve_fixtures(json.loads(path.read_text(encoding="utf-8")), root=root)
        return {key: resolve_fixtures(item, root=root) for key, item in mapping.items()}
    if isinstance(value, list):
        return [resolve_fixtures(item, root=root) for item in cast(list[Any], value)]
    return value


def namespace_event_ids(steps: Sequence[Mapping[str, Any]], namespace: str) -> list[dict[str, Any]]:
    """The steps with every scripted event id (`emit` events and `usage` steps) suffixed with
    `_<namespace>`, and every string anywhere in the steps that equals one of those ids (a
    `tool_use_id`, an `await` match, `stop_reason.event_ids`, ...) rewritten the same way.

    `events.ma_event_id` is unique across the whole database, so a scenario replayed twice into
    the same database (`app.cli replay`) needs ids of its own each time; real API ids are."""
    ids: dict[str, str] = {}
    for step in steps:
        event = step.get("event") if step.get("op") == "emit" else step
        if step.get("op") in ("emit", "usage") and isinstance(event, Mapping):
            event_id = cast(Mapping[str, Any], event).get("id")
            if isinstance(event_id, str) and event_id:
                ids[event_id] = f"{event_id}_{namespace}"

    def rewrite(value: Any) -> Any:
        if isinstance(value, str):
            return ids.get(value, value)
        if isinstance(value, Mapping):
            return {key: rewrite(item) for key, item in cast(Mapping[str, Any], value).items()}
        if isinstance(value, list):
            return [rewrite(item) for item in cast(list[Any], value)]
        return value

    return [cast(dict[str, Any], rewrite(step)) for step in steps]


def make_fault(kind: str, method: str, message: str | None = None) -> ManagedAgentsError:
    """The `ManagedAgentsError` a script's `fail_next` step names (`hang` is not an error)."""
    text = message or f"fake: injected {kind} on {method}"
    match kind:
        case "api_unavailable":
            return ApiUnavailableError(text, status_code=503, error_type="api_error")
        case "api_rejected":
            return ApiRejectedError(text, status_code=400, error_type="invalid_request_error")
        case "not_found":
            return SessionNotFoundError(text, status_code=404, error_type="not_found_error")
        case "busy":
            return SessionBusyError(text, status_code=409, error_type="invalid_request_error")
        case "disconnected":
            return StreamDisconnectedError(text)
        case _:
            msg = f"unknown fault kind {kind!r}; expected one of {sorted(FAULT_KINDS)}"
            raise ValueError(msg)


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[int]]:
    """Steps of a JSONL script and their 1-based line numbers (`#` and blank lines skipped)."""
    steps: list[dict[str, Any]] = []
    lines: list[int] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            step = json.loads(stripped)
        except json.JSONDecodeError as exc:
            msg = f"{path.name}:{number}: invalid JSON ({exc.msg})"
            raise ValueError(msg) from exc
        if not isinstance(step, dict):
            msg = f"{path.name}:{number}: a step must be a JSON object"
            raise ValueError(msg)
        steps.append(cast(dict[str, Any], step))
        lines.append(number)
    return steps, lines


def _check_step(step: Mapping[str, Any], index: int) -> None:
    """Reject malformed steps when the script is loaded (a test bug, reported early)."""
    op = step.get("op")
    where = f"step {index} ({op!r})"
    if op not in STEP_OPS:
        msg = f"step {index}: unknown op {op!r}; expected one of {sorted(STEP_OPS)}"
        raise ValueError(msg)
    if op == "meta" and index != 0:
        msg = f"{where}: meta must be the first step"
        raise ValueError(msg)
    if op == "emit" and not (
        isinstance(step.get("event"), Mapping) and isinstance(step["event"].get("type"), str)
    ):
        msg = f"{where}: emit needs an event object with a type"
        raise ValueError(msg)
    if op == "await" and not isinstance(step.get("match"), Mapping):
        msg = f"{where}: await needs a match object"
        raise ValueError(msg)
    if op in {"await_call", "fail_next"} and step.get("method") not in PROTOCOL_METHODS:
        msg = f"{where}: unknown method {step.get('method')!r}"
        raise ValueError(msg)
    if op == "fail_next" and step.get("error") not in FAULT_KINDS:
        msg = f"{where}: error must be one of {sorted(FAULT_KINDS)}"
        raise ValueError(msg)
    if op == "checkpoint" and not isinstance(step.get("name"), str):
        msg = f"{where}: checkpoint needs a name"
        raise ValueError(msg)
    if op == "set":
        unknown = set(step) - _SET_FIELDS - {"op"}
        if unknown:
            msg = f"{where}: unknown fields {sorted(unknown)}"
            raise ValueError(msg)
        if "status" in step and step["status"] not in _SESSION_STATUSES:
            msg = f"{where}: unknown status {step['status']!r}"
            raise ValueError(msg)


def _usage_from_payload(usage: Mapping[str, Any], previous: SessionUsage) -> SessionUsage:
    """`SessionUsage` from a `session.usage` event's `usage` object (fields it lacks keep their
    previous value; a non-USD list cost is ignored, like the real client)."""
    list_cost = previous.list_cost_cents
    cost = usage.get("list_cost")
    if isinstance(cost, Mapping):
        cost_map = cast(Mapping[str, Any], cost)
        amount = cost_map.get("amount")
        if cost_map.get("currency") == BUDGET_CURRENCY and isinstance(amount, str | int):
            list_cost = int(amount)
    server_tools = usage.get("server_tool_use")
    searches = previous.web_search_requests
    if isinstance(server_tools, Mapping):
        searches = cast(Mapping[str, Any], server_tools).get("web_search_requests", searches)
    return SessionUsage(
        list_cost_cents=list_cost,
        input_tokens=usage.get("input_tokens", previous.input_tokens),
        output_tokens=usage.get("output_tokens", previous.output_tokens),
        cache_read_input_tokens=usage.get(
            "cache_read_input_tokens", previous.cache_read_input_tokens
        ),
        web_search_requests=searches,
        active_seconds=usage.get("active_seconds", previous.active_seconds),
    )


def _budget_object(budget_cents: int) -> dict[str, Any]:
    return {
        "type": "limit",
        "max_list_cost": {"amount": str(budget_cents), "currency": BUDGET_CURRENCY},
    }


def build_usage_event(step: Mapping[str, Any], *, budget_cents: int | None) -> RawEvent:
    """The `session.usage` event a `usage` step emits: `usage` from the step's figures
    (`list_cost_cents` becomes `list_cost: {amount: "<cents>", currency: "USD"}`), `budget` from
    the session's current cap, and the step's `id` / `processed_at` when given."""
    usage: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
        if key in step:
            usage[key] = step[key]
    if "cache_creation" in step:
        usage["cache_creation"] = step["cache_creation"]
    if "web_search_requests" in step or "web_fetch_requests" in step:
        usage["server_tool_use"] = {
            "web_search_requests": step.get("web_search_requests", 0),
            "web_fetch_requests": step.get("web_fetch_requests", 0),
        }
    if "active_seconds" in step:
        usage["active_seconds"] = step["active_seconds"]
    if step.get("list_cost_cents") is not None:
        usage["list_cost"] = {"amount": str(step["list_cost_cents"]), "currency": BUDGET_CURRENCY}
    event: RawEvent = {"type": "session.usage", "usage": usage}
    if budget_cents is not None:
        event["budget"] = _budget_object(budget_cents)
    for key in ("id", "processed_at"):
        if key in step:
            event[key] = step[key]
    return event


# --- the fake ---------------------------------------------------------------------------------


class FakeManagedAgentsClient:
    """Scripted, in-memory Managed Agents (README.md).

    One session is scripted (`session_id`); it exists from construction so that resume tests
    can follow it without `create_session`. The first `create_session` call returns it; later
    calls create unscripted sessions that only record what they receive.
    """

    created: list[CreatedSession]
    sent: list[SentEvent]
    calls: list[RecordedCall]
    budget_updates: list[tuple[str, int]]
    archived: list[str]
    archived_threads: list[tuple[str, str]]
    deleted: list[str]
    closed: bool

    def __init__(
        self,
        script: Sequence[ScriptStep] = (),
        *,
        session_id: str = "sesn_fake_0001",
        list_cost_cents: int | None = 0,
        budget_cents: int | None = None,
        await_timeout: float = 5.0,
        workspace_sessions: Sequence[SessionInfo] = (),
        page_size: int | None = None,
        primary_thread_id: str | None = None,
        step_lines: Sequence[int] | None = None,
        source: str | None = None,
        id_namespace: str | None = None,
    ) -> None:
        """`workspace_sessions`: other sessions `list_sessions` reports (nightly orphan sweep
        tests); they can be listed, retrieved and deleted. `page_size` caps every listing page
        (so a backfill spans pages). `step_lines`/`source` only improve error messages.
        `id_namespace` makes every event id of this instance its own: the script's ids get
        `_<namespace>` (`namespace_event_ids`) and generated ids read
        `sevt_fake_<namespace>_<n>` (`app.cli replay` passes a fresh one per run)."""
        steps = [cast(dict[str, Any], resolve_fixtures(dict(step))) for step in script]
        if id_namespace:
            steps = namespace_event_ids(steps, id_namespace)
        self._id_prefix = f"sevt_fake_{id_namespace}_" if id_namespace else "sevt_fake_"
        for index, step in enumerate(steps):
            _check_step(step, index)
        self._steps = steps
        self._step_lines = list(step_lines) if step_lines is not None else None
        self._source = source
        self._meta: dict[str, Any] = (
            {key: value for key, value in steps[0].items() if key != "op"}
            if steps and steps[0].get("op") == "meta"
            else {}
        )
        self.session_id = session_id
        self.await_timeout = await_timeout
        self.page_size = page_size

        self.created = []
        self.sent = []
        self.calls = []
        self.budget_updates = []
        self.archived = []
        self.archived_threads = []
        self.deleted = []
        self.closed = False

        primary = primary_thread_id or str(
            self._meta.get("primary_thread_id", DEFAULT_PRIMARY_THREAD_ID)
        )
        self._sessions: dict[str, _Session] = {}
        self._session = _Session(
            id=session_id,
            created_at=FAKE_EPOCH,
            primary_thread_id=primary,
            scripted=True,
            budget_cents=budget_cents,
            usage=SessionUsage(list_cost_cents=list_cost_cents),
        )
        self._sessions[session_id] = self._session
        for info in workspace_sessions:
            self._sessions[info.id] = _Session(
                id=info.id,
                created_at=info.created_at or FAKE_EPOCH,
                primary_thread_id=f"{DEFAULT_PRIMARY_THREAD_ID}_{len(self._sessions)}",
                scripted=False,
                status=info.status,
                budget_cents=info.budget_cents,
                usage=info.usage,
                metadata=dict(info.metadata),
                archived=info.archived,
            )
        self._scripted_created = False
        self._extra_sessions = 0
        self._event_counter = 0

        self._faults: dict[str, deque[_Fault]] = {}
        self._latency: dict[str, float] = {}
        self._call_counts: dict[str, int] = {}
        self._success_counts: dict[str, int] = {}
        self._consumed_calls: dict[str, int] = {}
        self._driver_sends: list[SentEvent] = []
        self._send_cursor = 0

        self._driver: asyncio.Task[None] | None = None
        self._step_index = 0
        self._driver_finished = not steps
        self._mismatches: list[ScriptMismatchError] = []
        self._waiters: set[asyncio.Event] = set()
        self._reached: set[str] = set()
        self._released: set[str] = set()
        self._at_checkpoint: str | None = None

    # --- construction helpers ---------------------------------------------------------------

    @classmethod
    def from_jsonl(cls, path: Path | str, **kwargs: Any) -> FakeManagedAgentsClient:
        """Load a script file (one JSON object per line, `#` comment lines and blank lines
        skipped). A bare scenario name (`"happy_path"`) is looked up in `FIXTURES_DIR`."""
        resolved = Path(path)
        if not resolved.exists() and not resolved.is_absolute():
            candidate = FIXTURES_DIR / resolved
            resolved = candidate if candidate.suffix else candidate.with_suffix(".jsonl")
        steps, lines = load_jsonl(resolved)
        kwargs.setdefault("step_lines", lines)
        kwargs.setdefault("source", resolved.name)
        return cls(steps, **kwargs)

    @classmethod
    def from_scenario(cls, name: str, **kwargs: Any) -> FakeManagedAgentsClient:
        """`from_jsonl(FIXTURES_DIR / f"{name}.jsonl")`."""
        return cls.from_jsonl(FIXTURES_DIR / f"{name}.jsonl", **kwargs)

    # --- inspection -------------------------------------------------------------------------

    @property
    def meta(self) -> Mapping[str, Any]:
        """The script's `meta` step (description, request, ...) without `op`; empty when
        absent."""
        return copy.deepcopy(self._meta)

    @property
    def script(self) -> list[dict[str, Any]]:
        """The steps, `$fixture` values resolved."""
        return copy.deepcopy(self._steps)

    @property
    def history(self) -> list[dict[str, Any]]:
        """Every event of the scripted session's history so far, oldest first (what
        `list_events` pages), echoes included."""
        return copy.deepcopy(self._session.history)

    def thread_history(self, thread_id: str) -> list[dict[str, Any]]:
        """Every event emitted on one thread's scope so far, oldest first."""
        return copy.deepcopy(self._session.threads[thread_id].history)

    @property
    def status(self) -> SessionStatus:
        """The scripted session's tracked status (no status lag applied)."""
        return self._session.status

    @property
    def primary_thread_id(self) -> str:
        return self._session.primary_thread_id

    @property
    def open_streams(self) -> frozenset[str]:
        """Scopes of the scripted session with at least one open stream right now."""
        return self._session.open_scopes()

    def session_info(self, session_id: str | None = None) -> SessionInfo:
        """What `retrieve_session` would return, without recording a call or consuming lag."""
        return self._sessions[session_id or self.session_id].info(consume_lag=False)

    def threads(self) -> list[ThreadInfo]:
        """What `list_threads` would return for the scripted session, without a call."""
        return self._thread_infos(self._session)

    @property
    def unmatched_sends(self) -> list[SentEvent]:
        """Sends to the scripted session that no `await` step consumed (yet)."""
        return list(self._driver_sends[self._send_cursor :])

    @property
    def at_checkpoint(self) -> str | None:
        """The checkpoint the driver is blocked at, if any."""
        return self._at_checkpoint

    @property
    def mismatches(self) -> list[ScriptMismatchError]:
        return list(self._mismatches)

    @property
    def done(self) -> bool:
        """True once every step ran without a mismatch."""
        return self._driver_finished and not self._mismatches

    def calls_of(self, method: str) -> list[RecordedCall]:
        return [call for call in self.calls if call.method == method]

    # --- test controls ----------------------------------------------------------------------

    def fail_next(
        self, method: str, error: ManagedAgentsError | FaultKind, *, after: int = 0
    ) -> None:
        """Make the next call of `method` (a Protocol method name) raise `error`, after
        `after` calls that succeed normally. `error` may be a fault kind name; `"hang"` blocks
        the call until it is cancelled (a process killed mid-call)."""
        if method not in PROTOCOL_METHODS:
            msg = f"unknown method {method!r}; expected one of {sorted(PROTOCOL_METHODS)}"
            raise ValueError(msg)
        fault_error: ManagedAgentsError | Literal["hang"]
        if isinstance(error, str):
            fault_error = "hang" if error == "hang" else make_fault(error, method)
        else:
            fault_error = error
        self._faults.setdefault(method, deque()).append(_Fault(fault_error, after))

    def set_latency(self, method: str, seconds: float) -> None:
        """Make every later call of `method` (a Protocol method name) wait `seconds` before it
        runs, like a slow network (0 removes it). The fake's other calls answer at once, which
        hides races a real client's latency exposes (a backfill still in flight when a decision
        ends the consumer). The wait comes before any `fail_next` fault."""
        if method not in PROTOCOL_METHODS:
            msg = f"unknown method {method!r}; expected one of {sorted(PROTOCOL_METHODS)}"
            raise ValueError(msg)
        if seconds < 0:
            msg = f"latency must be >= 0, got {seconds}"
            raise ValueError(msg)
        if seconds:
            self._latency[method] = seconds
        else:
            self._latency.pop(method, None)

    def start(self) -> None:
        """Start the script driver now (normally it starts with the first `create_session` or
        stream). Idempotent; needs a running event loop."""
        self._ensure_driver()

    def emit(self, event: Mapping[str, Any], *, scope: str = PRIMARY_SCOPE) -> RawEvent:
        """Emit one event on the scripted session from test code, as an `emit` step would;
        returns the stamped event."""
        problem = self._emit_problem(self._session, scope)
        if problem:
            raise ValueError(problem)
        return self._emit(self._session, event, scope)

    def disconnect(self, scope: str = PRIMARY_SCOPE, *, error_type: str | None = None) -> int:
        """Drop the open stream(s) of `scope` (`"all"` for every scope): their iterators raise
        `StreamDisconnectedError`. Returns how many streams were dropped."""
        return self._disconnect(self._session, scope, error_type)

    async def reached(self, checkpoint: str) -> None:
        """Wait until the script driver stops at `{"op": "checkpoint", "name": checkpoint}`;
        AssertionError after the client's `await_timeout` (or the driver's first mismatch)."""
        ok = await self._wait_until(
            lambda: checkpoint in self._reached or self._driver_stopped, self.await_timeout
        )
        if checkpoint in self._reached:
            return
        self._raise_first_mismatch()
        if not ok:
            msg = f"checkpoint {checkpoint!r} not reached within {self.await_timeout}s"
            raise AssertionError(msg)
        msg = f"the script ended without reaching checkpoint {checkpoint!r}"
        raise AssertionError(msg)

    def release(self, checkpoint: str) -> None:
        """Let the driver continue past `checkpoint` (also before it gets there)."""
        self._released.add(checkpoint)
        self._notify()

    async def called(self, method: str, count: int = 1) -> RecordedCall:
        """Wait until `method` has been called `count` times (failed and pending calls
        included) and return that call; AssertionError after `await_timeout`."""
        if method not in PROTOCOL_METHODS:
            msg = f"unknown method {method!r}"
            raise ValueError(msg)
        ok = await self._wait_until(
            lambda: self._call_counts.get(method, 0) >= count, self.await_timeout
        )
        if not ok:
            seen = self._call_counts.get(method, 0)
            msg = f"{method} called {seen} times, expected {count} within {self.await_timeout}s"
            raise AssertionError(msg)
        return self.calls_of(method)[count - 1]

    async def wait_until_done(self) -> None:
        """Wait until every step ran; AssertionError after the client's `await_timeout`, or
        the first recorded mismatch."""
        ok = await self._wait_until(lambda: self._driver_stopped, self.await_timeout)
        self._raise_first_mismatch()
        if not ok:
            msg = (
                f"script not finished within {self.await_timeout}s: stuck at "
                f"{self._describe_step(self._step_index)}"
            )
            raise AssertionError(msg)

    def assert_script_done(self) -> None:
        """Raise the first recorded `ScriptMismatchError`, or an AssertionError naming the
        first step not reached."""
        self._raise_first_mismatch()
        if not self._driver_finished and self._step_index < len(self._steps):
            msg = f"script not finished: stopped before {self._describe_step(self._step_index)}"
            raise AssertionError(msg)

    async def shutdown(self) -> None:
        """Cancel the driver (end of a test that leaves the script unfinished on purpose)."""
        task = self._driver
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    # --- ManagedAgentsClient ---------------------------------------------------------------

    async def create_session(
        self,
        *,
        agent: AgentPin,
        environment_id: str,
        budget_cents: int,
        metadata: Mapping[str, str],
        title: str | None = None,
    ) -> SessionInfo:
        call = self._record(
            "create_session",
            None,
            agent=agent,
            environment_id=environment_id,
            budget_cents=budget_cents,
            metadata=dict(metadata),
            title=title,
        )
        await self._fault("create_session", call)
        problem = _create_problem(agent, environment_id, budget_cents, metadata)
        if problem:
            raise self._reject(call, problem)
        if not self._scripted_created:
            self._scripted_created = True
            session = self._session
        else:
            self._extra_sessions += 1
            session = _Session(
                id=f"sesn_fake_extra_{self._extra_sessions:04d}",
                created_at=FAKE_EPOCH,
                primary_thread_id=f"{DEFAULT_PRIMARY_THREAD_ID}_{self._extra_sessions}",
                scripted=False,
                usage=SessionUsage(list_cost_cents=0),
            )
            self._sessions[session.id] = session
        session.budget_cents = budget_cents
        session.metadata = dict(metadata)
        session.title = title
        call.session_id = session.id
        self.created.append(
            CreatedSession(
                session_id=session.id,
                agent=agent,
                environment_id=environment_id,
                budget_cents=budget_cents,
                metadata=dict(metadata),
                title=title,
            )
        )
        if session.scripted:
            self._ensure_driver()
        self._succeeded("create_session")
        return session.info(consume_lag=False)

    async def send_user_message(self, session_id: str, text: str) -> None:
        call = self._record("send_user_message", session_id, text=text)
        await self._fault("send_user_message", call)
        session = self._live_session(call, session_id)
        if session.status == "terminated" or session.archived:
            raise self._reject(call, "session is terminated: it accepts no new messages")
        if session.budget_blocked:
            raise self._reject(
                call,
                "session has reached its budget: only settle events are accepted until the "
                "budget is raised",
            )
        payload = {"type": "user.message", "content": [{"type": "text", "text": text}]}
        self._accept_send(session, payload, echo_id=self._next_id())
        self._succeeded("send_user_message")

    async def send_custom_tool_result(
        self, session_id: str, tool_use_id: str, content: str, is_error: bool
    ) -> None:
        call = self._record(
            "send_custom_tool_result",
            session_id,
            tool_use_id=tool_use_id,
            content=content,
            is_error=is_error,
        )
        await self._fault("send_custom_tool_result", call)
        session = self._live_session(call, session_id)
        if session.status == "terminated" or session.archived:
            raise self._reject(call, "session is terminated")
        if tool_use_id not in session.custom_tool_use_ids:
            raise self._reject(call, f"no agent.custom_tool_use with id {tool_use_id!r}")
        payload = {
            "type": "user.custom_tool_result",
            "custom_tool_use_id": tool_use_id,
            "content": [{"type": "text", "text": content}],
            "is_error": is_error,
        }
        # "A second result for the same call is accepted and has no effect": no second echo.
        first = tool_use_id not in session.answered_tool_use_ids
        session.answered_tool_use_ids.add(tool_use_id)
        self._accept_send(session, payload, echo_id=self._next_id() if first else None)
        self._succeeded("send_custom_tool_result")

    async def send_interrupt(self, session_id: str, thread_id: str | None = None) -> None:
        call = self._record("send_interrupt", session_id, thread_id=thread_id)
        await self._fault("send_interrupt", call)
        session = self._live_session(call, session_id)
        if session.status == "terminated" or session.archived:
            raise self._reject(call, "session is terminated")
        if thread_id is not None and thread_id not in session.threads:
            raise self._not_found(call, f"thread {thread_id} not found")
        payload: dict[str, Any] = {"type": "user.interrupt"}
        if thread_id is not None:
            payload["session_thread_id"] = thread_id
        if thread_id is None:
            self._close_pending_custom_tool_calls(session)
        # "Interrupt events may have empty IDs in the current implementation" [SKILL].
        self._accept_send(session, payload, echo_id="")
        self._succeeded("send_interrupt")

    def stream_session(self, session_id: str) -> AbstractAsyncContextManager[EventStream]:
        return self._open_stream("stream_session", session_id, None)

    def stream_thread(
        self, session_id: str, thread_id: str
    ) -> AbstractAsyncContextManager[EventStream]:
        return self._open_stream("stream_thread", session_id, thread_id)

    async def list_events(
        self,
        session_id: str,
        *,
        since: dt.datetime | None = None,
        page: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> EventPage:
        call = self._record("list_events", session_id, since=since, page=page, limit=limit)
        await self._fault("list_events", call)
        session = self._live_session(call, session_id)
        if since is not None and since.tzinfo is None:
            msg = "list_events: `since` must be timezone-aware"
            raise ValueError(msg)
        events = session.history
        if since is not None:
            events = [event for event in events if _at_or_after(event, since)]
        result = self._page(call, events, page, limit)
        self._succeeded("list_events")
        return result

    async def list_thread_events(
        self,
        session_id: str,
        thread_id: str,
        *,
        page: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> EventPage:
        call = self._record(
            "list_thread_events", session_id, thread_id=thread_id, page=page, limit=limit
        )
        await self._fault("list_thread_events", call)
        session = self._live_session(call, session_id)
        thread = session.threads.get(thread_id)
        if thread is None:
            raise self._not_found(call, f"thread {thread_id} not found")
        result = self._page(call, thread.history, page, limit)
        self._succeeded("list_thread_events")
        return result

    async def list_threads(self, session_id: str) -> list[ThreadInfo]:
        call = self._record("list_threads", session_id)
        await self._fault("list_threads", call)
        session = self._live_session(call, session_id)
        self._succeeded("list_threads")
        return self._thread_infos(session)

    async def archive_thread(self, session_id: str, thread_id: str) -> None:
        call = self._record("archive_thread", session_id, thread_id=thread_id)
        await self._fault("archive_thread", call)
        session = self._live_session(call, session_id)
        if thread_id == session.primary_thread_id:
            raise self._reject(call, "the primary thread cannot be archived")
        thread = session.threads.get(thread_id)
        if thread is None:
            raise self._not_found(call, f"thread {thread_id} not found")
        if not thread.archived:
            thread.archived = True
            self.archived_threads.append((session_id, thread_id))
        self._succeeded("archive_thread")
        self._notify()

    async def retrieve_session(self, session_id: str) -> SessionInfo:
        call = self._record("retrieve_session", session_id)
        await self._fault("retrieve_session", call)
        session = self._live_session(call, session_id)
        self._succeeded("retrieve_session")
        return session.info(consume_lag=True)

    async def update_budget(self, session_id: str, budget_cents: int) -> SessionInfo:
        call = self._record("update_budget", session_id, budget_cents=budget_cents)
        await self._fault("update_budget", call)
        session = self._live_session(call, session_id)
        if session.status == "terminated" or session.archived:
            raise self._reject(call, "session is terminated")
        if isinstance(budget_cents, bool) or not isinstance(budget_cents, int) or budget_cents < 1:
            raise self._reject(call, "budget must be a positive integer amount of cents")
        consumed = session.usage.list_cost_cents or 0
        if budget_cents <= consumed:
            raise self._reject(
                call,
                f"budget {budget_cents} must exceed the consumed list cost {consumed}",
                error_type="budget_not_raised",
            )
        session.budget_cents = budget_cents
        session.budget_blocked = False
        self.budget_updates.append((session_id, budget_cents))
        self._emit(session, {"type": "session.updated", "budget": _budget_object(budget_cents)})
        self._succeeded("update_budget")
        return session.info(consume_lag=False)

    async def archive_session(self, session_id: str) -> None:
        call = self._record("archive_session", session_id)
        await self._fault("archive_session", call)
        session = self._live_session(call, session_id)
        if session.archived:
            self._succeeded("archive_session")
            return
        if session.reported_status(consume=False) == "running":
            raise self._busy(call, "session is running: interrupt it and wait for idle first")
        session.archived = True
        self.archived.append(session_id)
        self._emit(session, {"type": "session.status_terminated"})
        self._succeeded("archive_session")

    async def delete_session(self, session_id: str) -> None:
        call = self._record("delete_session", session_id)
        await self._fault("delete_session", call)
        session = self._live_session(call, session_id)
        if session.reported_status(consume=False) == "running":
            raise self._busy(call, "session is running: interrupt it and wait for idle first")
        deleted = {
            "id": self._next_id(),
            "type": "session.deleted",
            "processed_at": format_instant(self._next_stamp(session)),
        }
        for scope in list(session.streams):
            self._deliver(session, scope, deleted)
        self._end_streams(session, None)
        session.deleted = True
        session.history.clear()
        for thread in session.threads.values():
            thread.history.clear()
        self.deleted.append(session_id)
        self._succeeded("delete_session")
        self._notify()

    async def list_sessions(
        self, *, created_before: dt.datetime, include_archived: bool = True
    ) -> list[SessionInfo]:
        call = self._record(
            "list_sessions",
            None,
            created_before=created_before,
            include_archived=include_archived,
        )
        await self._fault("list_sessions", call)
        if created_before.tzinfo is None:
            msg = "list_sessions: `created_before` must be timezone-aware"
            raise ValueError(msg)
        sessions = [
            session
            for session in self._sessions.values()
            if not session.deleted
            and session.created_at < created_before
            and (include_archived or not session.archived)
        ]
        sessions.sort(key=lambda session: session.created_at)
        self._succeeded("list_sessions")
        return [session.info(consume_lag=False) for session in sessions]

    async def aclose(self) -> None:
        call = self._record("aclose", None)
        await self._fault("aclose", call)
        self.closed = True
        self._succeeded("aclose")

    # --- calls, faults and errors -------------------------------------------------------------

    def _record(self, method: str, session_id: str | None, **args: Any) -> RecordedCall:
        call = RecordedCall(method=method, session_id=session_id, args=args)
        self.calls.append(call)
        self._call_counts[method] = self._call_counts.get(method, 0) + 1
        self._notify()
        return call

    def _succeeded(self, method: str) -> None:
        self._success_counts[method] = self._success_counts.get(method, 0) + 1
        self._notify()

    async def _fault(self, method: str, call: RecordedCall) -> None:
        latency = self._latency.get(method)
        if latency:
            await asyncio.sleep(latency)
        queue = self._faults.get(method)
        if not queue:
            return
        fault = queue[0]
        if fault.after > 0:
            fault.after -= 1
            return
        queue.popleft()
        if fault.error == "hang":
            await self._hang(method, call)
        call.error = fault.error
        raise fault.error

    async def _hang(self, method: str, call: RecordedCall) -> NoReturn:
        """Block like a call to a process that died: until cancelled. A hang nobody cancels
        is a test bug: after `await_timeout` it is recorded as a mismatch and the call fails."""
        try:
            await asyncio.sleep(self.await_timeout)
        except asyncio.CancelledError:
            call.error = ApiUnavailableError(f"fake: hung {method} cancelled")
            raise
        self._record_mismatch(f"the hung {method} call was never cancelled")
        error = ApiUnavailableError(f"fake: hung {method} timed out", status_code=504)
        call.error = error
        raise error

    def _reject(
        self, call: RecordedCall, message: str, *, error_type: str = "invalid_request_error"
    ) -> ApiRejectedError:
        error = ApiRejectedError(f"fake: {message}", status_code=400, error_type=error_type)
        call.error = error
        return error

    def _not_found(self, call: RecordedCall, message: str) -> SessionNotFoundError:
        error = SessionNotFoundError(
            f"fake: {message}", status_code=404, error_type="not_found_error"
        )
        call.error = error
        return error

    def _busy(self, call: RecordedCall, message: str) -> SessionBusyError:
        error = SessionBusyError(
            f"fake: {message}", status_code=409, error_type="invalid_request_error"
        )
        call.error = error
        return error

    def _live_session(self, call: RecordedCall, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None or session.deleted:
            raise self._not_found(call, f"session {session_id} not found")
        return session

    # --- sends ----------------------------------------------------------------------------

    def _close_pending_custom_tool_calls(self, session: _Session) -> None:
        """Probe P14: a `user.interrupt` (without a thread id) makes the platform answer every
        custom tool call still waiting for a result with an `agent.tool_result`, before the
        interrupt's own echo. The call then counts as answered: a later
        `user.custom_tool_result` is accepted and recorded, never echoed."""
        pending = [
            event["id"]
            for event in session.history
            if event.get("type") == "agent.custom_tool_use"
            and event["id"] in session.custom_tool_use_ids - session.answered_tool_use_ids
        ]
        for tool_use_id in pending:
            session.answered_tool_use_ids.add(tool_use_id)
            self._emit(
                session,
                {
                    "type": "agent.tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": True,
                    "content": [{"type": "text", "text": INTERRUPTED_TOOL_TEXT}],
                },
            )

    def _accept_send(
        self, session: _Session, payload: dict[str, Any], *, echo_id: str | None
    ) -> None:
        sent = SentEvent(
            session_id=session.id,
            payload=copy.deepcopy(payload),
            open_streams=session.open_scopes(),
        )
        self.sent.append(sent)
        if session.scripted:
            self._driver_sends.append(sent)
        if echo_id is not None:
            self._emit(session, {**payload, "id": echo_id})
        self._notify()

    # --- streams ----------------------------------------------------------------------------

    @asynccontextmanager
    async def _open_stream(
        self, method: str, session_id: str, thread_id: str | None
    ) -> AsyncIterator[_Stream]:
        args: dict[str, Any] = {} if thread_id is None else {"thread_id": thread_id}
        call = self._record(method, session_id, **args)
        await self._fault(method, call)
        session = self._live_session(call, session_id)
        if thread_id is not None and thread_id not in session.threads:
            raise self._not_found(call, f"thread {thread_id} not found")
        scope = PRIMARY_SCOPE if thread_id is None else thread_id
        stream = _Stream(scope)
        session.streams.setdefault(scope, []).append(stream)
        self._succeeded(method)
        if session.scripted:
            self._ensure_driver()
        try:
            yield stream
        finally:
            stream.finished = True
            streams = session.streams.get(scope, [])
            if stream in streams:
                streams.remove(stream)
            self._notify()

    def _deliver(self, session: _Session, scope: str, event: RawEvent) -> None:
        for stream in session.streams.get(scope, []):
            stream.queue.put_nowait(copy.deepcopy(event))

    def _end_streams(self, session: _Session, scope: str | None) -> None:
        """End the iterators of `scope` (every scope when None) normally."""
        scopes = list(session.streams) if scope is None else [scope]
        for name in scopes:
            for stream in session.streams.get(name, []):
                stream.queue.put_nowait(_END)
            session.streams[name] = []
        self._notify()

    def _disconnect(self, session: _Session, scope: str, error_type: str | None) -> int:
        scopes = list(session.streams) if scope == "all" else [scope]
        dropped = 0
        for name in scopes:
            for stream in session.streams.get(name, []):
                reason = f"event: error ({error_type})" if error_type else "connection dropped"
                stream.queue.put_nowait(
                    StreamDisconnectedError(f"fake: {reason} on {name}", error_type=error_type)
                )
                dropped += 1
            session.streams[name] = []
        self._notify()
        return dropped

    # --- listings ---------------------------------------------------------------------------

    def _page(
        self, call: RecordedCall, events: list[RawEvent], page: str | None, limit: int
    ) -> EventPage:
        if limit < 1:
            raise self._reject(call, f"limit must be positive, got {limit}")
        offset = 0
        if page is not None:
            if not page.startswith("p") or not page[1:].isdigit():
                raise self._reject(call, f"invalid page cursor {page!r}")
            offset = int(page[1:])
        size = min(limit, self.page_size) if self.page_size else limit
        chunk = events[offset : offset + size]
        end = offset + len(chunk)
        next_page = f"p{end}" if end < len(events) else None
        return EventPage(events=copy.deepcopy(chunk), next_page=next_page)

    def _thread_infos(self, session: _Session) -> list[ThreadInfo]:
        primary_status: ThreadStatus = session.status
        infos = [
            ThreadInfo(
                id=session.primary_thread_id,
                agent_name=COORDINATOR_AGENT_NAME,
                parent_thread_id=None,
                status=primary_status,
            )
        ]
        infos.extend(
            ThreadInfo(
                id=thread.id,
                agent_name=thread.agent_name,
                parent_thread_id=thread.parent_thread_id,
                status=thread.status,
                archived=thread.archived,
            )
            for thread in session.threads.values()
        )
        return infos

    # --- events -----------------------------------------------------------------------------

    def _next_id(self) -> str:
        self._event_counter += 1
        return f"{self._id_prefix}{self._event_counter:04d}"

    def _next_stamp(self, session: _Session) -> dt.datetime:
        stamp = FAKE_EPOCH if session.latest is None else session.latest + AUTO_STAMP_STEP
        session.latest = stamp
        return stamp

    def _emit_problem(self, session: _Session, scope: str) -> str | None:
        if session.deleted:
            return "emit to a deleted session"
        if scope == PRIMARY_SCOPE:
            return None
        thread = session.threads.get(scope)
        if thread is None:
            return f"emit to unknown thread scope {scope!r} (no session.thread_created for it)"
        if thread.archived:
            return f"emit to archived thread {scope!r}: archived threads take no new work"
        return None

    def _emit(
        self, session: _Session, event: Mapping[str, Any], scope: str = PRIMARY_SCOPE
    ) -> RawEvent:
        """Stamp, store, apply side effects and deliver one event (README, "Script format")."""
        raw: RawEvent = copy.deepcopy(dict(event))
        if "id" not in raw:
            raw["id"] = self._next_id()
        if "processed_at" not in raw:
            raw["processed_at"] = format_instant(self._next_stamp(session))
        else:
            stamp = _parse_instant(raw["processed_at"])
            if stamp is not None and (session.latest is None or stamp > session.latest):
                session.latest = stamp
        if scope == PRIMARY_SCOPE:
            session.history.append(raw)
        else:
            session.threads[scope].history.append(raw)
        self._apply(session, raw, scope)
        self._deliver(session, scope, raw)
        event_type = raw.get("type")
        if event_type in _STREAM_ENDING_TYPES and scope == PRIMARY_SCOPE:
            self._end_streams(session, None)
        elif event_type == "session.thread_status_terminated" and scope != PRIMARY_SCOPE:
            self._end_streams(session, scope)
        self._notify()
        return raw

    def _apply(self, session: _Session, raw: RawEvent, scope: str) -> None:
        """The tracked state an event changes: status, threads, usage, budget, tool uses."""
        event_type = raw.get("type")
        if not isinstance(event_type, str):
            return
        if scope == PRIMARY_SCOPE and event_type in _SESSION_STATUS_BY_EVENT:
            session.status = _SESSION_STATUS_BY_EVENT[event_type]
            if event_type == "session.status_idle":
                session.lag_remaining = session.status_lag
                stop_reason = raw.get("stop_reason")
                if isinstance(stop_reason, Mapping):
                    reason = cast(Mapping[str, Any], stop_reason).get("type")
                    if reason == "budget_reached":
                        session.budget_blocked = True
            else:
                session.lag_remaining = 0
                if event_type == "session.status_running":
                    session.budget_blocked = False
        elif event_type == "session.deleted" and scope == PRIMARY_SCOPE:
            session.deleted = True
        elif event_type == "session.thread_created":
            thread_id = raw.get("session_thread_id")
            if isinstance(thread_id, str) and thread_id not in session.threads:
                agent_name = raw.get("agent_name")
                session.threads[thread_id] = _Thread(
                    id=thread_id,
                    agent_name=agent_name if isinstance(agent_name, str) else None,
                    parent_thread_id=session.primary_thread_id,
                )
        elif event_type in _THREAD_STATUS_BY_EVENT:
            thread = session.threads.get(str(raw.get("session_thread_id")))
            if thread is not None:
                thread.status = _THREAD_STATUS_BY_EVENT[event_type]
        elif event_type == "session.usage":
            usage = raw.get("usage")
            if isinstance(usage, Mapping):
                session.usage = _usage_from_payload(cast(Mapping[str, Any], usage), session.usage)
        elif event_type == "agent.custom_tool_use":
            tool_use_id = raw.get("id")
            if isinstance(tool_use_id, str) and tool_use_id:
                session.custom_tool_use_ids.add(tool_use_id)
        if event_type == "session.updated":
            budget = raw.get("budget")
            if isinstance(budget, Mapping):
                limit = cast(Mapping[str, Any], budget).get("max_list_cost")
                if isinstance(limit, Mapping):
                    amount = cast(Mapping[str, Any], limit).get("amount")
                    if isinstance(amount, str | int):
                        session.budget_cents = int(amount)

    # --- the driver -------------------------------------------------------------------------

    @property
    def _driver_stopped(self) -> bool:
        return self._driver_finished or bool(self._mismatches)

    def _ensure_driver(self) -> None:
        if self._driver is None and self._steps:
            self._driver = asyncio.get_running_loop().create_task(
                self._run_driver(), name=f"fake-ma-driver-{self.session_id}"
            )

    async def _run_driver(self) -> None:
        try:
            for index, step in enumerate(self._steps):
                self._step_index = index
                await self._run_step(step)
                self._step_index = index + 1
                if self._step_index < len(self._steps):
                    await asyncio.sleep(0)  # let the backend run between steps
            # Marked before yielding: a test that saw the last event sees a finished script.
            self._driver_finished = True
        except _ScriptStoppedError:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a bug in a step: surface it through assert_script_done
            self._record_mismatch(f"{type(exc).__name__}: {exc}")
        finally:
            self._notify()

    async def _run_step(self, step: Mapping[str, Any]) -> None:
        session = self._session
        timeout = float(step.get("timeout", self.await_timeout))
        match step["op"]:
            case "meta":
                return
            case "emit":
                scope = str(step.get("scope", PRIMARY_SCOPE))
                problem = self._emit_problem(session, scope)
                if problem:
                    self._fail(problem)
                self._emit(session, step["event"], scope)
            case "await":
                await self._step_await(step, timeout)
            case "await_call":
                await self._step_await_call(step, timeout)
            case "await_stream":
                scope = str(step.get("scope", PRIMARY_SCOPE))
                ok = await self._wait_until(
                    lambda: scope in session.open_scopes(), timeout, stop_on_mismatch=True
                )
                if not ok:
                    self._fail(f"timed out after {timeout}s waiting for a {scope!r} stream")
            case "usage":
                self._emit(session, build_usage_event(step, budget_cents=session.budget_cents))
            case "set":
                self._step_set(session, step)
            case "disconnect":
                self._disconnect(
                    session, str(step.get("scope", PRIMARY_SCOPE)), step.get("error_type")
                )
            case "fail_next":
                method = str(step["method"])
                kind = str(step["error"])
                error: ManagedAgentsError | Literal["hang"] = (
                    "hang" if kind == "hang" else make_fault(kind, method, step.get("message"))
                )
                self._faults.setdefault(method, deque()).append(
                    _Fault(error, int(step.get("after", 0)))
                )
            case "checkpoint":
                await self._step_checkpoint(str(step["name"]), timeout)
            case _:  # pragma: no cover - rejected by _check_step
                self._fail(f"unknown op {step['op']!r}")

    async def _step_await(self, step: Mapping[str, Any], wait_seconds: float) -> None:
        expected = step["match"]
        for number in range(1, int(step.get("count", 1)) + 1):
            ok = await self._wait_until(
                lambda: self._send_cursor < len(self._driver_sends),
                wait_seconds,
                stop_on_mismatch=True,
            )
            if not ok:
                self._fail(
                    f"timed out after {wait_seconds}s waiting for send #{number} matching "
                    f"{json.dumps(expected, ensure_ascii=False)}"
                )
            sent = self._driver_sends[self._send_cursor]
            self._send_cursor += 1
            if not contains(sent.payload, expected):
                self._fail(
                    f"the backend sent {json.dumps(sent.payload, ensure_ascii=False)[:500]}, "
                    f"expected a send matching {json.dumps(expected, ensure_ascii=False)}"
                )

    async def _step_await_call(self, step: Mapping[str, Any], wait_seconds: float) -> None:
        method = str(step["method"])
        for _ in range(int(step.get("count", 1))):
            ok = await self._wait_until(
                lambda: self._success_counts.get(method, 0) > self._consumed_calls.get(method, 0),
                wait_seconds,
                stop_on_mismatch=True,
            )
            if not ok:
                self._fail(
                    f"timed out after {wait_seconds}s waiting for a successful {method} call"
                )
            self._consumed_calls[method] = self._consumed_calls.get(method, 0) + 1

    async def _step_checkpoint(self, name: str, wait_seconds: float) -> None:
        self._at_checkpoint = name
        self._reached.add(name)
        self._notify()
        ok = await self._wait_until(
            lambda: name in self._released, wait_seconds, stop_on_mismatch=True
        )
        self._at_checkpoint = None
        if not ok:
            self._fail(f"checkpoint {name!r} not released within {wait_seconds}s")
        self._released.discard(name)

    def _step_set(self, session: _Session, step: Mapping[str, Any]) -> None:
        if "status" in step:
            session.status = cast(SessionStatus, step["status"])
        if "status_lag" in step:
            session.status_lag = int(step["status_lag"])
        if "budget_cents" in step:
            session.budget_cents = step["budget_cents"]
        if "list_cost_cents" in step:
            session.usage = dataclasses.replace(
                session.usage, list_cost_cents=step["list_cost_cents"]
            )
        if "page_size" in step:
            self.page_size = step["page_size"]

    # --- waiting and mismatches -----------------------------------------------------------------

    def _notify(self) -> None:
        for waiter in self._waiters:
            waiter.set()

    async def _wait_until(
        self, predicate: Callable[[], bool], wait_seconds: float, *, stop_on_mismatch: bool = False
    ) -> bool:
        """Wait until `predicate()` holds; False after `wait_seconds`. With
        `stop_on_mismatch`, a mismatch recorded meanwhile stops the driver at once."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while not predicate():
            if stop_on_mismatch and self._mismatches:
                raise _ScriptStoppedError
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            waiter = asyncio.Event()
            self._waiters.add(waiter)
            try:
                async with asyncio.timeout(remaining):
                    await waiter.wait()
            except TimeoutError:
                pass
            finally:
                self._waiters.discard(waiter)
        return True

    def _describe_step(self, index: int) -> str:
        if index >= len(self._steps):
            return "the end of the script"
        step = self._steps[index]
        where = f"step {index}"
        if self._step_lines is not None and index < len(self._step_lines):
            where += f" ({self._source or 'script'} line {self._step_lines[index]})"
        detail = {key: value for key, value in step.items() if key != "op"}
        text = json.dumps(detail, ensure_ascii=False)
        return f"{where} {step['op']} {text[:200]}"

    def _record_mismatch(self, message: str) -> ScriptMismatchError:
        error = ScriptMismatchError(f"{self._describe_step(self._step_index)}: {message}")
        self._mismatches.append(error)
        self._notify()
        return error

    def _fail(self, message: str) -> NoReturn:
        self._record_mismatch(message)
        raise _ScriptStoppedError

    def _raise_first_mismatch(self) -> None:
        if self._mismatches:
            raise self._mismatches[0]


def _at_or_after(event: RawEvent, since: dt.datetime) -> bool:
    stamp = _parse_instant(event.get("processed_at"))
    return stamp is not None and stamp >= since


def _create_problem(
    agent: AgentPin, environment_id: str, budget_cents: int, metadata: Mapping[str, str]
) -> str | None:
    """The `sessions.create` rules the fake enforces (notes §2d, "Create parameters")."""
    if not agent.id or agent.version < 1:
        return "agent must be {type: agent, id, version >= 1}"
    if not environment_id:
        return "environment_id is required"
    if isinstance(budget_cents, bool) or not isinstance(budget_cents, int) or budget_cents < 1:
        return "budget max_list_cost.amount must be a positive integer string"
    if len(metadata) > 16:
        return "metadata allows at most 16 pairs"
    for key, value in metadata.items():
        if len(key) > 64 or len(value) > 512:
            return "metadata keys are at most 64 characters and values at most 512"
    return None


def _conforms(client: FakeManagedAgentsClient) -> ManagedAgentsClient:
    """Static check only: pyright fails here if the fake drifts from the Protocol."""
    return client


__all__ = [
    "FAKE_EPOCH",
    "FIXTURES_DIR",
    "FIXTURES_ROOT",
    "PROTOCOL_METHODS",
    "STEP_OPS",
    "CreatedSession",
    "FakeManagedAgentsClient",
    "FaultKind",
    "RecordedCall",
    "ScriptMismatchError",
    "ScriptStep",
    "SentEvent",
    "StepOp",
    "build_usage_event",
    "contains",
    "format_instant",
    "load_jsonl",
    "make_fault",
    "resolve_fixtures",
]
