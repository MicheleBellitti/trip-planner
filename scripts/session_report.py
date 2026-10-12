#!/usr/bin/env python3
"""What fills the context of a Managed Agents session? A read-only report.

A session that stops at its budget with few web searches usually carries a large context that
every model request re-reads (cache_read_input_tokens). This script lists the whole history of
one or more sessions (the primary thread and every subagent thread) and says where the tokens
sit:

    uv run python ../scripts/session_report.py --session sesn_01L6XwY6Xm7uHcTm7DkXeRaz
    uv run python ../scripts/session_report.py --session sesn_a sesn_b --out report.md
    uv run python ../scripts/session_report.py --static          # no API: the fixed context

Run it from `backend/` (its venv has anthropic 1.13.0 and PyYAML). It only READS: it lists
events and threads and retrieves the session, never sends an event, never creates a session, and
costs nothing. Credentials are the SDK's own (ANTHROPIC_API_KEY, or the development federation
variables); the key is never printed, and any `sk-ant-...` or `Bearer ...` string in the output is
redacted. Text taken from events (page titles, queries, messages) is capped at 200 characters.

Live report, per session:

- the totals (`session.usage` snapshots and the session's own usage), and per thread: model
  requests, input / cache creation / cache read / output tokens summed from
  `span.model_request_end.model_usage`, the first, maximum and final context size of a request
  (input + cache creation + cache read), the system prompt and tool definition sizes from the
  thread's agent snapshot;
- a token timeline per thread: one row per model request, the context growth against the
  previous request and the tool results, messages and calls added in between;
- the contributors: every tool call and its result, every agent message and inter-agent message,
  grouped by kind (web_search, web_fetch, MCP, skill files, workspace reads, bash, write/edit,
  submit_plan, ...), the top 20 tool results by size, and the biggest items by "carried" tokens,
  that is estimated tokens x the number of later model requests that re-read them;
- the compact event history of the session and of each thread (`--no-history` drops it).

Sizes are characters of the event JSON content, tokens are chars / 4 (an estimate: real
tokenisation differs, especially for JSON and non-English text). The context an item adds is
only approximated: thinking blocks carry no content in events, and the system prompt and tool
definitions are not events; the report shows the part of the final context its items do not
explain.

`--static` needs no API: it estimates the fixed context of each agent from
`profiles/<profile>/agents/*.md` (system prompt), the custom tools it declares
(`agents/tools/submit_plan.json`) and the skills it references (descriptions, always present;
SKILL.md and the data files the agent reads), in characters and tokens. Built-in tool and MCP tool
definitions cannot be measured offline: compare with the live "first request" context.

`--save-raw DIR` stores the fetched events as JSON (they contain page text: keep DIR out of the
repository) and `--from-raw DIR` analyses them again without any network.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
for _path in (SCRIPTS_DIR, REPO_ROOT / "backend"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import yaml  # noqa: E402

CHARS_PER_TOKEN = 4
SNIPPET_CAP = 200
LABEL_CAP = 120
TOP_N = 20
TIMELINE_ROW_CAP = 200
USAGE_ROW_CAP = 40
DEFAULT_SUMMARY_BYTES = 1_000_000
"""GitHub rejects a step summary above 1 MiB (1,048,576 bytes); stay below it."""

SESSION_ID_RE = re.compile(r"^sesn_[A-Za-z0-9]+$")
PRIMARY_KEY = "primary"
TOOL_SEARCH_NAMES = frozenset({"web_search", "web_fetch"})
FS_TOOL_NAMES = frozenset({"read", "bash", "grep", "glob", "edit", "write"})
LABEL_KEYS = ("query", "url", "path", "file_path", "command", "pattern", "name")

SKILL_FILE_RE = re.compile(
    r"SKILL\.md|example\.json|templates\.json|schemas/[\w.-]+\.json|/skills?/|skill_dir",
    re.IGNORECASE,
)
SCRIPT_RUN_RE = re.compile(r"\b(?:python3?|uv run)\b.*\.py\b")
READ_COMMAND_RE = re.compile(r"\b(?:cat|head|tail|sed|nl|less|more|bat)\b")
SECRET_RES = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
)

READING_GUIDE = """\
How to read it: every model request re-reads the whole context of its thread (cache read), so
the cost of an item is its size times the requests that come after it, not its size alone
("tokens carried"). The fixed part (system prompt, tool definitions, skill descriptions) is paid
by every request; compare the `first ctx` column with the `--static` floor. Output tokens
include thinking, which events do not carry.
"""

KIND_ORDER = (
    "web_search",
    "web_fetch",
    "mcp",
    "skill_file",
    "workspace_read",
    "read_other",
    "bash",
    "write_edit",
    "search_fs",
    "custom_tool",
    "other_tool",
    "inter_agent_in",
    "inter_agent_out",
    "agent_message",
    "user_message",
)

# --- small helpers ----------------------------------------------------------------------------


def est_tokens(chars: int) -> int:
    """Estimated tokens of `chars` characters (chars / 4, rounded up)."""
    return (chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def redact(text: str) -> str:
    """Hide anything that looks like an API key or bearer token, and the key of the environment."""
    for pattern in SECRET_RES:
        text = pattern.sub("[redacted]", text)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_IDENTITY_TOKEN"):
        secret = os.environ.get(name, "").strip()
        if len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    return text


def clean(text: object, cap: int = SNIPPET_CAP) -> str:
    """One line of event text, safe in a Markdown table cell, at most `cap` characters."""
    flat = " ".join(str(text).split())
    flat = flat.replace("|", "/").replace("`", "'")
    if len(flat) > cap:
        flat = flat[: max(cap - 3, 0)] + "..."
    return redact(flat)


def as_dict(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def as_list(value: object) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def parse_ts(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def hms(value: dt.datetime | None) -> str:
    return value.astimezone(dt.UTC).strftime("%H:%M:%S") if value else "-"


def json_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def content_chars(content: object) -> int:
    """Characters a tool result or message adds: text blocks by length, others by their JSON."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    total = 0
    for block in as_list(content):
        if isinstance(block, dict):
            data = cast(dict[str, Any], block)
            text = data.get("text")
            if data.get("type") == "text" and isinstance(text, str):
                total += len(text)
            else:
                total += json_chars(data)
        else:
            total += len(str(block))
    return total


