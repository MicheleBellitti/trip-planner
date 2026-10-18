"""scripts/probe_session.py, offline only: argument parsing, the dry run (no network), the
guards, and the report plumbing on the two probes that create no session (P1, P2) against the
in-memory API. The live probes themselves are never run here."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any, cast

import probe_session as ps
import pytest
from scripts_testlib import REPO_ROOT, FakeAnthropicApi


def run(*args: str, client: Any = None) -> tuple[int, str]:
    lines: list[str] = []
    code = ps.main(list(args), client=client, out=lines.append)
    return code, "\n".join(lines)


@pytest.fixture
def no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import anthropic

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("no client may be built here")

    monkeypatch.setattr(anthropic, "Anthropic", refuse)


def test_every_probe_of_the_checklist_is_implemented() -> None:
    assert tuple(f"P{n}" for n in range(1, 15)) == ps.PROBE_IDS
    notes = (REPO_ROOT / "docs" / "managed-agents-notes.md").read_text(encoding="utf-8")
    for probe_id in ps.PROBE_IDS:
        assert f"| {probe_id} |" in notes


def test_only_parses_and_adds_dependencies() -> None:
    assert ps.parse_only("p1, P4") == ["P1", "P4"]
    assert ps.parse_only("P7") == ["P6", "P7"]
    assert ps.parse_only("P13") == ["P8", "P13"]
    assert ps.parse_only(None) == list(ps.PROBE_IDS)
    assert ps.parse_only("P14") == ["P14"]
    with pytest.raises(argparse.ArgumentTypeError):
        ps.parse_only("P15")


def test_parse_args_defaults_and_limits() -> None:
    args = ps.parse_args([])
    assert args.only == list(ps.PROBE_IDS)
    assert args.max_total_cents == ps.DEFAULT_MAX_TOTAL_CENTS
    assert not args.yes
    assert not args.dry_run
    assert args.report_dir == REPO_ROOT / "docs" / "probes"
    with pytest.raises(SystemExit):
        ps.parse_args(["--max-total-cents", "0"])
    with pytest.raises(SystemExit):
        ps.parse_args(["--only", "P99"])
    with pytest.raises(SystemExit):
        ps.parse_args(["--profile", "production"])  # development only: there is no such option


def test_inputs_come_from_the_development_profile() -> None:
    inputs = ps.load_inputs(REPO_ROOT)
    assert inputs.session_budget_cents == 100
    assert inputs.cheap_model == "claude-haiku-5-5"
    assert inputs.models["coordinator"] == "claude-sonnet-5-5"
    assert {s["name"] for s in inputs.flights["mcp_servers"]} == {"expedia", "kiwi", "lastminute"}
    assert "$ref" not in str(inputs.submit_plan_tool)
    assert "$defs" in inputs.raw_plan_schema
    assert inputs.environment["config"]["networking"] == {"type": "unrestricted"}


def test_dry_run_prints_the_plan_without_network(no_client: None, tmp_path: Path) -> None:
    code, out = run("--dry-run", "--report-dir", str(tmp_path))
    assert code == 0
    assert "no network" in out
    for probe_id in ps.PROBE_IDS:
        assert f"  {probe_id} " in out
    assert "each capped at 100 US cents" in out
    assert not any(tmp_path.iterdir())


def test_dry_run_of_p14_alone_stays_under_a_dollar(no_client: None, tmp_path: Path) -> None:
    code, out = run("--dry-run", "--only", "P14", "--report-dir", str(tmp_path))
    assert code == 0
    assert "  P14  Custom tool wait" in out
    assert "  P14: ask_traveller (custom) left unanswered 240 s" in out
    assert "each capped at 100 US cents (P14: 25)" in out
    assert "worst case about 50 cents" in out
    assert not any(tmp_path.iterdir())


def test_p14_message_delegates_before_the_custom_tool() -> None:
    text = ps.p14_message("probe-20261018120000-p14-worker")
    assert text.index("Delegate") < text.index("call ask_traveller")
    assert "without waiting for its report" in text
    assert f"{ps.P14_SLEEPS} times" in text
    assert ps.P14_TOOL["name"] == "ask_traveller"
    assert ps.P14_TOOL["type"] == "custom"


def test_without_yes_nothing_runs(no_client: None, tmp_path: Path) -> None:
    code, out = run("--only", "P4", "--report-dir", str(tmp_path))
    assert code == 2
    assert "--yes" in out
    assert not any(tmp_path.iterdir())


def test_refuses_ci_and_a_missing_key(
    no_client: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CI", "true")
    code, out = run("--yes", "--report-dir", str(tmp_path))
    assert code == 2
    assert "CI" in out
    monkeypatch.delenv("CI")
    code, out = run("--yes", "--report-dir", str(tmp_path))
    assert code == 2
    assert "ANTHROPIC_API_KEY" in out
    assert "ANTHROPIC_FEDERATION_RULE_ID" in out  # both options are named
    assert not any(tmp_path.iterdir())


def test_credentials_are_a_key_or_the_whole_federation_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not ps.has_anthropic_credentials()
    monkeypatch.setenv("ANTHROPIC_FEDERATION_RULE_ID", "fdrl_test")
    monkeypatch.setenv("ANTHROPIC_ORGANIZATION_ID", "org-test")
    assert not ps.has_anthropic_credentials()  # no identity token yet
    monkeypatch.setenv("ANTHROPIC_IDENTITY_TOKEN_FILE", "/nonexistent/token")
    assert ps.has_anthropic_credentials()
    monkeypatch.delenv("ANTHROPIC_FEDERATION_RULE_ID")
    assert not ps.has_anthropic_credentials()  # incomplete
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert ps.has_anthropic_credentials()


def test_auth_mode_prefers_the_key_like_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ps.anthropic_auth_mode() is None
    monkeypatch.setenv("ANTHROPIC_FEDERATION_RULE_ID", "fdrl_test")
    monkeypatch.setenv("ANTHROPIC_ORGANIZATION_ID", "org-test")
    monkeypatch.setenv("ANTHROPIC_IDENTITY_TOKEN_FILE", "/nonexistent/token")
    assert ps.anthropic_auth_mode() == "federation"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")  # a blank key is no key
    assert ps.anthropic_auth_mode() == "federation"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert ps.anthropic_auth_mode() == "api-key"  # a static key wins over federation


def test_p1_and_p2_against_the_fake_api_write_a_report(
    tmp_path: Path, fake_api: FakeAnthropicApi
) -> None:
    sse_log = tmp_path / "sse.log"
    code, out = run(
        "--yes",
        "--only",
        "P1,P2",
        "--report-dir",
        str(tmp_path / "probes"),
        "--sse-log",
        str(sse_log),
        client=fake_api.client(),
    )
    reports = list((tmp_path / "probes").glob("*.md"))
    assert len(reports) == 1, out
    report = reports[0].read_text(encoding="utf-8")
    assert code == 0, report
    assert "| P1 | Environment shape | done |" in report
    assert "same name again: 409" in report
    assert "raw ($defs and $ref): accepted; echoed input_schema identical" in report
    assert "inlined (deployed): accepted; echoed input_schema identical" in report
    assert "Sessions' total list cost: 0 US cents" in report
    assert "## Cleanup" in report
    assert "FAILED" not in report
    assert fake_api.environments == {}  # deleted
    assert all(agent["archived_at"] for agent in fake_api.agents.values())  # archived
    assert all(agent["name"].startswith("probe-") for agent in fake_api.agents.values())


def test_report_path_never_overwrites(tmp_path: Path) -> None:
    day = dt.date(2026, 10, 13)
    first = ps.report_path(tmp_path, day)
    assert first.name == "2026-10-13.md"
    first.write_text("x")
    assert ps.report_path(tmp_path, day).name == "2026-10-13-2.md"


def test_event_helpers() -> None:
    idle = {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}}
    waiting = {
        "type": "session.status_idle",
        "stop_reason": {"type": "requires_action", "event_ids": ["x"]},
    }
    assert ps.is_final_idle(idle)
    assert not ps.is_final_idle(waiting)
    assert ps.usage_cents({"usage": {"list_cost": {"amount": "42", "currency": "USD"}}}) == 42
    assert ps.usage_cents({"usage": {}}) == 0
    assert ps.hosts_in(
        {"content": [{"text": "book at https://www.kiwi.com/x?y=1 or https://Lastminute.com/a"}]}
    ) == {
        "www.kiwi.com",
        "lastminute.com",
    }
    assert ps.json_diff({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 3], "c": 0}) == ["/b[1] changed"]


def test_p14_helpers() -> None:
    origin = ps.parse_time("2026-10-18T10:00:00Z")
    assert origin == dt.datetime(2026, 10, 18, 10, tzinfo=dt.UTC)
    assert ps.parse_time("2026-10-18T10:04:05.123456789Z") == dt.datetime(
        2026, 10, 18, 10, 4, 5, 123456, tzinfo=dt.UTC
    )
    assert ps.parse_time("2026-10-18T10:00:00") is None  # naive: not a server timestamp
    assert ps.parse_time(None) is None
    assert ps.since("2026-10-18T10:04:05Z", origin) == "+245s"
    assert ps.since("2026-10-18T09:59:58Z", origin) == "-2s"
    assert ps.since("garbage", origin) == "?"
    assert (
        ps.label(
            {
                "type": "session.thread_status_idle",
                "agent_name": "probe-20261018120000-p14-worker",
                "stop_reason": {"type": "end_turn"},
            }
        )
        == "session.thread_status_idle[p14-worker]:end_turn"
    )
    assert ps.label({"type": "user.custom_tool_result", "is_error": True}) == (
        "user.custom_tool_result:is_error"
    )
    before = ps.cache_counts(
        {
            "input_tokens": 10,
            "cache_read_input_tokens": 100,
            "cache_creation": {"ephemeral_5m_input_tokens": 50, "ephemeral_1h_input_tokens": None},
        }
    )
    after = ps.cache_counts(
        {
            "input_tokens": 12,
            "cache_read_input_tokens": 900,
            "cache_creation": {"ephemeral_5m_input_tokens": 80},
        }
    )
    assert ps.counts_delta(before, after) == {
        "input": 2,
        "cache_read": 800,
        "cache_write": 0,
        "write_5m": 30,
        "write_1h": 0,
        "output": 0,
    }
    span = ps.cache_counts({"cache_creation_input_tokens": 7, "cache_read_input_tokens": 3})
    assert (span["cache_write"], span["cache_read"]) == (7, 3)


def test_cache_after_wait_places_requests_by_their_start() -> None:
    """The 2026-10-18 run: the request that makes the custom tool call ends after the
    `agent.custom_tool_use` event, so it must still count as the request before the wait."""

    def span(kind: str, ident: str, at: str, **extra: Any) -> dict[str, Any]:
        return {"type": f"span.model_request_{kind}", "id": ident, "processed_at": at, **extra}

    history = [
        span("start", "s1", "2026-10-18T17:00:55.899690Z"),
        {
            "type": "agent.custom_tool_use",
            "id": "ask",
            "processed_at": "2026-10-18T17:00:57.046615Z",
        },
        span(
            "end",
            "e1",
            "2026-10-18T17:00:57.046616Z",
            model_request_start_id="s1",
            model_usage={"input_tokens": 4, "cache_creation_input_tokens": 6061},
        ),
        span("start", "w1", "2026-10-18T17:01:00Z", session_thread_id="sthr_worker"),
        {"type": "user.custom_tool_result", "processed_at": "2026-10-18T17:04:58.549621Z"},
        span("start", "s2", "2026-10-18T17:04:58.726929Z"),
        span(
            "end",
            "e2",
            "2026-10-18T17:04:59.579522Z",
            model_request_start_id="s2",
            model_usage={
                "input_tokens": 2,
                "cache_read_input_tokens": 6061,
                "cache_creation_input_tokens": 378,
            },
        ),
    ]
    assert [start for start, _ in ps.primary_requests(history)] == [
        ps.parse_time("2026-10-18T17:00:55.899690Z"),
        ps.parse_time("2026-10-18T17:04:58.726929Z"),
    ]
    found = ps.cache_after_wait(
        history,
        ps.parse_time("2026-10-18T17:00:57.046615Z"),
        ps.parse_time("2026-10-18T17:04:58.549621Z"),
    )
    assert found is not None
    detail, verdict = found
    assert "(prompt 6065)" in detail
    assert "start-to-start gap 243 s" in detail
    assert verdict.endswith("read 6061 of the earlier 6065-token prompt from the cache: WARM")
    assert ps.cache_after_wait(history, None, None) is None


def test_error_detail_keeps_the_api_message_only() -> None:
    rejected = ValueError("ignored")
    rejected.status_code = 400  # type: ignore[attr-defined]
    rejected.body = {"error": {"type": "invalid_request_error", "message": "x" * 300}}  # type: ignore[attr-defined]

    assert ps.error_detail(rejected) == "400 invalid_request_error: " + "x" * 200
    assert ps.error_detail(ValueError("no body")) == "ValueError"


def test_session_recorder_waits_for_recorded_events() -> None:
    recorder = ps.SessionRecorder(cast(Any, None), "sesn_test")
    recorder.events += [{"type": "a"}, {"type": "b"}, {"type": "a"}]
    assert recorder.wait_for(lambda e: e["type"] == "a", timeout=0) == (0, {"type": "a"})
    assert recorder.wait_for(lambda e: e["type"] == "a", after=1, timeout=0) == (2, {"type": "a"})
    assert recorder.wait_for(lambda e: e["type"] == "c", timeout=0.05) is None


def test_p5_step_4_fetches_a_url_only_the_model_builds() -> None:
    """Step 4 tests web_fetch's URL-source rule: the prompt must never show the URL or its host
    (a URL in a user message is fetchable), and the host must pass the `limited` host filter so
    that only the URL-source rule can refuse it."""
    assert ps.P5_MODEL_BUILT_HOST not in ps.P5_PROMPT
    assert ps.P5_MODEL_BUILT_HOST in ps.LIMITED_HOSTS
    assert "build its API URL yourself" in ps.P5_PROMPT
