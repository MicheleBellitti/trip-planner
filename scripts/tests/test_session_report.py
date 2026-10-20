"""scripts/session_report.py, offline: fabricated event histories (shaped like the SDK's event
types), the analysis, the Markdown, the static estimate and the read-only fetch layer over
httpx2.MockTransport. Nothing here touches the network."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import httpx2
import pytest
import session_report as sr
from scripts_testlib import CLOSED_PORT_URL, REPO_ROOT

SESSION = "sesn_01TESTSESSION"
PRIMARY = "sthr_primary"
CHILD = "sthr_flights"
T0 = dt.datetime(2026, 10, 12, 9, 0, 0, tzinfo=dt.UTC)


class Clock:
    def __init__(self) -> None:
        self.t = T0
        self.n = 0

    def tick(self, seconds: float = 1.0) -> str:
        self.t += dt.timedelta(seconds=seconds)
        return self.t.isoformat().replace("+00:00", "Z")

    def event(self, kind: str, **fields: Any) -> dict[str, Any]:
        self.n += 1
        return {"id": f"sevt_{self.n:04d}", "type": kind, "processed_at": self.tick(), **fields}


def text(value: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": value}]


def request(
    clock: Clock, events: list[dict[str, Any]], *, inp: int, cc: int, cr: int, out: int
) -> None:
    start = clock.event("span.model_request_start")
    events.append(start)
    events.append(
        clock.event(
            "span.model_request_end",
            model_request_start_id=start["id"],
            is_error=False,
            model_usage={
                "input_tokens": inp,
                "cache_creation_input_tokens": cc,
                "cache_read_input_tokens": cr,
                "output_tokens": out,
            },
        )
    )


def tool_call(
    clock: Clock,
    events: list[dict[str, Any]],
    kind: str,
    name: str,
    tool_input: dict[str, Any],
    result: str,
    **extra: Any,
) -> str:
    use = clock.event(kind, name=name, input=tool_input, **extra)
    events.append(use)
    result_kind, key = {
        "agent.tool_use": ("agent.tool_result", "tool_use_id"),
        "agent.mcp_tool_use": ("agent.mcp_tool_result", "mcp_tool_use_id"),
        "agent.custom_tool_use": ("user.custom_tool_result", "custom_tool_use_id"),
    }[kind]
    events.append(clock.event(result_kind, **{key: use["id"]}, content=text(result)))
    return use["id"]


def make_raw(*, send_tool: bool = False) -> sr.RawSession:
    clock = Clock()
    primary: list[dict[str, Any]] = [clock.event("user.message", content=text("Plan Lisbon " * 10))]
    request(clock, primary, inp=1200, cc=6000, cr=0, out=300)
    tool_call(
        clock,
        primary,
        "agent.tool_use",
        "read",
        {"path": "/mnt/skills/trip-tracker-schema/SKILL.md"},
        "S" * 16000,
    )
    request(clock, primary, inp=300, cc=4500, cr=6000, out=200)
    sent = clock.event(
        "agent.thread_message_sent",
        to_session_thread_id=CHILD,
        to_agent_name="flights",
        content=text("Find flights MXP-LIS " * 5),
    )
    if send_tool:
        primary.append(
            clock.event(
                "agent.tool_use",
                name="send_to_agent",
                input={"agent": "flights", "message": "Find flights MXP-LIS " * 5},
            )
        )
    primary.append(sent)
    # a cross-posted copy of a subagent's tool use: must not be counted on the primary thread
    primary.append(
        clock.event(
            "agent.tool_use", name="web_search", input={"query": "dup"}, session_thread_id=CHILD
        )
    )
    primary.append(
        clock.event("session.thread_created", session_thread_id=CHILD, agent_name="flights")
    )
    primary.append(
        clock.event(
            "agent.thread_message_received",
            from_session_thread_id=CHILD,
            from_agent_name="flights",
            content=text("Written /workspace/results/flights.json v1"),
        )
    )
    tool_call(
        clock,
        primary,
        "agent.tool_use",
        "read",
        {"path": "/workspace/results/flights.json"},
        "R" * 4000,
    )
    request(clock, primary, inp=100, cc=1500, cr=10500, out=900)
    tool_call(
        clock,
        primary,
        "agent.custom_tool_use",
        "submit_plan",
        {"title": "Lisbon", "days": ["x" * 3000]},
        "ok",
    )
    request(clock, primary, inp=50, cc=900, cr=12000, out=2500)
    primary.append(
        clock.event(
            "session.usage",
            usage={
                "list_cost": {"amount": "62", "currency": "USD"},
                "input_tokens": 1650,
                "output_tokens": 3900,
                "cache_read_input_tokens": 28500,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 12900,
                    "ephemeral_1h_input_tokens": 0,
                },
                "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 0},
                "active_seconds": 105.0,
            },
        )
    )
    primary.append(clock.event("session.status_idle", stop_reason={"type": "end_turn"}))

    child: list[dict[str, Any]] = []
    request(clock, child, inp=900, cc=2000, cr=0, out=100)
    tool_call(
        clock,
        child,
        "agent.tool_use",
        "web_search",
        {"query": "flights Milan Lisbon"},
        "WEB " * 6000,
    )
    tool_call(
        clock,
        child,
        "agent.mcp_tool_use",
        "search-flight",
        {"from": "MXP", "to": "LIS"},
        '{"flights": []}' * 400,
        mcp_server_name="kiwi",
    )
    tool_call(
        clock,
        child,
        "agent.tool_use",
        "bash",
        {"command": "cat /mnt/skills/booking-links/SKILL.md"},
        "B" * 8000,
    )
    tool_call(
        clock,
        child,
        "agent.tool_use",
        "bash",
        {"command": "python3 /mnt/skills/travel-research-rules/write_result.py flights x.json"},
        "written v1",
    )
    request(clock, child, inp=200, cc=7000, cr=2900, out=700)
    child.append(clock.event("agent.message", content=text("Done. " + "z" * 500)))
    request(clock, child, inp=80, cc=300, cr=10100, out=50)
    child.append(clock.event("agent.tool_result", tool_use_id="sevt_missing", content=text("x")))

    threads = [
        {
            "id": PRIMARY,
            "parent_thread_id": None,
            "status": "idle",
            "agent": {
                "name": "coordinator",
                "model": {"id": "claude-sonnet-5-5"},
                "system": "p" * 14000,
                "tools": [
                    {"type": "custom", "name": "submit_plan", "input_schema": {"type": "object"}}
                ],
                "skills": [{"skill_id": "a"}, {"skill_id": "b"}],
                "mcp_servers": [],
            },
            "usage": {"list_cost": {"amount": "40", "currency": "USD"}},
        },
        {
            "id": CHILD,
            "parent_thread_id": PRIMARY,
            "status": "idle",
            "agent": {
                "name": "flights",
                "model": "claude-haiku-5-5",
                "system": "f" * 5000,
                "tools": [],
                "skills": [{"skill_id": "c"}],
                "mcp_servers": [{"name": "kiwi"}, {"name": "expedia"}],
            },
            "usage": {"list_cost": {"amount": "9", "currency": "USD"}},
        },
    ]
    return sr.RawSession(
        session_id=SESSION,
        session={
            "id": SESSION,
            "status": "idle",
            "usage": {
                "list_cost": {"amount": "62", "currency": "USD"},
                "cache_read_input_tokens": 28500,
                "input_tokens": 1650,
                "output_tokens": 3900,
            },
        },
        threads=threads,
        session_events=primary,
        thread_events={PRIMARY: [], CHILD: child},
    )


def report_for(raw: sr.RawSession | None = None) -> sr.SessionReport:
    return sr.analyse(raw or make_raw())


def thread(report: sr.SessionReport, agent: str) -> sr.ThreadReport:
    return next(t for t in report.threads if t.agent == agent)


# --- analysis ---------------------------------------------------------------------------------


def test_requests_and_context_sizes_per_thread() -> None:
    report = report_for()
    assert [t.agent for t in report.threads] == ["coordinator", "flights"]
    coordinator = thread(report, "coordinator")
    assert [r.context for r in coordinator.requests] == [7200, 10800, 12100, 12950]
    assert coordinator.first_context == 7200
    assert coordinator.max_context == coordinator.final_context == 12950
    assert coordinator.total("cache_read") == 28500
    assert coordinator.total("output_tokens") == 3900
    flights = thread(report, "flights")
    assert len(flights.requests) == 3
    assert flights.max_context == 10480
    assert flights.model == "claude-haiku-5-5"
    assert coordinator.model == "claude-sonnet-5-5"


def test_agent_snapshot_sizes_and_session_totals() -> None:
    report = report_for()
    coordinator = thread(report, "coordinator")
    assert coordinator.system_chars == 14000
    assert coordinator.custom_tools[0][0] == "submit_plan"
    assert coordinator.skills == 2
    assert thread(report, "flights").mcp_servers == ["kiwi", "expedia"]
    assert report.status == "idle"
    assert len(report.usage_snapshots) == 1
    assert report.stop_reasons == ["end_turn"]


def test_cross_posted_events_are_not_counted_on_the_primary_thread() -> None:
    coordinator = thread(report_for(), "coordinator")
    assert not [i for i in coordinator.items if "dup" in i.label]


def test_tool_results_are_classified_and_sized() -> None:
    report = report_for()
    by_label = {(i.role, i.label): i for t in report.threads for i in t.items}
    search = by_label[("tool_result", "web_search flights Milan Lisbon")]
    assert (search.kind, search.chars) == ("web_search", 24000)
    mcp = next(i for i in thread(report, "flights").items if i.kind == "mcp")
    assert mcp.tool == "kiwi.search-flight"
    skills = [
        i
        for t in report.threads
        for i in t.items
        if i.kind == "skill_file" and i.role == "tool_result"
    ]
    assert sorted(i.chars for i in skills) == [8000, 16000]
    reads = [i for i in thread(report, "coordinator").items if i.kind == "workspace_read"]
    assert {i.role for i in reads} == {"tool_input", "tool_result"}
    # running a skill script is a bash call, not a skill load
    script = next(i for i in thread(report, "flights").items if "write_result" in i.label)
    assert script.kind == "bash"
    submit = [i for i in thread(report, "coordinator").items if i.tool == "submit_plan"]
    assert {i.kind for i in submit} == {"custom_tool"}
    unmatched = [i for i in thread(report, "flights").items if i.tool == "(unmatched)"]
    assert len(unmatched) == 1


def test_rereads_count_the_later_requests() -> None:
    report = report_for()
    coordinator = thread(report, "coordinator")
    skill = next(i for i in coordinator.items if i.kind == "skill_file" and i.role == "tool_result")
    # entered after request 1: requests 2, 3 and 4 re-read it
    assert skill.rereads == 3
    assert skill.carried == skill.tokens * 3 == 12000
    flights = thread(report, "flights")
    search = next(i for i in flights.items if i.kind == "web_search" and i.role == "tool_result")
    assert search.rereads == 2


def test_growth_between_requests_is_attributed() -> None:
    coordinator = thread(report_for(), "coordinator")
    second = coordinator.requests[1]
    assert second.added_items >= 1
    assert second.added_tokens >= 4000
    assert "SKILL.md" in second.biggest_label


def test_send_to_agent_tool_use_suppresses_the_duplicate_message_item() -> None:
    plain = thread(report_for(make_raw()), "coordinator")
    sent_plain = next(i for i in plain.items if i.role == "inter_agent_out")
    assert sent_plain.counted
    dup = thread(report_for(make_raw(send_tool=True)), "coordinator")
    sent_dup = next(i for i in dup.items if i.role == "inter_agent_out")
    assert not sent_dup.counted


def test_no_span_events_falls_back_to_thread_usage_and_warns() -> None:
    raw = make_raw()
    raw.session_events = [e for e in raw.session_events if not e["type"].startswith("span.")]
    raw.threads[0]["usage"] = {
        "input_tokens": 5,
        "output_tokens": 6,
        "cache_read_input_tokens": 7,
        "cache_creation": {"ephemeral_5m_input_tokens": 8},
    }
    raw.thread_events[CHILD] = []
    report = sr.analyse(raw)
    assert report.warnings
    totals = sr._thread_totals(thread(report, "coordinator"))
    assert totals == {"input": 5, "cache_creation": 8, "cache_read": 7, "output": 6}


# --- rendering --------------------------------------------------------------------------------


def test_markdown_has_every_section_and_the_top_tables() -> None:
    text_ = sr.render_session(report_for(), top=3)
    for heading in (
        "## Session `sesn_01TESTSESSION`",
        "### Threads",
        "#### Fixed context from the agent snapshots",
        "### What fills the context",
        "### Top 3 largest tool results",
        "### Top 3 items by tokens carried",
        "### Skill loads",
        "### Messages between agents and from the user",
        "### Token timeline per thread",
        "### Event history",
    ):
        assert heading in text_
    top = text_.split("### Top 3 largest tool results")[1].split("###")[0]
    rows = [line for line in top.splitlines() if re.match(r"\| \d+ \|", line)]
    assert len(rows) == 3
    assert "web_search" in rows[0]
    assert "24,000" in rows[0]
    assert "no-history" not in text_
    assert "### Event history" not in sr.render_session(report_for(), history=False)


def test_text_is_capped_and_secrets_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "envkey-0123456789")
    raw = make_raw()
    raw.thread_events[CHILD].append(
        Clock().event(
            "agent.message",
            content=text("start " + "w" * 400 + " sk-ant-api03-SECRETSECRET envkey-0123456789"),
        )
    )
    raw.thread_events[CHILD].append(
        Clock().event(
            "agent.tool_use",
            name="web_fetch",
            input={"url": "https://x.test/?k=sk-ant-api03-LEAKLEAK&t=" + "a" * 300},
        )
    )
    body = sr.build_report([sr.analyse(raw)], None, generated_at=T0)
    assert "SECRETSECRET" not in body
    assert "LEAKLEAK" not in body
    assert "envkey-0123456789" not in body
    for line in body.splitlines():
        for cell in line.split(" | "):
            assert len(cell) <= sr.SNIPPET_CAP + 80  # a cell is a capped snippet plus framing
    assert re.search(r"start w+\.\.\.", body)


def test_table_cells_cannot_break_the_markdown() -> None:
    assert "|" not in sr.clean("a | b\nc")
    assert sr.clean("x" * 500) == "x" * 197 + "..."


def test_comparison_lists_every_session() -> None:
    second = make_raw()
    second.session_id = "sesn_02OTHER"
    body = sr.build_report([report_for(), sr.analyse(second)], None, generated_at=T0)
    assert "## Sessions compared" in body
    assert body.count("## Session `") == 2


def test_truncate_markdown_keeps_a_line_boundary_and_the_limit() -> None:
    text_ = "\n".join(f"line {i} é" for i in range(2000))
    cut = sr.truncate_markdown(text_, 5000)
    assert len(cut.encode()) <= 5000
    assert "truncated" in cut
    assert sr.truncate_markdown("short", 5000) == "short"


# --- static -----------------------------------------------------------------------------------


def test_static_estimate_reads_prompts_tools_and_skills(fake_repo: Path) -> None:
    agents = sr.static_agents(fake_repo)
    assert [a.name for a in agents] == [
        "coordinator",
        "activities",
        "flights",
        "lodging",
        "transport",
    ]
    coordinator = agents[0]
    body = (fake_repo / "profiles/development/agents/coordinator.md").read_text(encoding="utf-8")
    assert coordinator.system_chars == len(sr.split_frontmatter(body)[1])
    assert [name for name, _ in coordinator.custom_tools] == ["submit_plan", "ask_traveller"]
    tools = [
        json.loads(
            (fake_repo / f"profiles/development/agents/tools/{name}.json").read_text("utf-8")
        )
        for name in ("submit_plan", "ask_traveller")
    ]
    assert coordinator.tools_chars == sum(sr.json_chars(tool) for tool in tools)
    assert coordinator.skills == ["trip-tracker-schema", "travel-research-rules"]
    assert coordinator.floor_chars == (
        coordinator.system_chars + coordinator.tools_chars + coordinator.descriptions_chars
    )
    assert coordinator.loaded_chars > coordinator.floor_chars
    flights = next(a for a in agents if a.name == "flights")
    assert flights.custom_tools == []
    assert "kiwi.search-flight" in flights.mcp_tools
    assert {"web_search", "bash"} <= set(flights.builtin_tools)


def test_static_report_renders_the_floor_table(fake_repo: Path) -> None:
    out = sr.render_static(sr.static_agents(fake_repo))
    assert out.startswith("## Static estimate")
    assert "| coordinator |" in out
    assert "floor ~tokens" in out


def test_static_runs_on_the_real_repository() -> None:
    agents = sr.static_agents(REPO_ROOT)
    coordinator = agents[0]
    assert coordinator.name == "coordinator"
    assert coordinator.tools_chars > 5000
    assert any(
        f.label.endswith("trip-tracker-schema/example.json") and f.tier == "expected"
        for f in coordinator.files
    )
    assert all(a.floor_chars > 1000 for a in agents)


def test_static_fails_clearly_without_rendered_profiles(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="render_profiles"):
        sr.static_agents(tmp_path)


# --- the read-only fetch layer ----------------------------------------------------------------


class FakeApi:
    """GET-only Managed Agents endpoints over a RawSession, with two pages of session events."""

    def __init__(self, raw: sr.RawSession) -> None:
        self.raw = raw
        self.calls: list[tuple[str, str, str]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.calls.append((request.method, path, str(request.url.query)))
        raw = self.raw
        if request.method != "GET":
            return httpx2.Response(
                405, json={"type": "error", "error": {"type": "x", "message": "m"}}
            )
        base = f"/v1/sessions/{raw.session_id}"
        if path == base:
            return httpx2.Response(200, json=raw.session)
        if path == f"{base}/threads":
            return httpx2.Response(200, json={"data": raw.threads, "next_page": None})
        if path == f"{base}/events":
            page = request.url.params.get("page")
            half = len(raw.session_events) // 2
            if page is None:
                return httpx2.Response(
                    200, json={"data": raw.session_events[:half], "next_page": "page2"}
                )
            return httpx2.Response(200, json={"data": raw.session_events[half:], "next_page": None})
        match = re.fullmatch(rf"{re.escape(base)}/threads/([^/]+)/events", path)
        if match:
            return httpx2.Response(
                200, json={"data": raw.thread_events.get(match.group(1), []), "next_page": None}
            )
        return httpx2.Response(
            404, json={"type": "error", "error": {"type": "not_found_error", "message": "nf"}}
        )


def live_source(api: FakeApi) -> sr.LiveSource:
    import anthropic

    sdk = anthropic.AsyncAnthropic(
        api_key="sk-ant-test-not-a-key",
        base_url=CLOSED_PORT_URL,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handler)),
    )
    return sr.LiveSource(sdk)


def test_live_source_reads_everything_with_get_requests_only() -> None:
    raw = make_raw()
    api = FakeApi(raw)
    fetched = asyncio.run(live_source(api).fetch(SESSION))
    assert {c[0] for c in api.calls} == {"GET"}
    paths = [c[1] for c in api.calls]
    assert f"/v1/sessions/{SESSION}/threads/{CHILD}/events" in paths
    assert f"/v1/sessions/{SESSION}/threads/{PRIMARY}/events" in paths
    assert len(fetched.session_events) == len(raw.session_events)
    assert fetched.thread_events[CHILD] == raw.thread_events[CHILD]
    assert fetched.warnings == []
    report = sr.analyse(fetched)
    assert thread(report, "flights").max_context == 10480


def test_a_thread_that_cannot_be_listed_is_a_warning_not_a_failure() -> None:
    raw = make_raw()
    api = FakeApi(raw)
    del raw.thread_events[CHILD]
    original = api.handler

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith(f"{CHILD}/events"):
            return httpx2.Response(
                404, json={"type": "error", "error": {"type": "not_found_error", "message": "gone"}}
            )
        return original(request)

    import anthropic

    sdk = anthropic.AsyncAnthropic(
        api_key="sk-ant-test-not-a-key",
        base_url=CLOSED_PORT_URL,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    fetched = asyncio.run(sr.LiveSource(sdk).fetch(SESSION))
    assert any(CHILD in w for w in fetched.warnings)
    assert CHILD not in fetched.thread_events


# --- the command line -------------------------------------------------------------------------


def run_main(*args: str, source: Any = None) -> tuple[int, str]:
    lines: list[str] = []
    code = sr.main(list(args), source=source, out=lines.append, generated_at=T0)
    return code, "\n".join(lines)


class StubSource:
    def __init__(self, raw: sr.RawSession) -> None:
        self.raw = raw
        self.fetched: list[str] = []

    async def fetch(self, session_id: str) -> sr.RawSession:
        self.fetched.append(session_id)
        return self.raw


def test_main_writes_the_file_and_prints_the_same_report(tmp_path: Path) -> None:
    out_file = tmp_path / "r.md"
    summary = tmp_path / "s.md"
    stub = StubSource(make_raw())
    code, printed = run_main(
        "--session", SESSION, "--out", str(out_file), "--summary-out", str(summary), source=stub
    )
    assert code == 0
    assert stub.fetched == [SESSION]
    assert printed == out_file.read_text(encoding="utf-8")
    assert summary.read_text(encoding="utf-8") == printed
    assert "Generated 2026-10-12 09:00 UTC" in printed


def test_main_accepts_several_ids_in_any_form(tmp_path: Path) -> None:
    stub = StubSource(make_raw())
    code, _ = run_main(
        "--session",
        "sesn_a,sesn_b",
        "sesn_c",
        "--session",
        "sesn_a",
        "--out",
        str(tmp_path / "r.md"),
        "--no-stdout",
        source=stub,
    )
    assert code == 0
    assert stub.fetched == ["sesn_a", "sesn_b", "sesn_c"]


def test_main_save_raw_then_from_raw_round_trips(tmp_path: Path) -> None:
    stub = StubSource(make_raw())
    raw_dir = tmp_path / "raw"
    run_main(
        "--session",
        SESSION,
        "--save-raw",
        str(raw_dir),
        "--out",
        str(tmp_path / "a.md"),
        "--no-stdout",
        source=stub,
    )
    code, printed = run_main(
        "--session",
        SESSION,
        "--from-raw",
        str(raw_dir),
        "--no-history",
        "--out",
        str(tmp_path / "b.md"),
    )
    assert code == 0
    assert "### Token timeline per thread" in printed
    assert "### Event history" not in printed


def test_main_combines_static_and_sessions(tmp_path: Path) -> None:
    code, printed = run_main(
        "--static",
        "--session",
        SESSION,
        "--out",
        str(tmp_path / "r.md"),
        source=StubSource(make_raw()),
    )
    assert code == 0
    assert printed.index("## Static estimate") < printed.index("## Session `")


def test_main_reports_a_failed_fetch_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Failing:
        async def fetch(self, session_id: str) -> sr.RawSession:
            raise RuntimeError("boom sk-ant-api03-SHOULDNOTSHOW")

    code, _ = run_main("--session", SESSION, "--out", str(tmp_path / "r.md"), source=Failing())
    assert code == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "SHOULDNOTSHOW" not in err


@pytest.mark.parametrize(
    "args",
    [[], ["--session", "not-an-id"], ["--session", "sesn_a", "--top", "0"]],
)
def test_main_rejects_bad_arguments(args: list[str]) -> None:
    with pytest.raises(SystemExit) as info:
        run_main(*args)
    assert info.value.code == 2