def content_text(content: object) -> str:
    """The text of a content value, for snippets (non-text blocks give their title or type)."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in as_list(content):
        if isinstance(block, dict):
            data = cast(dict[str, Any], block)
            text = data.get("text")
            if isinstance(text, str):
                parts.append(text)
            else:
                parts.append(str(data.get("title") or data.get("source") or data.get("type") or ""))
    return " ".join(parts)


def tool_label(name: str, tool_input: Mapping[str, Any]) -> str:
    """`name` plus the most telling input value (query, url, path, command...)."""
    for key in LABEL_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return clean(f"{name} {value}", LABEL_CAP)
    if tool_input:
        return clean(f"{name} {json.dumps(tool_input, ensure_ascii=False)}", LABEL_CAP)
    return clean(name, LABEL_CAP)


def classify_tool(name: str, tool_input: Mapping[str, Any], *, mcp: bool = False) -> str:
    """The contributor kind of a tool call (see KIND_ORDER)."""
    if mcp:
        return "mcp"
    if name in TOOL_SEARCH_NAMES:
        return name
    if name in FS_TOOL_NAMES:
        blob = json.dumps(tool_input, ensure_ascii=False)
        if name == "read":
            path = str(tool_input.get("path") or tool_input.get("file_path") or "")
            if SKILL_FILE_RE.search(path):
                return "skill_file"
            return "workspace_read" if path.startswith("/workspace") else "read_other"
        if name == "bash":
            command = str(tool_input.get("command") or "")
            if (
                SKILL_FILE_RE.search(command)
                and READ_COMMAND_RE.search(command)
                and not SCRIPT_RUN_RE.search(command)
            ):
                return "skill_file"
            return "bash"
        if name in ("write", "edit"):
            return "write_edit"
        if SKILL_FILE_RE.search(blob):
            return "skill_file"
        return "search_fs"
    return "other_tool"


# --- the data model ---------------------------------------------------------------------------


@dataclass(slots=True)
class Item:
    """Something that entered a thread's context: a tool call input, a result, a message."""

    kind: str
    role: str
    """tool_input, tool_result, agent_message, inter_agent_in, inter_agent_out, user_message."""
    tool: str
    label: str
    chars: int
    ts: dt.datetime | None
    seq: int
    is_error: bool = False
    counted: bool = True
    """False for an item that may duplicate another (a thread_message_sent next to the
    send_to_agent call that carries the same text): listed, not added to the totals."""
    rereads: int = 0
    """Model requests of the thread that started after the item and so re-read it."""

    @property
    def tokens(self) -> int:
        return est_tokens(self.chars)

    @property
    def carried(self) -> int:
        return self.tokens * self.rereads


@dataclass(slots=True)
class Request:
    """One model request of a thread (a `span.model_request_end`)."""

    index: int
    start: dt.datetime | None
    end: dt.datetime | None
    input_tokens: int
    cache_creation: int
    cache_read: int
    output_tokens: int
    is_error: bool
    added_tokens: int = 0
    added_items: int = 0
    biggest_label: str = ""

    @property
    def context(self) -> int:
        return self.input_tokens + self.cache_creation + self.cache_read


@dataclass(slots=True)
class ThreadReport:
    key: str
    agent: str
    model: str
    is_primary: bool
    system_chars: int
    tools_chars: int
    custom_tools: list[tuple[str, int]]
    skills: int
    mcp_servers: list[str]
    api_usage: dict[str, Any]
    requests: list[Request]
    items: list[Item]
    history: list[tuple[int, dt.datetime | None, str, str]]
    event_count: int

    def total(self, field_name: str) -> int:
        return sum(getattr(r, field_name) for r in self.requests)

    @property
    def max_context(self) -> int:
        return max((r.context for r in self.requests), default=0)

    @property
    def first_context(self) -> int:
        return self.requests[0].context if self.requests else 0

    @property
    def final_context(self) -> int:
        return self.requests[-1].context if self.requests else 0


@dataclass(slots=True)
class SessionReport:
    session_id: str
    status: str
    usage: dict[str, Any]
    usage_snapshots: list[dict[str, Any]]
    stop_reasons: list[str]
    threads: list[ThreadReport]
    session_event_count: int
    warnings: list[str] = field(default_factory=list[str])


