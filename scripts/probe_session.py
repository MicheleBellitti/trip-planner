#!/usr/bin/env python3
"""Live probes P1..P13 of docs/managed-agents-notes.md section 4, development profile only.

The probes answer what the docs and the SDK could not settle offline: MCP reachability and
tool names (P4), web tools under `limited` networking (P5), inter-agent tools and thread reuse
(P6), stream ids and cross-posts (P7), the custom-tool round trip (P8), budget pause and resume
(P9), interrupt and cleanup races (P10), skill pinning (P11), `ant apply` and the `multiagent`
update semantics (P12), and the usage fields (P13). Each finding lands in a Markdown report,
docs/probes/<YYYY-MM-DD>.md, that the owners of the open seams read.

It SPENDS REAL MONEY, so it never runs by itself:

    uv run python ../scripts/probe_session.py --dry-run             # the plan; no network at all
    uv run python ../scripts/probe_session.py --yes                 # every probe
    uv run python ../scripts/probe_session.py --yes --only P1,P2,P4

Guards: the development workspace only (ANTHROPIC_API_KEY from the environment, or the
federation variables ANTHROPIC_IDENTITY_TOKEN_FILE, ANTHROPIC_FEDERATION_RULE_ID and
ANTHROPIC_ORGANIZATION_ID; never production credentials), never from CI (refuses when CI is
set), every session capped at the development profile's session budget (60 US cents; P9 uses
3), and no new session once the sessions' list cost reaches --max-total-cents (default 150).
Every resource it creates is named `probe-<stamp>-...` and removed at the end: sessions
deleted, agents archived (agents have no delete), environments deleted, skills deleted. The
raw SSE log goes to --sse-log, by default under the system temp directory and never into the
repository, because it carries web page text; the report holds only tool names, event types,
ids, statuses and hostnames.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bootstrap  # noqa: E402
import render_profiles  # noqa: E402
import yaml  # noqa: E402

if TYPE_CHECKING:
    import anthropic

REPO_ROOT = SCRIPTS_DIR.parent
PROFILE = "development"
ROME = ZoneInfo("Europe/Rome")
DEFAULT_MAX_TOTAL_CENTS = 150
P9_BUDGET_CENTS = 3
TURN_TIMEOUT_SECONDS = 420.0
LIMITED_HOSTS = ["photon.komoot.io", "api.open-meteo.com"]
P5_MODEL_BUILT_HOST = "photon.komoot.io"
"""Step 4 of P5: a URL the model builds itself on this host, which the prompt never shows. The
host is in LIMITED_HOSTS, so only web_fetch's URL-source rule (a URL must have appeared in a
user message, a custom tool result or a web_search/web_fetch result) can refuse it. Decides
whether the activities agent, which has no bash, can geocode through web_fetch."""
P5_PROMPT = (
    "1. web_fetch https://www.example.org\n"
    "2. web_fetch https://api.open-meteo.com/v1/forecast?latitude=45.46&longitude=9.19&current=temperature_2m\n"
    "3. web_search: Lisbon tram 28\n"
    "4. Find the coordinates of Castelo de Sao Jorge in Lisbon with komoot's public Photon "
    "geocoder: build its API URL yourself and web_fetch it directly, without searching first.\n"
    "Report for each step only: ok, or the error code."
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)]+")
PING = "_probe.ping"


@dataclass(frozen=True)
class Probe:
    id: str
    title: str
    decides: str
    sessions: int
    """Sessions it creates (each capped at the session budget)."""
    run: Callable[[ProbeContext], ProbeResult]


@dataclass
class ProbeResult:
    status: str = "done"
    """done (facts recorded), unexpected (a documented expectation failed), error, skipped."""
    findings: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.findings.append(text)


class ProbeSkippedError(Exception):
    """A probe cannot run (budget reached, a prerequisite missing)."""


# --- inputs from the development profile -------------------------------------------------------


@dataclass(frozen=True)
class ProfileInputs:
    session_budget_cents: int
    models: Mapping[str, str]
    flights: Mapping[str, Any]
    """The rendered flights agent (frontmatter + system): its MCP servers."""
    submit_plan_tool: Mapping[str, Any]
    raw_plan_schema: Mapping[str, Any]
    environment: Mapping[str, Any]

    @property
    def cheap_model(self) -> str:
        return str(self.models["flights"])  # the development subagent model, Haiku 5.5


def load_inputs(repo_root: Path = REPO_ROOT) -> ProfileInputs:
    profiles = render_profiles.load_profiles(repo_root)[PROFILE]
    base = repo_root / "profiles" / PROFILE
    flights, system = render_profiles.parse_agent_file(
        (base / "agents" / "flights.md").read_text(encoding="utf-8"), source="flights.md"
    )
    return ProfileInputs(
        session_budget_cents=int(profiles["session_budget_cents"]),
        models=dict(profiles["models"]),
        flights={**flights, "system": system},
        submit_plan_tool=json.loads(
            (base / "agents/tools/submit_plan.json").read_text(encoding="utf-8")
        ),
        raw_plan_schema=json.loads((repo_root / "schema/plan.json").read_text(encoding="utf-8")),
        environment=yaml.safe_load((base / "environments/cloud.yaml").read_text(encoding="utf-8")),
    )


# --- the context: client, resources, cost, logs -------------------------------------------------


class ProbeContext:
    def __init__(
        self,
        client: anthropic.Anthropic,
        inputs: ProfileInputs,
        *,
        stamp: str,
        max_total_cents: int,
        sse_log: Path,
        repo_root: Path = REPO_ROOT,
    ) -> None:
        self.client = client
        self.once = client.with_options(max_retries=0)
        self.inputs = inputs
        self.stamp = stamp
        self.max_total_cents = max_total_cents
        self.repo_root = repo_root
        self.sse_log_path = sse_log
        sse_log.parent.mkdir(parents=True, exist_ok=True)
        self._log = sse_log.open("a", encoding="utf-8")
        self._log_lock = threading.Lock()
        self.cleanup: list[tuple[str, Callable[[], object]]] = []
        self.sessions: dict[str, str] = {}
        """Live probe sessions: id -> label."""
        self.costs: dict[str, int] = {}
        """Last known list cost of every probe session, deleted ones included (US cents)."""
        self.environments: dict[str, str] = {}
        self.shared: dict[str, Any] = {}
        """Results later probes reuse (P13 reads P6's and P8's sessions)."""

    # naming, raw JSON, logging --------------------------------------------------------------

    def name(self, label: str) -> str:
        return f"probe-{self.stamp}-{label}"

    @staticmethod
    def raw(response: Any) -> dict[str, Any]:
        return response.http_response.json()

    def log(self, scope: str, line: str) -> None:
        with self._log_lock:
            self._log.write(f"{time.time():.3f} {scope} {line}\n")
            self._log.flush()

    def close(self) -> None:
        self._log.close()

    # money ----------------------------------------------------------------------------------

    def refresh_cost(self, session_id: str) -> None:
        with contextlib.suppress(Exception):
            session = self.raw(self.client.beta.sessions.with_raw_response.retrieve(session_id))
            self.costs[session_id] = max(self.costs.get(session_id, 0), usage_cents(session))

    def spent_cents(self) -> int:
        for session_id in list(self.sessions):
            self.refresh_cost(session_id)
        return sum(self.costs.values())

    def ensure_budget(self) -> None:
        spent = self.spent_cents()
        if spent >= self.max_total_cents:
            raise ProbeSkippedError(
                f"total list cost {spent} cents reached --max-total-cents {self.max_total_cents}"
            )

    # resources ------------------------------------------------------------------------------

    def environment(self, kind: str) -> str:
        """A probe environment: `limited` (the spec's original hosts, MCP allowed) or the
        development profile's own config (unrestricted). Created once per run."""
        if kind in self.environments:
            return self.environments[kind]
        config: Any
        if kind == "limited":
            config = {
                "type": "cloud",
                "networking": {
                    "type": "limited",
                    "allowed_hosts": LIMITED_HOSTS,
                    "allow_mcp_servers": True,
                },
            }
        else:
            config = dict(self.inputs.environment["config"])
        env = self.raw(
            self.once.beta.environments.with_raw_response.create(
                name=self.name(f"env-{kind}"), config=config
            )
        )
        self.environments[kind] = env["id"]
        self.cleanup.append(
            (f"delete environment {env['id']}", lambda: self.delete_environment(env["id"]))
        )
        return env["id"]

    def delete_environment(self, env_id: str) -> None:
        try:
            self.once.beta.environments.delete(env_id)
        except Exception:  # still referenced: archive instead
            self.once.beta.environments.archive(env_id)

    def agent(self, label: str, **body: Any) -> dict[str, Any]:
        body.setdefault("model", self.inputs.cheap_model)
        name = body.pop("name", None) or self.name(label)
        agent = self.raw(
            self.once.beta.agents.with_raw_response.create(
                name=name, model=body.pop("model"), extra_body=body
            )
        )
        self.cleanup.append(
            (f"archive agent {agent['id']}", lambda: self.once.beta.agents.archive(agent["id"]))
        )
        return agent

    def session(
        self, agent: Mapping[str, Any], env_id: str, *, budget_cents: int | None = None, label: str
    ) -> str:
        self.ensure_budget()
        cents = budget_cents or self.inputs.session_budget_cents
        session = self.raw(
            self.once.beta.sessions.with_raw_response.create(
                agent={"type": "agent", "id": agent["id"], "version": agent["version"]},
                environment_id=env_id,
                budget={
                    "type": "limit",
                    "max_list_cost": {"amount": str(cents), "currency": "USD"},
                },
                metadata={"app": "trip-planner", "probe": label, "stamp": self.stamp},
                title=self.name(label),
            )
        )
        session_id = session["id"]
        self.sessions[session_id] = label
        self.cleanup.append(
            (f"delete session {session_id}", lambda: self.delete_session(session_id))
        )
        return session_id

    def wait_not_running(self, session_id: str, *, seconds: float = 30.0) -> str:
        deadline = time.monotonic() + seconds
        status = ""
        while time.monotonic() < deadline:
            status = self.raw(self.client.beta.sessions.with_raw_response.retrieve(session_id))[
                "status"
            ]
            if status != "running":
                return status
            time.sleep(0.5)
        return status

    def delete_session(self, session_id: str) -> None:
        """Record the cost, interrupt if still running, delete. Already gone is fine."""
        import anthropic

        if session_id not in self.sessions:
            return
        try:
            self.refresh_cost(session_id)
            if self.wait_not_running(session_id) == "running":
                with contextlib.suppress(Exception):
                    self.once.beta.sessions.events.send(
                        session_id, events=[{"type": "user.interrupt"}]
                    )
                self.wait_not_running(session_id)
            self.once.beta.sessions.delete(session_id)
        except anthropic.NotFoundError:
            pass
        self.sessions.pop(session_id, None)

    # streams --------------------------------------------------------------------------------

    def send_message(self, session_id: str, text: str) -> None:
        self.once.beta.sessions.events.send(
            session_id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": text}]}],
        )

    @contextlib.contextmanager
    def session_stream(self, session_id: str) -> Iterator[Iterator[dict[str, Any]]]:
        """The raw SSE of the session stream, opened before anything is sent."""
        from anthropic import Stream

        with self.client.beta.sessions.events.with_streaming_response.stream(
            session_id
        ) as response:
            yield self._events(Stream.raw_events(response.http_response), f"session:{session_id}")

    def _events(self, raw_events: Iterator[Any], scope: str) -> Iterator[dict[str, Any]]:
        for sse in raw_events:
            self.log(scope, json.dumps({"event": sse.event, "id": sse.id, "data": sse.data}))
            if sse.event == "ping" or not sse.data.strip():
                yield {"type": PING}  # lets a waiting loop check its deadline
                continue
            data = json.loads(sse.data)
            if isinstance(data, dict):
                if sse.event:
                    data.setdefault("type", sse.event)
                data["_sse_event"] = sse.event
                data["_sse_id"] = sse.id
                yield data

    def run_turn(
        self,
        session_id: str,
        message: str | None,
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        until: Callable[[dict[str, Any]], bool] = lambda ev: is_final_idle(ev),
        timeout: float = TURN_TIMEOUT_SECONDS,
    ) -> list[dict[str, Any]]:
        """Open the stream, send `message` (if any), collect events until `until` says so."""
        events: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout
        with self.session_stream(session_id) as stream:
            if message is not None:
                self.send_message(session_id, message)
            for event in stream:
                if time.monotonic() > deadline:
                    events.append({"type": "_probe.timeout"})
                    break
                if event.get("type") == PING:
                    continue
                events.append(event)
                if on_event is not None:
                    on_event(event)
                if until(event) or event.get("type") in (
                    "session.status_terminated",
                    "session.deleted",
                ):
                    break
        return events

    def history(self, session_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            kwargs: dict[str, Any] = {"limit": 1000}
            if page:
                kwargs["page"] = page
            body = self.raw(
                self.client.beta.sessions.events.with_raw_response.list(session_id, **kwargs)
            )
            out.extend(body.get("data", []))
            page = body.get("next_page")
            if not page:
                return out

    def thread_history(self, session_id: str, thread_id: str) -> list[dict[str, Any]]:
        body = self.raw(
            self.client.beta.sessions.threads.events.with_raw_response.list(
                thread_id, session_id=session_id, limit=1000
            )
        )
        return list(body.get("data", []))


class ThreadFollower(threading.Thread):
    """Follows one thread's stream (raw SSE) in the background, P6/P7: opens the stream, lists
    the thread's history right away, then records every event until stopped."""

    def __init__(self, ctx: ProbeContext, session_id: str, thread_id: str, agent_name: str) -> None:
        super().__init__(daemon=True)
        self.ctx, self.session_id, self.thread_id, self.agent_name = (
            ctx,
            session_id,
            thread_id,
            agent_name,
        )
        self.events: list[dict[str, Any]] = []
        self.initial_history: int | None = None
        self.error: str | None = None
        self._response: Any = None

    def run(self) -> None:
        from anthropic import Stream

        try:
            with self.ctx.client.beta.sessions.threads.events.with_streaming_response.stream(
                self.thread_id, session_id=self.session_id
            ) as response:
                self._response = response
                self.initial_history = len(self.ctx.thread_history(self.session_id, self.thread_id))
                for event in self.ctx._events(
                    Stream.raw_events(response.http_response), f"thread:{self.thread_id}"
                ):
                    if event.get("type") != PING:
                        self.events.append(event)
        except Exception as exc:  # closed by stop(), or a real error
            self.error = type(exc).__name__

    def stop(self) -> None:
        if self._response is not None:
            with contextlib.suppress(Exception):
                self._response.http_response.close()
        self.join(timeout=5)


# --- event helpers ----------------------------------------------------------------------------


def stop_reason(event: Mapping[str, Any]) -> str | None:
    reason = event.get("stop_reason")
    if isinstance(reason, Mapping):
        return str(reason.get("type"))
    return reason if isinstance(reason, str) else None


def is_final_idle(event: Mapping[str, Any]) -> bool:
    return event.get("type") == "session.status_idle" and stop_reason(event) != "requires_action"


def usage_cents(obj: Mapping[str, Any]) -> int:
    cost = (obj.get("usage") or {}).get("list_cost") or {}
    try:
        return int(cost.get("amount", 0))
    except (TypeError, ValueError):
        return 0


def types_of(events: list[dict[str, Any]]) -> list[str]:
    return [str(e.get("type")) for e in events]


def hosts_in(value: Any) -> set[str]:
    """Hostnames of the URLs inside a JSON value (never the URLs or the text around them)."""
    found: set[str] = set()
    for url in URL_PATTERN.findall(json.dumps(value)):
        match = re.match(r"https?://([^/:?#]+)", url)
        if match:
            found.add(match.group(1).lower())
    return found


def error_status(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    kind = ""
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            kind = str(error.get("type") or "")
    return f"{status or type(exc).__name__}{' ' + kind if kind else ''}"


def json_diff(sent: Any, echoed: Any, path: str = "") -> list[str]:
    """Paths where the echo differs from what was sent (keys added by the server ignored)."""
    if isinstance(sent, Mapping) and isinstance(echoed, Mapping):
        out: list[str] = []
        for key, value in sent.items():
            if key not in echoed:
                out.append(f"{path}/{key} dropped")
            else:
                out.extend(json_diff(value, echoed[key], f"{path}/{key}"))
        return out
    if isinstance(sent, list) and isinstance(echoed, list):
        if len(sent) != len(echoed):
            return [f"{path} length {len(sent)} -> {len(echoed)}"]
        return [
            d
            for i, (a, b) in enumerate(zip(sent, echoed, strict=True))
            for d in json_diff(a, b, f"{path}[{i}]")
        ]
    return [] if sent == echoed else [f"{path} changed"]


# --- the probes -------------------------------------------------------------------------------


def p1_environment(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    config: Any = {
        "type": "cloud",
        "networking": {
            "type": "limited",
            "allowed_hosts": LIMITED_HOSTS,
            "allow_mcp_servers": True,
        },
    }
    env_id = ctx.environment("limited")
    echo = ctx.raw(ctx.client.beta.environments.with_raw_response.retrieve(env_id))
    diff = json_diff(config, echo.get("config"))
    result.add(
        f"limited environment created ({env_id}); echoed config "
        f"{'matches' if not diff else 'differs: ' + ', '.join(diff)}"
    )
    try:
        dup = ctx.raw(
            ctx.once.beta.environments.with_raw_response.create(
                name=ctx.name("env-limited"), config=config
            )
        )
        ctx.cleanup.append(
            (f"delete environment {dup['id']}", lambda: ctx.delete_environment(dup["id"]))
        )
        result.add("UNEXPECTED: a second environment with the same name was accepted")
        result.status = "unexpected"
    except Exception as exc:
        result.add(f"same name again: {error_status(exc)} (expected 409)")
        if getattr(exc, "status_code", None) != 409:
            result.status = "unexpected"
    unrestricted = ctx.environment("unrestricted")
    echo = ctx.raw(ctx.client.beta.environments.with_raw_response.retrieve(unrestricted))
    result.add(f"development profile environment config echoed as {json.dumps(echo.get('config'))}")
    return result


def p2_submit_plan_schema(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    tool = dict(ctx.inputs.submit_plan_tool)
    variants = {
        "raw ($defs and $ref)": ctx.inputs.raw_plan_schema,
        "inlined (deployed)": tool["input_schema"],
    }
    for label, schema in variants.items():
        body_tool = {**tool, "input_schema": schema}
        try:
            agent = ctx.agent(f"p2-{'raw' if 'raw' in label else 'inlined'}", tools=[body_tool])
            echoed = next((t for t in agent.get("tools", []) if t.get("name") == "submit_plan"), {})
            diff = json_diff(schema, echoed.get("input_schema"))
            result.add(
                f"{label}: accepted; echoed input_schema "
                f"{'identical' if not diff else 'differs at ' + ', '.join(diff[:10])}"
            )
        except Exception as exc:
            result.add(f"{label}: rejected {error_status(exc)}: {str(exc)[:300]}")
            if "inlined" in label:
                result.status = "unexpected"
    return result


def p3_models_and_budget(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    env_id = ctx.environment("unrestricted")
    for model in sorted(set(ctx.inputs.models.values()) | {"claude-opus-5-5"}):
        agent = ctx.agent(f"p3-{model}", model=model, system="Reply with one word.")
        try:
            session_id = ctx.session(agent, env_id, label=f"p3-{model}")
            result.add(f"{model}: budgeted session accepted ({session_id})")
            ctx.delete_session(session_id)
        except ProbeSkippedError:
            raise
        except Exception as exc:
            result.add(f"{model}: session create failed {error_status(exc)}")
            result.status = "unexpected"
    return result


def p4_mcp(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    servers = list(ctx.inputs.flights.get("mcp_servers") or [])
    toolsets = [
        {
            "type": "mcp_toolset",
            "mcp_server_name": server["name"],
            "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
        }
        for server in servers
    ]
    agent = ctx.agent(
        "p4-mcp",
        system="You are a probe. Follow the user's instructions exactly and briefly.",
        mcp_servers=servers,
        tools=toolsets,  # MCP only, every tool on: the probe reads the real tool names
    )
    session_id = ctx.session(agent, ctx.environment("unrestricted"), label="p4-mcp")
    depart = (dt.datetime.now(ROME).date() + dt.timedelta(days=45)).isoformat()
    events = ctx.run_turn(
        session_id,
        "First list the exact names of every tool you have, grouped by MCP server, one per line. "
        "Then call one flight-search tool of each MCP server once, for one adult, one way from "
        f"MXP to LIS on {depart}. "
        "Then stop.",
    )
    calls = [
        (e.get("mcp_server_name"), e.get("name"), e.get("evaluated_permission"))
        for e in events
        if e.get("type") == "agent.mcp_tool_use"
    ]
    result.add(
        "MCP tool calls (server, tool, permission): " + (", ".join(map(str, calls)) or "none")
    )
    for event in events:
        if event.get("type") == "agent.mcp_tool_result":
            hosts = sorted(hosts_in(event.get("content")))
            result.add(
                f"result of {event.get('mcp_tool_use_id')}: is_error={event.get('is_error')}, "
                f"link hosts {hosts}"
            )
        if event.get("type") == "session.error":
            error = event.get("error") or {}
            result.add(
                f"session.error {error.get('type')} server={error.get('mcp_server_name')} "
                f"retry={(error.get('retry_status') or {}).get('type')}"
            )
    listed = [e for e in events if e.get("type") == "agent.message"]
    if listed:
        text = " ".join(
            b.get("text", "") for b in listed[0].get("content", []) if isinstance(b, dict)
        )
        names = sorted(
            set(re.findall(r"[A-Za-z][\w-]{2,60}", text))
            & set(re.findall(r"\b[a-z]+[_-][a-z_-]+\b", text))
        )
        result.add(f"tool names the agent listed (filtered tokens): {names}")
    result.add(
        f"turn ended with {types_of(events)[-1:]} {stop_reason(events[-1]) if events else ''}"
    )
    return result


def p5_web_tools(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    agent = ctx.agent(
        "p5-web",
        system="You are a probe. Use only the tools the user names, once each, then stop.",
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": "web_fetch", "enabled": True},
                    {"name": "web_search", "enabled": True},
                ],
            }
        ],
    )
    for kind in ("limited", "unrestricted"):
        session_id = ctx.session(agent, ctx.environment(kind), label=f"p5-{kind}")
        events = ctx.run_turn(session_id, P5_PROMPT)
        uses = {e.get("id"): e for e in events if e.get("type") == "agent.tool_use"}
        built_attempts = 0
        for event in events:
            if event.get("type") != "agent.tool_result":
                continue
            use = uses.get(event.get("tool_use_id"), {})
            content = json.dumps(event.get("content"))
            codes = sorted(
                set(re.findall(r"\b[a-z]+(?:_[a-z]+)+_error\b|\burl_not_allowed\b", content))
            )
            items = len(event.get("content") or [])
            target = (use.get("input") or {}).get("url") or (use.get("input") or {}).get("query")
            built = use.get("name") == "web_fetch" and P5_MODEL_BUILT_HOST in hosts_in(target)
            built_attempts += built
            result.add(
                f"{kind}: {use.get('name')} {target}"
                f"{' (URL built by the model, step 4)' if built else ''}: "
                f"is_error={event.get('is_error')} codes={codes} content_blocks={items}"
            )
        if not built_attempts:
            result.add(f"{kind}: step 4 (URL built by the model): no web_fetch attempted")
    restricted = ctx.agent(
        "p5-allowed-domains",
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": "web_fetch", "enabled": True, "allowed_domains": ["booking.com"]}
                ],
            }
        ],
    )
    try:
        session_id = ctx.session(restricted, ctx.environment("limited"), label="p5-allowed-domains")
        result.add(
            "allowed_domains [booking.com] outside allowed_hosts: session ACCEPTED "
            f"({session_id}); expected 400"
        )
        result.status = "unexpected"
    except ProbeSkippedError:
        raise
    except Exception as exc:
        result.add(
            f"allowed_domains [booking.com] outside allowed_hosts: {error_status(exc)} (expected "
            "400)"
        )
    return result


def p6_inter_agent(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    tools = [
        {
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": False},
            "configs": [{"name": "read", "enabled": True}],
        }
    ]
    sub_a = ctx.agent(
        "p6-a",
        name=ctx.name("p6-a"),
        system="You are subagent A, a probe. Do exactly what you are asked, briefly.",
        tools=tools,
    )
    sub_b = ctx.agent(
        "p6-b",
        name=ctx.name("p6-b"),
        system="You are subagent B, a probe. Do exactly what you are asked, briefly.",
        tools=tools,
    )
    coordinator = ctx.agent(
        "p6-coordinator",
        system="You are a probe coordinator. Follow the user's numbered steps exactly and briefly.",
        tools=tools,
        multiagent={
            "type": "multiagent_20261001",
            "subagents": {
                "type": "enabled",
                "inline_agents": {"type": "disabled"},
                "predefined_agents": [
                    {"type": "agent", "id": sub_a["id"], "version": sub_a["version"]},
                    {"type": "agent", "id": sub_b["id"], "version": sub_b["version"]},
                ],
            },
            "workflows": {"type": "disabled"},
            "advisor": {"type": "disabled"},
        },
    )
    session_id = ctx.session(coordinator, ctx.environment("unrestricted"), label="p6-multiagent")
    followers: dict[str, ThreadFollower] = {}

    def follow(event: dict[str, Any]) -> None:
        if event.get("type") == "session.thread_created" and event.get("session_thread_id"):
            follower = ThreadFollower(
                ctx, session_id, event["session_thread_id"], str(event.get("agent_name"))
            )
            followers[event["session_thread_id"]] = follower
            follower.start()

    name_a, name_b = sub_a["name"], sub_b["name"]
    events = ctx.run_turn(
        session_id,
        "1. List the exact names of all your tools.\n"
        f"2. Delegate to {name_a}: 'List the exact names of all your tools, then ask the "
        "coordinator one question before you finish.'\n"
        f"3. Ask {name_a} to send a short note directly to {name_b}, if it has a tool for that.\n"
        f"4. After {name_a}'s report arrives, delegate to {name_a} a second time: 'Say done.'\n"
        "5. Then stop.",
        on_event=follow,
    )
    time.sleep(3)
    for follower in followers.values():
        follower.stop()
    coordinator_tools = sorted(
        {str(e.get("name")) for e in events if e.get("type") == "agent.tool_use"}
    )
    result.add(f"coordinator tool names used: {coordinator_tools}")
    created = [
        (e.get("agent_name"), e.get("session_thread_id"))
        for e in events
        if e.get("type") == "session.thread_created"
    ]
    result.add(f"threads created: {created}")
    per_agent: dict[str, int] = {}
    for agent_name, _ in created:
        per_agent[str(agent_name)] = per_agent.get(str(agent_name), 0) + 1
    if per_agent.get(name_a, 0) > 1:
        result.add(f"re-delegation to {name_a} opened a NEW thread ({per_agent[name_a]} threads)")
    elif per_agent.get(name_a) == 1:
        result.add(f"re-delegation to {name_a} REUSED its thread (one thread_created)")
    for thread_id, follower in followers.items():
        names = sorted(
            {str(e.get("name")) for e in follower.events if e.get("type") == "agent.tool_use"}
        )
        result.add(
            f"thread {thread_id} ({follower.agent_name}): tool names {names}; history at open "
            f"{follower.initial_history}; stream error {follower.error}"
        )
    messages = [
        (e.get("type"), e.get("from_agent_name") or e.get("to_agent_name"))
        for e in events
        if str(e.get("type", "")).startswith("agent.thread_message")
    ]
    result.add(f"inter-agent messages on the primary stream: {messages}")
    ctx.shared["p6"] = {
        "session_id": session_id,
        "events": events,
        "followers": followers,
        "name_a": name_a,
    }

    a_threads = [tid for name, tid in created if name == name_a and tid]
    if a_threads:
        thread_id = a_threads[-1]
        try:
            archived = ctx.raw(
                ctx.once.beta.sessions.threads.with_raw_response.archive(
                    thread_id, session_id=session_id
                )
            )
            result.add(
                f"archived {name_a}'s thread {thread_id}: archived_at "
                f"set={bool(archived.get('archived_at'))}"
            )
            again = ctx.run_turn(
                session_id, f"Delegate to {name_a} once more: 'Say done again.' Then stop."
            )
            after = [
                (e.get("agent_name"), e.get("session_thread_id"))
                for e in again
                if e.get("type") == "session.thread_created"
            ]
            result.add(
                f"delegation after archiving: threads created {after}; ended "
                f"{stop_reason(again[-1]) if again else None}"
            )
        except Exception as exc:
            result.add(f"archiving or re-delegating failed: {error_status(exc)}")
    return result


def p7_streams(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    shared = ctx.shared.get("p6")
    if not shared:
        raise ProbeSkippedError("P7 reads the streams recorded by P6, which did not run")
    events: list[dict[str, Any]] = shared["events"]
    followers: dict[str, ThreadFollower] = shared["followers"]
    with_ids = sum(1 for e in events if e.get("_sse_id"))
    result.add(f"session stream: {with_ids}/{len(events)} SSE messages carry an `id:` line")
    usage = [e for e in events if e.get("type") == "session.usage"]
    result.add(
        f"session.usage events on the raw session stream: {len(usage)} (SSE event name "
        f"{usage[0].get('_sse_event') if usage else None}); the 1.13.0 typed iterator drops them"
    )
    primary = {
        (e.get("type"), e.get("session_thread_id"), e.get("processed_at")): e.get("id")
        for e in events
        if str(e.get("type", "")).startswith("session.thread_status")
    }
    for thread_id, follower in followers.items():
        same, different = 0, 0
        for event in follower.events:
            if not str(event.get("type", "")).startswith("session.thread_status"):
                continue
            key = (
                event.get("type"),
                event.get("session_thread_id") or thread_id,
                event.get("processed_at"),
            )
            if key in primary:
                if primary[key] == event.get("id"):
                    same += 1
                else:
                    different += 1
        result.add(
            f"thread {thread_id}: history length right after thread_created = "
            f"{follower.initial_history}; thread_status copies with the same id {same}, different "
            f"id {different}"
        )
    return result


def p8_custom_tool(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    agent = ctx.agent(
        "p8-submit",
        system="You are a probe. Call submit_plan with the plan the user gives. If the tool "
        "returns an error, change exactly what the error says and call it again. After "
        "'Plan accepted.' stop.",
        tools=[dict(ctx.inputs.submit_plan_tool)],
    )
    session_id = ctx.session(agent, ctx.environment("unrestricted"), label="p8-submit")
    start = (dt.datetime.now(ROME).date() + dt.timedelta(days=40)).isoformat()
    plan = {
        "title": "Prova",
        "destination": "Lisbona, Portogallo",
        "timezone": "Europe/Lisbon",
        "start_date": start,
        "end_date": start,
        "travelers": 1,
        "days": [
            {"date": start, "stops": [{"ref": "d1-s1", "title": "Passeggiata", "kind": "activity"}]}
        ],
        "bookings": [],
        "summary": "Prova.",
    }
    calls: list[str] = []
    statuses: list[str] = []

    def on_event(event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "agent.custom_tool_use" and event.get("name") == "submit_plan":
            calls.append(str(event.get("id")))
            if len(calls) == 1:
                text, error = "summary: write 'Piano di prova.' instead of 'Prova.'", True
            else:
                text, error = "Plan accepted.", False
            ctx.once.beta.sessions.events.send(
                session_id,
                events=[
                    {
                        "type": "user.custom_tool_result",
                        "custom_tool_use_id": event["id"],
                        "content": [{"type": "text", "text": text}],
                        "is_error": error,
                    }
                ],
            )
        if kind in ("session.status_idle", "session.status_running"):
            statuses.append(f"{kind.split('_')[-1]}:{stop_reason(event) or ''}".rstrip(":"))

    events = ctx.run_turn(
        session_id, "Submit this plan:\n```json\n" + json.dumps(plan) + "\n```", on_event=on_event
    )
    result.add(f"submit_plan calls: {len(calls)} (ids {calls}); status sequence {statuses}")
    if calls:
        try:
            ctx.once.beta.sessions.events.send(
                session_id,
                events=[
                    {
                        "type": "user.custom_tool_result",
                        "custom_tool_use_id": calls[0],
                        "content": [{"type": "text", "text": "duplicate"}],
                        "is_error": False,
                    }
                ],
            )
            time.sleep(3)
            status = ctx.raw(ctx.client.beta.sessions.with_raw_response.retrieve(session_id))[
                "status"
            ]
            result.add(
                "duplicate result for the first call: accepted, session status afterwards "
                f"{status} (expected idle, no effect)"
            )
        except Exception as exc:
            result.add(f"duplicate result for the first call: {error_status(exc)}")
    if len(calls) != 2 or not events or stop_reason(events[-1]) != "end_turn":
        result.status = "unexpected"
    ctx.shared["p8"] = {"session_id": session_id}
    return result


def p9_budget(ctx: ProbeContext) -> ProbeResult:
    """The budget is checked before each model request, so the turn needs many requests: ten
    `write` calls, each answered by a tool result, on the profile's coordinator model (Sonnet
    5.5 in development: about a cent per request, so 3 cents run out after a few files). The
    budget is removed only once the session is interrupted and idle, so nothing runs uncapped."""
    result = ProbeResult()
    agent = ctx.agent(
        "p9-budget",
        model=ctx.inputs.models["coordinator"],
        system="You are a probe. Do exactly what the user asks, one tool call at a time.",
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [{"name": "write", "enabled": True}],
            }
        ],
    )
    session_id = ctx.session(
        agent, ctx.environment("unrestricted"), budget_cents=P9_BUDGET_CENTS, label="p9-budget"
    )
    events = ctx.run_turn(
        session_id,
        "Write ten files, /tmp/p9/part-01.txt to /tmp/p9/part-10.txt, each a 300-word passage "
        "on the history of Lisbon's trams: one `write` call per file, in order.",
    )
    result.add(
        "session events up to the cap: "
        f"{[t for t in types_of(events) if t.startswith('session.')]}; turn ended "
        f"{stop_reason(events[-1]) if events else None} (expected budget_reached)"
    )
    if not events or stop_reason(events[-1]) != "budget_reached":
        result.status = "unexpected"
        return result
    try:
        ctx.send_message(session_id, "Continue.")
        result.add("user.message at the cap: ACCEPTED (expected 400)")
        result.status = "unexpected"
    except Exception as exc:
        result.add(f"user.message at the cap: {error_status(exc)} (expected 400)")
    session = ctx.raw(ctx.client.beta.sessions.with_raw_response.retrieve(session_id))
    raised = usage_cents(session) + 5
    seen: list[str] = []
    with ctx.session_stream(session_id) as stream:
        ctx.once.beta.sessions.update(
            session_id,
            budget={"type": "limit", "max_list_cost": {"amount": str(raised), "currency": "USD"}},
        )
        deadline = time.monotonic() + 60
        for event in stream:
            if time.monotonic() > deadline:
                seen.append("(nothing more within 60 s)")
                break
            if event.get("type") == PING:
                continue
            seen.append(f"{event.get('type')}:{stop_reason(event) or ''}".rstrip(":"))
            if is_final_idle(event):
                break
    result.add(
        f"after raising the budget to {raised} cents: {seen[:12]} (a session.status_running means "
        "it resumed by itself)"
    )
    with contextlib.suppress(Exception):
        ctx.once.beta.sessions.events.send(session_id, events=[{"type": "user.interrupt"}])
    ctx.wait_not_running(session_id)
    with ctx.session_stream(session_id) as stream:
        ctx.once.beta.sessions.update(session_id, budget=None)
        deadline = time.monotonic() + 30
        for event in stream:
            if event.get("type") == "session.updated":
                result.add(
                    "budget removed on the idle session: session.updated "
                    f"budget={json.dumps(event.get('budget'))} (expected null)"
                )
                break
            if time.monotonic() > deadline:
                result.add("budget removed: no session.updated within 30 s")
                break
    return result


def p10_interrupt(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    agent = ctx.agent("p10-interrupt", system="You are a probe. Answer at great length.")
    session_id = ctx.session(agent, ctx.environment("unrestricted"), label="p10-interrupt")
    sent = {"done": False}

    def on_event(event: dict[str, Any]) -> None:
        if not sent["done"] and str(event.get("type", "")).startswith(
            ("agent.", "span.model_request_start")
        ):
            ctx.once.beta.sessions.events.send(session_id, events=[{"type": "user.interrupt"}])
            sent["done"] = True

    events = ctx.run_turn(
        session_id,
        "Count slowly from 1 to 500, one number per line, with a comment on each.",
        on_event=on_event,
    )
    echoes = [e for e in events if e.get("type") == "user.interrupt"]
    result.add(
        f"interrupt echo on the stream: id={[e.get('id') for e in echoes]} "
        f"processed_at={[e.get('processed_at') for e in echoes]}; turn ended "
        f"{stop_reason(events[-1]) if events else None}"
    )
    listed = [e for e in ctx.history(session_id) if e.get("type") == "user.interrupt"]
    result.add(
        f"listed interrupt copies: id={[e.get('id') for e in listed]} "
        f"processed_at={[e.get('processed_at') for e in listed]}"
    )
    try:
        ctx.once.beta.sessions.archive(session_id)
        result.add("archive right after the idle event: accepted at once")
    except Exception as exc:
        result.add(f"archive right after the idle event: {error_status(exc)} (the post-idle race)")
        ctx.wait_not_running(session_id)
        ctx.once.beta.sessions.archive(session_id)
    status = ctx.raw(ctx.client.beta.sessions.with_raw_response.retrieve(session_id))["status"]
    result.add(f"status after archive: {status} (expected terminated)")
    cutoff = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)
    page = ctx.client.beta.sessions.list(created_at_lt=cutoff, include_archived=True, limit=50)
    mine = next((s for s in page.data if s.id == session_id), None)
    result.add(
        f"sessions.list(include_archived=True) lists it: {mine is not None}; metadata "
        f"{dict(mine.metadata) if mine else None}"
    )
    ctx.delete_session(session_id)
    result.add("deleted after archiving")
    return result


def p11_skills(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    name = ctx.name("skill")
    with tempfile.TemporaryDirectory() as temp:
        skill_dir = Path(temp) / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Probe skill.\n---\nSay hello.\n", encoding="utf-8"
        )
        (skill_dir / "hello.py").write_text("print('hello')\n", encoding="utf-8")
        files = bootstrap.collect_skill_files(skill_dir)
        upload = [(f.upload_name(name), f.abs_path.read_bytes(), f.content_type()) for f in files]
        skill = ctx.raw(ctx.once.skills.with_raw_response.create(files=upload, display_name=name))
        skill_id, first = skill["id"], skill["latest_version_id"]

        def delete_skill() -> None:
            for version in ctx.client.skills.versions.list(skill_id):
                with contextlib.suppress(Exception):
                    ctx.once.skills.versions.delete(version.id, skill_id=skill_id)
            ctx.once.skills.delete(skill_id)

        ctx.cleanup.append((f"delete skill {skill_id}", delete_skill))
        result.add(
            f"skill id format {re.sub(r'[A-Za-z0-9]{6,}$', '…', skill_id)}, version id format "
            f"{re.sub(r'[A-Za-z0-9]{6,}$', '…', first)}"
        )
        tools = [
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [{"name": "read", "enabled": True}],
            }
        ]
        latest = ctx.agent(
            "p11-latest",
            tools=tools,
            skills=[{"type": "custom", "skill_id": skill_id, "version": "latest"}],
        )
        pinned = ctx.agent(
            "p11-pinned",
            tools=tools,
            skills=[{"type": "custom", "skill_id": skill_id, "version": first}],
        )
        result.add(
            f"echoed version: 'latest' agent -> {latest['skills'][0].get('version')}, pinned "
            f"agent -> {pinned['skills'][0].get('version')}"
        )
        (skill_dir / "hello.py").write_text("print('hello again')\n", encoding="utf-8")
        files = bootstrap.collect_skill_files(skill_dir)
        upload = [(f.upload_name(name), f.abs_path.read_bytes(), f.content_type()) for f in files]
        second = ctx.raw(ctx.once.skills.versions.with_raw_response.create(skill_id, files=upload))[
            "id"
        ]
        result.add(f"new version {second}")
    session_id = ctx.session(latest, ctx.environment("unrestricted"), label="p11-latest")
    session = ctx.raw(ctx.client.beta.sessions.with_raw_response.retrieve(session_id))
    seen = [s.get("version") for s in (session.get("agent") or {}).get("skills", [])]
    verdict = (
        "the NEW version (resolved at session time)"
        if second in seen
        else "the OLD version (resolved at agent save time)"
        if first in seen
        else "neither"
    )
    result.add(f"a new session of the 'latest' agent gets {seen}: {verdict}")
    return result


def p12_ant_and_multiagent_update(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    ant = shutil.which("ant")
    if ant is None:
        result.add(
            "ant CLI not installed: install needs Michele's OK (brew install anthropics/tap/ant); "
            "part 1 skipped"
        )
    else:
        version = subprocess.run(
            [ant, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
        result.add(f"ant --version: {version.stdout.strip() or version.stderr.strip()}")
        lock = ctx.repo_root / "backend" / f".probe-ant-lock-{ctx.stamp}.json"
        try:
            run = subprocess.run(
                [
                    ant,
                    "apply",
                    "--dry-run",
                    "-v",
                    "--lock-file",
                    str(lock.relative_to(ctx.repo_root)),
                    f"profiles/{PROFILE}",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                cwd=ctx.repo_root,
            )
        finally:
            lock.unlink(missing_ok=True)
        output = run.stdout + run.stderr
        ctx.log("ant", output)
        result.add(
            f"ant apply --dry-run exit {run.returncode}; output logged to {ctx.sse_log_path}"
        )
        result.add(
            "keys relative to the lockfile directory (../profiles/...): "
            f"{'../profiles/' in output}; to the cwd (./profiles/...): "
            f"{'./profiles/' in output and '../profiles/' not in output}"
        )
        result.add(
            f"environment classified: {'environment' in output}; submit_plan spliced: "
            f"{'submit_plan' in output}; predefined agents as agent refs: "
            f"{'predefined_agents' in output}"
        )
    sub = ctx.agent("p12-sub", system="Probe subagent.")
    complete = {
        "type": "multiagent_20261001",
        "subagents": {
            "type": "enabled",
            "inline_agents": {"type": "disabled"},
            "predefined_agents": [{"type": "agent", "id": sub["id"], "version": sub["version"]}],
        },
        "workflows": {"type": "disabled"},
        "advisor": {"type": "disabled"},
    }
    coordinator = ctx.agent("p12-coordinator", system="Probe coordinator.", multiagent=complete)
    partial = {"type": "multiagent_20261001", "subagents": complete["subagents"]}
    updated = ctx.raw(
        ctx.once.beta.agents.with_raw_response.update(
            coordinator["id"], version=coordinator["version"], extra_body={"multiagent": partial}
        )
    )
    echoed = updated.get("multiagent") or {}
    verdict = (
        "merged (kept)"
        if echoed.get("workflows") == {"type": "disabled"}
        else "replaced (defaults)"
    )
    result.add(
        f"partial multiagent update: workflows {json.dumps(echoed.get('workflows'))}, advisor "
        f"{json.dumps(echoed.get('advisor'))} -> {verdict}"
    )
    return result


def p13_usage(ctx: ProbeContext) -> ProbeResult:
    result = ProbeResult()
    targets = [
        (label, ctx.shared[label]["session_id"]) for label in ("p8", "p6") if label in ctx.shared
    ]
    if not targets:
        raise ProbeSkippedError("P13 reads the sessions of P6 and P8, which did not run")
    for label, session_id in targets:
        session = ctx.raw(ctx.client.beta.sessions.with_raw_response.retrieve(session_id))
        usage = session.get("usage") or {}
        tools_used = usage.get("server_tool_use") or {}
        result.add(
            f"{label} session usage: list_cost={json.dumps(usage.get('list_cost'))}, "
            f"web_search_requests={tools_used.get('web_search_requests')}, "
            f"active_seconds={usage.get('active_seconds')}"
        )
        threads = ctx.raw(ctx.client.beta.sessions.threads.with_raw_response.list(session_id)).get(
            "data", []
        )
        for thread in threads:
            detail = ctx.raw(
                ctx.client.beta.sessions.threads.with_raw_response.retrieve(
                    thread["id"], session_id=session_id
                )
            )
            primary = thread.get("parent_thread_id") is None
            result.add(
                f"  thread {thread['id']} "
                f"({'primary' if primary else (detail.get('agent') or {}).get('name')}): "
                f"list_cost={json.dumps((detail.get('usage') or {}).get('list_cost'))}"
            )
    return result


PROBES: tuple[Probe, ...] = (
    Probe(
        "P1", "Environment shape", "notes §2b fields; unique environment names", 0, p1_environment
    ),
    Probe(
        "P2",
        "submit_plan schema",
        "D1: is $defs/$ref accepted, is the inlined schema echoed intact",
        0,
        p2_submit_plan_schema,
    ),
    Probe(
        "P3",
        "Model and budget acceptance",
        "I14: Haiku/Sonnet/Opus 5.5 accept a session budget",
        3,
        p3_models_and_budget,
    ),
    Probe(
        "P4",
        "Travel MCP reachability and tool names",
        "D3, D6: exact MCP tool names; whether the servers accept a session",
        1,
        p4_mcp,
    ),
    Probe(
        "P5",
        "Web tools vs allowed_hosts",
        "D4: limited vs unrestricted networking; whether web_fetch refuses a URL the model "
        "builds (activities geocoding)",
        2,
        p5_web_tools,
    ),
    Probe(
        "P6",
        "Inter-agent tools and thread reuse",
        "D5; consumer.superseded_threads",
        1,
        p6_inter_agent,
    ),
    Probe(
        "P7",
        "Streams, ids, cross-posts",
        "§2f dedupe key; I8 (session.usage on the raw stream)",
        0,
        p7_streams,
    ),
    Probe(
        "P8",
        "Custom tool round trip",
        "§2e submit_plan answers; duplicate results",
        1,
        p8_custom_tool,
    ),
    Probe(
        "P9",
        "Budget pause and resume",
        "§2d budget flow; budget_paused and 'Continua'",
        1,
        p9_budget,
    ),
    Probe(
        "P10",
        "Interrupt and cleanup",
        "I23, I24; SessionBusyError mapping; orphan sweep",
        1,
        p10_interrupt,
    ),
    Probe("P11", "Skills", "skill version pinning ('latest' vs a version id)", 1, p11_skills),
    Probe(
        "P12",
        "ant CLI and multiagent update",
        "D2, I21: whether bootstrap.py is needed; lockfile keys; multiagent update semantics",
        0,
        p12_ant_and_multiagent_update,
    ),
    Probe(
        "P13",
        "Usage fields",
        "the cost_cents source (session and per-thread list_cost)",
        0,
        p13_usage,
    ),
)
PROBE_IDS = tuple(p.id for p in PROBES)


# --- report -----------------------------------------------------------------------------------


def report_path(directory: Path, today: dt.date) -> Path:
    path = directory / f"{today.isoformat()}.md"
    counter = 2
    while path.exists():
        path = directory / f"{today.isoformat()}-{counter}.md"
        counter += 1
    return path


def render_report(
    results: list[tuple[Probe, ProbeResult]],
    *,
    started: dt.datetime,
    inputs: ProfileInputs,
    spent_cents: int,
    sse_log: Path,
    cleanup: list[str],
) -> str:
    lines = [
        f"# Live probes, {started.date().isoformat()}",
        "",
        f"Run by scripts/probe_session.py at {started.isoformat(timespec='seconds')} against the "
        f"{PROFILE} profile "
        f"(models {', '.join(sorted(set(inputs.models.values())))}; session budget "
        f"{inputs.session_budget_cents} US cents). "
        f"Sessions' total list cost: {spent_cents} US cents. Raw SSE log (not committed, may hold "
        f"web text): `{sse_log}`.",
        "",
        "Checklist: docs/managed-agents-notes.md section 4. Statuses: done (facts recorded "
        "below), unexpected "
        "(a documented expectation failed), error, skipped.",
        "",
        "| # | Probe | Status | Decides |",
        "|---|---|---|---|",
    ]
    for probe, result in results:
        lines.append(f"| {probe.id} | {probe.title} | {result.status} | {probe.decides} |")
    for probe, result in results:
        lines += ["", f"## {probe.id}. {probe.title}", ""]
        lines += [f"- {finding}" for finding in result.findings] or ["- (no findings)"]
    lines += ["", "## Cleanup", ""] + ([f"- {item}" for item in cleanup] or ["- nothing to clean"])
    return "\n".join(lines) + "\n"


# --- CLI --------------------------------------------------------------------------------------


def parse_only(text: str | None) -> list[str]:
    if not text:
        return list(PROBE_IDS)
    wanted = [item.strip().upper() for item in text.split(",") if item.strip()]
    unknown = [item for item in wanted if item not in PROBE_IDS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown probe(s) {unknown}; choose from {', '.join(PROBE_IDS)}"
        )
    if "P7" in wanted and "P6" not in wanted:
        wanted.append("P6")
    if "P13" in wanted and not {"P6", "P8"} & set(wanted):
        wanted.append("P8")
    return [pid for pid in PROBE_IDS if pid in wanted]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="probe_session.py",
        description="Live probes P1..P13 (docs/managed-agents-notes.md §4) on the development "
        "profile. Spends real money.",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the probe plan; no network")
    parser.add_argument("--yes", action="store_true", help="run the probes (they spend money)")
    parser.add_argument(
        "--only", type=parse_only, default=None, help="comma-separated probe ids, e.g. P1,P4"
    )
    parser.add_argument(
        "--max-total-cents",
        type=int,
        default=DEFAULT_MAX_TOTAL_CENTS,
        help="stop creating sessions past this list cost (US cents)",
    )
    parser.add_argument("--report-dir", type=Path, default=REPO_ROOT / "docs" / "probes")
    parser.add_argument(
        "--sse-log", type=Path, default=None, help="raw SSE log (default: system temp dir)"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.only is None:
        args.only = list(PROBE_IDS)
    if args.max_total_cents < 1:
        parser.error("--max-total-cents must be positive")
    return args


def describe_plan(selected: list[Probe], inputs: ProfileInputs, max_total_cents: int) -> str:
    sessions = sum(p.sessions for p in selected)
    bound = min(
        max_total_cents + inputs.session_budget_cents, sessions * inputs.session_budget_cents
    )
    lines = [
        f"Probe plan, {PROFILE} profile (no network in a dry run):",
        f"  models: {dict(inputs.models)}; probe agents use {inputs.cheap_model}",
        "  MCP servers (P4): "
        f"{[s['name'] + ' ' + s['url'] for s in inputs.flights.get('mcp_servers', [])]}",
        f"  submit_plan tool (P2, P8): {len(json.dumps(inputs.submit_plan_tool))} bytes, inlined; "
        f"raw plan.json with $defs: {'$defs' in inputs.raw_plan_schema}",
        f"  environments: limited {LIMITED_HOSTS} + allow_mcp_servers, and the profile's own "
        f"{json.dumps(inputs.environment.get('config', {}).get('networking'))}",
    ]
    for probe in selected:
        lines.append(
            f"  {probe.id:<4} {probe.title}: {probe.sessions} session(s); decides {probe.decides}"
        )
    lines.append(
        f"  sessions: {sessions}, each capped at {inputs.session_budget_cents} US cents (P9: "
        f"{P9_BUDGET_CENTS}); "
        f"no new session past {max_total_cents} cents; worst case about {bound} cents"
    )
    lines.append("  every resource is named probe-<stamp>-... and removed at the end")
    return "\n".join(lines)


def anthropic_auth_mode() -> str | None:
    """How the SDK will authenticate: "api-key" (ANTHROPIC_API_KEY, which wins, as it does in the
    SDK and in `ant`), "federation" (a rule id, the organization id and an identity token file or
    token: Workload Identity Federation, docs/deploy.md), or None when neither is complete."""
    if (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return "api-key"
    federation = ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID")
    token = os.environ.get("ANTHROPIC_IDENTITY_TOKEN_FILE") or os.environ.get(
        "ANTHROPIC_IDENTITY_TOKEN"
    )
    if all(os.environ.get(name) for name in federation) and token:
        return "federation"
    return None


def has_anthropic_credentials() -> bool:
    """A static key, or the complete federation variables: the SDK picks them up by itself."""
    return anthropic_auth_mode() is not None


def main(
    argv: list[str] | None = None,
    *,
    client: anthropic.Anthropic | None = None,
    out: Callable[[str], None] = print,
) -> int:
    args = parse_args(argv)
    repo_root: Path = args.repo_root.resolve()
    inputs = load_inputs(repo_root)
    selected = [p for p in PROBES if p.id in args.only]
    out(describe_plan(selected, inputs, args.max_total_cents))
    if args.dry_run:
        return 0
    if not args.yes:
        out("This spends real money on the development key. Re-run with --yes to run the probes.")
        return 2
    if os.environ.get("CI"):
        out("Refusing to run in CI: the probes are run by hand only.")
        return 2
    if client is None and not has_anthropic_credentials():
        out(
            "No Anthropic credentials: set ANTHROPIC_API_KEY (the development key), or the "
            "development workspace's federation variables (ANTHROPIC_FEDERATION_RULE_ID, "
            "ANTHROPIC_ORGANIZATION_ID and ANTHROPIC_IDENTITY_TOKEN_FILE)."
        )
        return 2
    if client is None:
        out(f"Anthropic auth mode: {anthropic_auth_mode()}")
    if client is None:
        import anthropic
        import httpx2

        client = anthropic.Anthropic(max_retries=4, timeout=httpx2.Timeout(600.0, connect=10.0))

    started = dt.datetime.now(ROME)
    stamp = started.strftime("%Y%m%d%H%M%S")
    sse_log = (
        args.sse_log or Path(tempfile.gettempdir()) / "trip-planner-probes" / f"{stamp}-sse.log"
    )
    ctx = ProbeContext(
        client,
        inputs,
        stamp=stamp,
        max_total_cents=args.max_total_cents,
        sse_log=sse_log,
        repo_root=repo_root,
    )
    results: list[tuple[Probe, ProbeResult]] = []
    cleaned: list[str] = []
    try:
        for probe in selected:
            out(f"{probe.id} {probe.title} ...")
            try:
                result = probe.run(ctx)
            except ProbeSkippedError as exc:
                result = ProbeResult(status="skipped", findings=[str(exc)])
            except Exception as exc:
                result = ProbeResult(
                    status="error",
                    findings=[f"{type(exc).__name__}: {error_status(exc)}: {str(exc)[:400]}"],
                )
                ctx.log("traceback", traceback.format_exc())
            results.append((probe, result))
            out(f"{probe.id} {result.status}")
    finally:
        spent = ctx.spent_cents()
        for label, action in reversed(ctx.cleanup):
            try:
                action()
                cleaned.append(f"{label}: ok")
            except Exception as exc:
                cleaned.append(f"{label}: FAILED {error_status(exc)} (remove it by hand)")
        ctx.close()
        args.report_dir.mkdir(parents=True, exist_ok=True)
        path = report_path(args.report_dir, started.date())
        path.write_text(
            render_report(
                results,
                started=started,
                inputs=inputs,
                spent_cents=spent,
                sse_log=sse_log,
                cleanup=cleaned,
            ),
            encoding="utf-8",
        )
        out(f"Report: {path}  (sessions' list cost {spent} US cents)")
    return 0 if all(r.status in ("done", "skipped") for _, r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
