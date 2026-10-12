"""evals/compare.py: the three blocking rules, rule 1 blocking even without a baseline (judge
and cost report-only), Markdown, explicit baseline updates, exit codes and the coordinator
decision."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import compare
import judge

Json = dict[str, Any]

PASSING_CHECKS = [
    {"name": "schema_valid", "status": "pass", "blocking": True, "message": "ok", "details": []},
    {
        "name": "cost_and_searches_vs_estimate",
        "status": "warn",
        "blocking": False,
        "message": "cost above",
        "details": [],
    },
]


def entry(request_id: str, *, cost: int | None = 40, score: int = 4, **scores: int) -> Json:
    return {
        "id": request_id,
        "status": "ready",
        "checks": copy.deepcopy(PASSING_CHECKS),
        "checks_passed": True,
        "warnings_count": 1,
        "submit_attempts": 1,
        "cost_cents": cost,
        "web_search_requests": 10,
        "judge": {
            "status": "ok",
            "scores": {
                c: {"score": scores.get(c, score), "reason": "fine"} for c in judge.CRITERIA
            },
        },
    }


def results(*entries: Json, profile: str = "development", **extra: Any) -> Json:
    return {
        "kind": compare.RESULTS_KIND,
        "format": 1,
        "date": "2026-10-13",
        "git_sha": "1a2b3c4d5e6f7a8b",
        "profile": profile,
        "aborted": False,
        "judge": {"model": "claude-sonnet-5-5"},
        "requests": list(entries),
        **extra,
    }


IDS = ("a", "b", "c", "d", "e")


def base_run() -> Json:
    return results(*(entry(i) for i in IDS))


def baseline() -> Json:
    return compare.baseline_from_results(base_run(), source="evals/results/base.json")


def blocking_rules(comparison: compare.Comparison) -> set[str]:
    return {finding.rule for finding in comparison.blocking_findings()}


# --- rules --------------------------------------------------------------------------------------


def test_identical_run_passes() -> None:
    comparison = compare.compare(base_run(), baseline())
    assert not comparison.blocked
    assert comparison.findings == []
    assert comparison.cost is not None
    assert comparison.cost.change == pytest.approx(0)


def test_a_failing_deterministic_check_blocks() -> None:
    run = base_run()
    run["requests"][2]["checks"][0].update(status="fail", message="summary empty")
    comparison = compare.compare(run, baseline())
    assert comparison.blocked
    assert blocking_rules(comparison) == {compare.RULE_CHECKS}
    [finding] = comparison.blocking_findings()
    assert finding.request_id == "c"
    assert "schema_valid fail" in finding.message


def test_a_check_error_blocks_but_a_non_blocking_warning_does_not() -> None:
    run = base_run()
    run["requests"][0]["checks"][0]["status"] = "error"
    assert compare.compare(run, baseline()).blocked
    run = base_run()
    run["requests"][0]["checks"][1]["status"] = "fail"  # cost check: blocking False
    assert not compare.compare(run, baseline()).blocked


def test_deterministic_failures_block_even_for_requests_not_in_the_baseline() -> None:
    new = entry("new-case")
    new["checks"][0]["status"] = "fail"
    comparison = compare.compare(results(*base_run()["requests"], new), baseline())
    assert comparison.blocked
    assert any("not in the baseline" in note for note in comparison.notes)


def test_aborted_or_empty_run_blocks() -> None:
    assert compare.compare(results(*base_run()["requests"], aborted=True), baseline()).blocked
    assert compare.compare(results(), baseline()).blocked


@pytest.mark.parametrize(("values", "blocked"), [((4, 4, 4, 3, 3), False), ((4, 4, 3, 3, 3), True)])
def test_judge_mean_drop_over_half_a_point_blocks(values: tuple[int, ...], blocked: bool) -> None:
    """Baseline mean 4.0: 3.6 is a drop of 0.4 (passes), 3.4 a drop of 0.6 (blocks)."""
    run = base_run()
    for item, value in zip(run["requests"], values, strict=True):
        item["judge"]["scores"]["preference_respect"]["score"] = value
    comparison = compare.compare(run, baseline())
    assert comparison.blocked is blocked
    if blocked:
        assert blocking_rules(comparison) == {compare.RULE_JUDGE}


def test_judge_drop_of_exactly_half_a_point_passes() -> None:
    run = results(entry("a"), entry("b"))
    base = compare.baseline_from_results(results(entry("a", score=4), entry("b", score=4)))
    run["requests"][0]["judge"]["scores"]["summary_clarity"]["score"] = 3  # mean 3.5: -0.5
    assert not compare.compare(run, base).blocked
    run["requests"][1]["judge"]["scores"]["summary_clarity"]["score"] = 3  # mean 3.0: -1.0
    comparison = compare.compare(run, base)
    assert comparison.blocked
    assert blocking_rules(comparison) == {compare.RULE_JUDGE}
    assert "Summary" in comparison.blocking_findings()[0].message


def test_judge_improvement_never_blocks() -> None:
    run = results(*(entry(i, score=5) for i in IDS))
    assert not compare.compare(run, baseline()).blocked


def test_missing_judge_score_blocks() -> None:
    run = base_run()
    run["requests"][1]["judge"] = {"status": "skipped", "error": "judge cap", "scores": None}
    comparison = compare.compare(run, baseline())
    assert comparison.blocked
    assert blocking_rules(comparison) == {compare.RULE_JUDGE}
    assert all(f.request_id == "b" for f in comparison.blocking_findings())


@pytest.mark.parametrize(("cost", "blocked"), [(52, False), (53, True)])
def test_mean_cost_rising_over_30_percent_blocks(cost: int, blocked: bool) -> None:
    """Baseline 40 cents per plan: 52 is +30% exactly (passes), 53 is +32.5%."""
    run = results(*(entry(i, cost=cost) for i in IDS))
    comparison = compare.compare(run, baseline())
    assert comparison.blocked is blocked
    if blocked:
        assert blocking_rules(comparison) == {compare.RULE_COST}


def test_missing_cost_blocks() -> None:
    run = base_run()
    run["requests"][0]["cost_cents"] = None
    comparison = compare.compare(run, baseline())
    assert blocking_rules(comparison) == {compare.RULE_COST}


def test_filtered_run_compares_only_its_requests() -> None:
    run = results(entry("a", cost=41), entry("b", cost=41))
    comparison = compare.compare(run, baseline())
    assert not comparison.blocked
    assert comparison.cost is not None
    assert comparison.cost.compared == 2
    assert any("in the baseline but not run: c, d, e" in note for note in comparison.notes)


# --- report-only, markdown, exit codes ----------------------------------------------------------


def write(path: Path, document: Json) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_missing_baseline_is_report_only_with_instructions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """All checks pass, no baseline: judge and cost are report-only, the run passes."""
    results_file = write(tmp_path / "run.json", base_run())
    markdown = tmp_path / "comment.md"
    code = compare.main(
        [str(results_file), "--baseline", str(tmp_path / "none.json"), "--markdown", str(markdown)]
    )
    assert code == compare.EXIT_PASS
    report = markdown.read_text(encoding="utf-8")
    assert report.startswith("## Trip planner evals: PASSED (no baseline")
    assert "REPORT ONLY" in report
    assert "every one passed" in report
    assert "--update-baseline" in report
    assert "| Judge (mean drop at most 0.5) | not compared |" in report
    assert report in capsys.readouterr().out


@pytest.mark.parametrize("status", ["fail", "error"])
def test_a_failing_check_blocks_without_a_baseline(tmp_path: Path, status: str) -> None:
    """Rule 1 needs no baseline: a broken contract never passes the gate, baseline or not."""
    run = base_run()
    run["requests"][0]["checks"][0].update(status=status, message="book_by after scheduled_for")
    comparison = compare.compare(run, None)
    assert comparison.report_only
    assert comparison.blocked
    assert blocking_rules(comparison) == {compare.RULE_CHECKS}
    results_file = write(tmp_path / "run.json", run)
    markdown = tmp_path / "comment.md"
    code = compare.main(
        [str(results_file), "--baseline", str(tmp_path / "none.json"), "--markdown", str(markdown)]
    )
    assert code == compare.EXIT_BLOCKED
    report = markdown.read_text(encoding="utf-8")
    assert report.startswith("## Trip planner evals: BLOCKED (no baseline")
    assert "| Deterministic checks | 1 failing |" in report
    assert "### Blocking findings" in report
    assert "`a` deterministic checks: schema_valid" in report
    assert "--update-baseline" not in report  # it would refuse this run anyway


def test_an_aborted_or_empty_run_blocks_without_a_baseline() -> None:
    assert compare.compare(results(*base_run()["requests"], aborted=True), None).blocked
    assert compare.compare(results(), None).blocked


def test_a_non_blocking_warning_passes_without_a_baseline() -> None:
    run = base_run()
    run["requests"][0]["checks"][1]["status"] = "fail"  # cost check: blocking False
    comparison = compare.compare(run, None)
    assert comparison.report_only
    assert not comparison.blocked


def test_exit_codes(tmp_path: Path) -> None:
    baseline_file = write(tmp_path / "baseline.json", baseline())
    ok = write(tmp_path / "ok.json", base_run())
    assert compare.main([str(ok), "--baseline", str(baseline_file)]) == compare.EXIT_PASS
    bad_run = results(*(entry(i, cost=80) for i in IDS))
    bad = write(tmp_path / "bad.json", bad_run)
    assert compare.main([str(bad), "--baseline", str(baseline_file)]) == compare.EXIT_BLOCKED
    assert compare.main([str(tmp_path / "missing.json")]) == compare.EXIT_USAGE
    not_results = write(tmp_path / "other.json", {"kind": "something"})
    assert compare.main([str(not_results), "--baseline", str(baseline_file)]) == compare.EXIT_USAGE


def test_profile_mismatch_is_a_usage_error_unless_allowed(tmp_path: Path) -> None:
    baseline_file = write(tmp_path / "baseline.json", baseline())
    production = write(
        tmp_path / "prod.json", results(*(entry(i) for i in IDS), profile="production")
    )
    assert compare.main([str(production), "--baseline", str(baseline_file)]) == compare.EXIT_USAGE
    assert (
        compare.main(
            [str(production), "--baseline", str(baseline_file), "--allow-profile-mismatch"]
        )
        == compare.EXIT_PASS
    )


def test_markdown_report(tmp_path: Path) -> None:
    run = results(*(entry(i, cost=60) for i in IDS))
    run["requests"][0]["judge"]["scores"]["time_coherence"]["score"] = 2
    comparison = compare.compare(
        run, baseline(), results_name="evals/results/x.json", baseline_name="evals/baseline.json"
    )
    report = compare.render_markdown(comparison)
    assert report.startswith("## Trip planner evals: BLOCKED")
    assert "| Mean cost per plan (at most +30%) | blocking: 60.0¢ vs 40.0¢ (+50%) |" in report
    assert "| Time coherence | 4.00 | 3.60 | -0.40 | 5 |" in report
    assert "| `a` | ready | – | 1 | 60¢ (40¢) | 10 | 2 (4) | 4 | 4 | 4 | 4 |" in report
    assert "### Blocking findings" in report


def test_baseline_file_accepts_a_results_file(tmp_path: Path) -> None:
    base_file = write(tmp_path / "older-run.json", base_run())
    run_file = write(tmp_path / "run.json", base_run())
    assert compare.main([str(run_file), "--baseline", str(base_file)]) == compare.EXIT_PASS


# --- baseline updates ---------------------------------------------------------------------------


def test_baseline_is_never_written_without_the_flag(tmp_path: Path) -> None:
    baseline_file = tmp_path / "baseline.json"
    run_file = write(tmp_path / "run.json", base_run())
    compare.main([str(run_file), "--baseline", str(baseline_file)])
    assert not baseline_file.exists()
    write(baseline_file, baseline())
    before = baseline_file.read_text(encoding="utf-8")
    better = write(tmp_path / "better.json", results(*(entry(i, cost=20, score=5) for i in IDS)))
    compare.main([str(better), "--baseline", str(baseline_file)])
    assert baseline_file.read_text(encoding="utf-8") == before


def test_update_baseline_writes_and_merges(tmp_path: Path) -> None:
    baseline_file = write(tmp_path / "baseline.json", baseline())
    run_file = write(tmp_path / "run.json", results(entry("a", cost=30, score=5)))
    code = compare.main([str(run_file), "--baseline", str(baseline_file), "--update-baseline"])
    assert code == compare.EXIT_PASS
    written = json.loads(baseline_file.read_text(encoding="utf-8"))
    assert written["kind"] == compare.BASELINE_KIND
    assert written["profile"] == "development"
    assert set(written["requests"]) == set(IDS)  # b-e kept from the previous baseline
    assert written["requests"]["a"]["cost_cents"] == 30
    assert written["requests"]["a"]["judge"]["time_coherence"] == 5
    assert written["requests"]["b"]["cost_cents"] == 40
    assert written["source"]["git_sha"] == "1a2b3c4d5e6f7a8b"


def test_update_baseline_refuses_failing_runs_unless_forced(tmp_path: Path) -> None:
    run = base_run()
    run["requests"][0]["checks"][0]["status"] = "fail"
    run_file = write(tmp_path / "run.json", run)
    baseline_file = tmp_path / "baseline.json"
    args = [str(run_file), "--baseline", str(baseline_file), "--update-baseline"]
    assert compare.main(args) == compare.EXIT_USAGE
    assert not baseline_file.exists()
    assert compare.main([*args, "--force"]) == compare.EXIT_PASS
    assert json.loads(baseline_file.read_text(encoding="utf-8"))["requests"]["a"]["valid"] is False


def test_update_baseline_refuses_another_profile(tmp_path: Path) -> None:
    baseline_file = write(tmp_path / "baseline.json", baseline())
    run_file = write(tmp_path / "run.json", results(*(entry(i) for i in IDS), profile="production"))
    args = [str(run_file), "--baseline", str(baseline_file), "--update-baseline"]
    assert compare.main(args) == compare.EXIT_USAGE
    assert json.loads(baseline_file.read_text(encoding="utf-8"))["profile"] == "development"


# --- coordinator decision -----------------------------------------------------------------------


def test_coordinator_switches_to_sonnet_with_as_many_valid_plans_and_warnings() -> None:
    opus = results(*(entry(i, cost=250) for i in IDS), profile="production")
    sonnet = results(*(entry(i, cost=150, score=3) for i in IDS), profile="production")
    decision = compare.decide_coordinator(opus, sonnet)
    assert decision.switch_to_sonnet
    assert decision.opus_valid == decision.sonnet_valid == 5
    assert decision.sonnet_cost == pytest.approx(150)
    report = compare.render_decision(decision)
    assert "switch the production coordinator to Sonnet 5.5" in report


def test_coordinator_stays_opus_with_fewer_valid_plans_or_more_warnings() -> None:
    opus = results(*(entry(i) for i in IDS), profile="production")
    fewer = copy.deepcopy(opus)
    fewer["requests"][0]["checks"][0]["status"] = "fail"
    assert not compare.decide_coordinator(opus, fewer).switch_to_sonnet
    noisier = copy.deepcopy(opus)
    noisier["requests"][0]["warnings_count"] = 3
    assert not compare.decide_coordinator(opus, noisier).switch_to_sonnet


def test_decide_coordinator_command(tmp_path: Path) -> None:
    opus = write(tmp_path / "opus.json", results(*(entry(i) for i in IDS), profile="production"))
    sonnet = write(
        tmp_path / "sonnet.json", results(*(entry(i) for i in IDS), profile="production")
    )
    markdown = tmp_path / "decision.md"
    code = compare.main(
        [str(sonnet), "--baseline", str(opus), "--decide-coordinator", "--markdown", str(markdown)]
    )
    assert code == compare.EXIT_PASS
    assert "Coordinator comparison" in markdown.read_text(encoding="utf-8")