@dataclass(slots=True)
class RawSession:
    """What was fetched for one session: the server's JSON as sent."""

    session_id: str
    session: dict[str, Any]
    threads: list[dict[str, Any]]
    session_events: list[dict[str, Any]]
    thread_events: dict[str, list[dict[str, Any]]]
    warnings: list[str] = field(default_factory=list[str])

    def to_json(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session": self.session,
            "threads": self.threads,
            "session_events": self.session_events,
            "thread_events": self.thread_events,
            "warnings": self.warnings,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> RawSession:
        thread_events = {
            str(k): [as_dict(e) for e in as_list(v)]
            for k, v in as_dict(data.get("thread_events")).items()
        }
        return cls(
            session_id=str(data.get("session_id") or ""),
            session=as_dict(data.get("session")),
            threads=[as_dict(t) for t in as_list(data.get("threads"))],
            session_events=[as_dict(e) for e in as_list(data.get("session_events"))],
            thread_events=thread_events,
            warnings=[str(w) for w in as_list(data.get("warnings"))],
        )


# --- analysis ---------------------------------------------------------------------------------


def _ordered(
    events: Sequence[Mapping[str, Any]],
) -> list[tuple[dt.datetime | None, dict[str, Any]]]:
    """Events sorted by processed_at (stable); an event without one takes the previous time."""
    stamped: list[tuple[dt.datetime | None, int, dict[str, Any]]] = []
    previous: dt.datetime | None = None
    for index, event in enumerate(events):
        ts = parse_ts(event.get("processed_at")) or previous
        previous = ts or previous
        stamped.append((ts, index, dict(event)))
    stamped.sort(key=lambda t: (t[0] or dt.datetime.min.replace(tzinfo=dt.UTC), t[1]))
    return [(ts, event) for ts, _, event in stamped]


def _dedupe(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for event in events:
        event_id = event.get("id")
        if isinstance(event_id, str) and event_id:
            if event_id in seen:
                continue
            seen.add(event_id)
        out.append(dict(event))
    return out


def _agent_snapshot(thread: Mapping[str, Any]) -> tuple[str, str, int, int, list[tuple[str, int]]]:
    """(name, model, system chars, tool definition chars, custom tools) of a thread's agent."""
    agent = as_dict(thread.get("agent"))
    model = agent.get("model")
    model_id = model if isinstance(model, str) else str(as_dict(model).get("id") or "?")
    system = agent.get("system")
    tools = as_list(agent.get("tools"))
    custom: list[tuple[str, int]] = []
    for tool in tools:
        data = as_dict(tool)
        if data.get("type") == "custom":
            custom.append((str(data.get("name") or "?"), json_chars(data)))
    return (
        str(agent.get("name") or ""),
        model_id,
        len(system) if isinstance(system, str) else 0,
        json_chars(tools) if tools else 0,
        custom,
    )


def _build_items(
    events: Sequence[tuple[dt.datetime | None, dict[str, Any]]],
) -> tuple[list[Item], list[tuple[int, dt.datetime | None, str, str]]]:
    """Context items and the compact history lines (seq, time, type, summary) of one thread."""
    items: list[Item] = []
    history: list[tuple[int, dt.datetime | None, str, str]] = []
    uses: dict[str, tuple[str, str, str]] = {}
    has_send_tool = any(
        e.get("type") == "agent.tool_use" and e.get("name") == "send_to_agent" for _, e in events
    )

    def add(item: Item) -> None:
        items.append(item)

    for seq, (ts, event) in enumerate(events, start=1):
        etype = str(event.get("type") or "?")
        summary = ""
        if etype in ("agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"):
            name = str(event.get("name") or "?")
            tool_input = as_dict(event.get("input"))
            mcp = etype == "agent.mcp_tool_use"
            server = str(event.get("mcp_server_name") or "")
            shown = f"{server}.{name}" if mcp else name
            kind = (
                "custom_tool"
                if etype == "agent.custom_tool_use"
                else classify_tool(name, tool_input, mcp=mcp)
            )
            label = tool_label(shown, tool_input)
            event_id = str(event.get("id") or "")
            uses[event_id] = (kind, shown, label)
            chars = json_chars(tool_input)
            add(Item(kind, "tool_input", shown, label, chars, ts, seq))
            summary = f"{label} (input {chars:,} chars)"
        elif etype in ("agent.tool_result", "agent.mcp_tool_result", "user.custom_tool_result"):
            use_id = str(
                event.get("tool_use_id")
                or event.get("mcp_tool_use_id")
                or event.get("custom_tool_use_id")
                or ""
            )
            kind, shown, label = uses.get(use_id, ("other_tool", "(unmatched)", "(unmatched call)"))
            chars = content_chars(event.get("content"))
            error = bool(event.get("is_error"))
            add(Item(kind, "tool_result", shown, label, chars, ts, seq, is_error=error))
            summary = f"-> {chars:,} chars{' ERROR' if error else ''}: {clean(label, 80)}"
        elif etype == "agent.message":
            chars = content_chars(event.get("content"))
            add(
                Item(
                    "agent_message",
                    "agent_message",
                    "agent.message",
                    "agent message",
                    chars,
                    ts,
                    seq,
                )
            )
            summary = f"{chars:,} chars: {clean(content_text(event.get('content')), 100)}"
        elif etype == "user.message":
            chars = content_chars(event.get("content"))
            add(
                Item("user_message", "user_message", "user.message", "user message", chars, ts, seq)
            )
            summary = f"{chars:,} chars: {clean(content_text(event.get('content')), 100)}"
        elif etype == "agent.thread_message_sent":
            chars = content_chars(event.get("content"))
            target = str(event.get("to_agent_name") or event.get("to_session_thread_id") or "?")
            add(
                Item(
                    "inter_agent_out",
                    "inter_agent_out",
                    "send_to_agent",
                    clean(f"message to {target}", LABEL_CAP),
                    chars,
                    ts,
                    seq,
                    counted=not has_send_tool,
                )
            )
            summary = (
                f"to {target}, {chars:,} chars: {clean(content_text(event.get('content')), 100)}"
            )
        elif etype == "agent.thread_message_received":
            chars = content_chars(event.get("content"))
            source = str(event.get("from_agent_name") or event.get("from_session_thread_id") or "?")
            add(
                Item(
                    "inter_agent_in",
                    "inter_agent_in",
                    "thread_message",
                    clean(f"message from {source}", LABEL_CAP),
                    chars,
                    ts,
                    seq,
                )
            )
            summary = (
                f"from {source}, {chars:,} chars: {clean(content_text(event.get('content')), 100)}"
            )
        elif etype == "span.model_request_end":
            usage = as_dict(event.get("model_usage"))
            summary = (
                f"in {as_int(usage.get('input_tokens')):,} / cache+ "
                f"{as_int(usage.get('cache_creation_input_tokens')):,} / cache read "
                f"{as_int(usage.get('cache_read_input_tokens')):,} / out "
                f"{as_int(usage.get('output_tokens')):,}"
                f"{' ERROR' if event.get('is_error') else ''}"
            )
        elif etype == "span.model_request_start":
            continue
        elif etype.startswith("session.thread_"):
            summary = clean(
                f"{event.get('agent_name') or event.get('session_thread_id') or ''}", 80
            )
        elif etype in ("session.status_idle", "session.thread_status_idle"):
            summary = clean(as_dict(event.get("stop_reason")).get("type") or "", 60)
        elif etype == "session.error":
            summary = clean(as_dict(event.get("error")).get("type") or "", 80)
        elif etype == "agent.thinking":
            summary = "(no content)"
        history.append((seq, ts, etype, summary))
    return items, history


def _build_requests(events: Sequence[tuple[dt.datetime | None, dict[str, Any]]]) -> list[Request]:
    starts: dict[str, dt.datetime | None] = {}
    for ts, event in events:
        if event.get("type") == "span.model_request_start":
            starts[str(event.get("id") or "")] = ts
    requests: list[Request] = []
    for ts, event in events:
        if event.get("type") != "span.model_request_end":
            continue
        usage = as_dict(event.get("model_usage"))
        start = starts.get(str(event.get("model_request_start_id") or "")) or ts
        requests.append(
            Request(
                index=len(requests) + 1,
                start=start,
                end=ts,
                input_tokens=as_int(usage.get("input_tokens")),
                cache_creation=as_int(usage.get("cache_creation_input_tokens")),
                cache_read=as_int(usage.get("cache_read_input_tokens")),
                output_tokens=as_int(usage.get("output_tokens")),
                is_error=bool(event.get("is_error")),
            )
        )
    return requests


def _attribute(requests: list[Request], items: list[Item]) -> None:
    """Fill each request's `added_*` and each item's `rereads` from the timestamps."""
    for item in items:
        if item.ts is None or not item.counted:
            continue
        item.rereads = sum(1 for r in requests if r.start is not None and r.start > item.ts)
    previous_end: dt.datetime | None = None
    for request in requests:
        upper = request.start
        added = [
            i
            for i in items
            if i.counted
            and i.ts is not None
            and upper is not None
            and (previous_end is None or i.ts > previous_end)
            and i.ts <= upper
        ]
        request.added_items = len(added)
        request.added_tokens = sum(i.tokens for i in added)
        if added:
            request.biggest_label = max(added, key=lambda i: i.chars).label
        previous_end = request.end or previous_end


def analyse(raw: RawSession) -> SessionReport:
    """Turn the fetched events of one session into a `SessionReport`. Pure and offline."""
    warnings = list(raw.warnings)
    primary_meta = next((t for t in raw.threads if not t.get("parent_thread_id")), None)
    primary_id = str(primary_meta.get("id")) if primary_meta else PRIMARY_KEY

    buckets: dict[str, list[dict[str, Any]]] = {}
    for event in raw.session_events:
        thread_id = event.get("session_thread_id")
        cross_posted = (
            isinstance(thread_id, str)
            and thread_id not in ("", primary_id)
            and str(event.get("type", "")).split(".", 1)[0] in ("agent", "user", "span")
        )
        if not cross_posted:
            buckets.setdefault(primary_id, []).append(event)
    for thread_id, events in raw.thread_events.items():
        buckets.setdefault(thread_id, []).extend(events)

    snapshots = [
        e for e in raw.session_events if e.get("type") == "session.usage" and e.get("usage")
    ]
    stop_reasons = [
        str(as_dict(e.get("stop_reason")).get("type") or "?")
        for e in raw.session_events
        if e.get("type") == "session.status_idle"
    ]

    metas: list[dict[str, Any]] = list(raw.threads)
    known = {str(t.get("id")) for t in metas}
    if primary_id not in known:
        metas.insert(0, {"id": primary_id, "parent_thread_id": None, "agent": {"name": ""}})
    for thread_id in buckets:
        if thread_id not in known and thread_id != primary_id:
            metas.append({"id": thread_id, "parent_thread_id": primary_id, "agent": {}})

    threads: list[ThreadReport] = []
    for meta in metas:
        thread_id = str(meta.get("id"))
        is_primary = not meta.get("parent_thread_id")
        name, model, system_chars, tools_chars, custom = _agent_snapshot(meta)
        agent = name or ("coordinator" if is_primary else thread_id)
        events = _ordered(_dedupe(buckets.get(thread_id, [])))
        requests = _build_requests(events)
        items, history = _build_items(events)
        _attribute(requests, items)
        agent_def = as_dict(meta.get("agent"))
        threads.append(
            ThreadReport(
                key=thread_id,
                agent=agent,
                model=model,
                is_primary=is_primary,
                system_chars=system_chars,
                tools_chars=tools_chars,
                custom_tools=custom,
                skills=len(as_list(agent_def.get("skills"))),
                mcp_servers=[
                    str(as_dict(s).get("name") or "?")
                    for s in as_list(agent_def.get("mcp_servers"))
                ],
                api_usage=as_dict(meta.get("usage")),
                requests=requests,
                items=items,
                history=history,
                event_count=len(events),
            )
        )
    threads.sort(key=lambda t: (not t.is_primary, t.agent))
    if not any(t.requests for t in threads):
        warnings.append(
            "no span.model_request_end event found: per-request usage is unavailable, the "
            "thread totals come from the API's thread usage only"
        )
    return SessionReport(
        session_id=raw.session_id,
        status=str(raw.session.get("status") or "?"),
        usage={
            **(as_dict(snapshots[-1].get("usage")) if snapshots else {}),
            **as_dict(raw.session.get("usage")),
        },
        usage_snapshots=[as_dict(s) for s in snapshots],
        stop_reasons=stop_reasons,
        threads=threads,
        session_event_count=len(raw.session_events),
        warnings=warnings,
    )


# --- rendering --------------------------------------------------------------------------------


def table(
    headers: Sequence[str], rows: Sequence[Sequence[object]], right: Sequence[int] = ()
) -> str:
    if not rows:
        return "_none_\n"
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(" ---: " if i in right else " --- " for i in range(len(headers))) + "|"
    body = ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join([head, sep, *body]) + "\n"


def n(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{int(value):,}"


def cost_cents(usage: Mapping[str, Any]) -> str:
    amount = as_dict(usage.get("list_cost")).get("amount")
    return f"{amount}c" if amount not in (None, "") else "-"


def _thread_totals(thread: ThreadReport) -> dict[str, int]:
    if thread.requests:
        return {
            "input": thread.total("input_tokens"),
            "cache_creation": thread.total("cache_creation"),
            "cache_read": thread.total("cache_read"),
            "output": thread.total("output_tokens"),
        }
    usage = thread.api_usage
    creation = as_dict(usage.get("cache_creation"))
    return {
        "input": as_int(usage.get("input_tokens")),
        "cache_creation": as_int(creation.get("ephemeral_5m_input_tokens"))
        + as_int(creation.get("ephemeral_1h_input_tokens")),
        "cache_read": as_int(usage.get("cache_read_input_tokens")),
        "output": as_int(usage.get("output_tokens")),
    }


def _render_summary(report: SessionReport) -> list[str]:
    out = [f"## Session `{report.session_id}`", ""]
    usage = report.usage
    creation = as_dict(usage.get("cache_creation"))
    server = as_dict(usage.get("server_tool_use"))
    totals = [_thread_totals(t) for t in report.threads]
    out.append(
        table(
            [
                "status",
                "list cost",
                "input",
                "cache creation",
                "cache read",
                "output",
                "web searches",
                "active s",
                "model requests",
                "threads",
            ],
            [
                [
                    report.status,
                    cost_cents(usage),
                    n(as_int(usage.get("input_tokens")) or sum(t["input"] for t in totals)),
                    n(
                        as_int(creation.get("ephemeral_5m_input_tokens"))
                        + as_int(creation.get("ephemeral_1h_input_tokens"))
                        or sum(t["cache_creation"] for t in totals)
                    ),
                    n(
                        as_int(usage.get("cache_read_input_tokens"))
                        or sum(t["cache_read"] for t in totals)
                    ),
                    n(as_int(usage.get("output_tokens")) or sum(t["output"] for t in totals)),
                    n(as_int(server.get("web_search_requests"))),
                    n(
                        usage.get("active_seconds")
                        if isinstance(usage.get("active_seconds"), (int, float))
                        else None
                    ),
                    n(sum(len(t.requests) for t in report.threads)),
                    n(len(report.threads)),
                ]
            ],
            right=range(1, 10),
        )
    )
    if report.stop_reasons:
        out.append(f"Idle stop reasons, in order: {', '.join(report.stop_reasons)}.\n")
    for warning in report.warnings:
        out.append(f"> Warning: {clean(warning, 300)}\n")
    return out


def _render_threads(report: SessionReport) -> list[str]:
    out = ["### Threads", ""]
    rows: list[list[object]] = []
    for t in report.threads:
        tot = _thread_totals(t)
        rows.append(
            [
                f"`{t.key}`",
                t.agent,
                t.model,
                n(len(t.requests)),
                n(tot["input"]),
                n(tot["cache_creation"]),
                n(tot["cache_read"]),
                n(tot["output"]),
                n(t.first_context),
                n(t.max_context),
                n(t.final_context),
                cost_cents(t.api_usage),
                n(t.event_count),
            ]
        )
    out.append(
        table(
            [
                "thread",
                "agent",
                "model",
                "requests",
                "input",
                "cache creation",
                "cache read",
                "output",
                "first ctx",
                "max ctx",
                "final ctx",
                "cost (API)",
                "events",
            ],
            rows,
            right=range(3, 13),
        )
    )
    out.append("Context of a request = input + cache creation + cache read tokens.\n")
    fixed: list[list[object]] = []
    for t in report.threads:
        custom = ", ".join(f"{name} {n(chars)}" for name, chars in t.custom_tools) or "-"
        fixed.append(
            [
                t.agent,
                n(t.system_chars),
                f"~{n(est_tokens(t.system_chars))}",
                n(t.tools_chars),
                custom,
                n(t.skills),
                ", ".join(t.mcp_servers) or "-",
            ]
        )
    out.append("#### Fixed context from the agent snapshots\n")
    out.append(
        table(
            [
                "agent",
                "system prompt chars",
                "~tokens",
                "tool definition chars (JSON)",
                "custom tool schema chars",
                "skills",
                "MCP servers",
            ],
            fixed,
            right=(1, 2, 3, 5),
        )
    )
    return out


def _render_contributors(report: SessionReport) -> list[str]:
    out = ["### What fills the context", ""]
    out.append(
        "Per thread and kind: items, characters, estimated tokens, and tokens carried (tokens x "
        "the later model requests that re-read the item). `carried / cache read` says how much "
        "of the thread's cache reads the kind explains.\n"
    )
    for t in report.threads:
        counted = [i for i in t.items if i.counted]
        if not counted:
            continue
        cache_read = _thread_totals(t)["cache_read"]
        groups: dict[tuple[str, str], list[Item]] = defaultdict(list)
        for item in counted:
            groups[(item.kind, item.role)].append(item)
        rows: list[list[object]] = []
        for (kind, role), group in sorted(
            groups.items(), key=lambda kv: -sum(i.carried for i in kv[1])
        ):
            chars = sum(i.chars for i in group)
            carried = sum(i.carried for i in group)
            rows.append(
                [
                    kind,
                    role,
                    n(len(group)),
                    n(chars),
                    f"~{n(est_tokens(chars))}",
                    f"~{n(max(i.tokens for i in group))}",
                    f"~{n(carried)}",
                    f"{carried / cache_read:.0%}" if cache_read else "-",
                ]
            )
        explained = sum(i.carried for i in counted)
        out.append(f"#### {t.agent} (`{t.key}`)\n")
        out.append(
            table(
                [
                    "kind",
                    "role",
                    "items",
                    "chars",
                    "~tokens",
                    "biggest item ~tokens",
                    "~tokens carried",
                    "carried / cache read",
                ],
                rows,
                right=range(2, 8),
            )
        )
        if t.requests:
            final = t.requests[-1]
            before_final = sum(
                i.tokens for i in counted if i.ts and final.start and i.ts < final.start
            )
            out.append(
                f"Items explain ~{n(explained)} of {n(cache_read)} cache-read tokens "
                f"({explained / cache_read:.0%} of them). At the final request the context is "
                f"{n(final.context)} tokens; the items before it add up to ~{n(before_final)}, so "
                f"~{n(max(final.context - before_final, 0))} are the system prompt, tool "
                "definitions, skill descriptions, thinking and estimation error.\n"
                if cache_read
                else "No cache reads in this thread.\n"
            )
    return out


def _all_items(report: SessionReport) -> list[tuple[ThreadReport, Item]]:
    return [(t, i) for t in report.threads for i in t.items if i.counted]


def _render_top(report: SessionReport, top: int) -> list[str]:
    pairs = _all_items(report)
    results = [(t, i) for t, i in pairs if i.role == "tool_result"]
    results.sort(key=lambda p: -p[1].chars)
    out = [f"### Top {top} largest tool results", ""]
    out.append(
        table(
            ["#", "tool", "thread", "call", "chars", "~tokens", "re-read x", "~tokens carried"],
            [
                [
                    k,
                    i.tool,
                    t.agent,
                    i.label,
                    n(i.chars),
                    f"~{n(i.tokens)}",
                    n(i.rereads),
                    f"~{n(i.carried)}",
                ]
                for k, (t, i) in enumerate(results[:top], start=1)
            ],
            right=(0, 4, 5, 6, 7),
        )
    )
    carried = sorted(pairs, key=lambda p: -p[1].carried)
    out.append(f"### Top {top} items by tokens carried (size x re-reads)\n")
    out.append(
        table(
            [
                "#",
                "role",
                "tool",
                "thread",
                "what",
                "chars",
                "~tokens",
                "re-read x",
                "~tokens carried",
            ],
            [
                [
                    k,
                    i.role,
                    i.tool,
                    t.agent,
                    i.label,
                    n(i.chars),
                    f"~{n(i.tokens)}",
                    n(i.rereads),
                    f"~{n(i.carried)}",
                ]
                for k, (t, i) in enumerate(carried[:top], start=1)
            ],
            right=(0, 5, 6, 7, 8),
        )
    )
    inputs = sorted((p for p in pairs if p[1].role == "tool_input"), key=lambda p: -p[1].chars)
    out.append("### Largest tool call inputs (written by the agent: files, scripts, submit_plan)\n")
    out.append(
        table(
            ["#", "tool", "thread", "call", "chars", "~tokens", "re-read x", "~tokens carried"],
            [
                [
                    k,
                    i.tool,
                    t.agent,
                    i.label,
                    n(i.chars),
                    f"~{n(i.tokens)}",
                    n(i.rereads),
                    f"~{n(i.carried)}",
                ]
                for k, (t, i) in enumerate(inputs[:10], start=1)
            ],
            right=(0, 4, 5, 6, 7),
        )
    )
    return out


def _render_messages(report: SessionReport) -> list[str]:
    rows: list[list[object]] = []
    for t in report.threads:
        for i in t.items:
            if i.role in ("inter_agent_in", "inter_agent_out", "user_message"):
                rows.append(
                    [
                        t.agent,
                        hms(i.ts),
                        i.role,
                        i.label,
                        n(i.chars),
                        f"~{n(i.tokens)}",
                        "yes" if i.counted else "no (duplicates a send_to_agent call)",
                    ]
                )
    out = ["### Messages between agents and from the user", ""]
    out.append(
        table(["thread", "time", "role", "what", "chars", "~tokens", "counted"], rows, right=(4, 5))
    )
    return out


def _render_skills(report: SessionReport) -> list[str]:
    rows: list[list[object]] = []
    for t in report.threads:
        for i in t.items:
            if i.kind == "skill_file" and i.role == "tool_result":
                rows.append(
                    [
                        t.agent,
                        hms(i.ts),
                        i.label,
                        n(i.chars),
                        f"~{n(i.tokens)}",
                        n(i.rereads),
                        f"~{n(i.carried)}",
                    ]
                )
    out = ["### Skill loads (read / cat of SKILL.md and skill files)", ""]
    out.append(
        table(
            ["thread", "time", "call", "chars", "~tokens", "re-read x", "~tokens carried"],
            rows,
            right=(3, 4, 5, 6),
        )
    )
    return out


def _render_timeline(report: SessionReport) -> list[str]:
    out = ["### Token timeline per thread", ""]
    out.append(
        "One row per model request. `delta` is the growth of the context against the previous "
        "request; `added` is what the events in between add (estimated tokens, number of items, "
        "the biggest one).\n"
    )
    for t in report.threads:
        if not t.requests:
            continue
        out.append(f"#### {t.agent} (`{t.key}`)\n")
        rows: list[list[object]] = []
        previous = 0
        for r in t.requests[:TIMELINE_ROW_CAP]:
            rows.append(
                [
                    r.index,
                    hms(r.start),
                    n(r.context),
                    f"{r.context - previous:+,}",
                    n(r.input_tokens),
                    n(r.cache_creation),
                    n(r.cache_read),
                    n(r.output_tokens),
                    f"~{n(r.added_tokens)} ({r.added_items})",
                    r.biggest_label or "-",
                    "ERROR" if r.is_error else "",
                ]
            )
            previous = r.context
        out.append(
            table(
                [
                    "req",
                    "start",
                    "context",
                    "delta",
                    "input",
                    "cache creation",
                    "cache read",
                    "output",
                    "added",
                    "biggest added",
                    "",
                ],
                rows,
                right=(0, 2, 3, 4, 5, 6, 7),
            )
        )
        if len(t.requests) > TIMELINE_ROW_CAP:
            out.append(f"_{len(t.requests) - TIMELINE_ROW_CAP} more requests not shown._\n")
    snapshots = report.usage_snapshots
    if snapshots:
        out.append("#### `session.usage` snapshots (cumulative, one before every idle)\n")
        shown = snapshots
        if len(snapshots) > USAGE_ROW_CAP:
            shown = snapshots[: USAGE_ROW_CAP // 2] + snapshots[-USAGE_ROW_CAP // 2 :]
        rows = []
        for s in shown:
            u = as_dict(s.get("usage"))
            c = as_dict(u.get("cache_creation"))
            rows.append(
                [
                    hms(parse_ts(s.get("processed_at"))),
                    cost_cents(u),
                    n(as_int(u.get("input_tokens"))),
                    n(
                        as_int(c.get("ephemeral_5m_input_tokens"))
                        + as_int(c.get("ephemeral_1h_input_tokens"))
                    ),
                    n(as_int(u.get("cache_read_input_tokens"))),
                    n(as_int(u.get("output_tokens"))),
                    n(as_int(as_dict(u.get("server_tool_use")).get("web_search_requests"))),
                ]
            )
        out.append(
            table(
                [
                    "time",
                    "list cost",
                    "input",
                    "cache creation",
                    "cache read",
                    "output",
                    "web searches",
                ],
                rows,
                right=range(1, 7),
            )
        )
    return out


def _render_history(report: SessionReport) -> list[str]:
    out = ["### Event history", ""]
    out.append(
        f"The session listing returned {n(report.session_event_count)} events. One line per event "
        "per thread (model request starts omitted; texts capped at "
        f"{SNIPPET_CAP} characters).\n"
    )
    for t in report.threads:
        out.append(f"#### {t.agent} (`{t.key}`), {n(t.event_count)} events\n")
        rows = [
            [seq, hms(ts), f"`{etype}`", clean(summary)] for seq, ts, etype, summary in t.history
        ]
        out.append(table(["seq", "time", "type", "summary"], rows, right=(0,)))
    return out


def render_session(report: SessionReport, *, top: int = TOP_N, history: bool = True) -> str:
    parts: list[str] = []
    for section in (
        _render_summary(report),
        _render_threads(report),
        _render_contributors(report),
        _render_top(report, top),
        _render_skills(report),
        _render_messages(report),
        _render_timeline(report),
    ):
        parts.extend(section)
    if history:
        parts.extend(_render_history(report))
    return "\n".join(parts) + "\n"


def render_comparison(reports: Sequence[SessionReport]) -> str:
    rows: list[list[object]] = []
    for r in reports:
        totals = [_thread_totals(t) for t in r.threads]
        rows.append(
            [
                f"`{r.session_id}`",
                cost_cents(r.usage),
                n(sum(len(t.requests) for t in r.threads)),
                n(sum(t["cache_read"] for t in totals)),
                n(sum(t["output"] for t in totals)),
                n(max((t.max_context for t in r.threads), default=0)),
            ]
        )
    return "## Sessions compared\n\n" + table(
        ["session", "list cost", "model requests", "cache read", "output", "max ctx"],
        rows,
        right=range(1, 6),
    )


# --- static estimate --------------------------------------------------------------------------


@dataclass(slots=True)
class StaticFile:
    label: str
    chars: int
    tier: str
    """always, expected or possible."""


@dataclass(slots=True)
class StaticAgent:
    name: str
    model: str
    system_chars: int
    custom_tools: list[tuple[str, int]]
    builtin_tools: list[str]
    mcp_tools: list[str]
    skills: list[str]
    skill_descriptions: list[tuple[str, int]]
    files: list[StaticFile]

    @property
    def tools_chars(self) -> int:
        return sum(c for _, c in self.custom_tools)

    @property
    def descriptions_chars(self) -> int:
        return sum(c for _, c in self.skill_descriptions)

    @property
    def floor_chars(self) -> int:
        """What every request re-reads at least, measurable offline."""
        return self.system_chars + self.tools_chars + self.descriptions_chars

    def tier_chars(self, tier: str) -> int:
        return sum(f.chars for f in self.files if f.tier == tier)

    @property
    def loaded_chars(self) -> int:
        return self.floor_chars + self.tier_chars("expected")


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            meta = yaml.safe_load("\n".join(lines[1:end])) or {}
            return as_dict(meta), "\n".join(lines[end + 1 :]).strip()
    return {}, text


def _file_chars(path: Path) -> int:
    return len(path.read_text(encoding="utf-8"))


def _skill_files(skill_dir: Path, agent: str) -> list[StaticFile]:
    files: list[StaticFile] = []
    for path in sorted(skill_dir.rglob("*")):
        rel = path.relative_to(skill_dir)
        if (
            not path.is_file()
            or "__pycache__" in rel.parts
            or path.name.startswith(".")
            or path.name.startswith("test_")
            or path.name == "conftest.py"
        ):
            continue
        try:
            chars = _file_chars(path)
        except UnicodeDecodeError:
            continue
        label = f"{skill_dir.name}/{rel.as_posix()}"
        if path.name == "SKILL.md" and len(rel.parts) == 1:
            tier = "expected"
        elif rel.parts[0] == "schemas":
            tier = "expected" if path.stem == agent else "possible"
        elif path.name == "example.json":
            tier = "expected" if agent == "coordinator" else "possible"
        else:
            tier = "possible"
        files.append(StaticFile(label, chars, tier))
    return files


def static_agents(repo: Path, profile: str = "development") -> list[StaticAgent]:
    agents_dir = repo / "profiles" / profile / "agents"
    if not agents_dir.is_dir():
        raise FileNotFoundError(f"{agents_dir} not found: run scripts/render_profiles.py")
    result: list[StaticAgent] = []
    for path in sorted(agents_dir.glob("*.md"), key=lambda p: (p.stem != "coordinator", p.stem)):
        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        name = str(meta.get("name") or path.stem)
        custom: list[tuple[str, int]] = []
        builtin: list[str] = []
        mcp_tools: list[str] = []
        for tool in as_list(meta.get("tools")):
            if isinstance(tool, str):
                tool_path = (path.parent / tool).resolve()
                if tool_path.is_file():
                    data = json.loads(tool_path.read_text(encoding="utf-8"))
                    custom.append(
                        (str(as_dict(data).get("name") or tool_path.stem), json_chars(data))
                    )
                continue
            data = as_dict(tool)
            enabled = [
                str(as_dict(c).get("name"))
                for c in as_list(data.get("configs"))
                if as_dict(c).get("enabled", True)
            ]
            if data.get("type") == "mcp_toolset":
                server = str(data.get("mcp_server_name") or "?")
                mcp_tools.extend(f"{server}.{t}" for t in enabled)
            else:
                builtin.extend(enabled)
        skills: list[str] = []
        descriptions: list[tuple[str, int]] = []
        files: list[StaticFile] = []
        for ref in as_list(meta.get("skills")):
            skill_dir = (path.parent / str(ref)).resolve()
            skills.append(skill_dir.name)
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            skill_meta, _ = split_frontmatter(skill_md.read_text(encoding="utf-8"))
            text = f"{skill_meta.get('name', '')} {skill_meta.get('description', '')}"
            descriptions.append((skill_dir.name, len(text.strip())))
            files.extend(_skill_files(skill_dir, name))
        result.append(
            StaticAgent(
                name=name,
                model=str(meta.get("model") or "?"),
                system_chars=len(body),
                custom_tools=custom,
                builtin_tools=builtin,
                mcp_tools=mcp_tools,
                skills=skills,
                skill_descriptions=descriptions,
                files=files,
            )
        )
    return result


def render_static(agents: Sequence[StaticAgent], profile: str = "development") -> str:
    out = [f"## Static estimate of the fixed context, profile `{profile}`", ""]
    out.append(
        "No API call. Characters are those of the files; tokens are chars / 4. **Floor** is what "
        "every model request of the agent re-reads at the very least: system prompt + custom tool "
        "schemas + skill name and description lines. **After skill loads** adds the files the "
        "agent is expected to read (each referenced skill's SKILL.md; its own "
        "`schemas/<agent>.json`; `example.json` for the coordinator). **Possible** is every other "
        "data file or script of the referenced skills, counted only if an agent reads them. "
        "Built-in tool definitions (bash, read, write, web_search, ...) and MCP tool schemas are "
        "not measurable offline: the live report's first-request context includes them.\n"
    )
    rows: list[list[object]] = []
    for a in agents:
        rows.append(
            [
                a.name,
                a.model,
                n(a.system_chars),
                n(a.tools_chars),
                n(a.descriptions_chars),
                n(a.floor_chars),
                f"~{n(est_tokens(a.floor_chars))}",
                n(a.tier_chars("expected")),
                f"~{n(est_tokens(a.loaded_chars))}",
                n(a.tier_chars("possible")),
            ]
        )
    out.append(
        table(
            [
                "agent",
                "model",
                "system chars",
                "custom tool chars",
                "skill description chars",
                "floor chars",
                "floor ~tokens",
                "skill file chars (expected)",
                "after loads ~tokens",
                "possible extra chars",
            ],
            rows,
            right=range(2, 10),
        )
    )
    for a in agents:
        out.append(f"### {a.name} ({a.model})\n")
        components: list[list[object]] = [
            [
                f"system prompt (profiles/.../agents/{a.name}.md body)",
                "always",
                n(a.system_chars),
                f"~{n(est_tokens(a.system_chars))}",
            ]
        ]
        for tool_name, chars in a.custom_tools:
            components.append(
                [
                    f"custom tool `{tool_name}` schema (compact JSON)",
                    "always",
                    n(chars),
                    f"~{n(est_tokens(chars))}",
                ]
            )
        for skill_name, chars in a.skill_descriptions:
            components.append(
                [
                    f"skill `{skill_name}` name + description",
                    "always",
                    n(chars),
                    f"~{n(est_tokens(chars))}",
                ]
            )
        for f in a.files:
            components.append([f"`{f.label}`", f.tier, n(f.chars), f"~{n(est_tokens(f.chars))}"])
        out.append(table(["component", "tier", "chars", "~tokens"], components, right=(2, 3)))
        out.append(
            f"Built-in tools enabled: {', '.join(a.builtin_tools) or 'none'}. "
            f"MCP tools: {', '.join(a.mcp_tools) or 'none'}.\n"
        )
    return "\n".join(out) + "\n"


# --- fetching ---------------------------------------------------------------------------------


class LiveSource:
    """Reads a session over the Managed Agents API, read-only (GET listings and a retrieve)."""

    def __init__(self, sdk: Any) -> None:
        from app.ma_client import SdkManagedAgentsClient

        self._sdk = sdk
        self._client = SdkManagedAgentsClient(sdk)

    async def _pages(self, call: Callable[[str | None], Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            resp = await call(page)
            body = as_dict(resp.http_response.json())
            items.extend(as_dict(i) for i in as_list(body.get("data")))
            nxt = body.get("next_page")
            if not isinstance(nxt, str) or not nxt or nxt == page:
                return items
            page = nxt

    async def fetch(self, session_id: str) -> RawSession:
        from app.ma_client import (
            ManagedAgentsError,
            iter_session_history,
            iter_thread_history,
        )

        sdk = self._sdk
        warnings: list[str] = []
        resp = await sdk.beta.sessions.with_raw_response.retrieve(session_id)
        session = as_dict(resp.http_response.json())

        async def threads_page(page: str | None) -> Any:
            if page is None:
                return await sdk.beta.sessions.threads.with_raw_response.list(session_id)
            return await sdk.beta.sessions.threads.with_raw_response.list(session_id, page=page)

        threads = await self._pages(threads_page)
        session_events = [dict(e) async for e in iter_session_history(self._client, session_id)]
        thread_events: dict[str, list[dict[str, Any]]] = {}
        for thread in threads:
            thread_id = str(thread.get("id"))
            try:
                thread_events[thread_id] = [
                    dict(e) async for e in iter_thread_history(self._client, session_id, thread_id)
                ]
            except ManagedAgentsError as exc:
                warnings.append(f"thread {thread_id}: events not listed ({clean(exc, 120)})")
        return RawSession(session_id, session, threads, session_events, thread_events, warnings)


def save_raw(raw: RawSession, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{raw.session_id}.json"
    path.write_text(json.dumps(raw.to_json(), ensure_ascii=False), encoding="utf-8")
    return path


def load_raw(directory: Path, session_id: str) -> RawSession:
    path = directory / f"{session_id}.json"
    return RawSession.from_json(json.loads(path.read_text(encoding="utf-8")))


def build_live_source() -> LiveSource:
    """A read-only source on the SDK's own credentials (key, or development federation)."""
    from anthropic import AsyncAnthropic

    from app.ma_client import MAX_RETRIES, REQUEST_TIMEOUT_SECONDS

    return LiveSource(AsyncAnthropic(max_retries=MAX_RETRIES, timeout=REQUEST_TIMEOUT_SECONDS))


# --- output -----------------------------------------------------------------------------------


def truncate_markdown(text: str, limit_bytes: int = DEFAULT_SUMMARY_BYTES) -> str:
    """`text` cut at a line boundary so that it, plus the notice, fits in `limit_bytes`."""
    data = text.encode("utf-8")
    if len(data) <= limit_bytes:
        return text
    notice = "\n\n> Report truncated to fit GitHub's step summary limit; the artifact has it all.\n"
    room = limit_bytes - len(notice.encode("utf-8"))
    cut = data[: max(room, 0)].decode("utf-8", errors="ignore")
    cut = cut[: cut.rfind("\n")] if "\n" in cut else cut
    return cut + notice


def build_report(
    sessions: Sequence[SessionReport],
    static: list[StaticAgent] | None,
    *,
    top: int = TOP_N,
    history: bool = True,
    generated_at: dt.datetime | None = None,
    profile: str = "development",
) -> str:
    stamp = (generated_at or dt.datetime.now(dt.UTC)).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        f"# Session context report\n\nGenerated {stamp}. Sizes: chars of event content; "
        f"tokens: chars / {CHARS_PER_TOKEN} (an estimate).\n",
        READING_GUIDE,
    ]
    if static is not None:
        parts.append(render_static(static, profile))
    if len(sessions) > 1:
        parts.append(render_comparison(sessions))
    for report in sessions:
        parts.append(render_session(report, top=top, history=history))
    return redact("\n".join(parts))


def parse_session_ids(values: Sequence[str]) -> list[str]:
    ids: list[str] = []
    for value in values:
        for part in re.split(r"[,\s]+", value.strip()):
            if not part:
                continue
            if not SESSION_ID_RE.match(part):
                raise argparse.ArgumentTypeError(f"not a session id (sesn_...): {part[:40]!r}")
            if part not in ids:
                ids.append(part)
    return ids


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report what fills the context of Managed Agents sessions (read-only)."
    )
    parser.add_argument(
        "--session",
        nargs="+",
        action="extend",
        default=[],
        metavar="ID",
        help="session id(s), sesn_...; repeatable, comma or space separated",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="estimate each agent's fixed context from the repository (no API)",
    )
    parser.add_argument("--profile", default="development", help="profile for --static")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="report file (default: session-report.md in the system temp dir)",
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=None,
        help="also write a copy cut to --summary-bytes (GITHUB_STEP_SUMMARY)",
    )
    parser.add_argument("--summary-bytes", type=int, default=DEFAULT_SUMMARY_BYTES)
    parser.add_argument("--top", type=int, default=TOP_N, help="rows in the top tables")
    parser.add_argument("--no-history", action="store_true", help="omit the event history")
    parser.add_argument("--no-stdout", action="store_true", help="do not print the report")
    parser.add_argument(
        "--save-raw",
        type=Path,
        default=None,
        metavar="DIR",
        help="store the fetched events as JSON (page text inside: keep it private)",
    )
    parser.add_argument(
        "--from-raw",
        type=Path,
        default=None,
        metavar="DIR",
        help="analyse events stored by --save-raw instead of calling the API",
    )
    args = parser.parse_args(argv)
    try:
        args.session = parse_session_ids(args.session)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if not args.session and not args.static:
        parser.error("give --session ID... and/or --static")
    if args.top < 1:
        parser.error("--top must be at least 1")
    return args


def main(
    argv: Sequence[str] | None = None,
    *,
    source: Any = None,
    out: Callable[[str], object] = print,
    generated_at: dt.datetime | None = None,
) -> int:
    args = parse_args(argv)
    static = static_agents(REPO_ROOT, args.profile) if args.static else None
    reports: list[SessionReport] = []
    if args.session:
        live = source
        try:
            for session_id in args.session:
                if args.from_raw is not None:
                    raw = load_raw(args.from_raw, session_id)
                else:
                    live = live or build_live_source()
                    raw = asyncio.run(live.fetch(session_id))
                    if args.save_raw is not None:
                        save_raw(raw, args.save_raw)
                reports.append(analyse(raw))
        except Exception as exc:
            from app.ma_client import ManagedAgentsError

            kind = "API error" if isinstance(exc, ManagedAgentsError) else type(exc).__name__
            print(f"session_report: {kind}: {clean(exc, 300)}", file=sys.stderr)
            return 1
    text = build_report(
        reports,
        static,
        top=args.top,
        history=not args.no_history,
        generated_at=generated_at,
        profile=args.profile,
    )
    path = args.out or Path(tempfile.gettempdir()) / "session-report.md"
    path.write_text(text, encoding="utf-8")
    if args.summary_out is not None:
        args.summary_out.write_text(truncate_markdown(text, args.summary_bytes), encoding="utf-8")
    if not args.no_stdout:
        out(text)
    print(f"session_report: wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
