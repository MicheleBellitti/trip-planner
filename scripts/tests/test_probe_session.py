"""scripts/probe_session.py, offline only: argument parsing, the dry run (no network), the
guards, and the report plumbing on the two probes that create no session (P1, P2) against the
in-memory API. The live probes themselves are never run here."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

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
    assert tuple(f"P{n}" for n in range(1, 14)) == ps.PROBE_IDS
    notes = (REPO_ROOT / "docs" / "managed-agents-notes.md").read_text(encoding="utf-8")
    for probe_id in ps.PROBE_IDS:
        assert f"| {probe_id} |" in notes


def test_only_parses_and_adds_dependencies() -> None:
    assert ps.parse_only("p1, P4") == ["P1", "P4"]
    assert ps.parse_only("P7") == ["P6", "P7"]
    assert ps.parse_only("P13") == ["P8", "P13"]
    assert ps.parse_only(None) == list(ps.PROBE_IDS)
    with pytest.raises(argparse.ArgumentTypeError):
        ps.parse_only("P14")


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


def test_p5_step_4_fetches_a_url_only_the_model_builds() -> None:
    """Step 4 tests web_fetch's URL-source rule: the prompt must never show the URL or its host
    (a URL in a user message is fetchable), and the host must pass the `limited` host filter so
    that only the URL-source rule can refuse it."""
    assert ps.P5_MODEL_BUILT_HOST not in ps.P5_PROMPT
    assert ps.P5_MODEL_BUILT_HOST in ps.LIMITED_HOSTS
    assert "build its API URL yourself" in ps.P5_PROMPT
