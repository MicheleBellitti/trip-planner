"""Compare an eval run with the baseline and decide whether the change may merge.

    cd backend
    uv run python ../evals/compare.py ../evals/results/2026-10-13-1a2b3c4d5e6f.json
    uv run python ../evals/compare.py RESULTS --markdown comment.md   # PR comment
    uv run python ../evals/compare.py RESULTS --update-baseline       # only when asked
    uv run python ../evals/compare.py SONNET_RESULTS --baseline OPUS_RESULTS --decide-coordinator

Spec ("Eval strutturate e versioning dei prompt"), evals/compare.py against
evals/baseline.json:

1. a deterministic check that fails blocks (any blocking check in `fail` or `error`, see
   evals/checks.py; an aborted or empty run blocks too);
2. a judge criterion whose mean drops by more than 0.5 blocks;
3. a mean cost per plan that rises by more than 30% blocks;
4. the baseline changes only through an explicit commit, never by itself: `--update-baseline`
   writes evals/baseline.json and nothing else; committing it is a separate, deliberate step.

Rules 2 and 3 compare the requests present in both files (a run filtered with `--tags` is
compared on its own requests). A request scored or costed in the baseline but not in the run
blocks, because the regression can't be ruled out. Rule 1 needs no baseline, so it always
blocks. Without a baseline, rules 2 and 3 are report-only (nothing to compare with) and the
report says how to create one.

`--baseline` also accepts a results file, which `--decide-coordinator` uses for the spec's
decision 3: the baseline is the run with the Opus 5.5 coordinator, the results the run with a
Sonnet 5.5 coordinator; with as many valid plans and no more warnings, production switches to
Sonnet 5.5 (procedure in evals/README.md).

Exit codes: 0 passed (with or without a baseline), baseline written or coordinator report;
1 blocked (with or without a baseline); 2 usage error (unreadable file, profile mismatch without
`--allow-profile-mismatch`, refused update).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

EVALS_DIR = Path(__file__).resolve().parent
if str(EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(EVALS_DIR))

from judge import CRITERIA  # noqa: E402

BASELINE_PATH = EVALS_DIR / "baseline.json"

RESULTS_KIND = "trip-planner-eval-results"
BASELINE_KIND = "trip-planner-eval-baseline"
BASELINE_FORMAT = 1

CRITERION_LABELS: Mapping[str, str] = {
    "time_coherence": "Time coherence",
    "realistic_transfers": "Realistic transfers",
    "preference_respect": "Preferences",
    "alternatives_quality": "Alternatives",
    "summary_clarity": "Summary",
}

MAX_JUDGE_DROP = 0.5
"""Spec: "un voto medio del giudice che scende di oltre 0,5 su un criterio blocca"."""
MAX_COST_INCREASE = 0.30
"""Spec: "un costo medio per piano che sale di oltre il 30% blocca"."""
EPSILON = 1e-9

EXIT_PASS = 0
EXIT_BLOCKED = 1
EXIT_USAGE = 2

RULE_CHECKS = "deterministic checks"
RULE_JUDGE = "judge criteria"
RULE_COST = "mean cost per plan"
RULE_RUN = "run"
BASELINE_FREE_RULES = frozenset({RULE_CHECKS, RULE_RUN})
"""Rule 1 (and an aborted or empty run) needs no baseline: it blocks even without one."""


class UsageError(Exception):
    """Unreadable input or a refused operation: exit 2."""


# --- reading ------------------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise UsageError(f"{path}: not a JSON object")
    return cast(dict[str, Any], data)


def is_results(document: Mapping[str, Any]) -> bool:
    return document.get("kind") == RESULTS_KIND and isinstance(document.get("requests"), list)


def is_baseline(document: Mapping[str, Any]) -> bool:
    return document.get("kind") == BASELINE_KIND and isinstance(document.get("requests"), dict)


def entries(results: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The per-request entries of a results file."""
    return [
        cast(Mapping[str, Any], entry)
        for entry in results.get("requests") or ()
        if isinstance(entry, Mapping)
    ]


def blocking_checks(entry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The entry's checks that block: blocking and `fail` or `error` (evals/checks.py)."""
    return [
        cast(Mapping[str, Any], check)
        for check in entry.get("checks") or ()
        if isinstance(check, Mapping)
        and check.get("blocking", True)
        and check.get("status") in ("fail", "error")
    ]


def judge_scores(entry: Mapping[str, Any]) -> dict[str, int | None]:
    """criterion -> score (None when not judged) of a results entry."""
    scores = (entry.get("judge") or {}).get("scores") or {}
    out: dict[str, int | None] = {}
    for criterion in CRITERIA:
        value = (scores.get(criterion) or {}).get("score") if isinstance(scores, Mapping) else None
        out[criterion] = value if isinstance(value, int) and not isinstance(value, bool) else None
    return out


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def is_valid(entry: Mapping[str, Any]) -> bool:
    """A valid plan: accepted (`ready`) with no blocking check failure."""
    return entry.get("status") == "ready" and not blocking_checks(entry)


def baseline_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """What the baseline keeps of one results entry."""
    return {
        "status": entry.get("status"),
        "valid": is_valid(entry),
        "warnings_count": _int_or_none(entry.get("warnings_count")),
        "submit_attempts": _int_or_none(entry.get("submit_attempts")),
        "cost_cents": _int_or_none(entry.get("cost_cents")),
        "web_search_requests": _int_or_none(entry.get("web_search_requests")),
        "judge": judge_scores(entry),
    }


def baseline_from_results(
    results: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """A baseline built from a results file, merged over `previous` (the requests of a
    filtered run replace theirs, the others are kept)."""
    requests: dict[str, Any] = dict((previous or {}).get("requests") or {})
    for entry in entries(results):
        requests[str(entry.get("id"))] = baseline_entry(entry)
    return {
        "kind": BASELINE_KIND,
        "format": BASELINE_FORMAT,
        "profile": results.get("profile"),
        "judge_model": (results.get("judge") or {}).get("model"),
        "source": {
            "results": source,
            "date": results.get("date"),
            "git_sha": results.get("git_sha"),
            "agent_versions": results.get("agent_versions"),
        },
        "requests": dict(sorted(requests.items())),
    }


def as_baseline(document: Mapping[str, Any], *, source: str | None = None) -> dict[str, Any]:
    """A baseline document, or a results file read as one."""
    if is_baseline(document):
        return dict(document)
    if is_results(document):
        return baseline_from_results(document, source=source)
    raise UsageError("the baseline is neither a baseline nor a results file")


# --- the rules ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    blocking: bool
    message: str
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class CriterionDelta:
    criterion: str
    baseline_mean: float | None
    current_mean: float | None
    compared: int

    @property
    def drop(self) -> float | None:
        if self.baseline_mean is None or self.current_mean is None:
            return None
        return self.baseline_mean - self.current_mean


@dataclass(frozen=True, slots=True)
class CostDelta:
    baseline_mean: float | None
    current_mean: float | None
    compared: int

    @property
    def change(self) -> float | None:
        """Relative change (0.3 = +30%); None when not comparable."""
        if self.baseline_mean is None or self.current_mean is None or self.baseline_mean <= 0:
            return None
        return self.current_mean / self.baseline_mean - 1


@dataclass(slots=True)
class Comparison:
    results_name: str
    profile: str | None
    git_sha: str | None
    baseline_name: str | None
    report_only: bool
    """No baseline: rules 2 and 3 are not compared. Rule 1 still blocks (BASELINE_FREE_RULES)."""
    findings: list[Finding] = field(default_factory=list[Finding])
    notes: list[str] = field(default_factory=list[str])
    criteria: list[CriterionDelta] = field(default_factory=list[CriterionDelta])
    cost: CostDelta | None = None
    rows: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def blocks(self, finding: Finding) -> bool:
        """Whether `finding` blocks this comparison. Rule 1 blocks with or without a baseline;
        rules 2 and 3 only against one (they produce no findings without it anyway)."""
        return finding.blocking and (not self.report_only or finding.rule in BASELINE_FREE_RULES)

    @property
    def blocked(self) -> bool:
        return any(self.blocks(finding) for finding in self.findings)

    def blocking_findings(self, rule: str | None = None) -> list[Finding]:
        return [f for f in self.findings if f.blocking and (rule is None or f.rule == rule)]


def check_findings(results: Mapping[str, Any]) -> list[Finding]:
    """Rule 1: every blocking check failure, plus an aborted or empty run."""
    findings: list[Finding] = []
    if results.get("aborted"):
        findings.append(Finding(RULE_RUN, True, "the run was aborted: results are partial"))
    run_entries = entries(results)
    if not run_entries:
        findings.append(Finding(RULE_RUN, True, "the run has no requests"))
    for entry in run_entries:
        request_id = str(entry.get("id"))
        if not entry.get("checks"):
            findings.append(Finding(RULE_CHECKS, True, "no checks recorded", request_id))
        for check in blocking_checks(entry):
            findings.append(
                Finding(
                    RULE_CHECKS,
                    True,
                    f"{check.get('name')} {check.get('status')}: {check.get('message')}",
                    request_id,
                )
            )
    return findings


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def judge_findings(
    results: Mapping[str, Any], baseline: Mapping[str, Any]
) -> tuple[list[Finding], list[CriterionDelta]]:
    """Rule 2: per criterion, the mean over the requests scored in the baseline."""
    current = {str(e.get("id")): e for e in entries(results)}
    base_requests = cast(Mapping[str, Any], baseline.get("requests") or {})
    findings: list[Finding] = []
    deltas: list[CriterionDelta] = []
    for criterion in CRITERIA:
        base_scores: list[float] = []
        now_scores: list[float] = []
        for request_id, base in base_requests.items():
            if request_id not in current:
                continue
            base_score = ((base or {}).get("judge") or {}).get(criterion)
            if not isinstance(base_score, int):
                continue
            score = judge_scores(current[request_id])[criterion]
            if score is None:
                judge = current[request_id].get("judge") or {}
                findings.append(
                    Finding(
                        RULE_JUDGE,
                        True,
                        f"{CRITERION_LABELS[criterion]} not scored (judge "
                        f"{judge.get('status', 'missing')}: {judge.get('error') or 'no score'})",
                        request_id,
                    )
                )
                continue
            base_scores.append(base_score)
            now_scores.append(score)
        delta = CriterionDelta(criterion, _mean(base_scores), _mean(now_scores), len(now_scores))
        deltas.append(delta)
        if delta.drop is not None and delta.drop > MAX_JUDGE_DROP + EPSILON:
            findings.append(
                Finding(
                    RULE_JUDGE,
                    True,
                    f"{CRITERION_LABELS[criterion]}: mean {delta.current_mean:.2f} vs baseline "
                    f"{delta.baseline_mean:.2f} (-{delta.drop:.2f}, more than {MAX_JUDGE_DROP})",
                )
            )
    return findings, deltas


def cost_findings(
    results: Mapping[str, Any], baseline: Mapping[str, Any]
) -> tuple[list[Finding], CostDelta]:
    """Rule 3: mean session cost per plan over the requests costed in the baseline."""
    current = {str(e.get("id")): e for e in entries(results)}
    base_requests = cast(Mapping[str, Any], baseline.get("requests") or {})
    findings: list[Finding] = []
    base_costs: list[float] = []
    now_costs: list[float] = []
    for request_id, base in base_requests.items():
        if request_id not in current:
            continue
        base_cost = _int_or_none((base or {}).get("cost_cents"))
        if base_cost is None:
            continue
        cost = _int_or_none(current[request_id].get("cost_cents"))
        if cost is None:
            findings.append(Finding(RULE_COST, True, "session cost not recorded", request_id))
            continue
        base_costs.append(base_cost)
        now_costs.append(cost)
    delta = CostDelta(_mean(base_costs), _mean(now_costs), len(now_costs))
    change = delta.change
    if change is not None and change > MAX_COST_INCREASE + EPSILON:
        findings.append(
            Finding(
                RULE_COST,
                True,
                f"mean cost per plan {delta.current_mean:.1f}¢ vs baseline "
                f"{delta.baseline_mean:.1f}¢ (+{change:.0%}, more than "
                f"{MAX_COST_INCREASE:.0%})",
            )
        )
    return findings, delta


def compare(
    results: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
    *,
    results_name: str = "results",
    baseline_name: str | None = None,
) -> Comparison:
    """Apply the rules. With `baseline` None, rules 2 and 3 are skipped (report-only) and
    rule 1 still blocks."""
    comparison = Comparison(
        results_name=results_name,
        profile=results.get("profile"),
        git_sha=results.get("git_sha"),
        baseline_name=baseline_name,
        report_only=baseline is None,
    )
    comparison.findings.extend(check_findings(results))
    base_requests: Mapping[str, Any] = {}
    if baseline is not None:
        judge_found, comparison.criteria = judge_findings(results, baseline)
        cost_found, comparison.cost = cost_findings(results, baseline)
        comparison.findings.extend(judge_found)
        comparison.findings.extend(cost_found)
        base_requests = cast(Mapping[str, Any], baseline.get("requests") or {})
        run_ids = {str(e.get("id")) for e in entries(results)}
        new = sorted(run_ids - set(base_requests))
        missing = sorted(set(base_requests) - run_ids)
        if new:
            comparison.notes.append(f"not in the baseline (checks only): {', '.join(new)}")
        if missing:
            comparison.notes.append(f"in the baseline but not run: {', '.join(missing)}")
        run_model = (results.get("judge") or {}).get("model")
        base_model = baseline.get("judge_model")
        if run_model and base_model and run_model != base_model:
            comparison.notes.append(
                f"judge model changed ({base_model} -> {run_model}): scores may not compare"
            )
    for entry in entries(results):
        request_id = str(entry.get("id"))
        base = cast(Mapping[str, Any], base_requests.get(request_id) or {})
        comparison.rows.append(
            {
                "id": request_id,
                "status": entry.get("status"),
                "failed_checks": [str(c.get("name")) for c in blocking_checks(entry)],
                "warnings_count": _int_or_none(entry.get("warnings_count")),
                "cost_cents": _int_or_none(entry.get("cost_cents")),
                "baseline_cost_cents": _int_or_none(base.get("cost_cents")),
                "web_search_requests": _int_or_none(entry.get("web_search_requests")),
                "scores": judge_scores(entry),
                "baseline_scores": dict(base.get("judge") or {}),
            }
        )
    return comparison


# --- rendering ----------------------------------------------------------------------------------


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _cents(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}¢"


def _score_cell(score: int | None, base: Any) -> str:
    if score is None:
        return "–"
    if isinstance(base, int) and base != score:
        return f"{score} ({base})"
    return str(score)


def render_markdown(comparison: Comparison) -> str:
    """The report, as Markdown for the PR comment (also printed to the terminal)."""
    verdict = "BLOCKED" if comparison.blocked else "PASSED"
    if comparison.report_only:
        verdict += " (no baseline: judge and cost REPORT ONLY)"
    lines = [
        f"## Trip planner evals: {verdict}",
        "",
        f"Results `{comparison.results_name}` · profile `{comparison.profile}` · git "
        f"`{(comparison.git_sha or 'unknown')[:12]}` · baseline "
        f"`{comparison.baseline_name or 'none'}`",
        "",
    ]
    if comparison.report_only:
        lines += [
            "No baseline yet, so the judge scores (rule 2) and the cost (rule 3) are not "
            "compared. The deterministic checks (rule 1) need no baseline and block on their "
            "own: "
            + (
                "they fail, so this run blocks. Fix the plans before creating a baseline from "
                "a run."
                if comparison.blocked
                else "every one passed."
            ),
            "",
        ]
        if not comparison.blocked:
            lines += [
                "To create the baseline from this run (only when the plans are good):",
                "",
                "```sh",
                "cd backend",
                f"uv run python ../evals/compare.py {comparison.results_name} --update-baseline",
                "git add ../evals/baseline.json   # then commit it explicitly",
                "```",
                "",
            ]
    lines += ["| Rule | Result |", "|---|---|"]
    check_failures = comparison.blocking_findings(RULE_CHECKS) + comparison.blocking_findings(
        RULE_RUN
    )
    lines.append(
        f"| Deterministic checks | "
        f"{'ok' if not check_failures else f'{len(check_failures)} failing'} |"
    )
    if comparison.report_only:
        lines.append("| Judge (mean drop at most 0.5) | not compared |")
        lines.append("| Mean cost per plan (at most +30%) | not compared |")
    else:
        judge_failures = comparison.blocking_findings(RULE_JUDGE)
        lines.append(
            f"| Judge (mean drop at most 0.5) | "
            f"{'ok' if not judge_failures else f'{len(judge_failures)} blocking'} |"
        )
        cost = comparison.cost
        change = cost.change if cost is not None else None
        cost_text = (
            f"{_cents(cost.current_mean)} vs {_cents(cost.baseline_mean)} ({change:+.0%})"
            if cost is not None and change is not None
            else "not comparable"
        )
        cost_failures = comparison.blocking_findings(RULE_COST)
        lines.append(
            f"| Mean cost per plan (at most +30%) | "
            f"{'ok' if not cost_failures else 'blocking'}: {cost_text} |"
        )
    lines.append("")
    blocking = [finding for finding in comparison.findings if comparison.blocks(finding)]
    if blocking:
        lines += ["### Blocking findings", ""]
        lines += [
            f"- {f'`{f.request_id}` ' if f.request_id else ''}{f.rule}: {f.message}"
            for f in blocking
        ]
        lines.append("")
    if comparison.criteria:
        lines += [
            "### Judge means",
            "",
            "| Criterion | Baseline | Now | Change | Plans |",
            "|---|---|---|---|---|",
        ]
        for delta in comparison.criteria:
            change_text = (
                "n/a"
                if delta.current_mean is None or delta.baseline_mean is None
                else f"{delta.current_mean - delta.baseline_mean + 0.0:+.2f}"
            )
            lines.append(
                f"| {CRITERION_LABELS[delta.criterion]} | {_fmt(delta.baseline_mean)} | "
                f"{_fmt(delta.current_mean)} | {change_text} | {delta.compared} |"
            )
        lines.append("")
    headers = " | ".join(CRITERION_LABELS[c] for c in CRITERIA)
    lines += [
        "### Requests",
        "",
        f"| Request | Status | Failed checks | Warnings | Cost | Searches | {headers} |",
        "|---|---|---|---|---|---|" + "---|" * len(CRITERIA),
    ]
    for row in comparison.rows:
        cost = row["cost_cents"]
        base_cost = row["baseline_cost_cents"]
        cost_text = "n/a" if cost is None else f"{cost}¢"
        if cost is not None and base_cost is not None and base_cost != cost:
            cost_text += f" ({base_cost}¢)"
        scores = " | ".join(
            _score_cell(row["scores"][c], row["baseline_scores"].get(c)) for c in CRITERIA
        )
        lines.append(
            f"| `{row['id']}` | {row['status'] or 'n/a'} | "
            f"{', '.join(row['failed_checks']) or '–'} | "
            f"{'n/a' if row['warnings_count'] is None else row['warnings_count']} | {cost_text} | "
            f"{'n/a' if row['web_search_requests'] is None else row['web_search_requests']} | "
            f"{scores} |"
        )
    lines.append("")
    if not comparison.report_only:
        lines.append("Values in brackets are the baseline's.")
        lines.append("")
    lines += [f"- {note}" for note in comparison.notes]
    return "\n".join(lines).rstrip() + "\n"


# --- coordinator decision (spec decision 3) -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoordinatorDecision:
    compared: list[str]
    opus_valid: int
    sonnet_valid: int
    opus_warnings: int
    sonnet_warnings: int
    opus_judge: dict[str, float | None]
    sonnet_judge: dict[str, float | None]
    opus_cost: float | None
    sonnet_cost: float | None

    @property
    def switch_to_sonnet(self) -> bool:
        """Spec: "a parita' di piani validi e di avvisi, il profilo production passa a Sonnet
        5.5": as many valid plans and no more warnings."""
        return self.sonnet_valid >= self.opus_valid and self.sonnet_warnings <= self.opus_warnings


def decide_coordinator(opus: Mapping[str, Any], sonnet: Mapping[str, Any]) -> CoordinatorDecision:
    """Compare a run with the Opus 5.5 coordinator (`opus`, a results file or baseline) and a
    run with the Sonnet 5.5 coordinator (`sonnet`, a results file) on their common requests."""
    opus_requests = cast(Mapping[str, Any], as_baseline(opus).get("requests") or {})
    sonnet_requests = cast(Mapping[str, Any], as_baseline(sonnet).get("requests") or {})
    common = sorted(set(opus_requests) & set(sonnet_requests))

    def totals(
        requests: Mapping[str, Any],
    ) -> tuple[int, int, dict[str, float | None], float | None]:
        rows = [cast(Mapping[str, Any], requests[i]) for i in common]
        valid = sum(1 for r in rows if r.get("valid"))
        warnings = sum(_int_or_none(r.get("warnings_count")) or 0 for r in rows)
        judge = {
            c: _mean([s for r in rows if isinstance(s := (r.get("judge") or {}).get(c), int)])
            for c in CRITERIA
        }
        costs = [c for r in rows if (c := _int_or_none(r.get("cost_cents"))) is not None]
        return valid, warnings, judge, _mean(costs)

    o_valid, o_warn, o_judge, o_cost = totals(opus_requests)
    s_valid, s_warn, s_judge, s_cost = totals(sonnet_requests)
    return CoordinatorDecision(
        compared=common,
        opus_valid=o_valid,
        sonnet_valid=s_valid,
        opus_warnings=o_warn,
        sonnet_warnings=s_warn,
        opus_judge=o_judge,
        sonnet_judge=s_judge,
        opus_cost=o_cost,
        sonnet_cost=s_cost,
    )


def render_decision(decision: CoordinatorDecision) -> str:
    verdict = (
        "switch the production coordinator to Sonnet 5.5"
        if decision.switch_to_sonnet
        else "keep Opus 5.5 as the production coordinator"
    )
    lines = [
        f"## Coordinator comparison: {verdict}",
        "",
        f"Requests compared: {', '.join(decision.compared) or 'none'}",
        "",
        "| | Opus 5.5 | Sonnet 5.5 |",
        "|---|---|---|",
        f"| Valid plans | {decision.opus_valid} | {decision.sonnet_valid} |",
        f"| Warnings | {decision.opus_warnings} | {decision.sonnet_warnings} |",
        f"| Mean cost per plan | {_cents(decision.opus_cost)} | {_cents(decision.sonnet_cost)} |",
    ]
    lines += [
        f"| {CRITERION_LABELS[c]} | {_fmt(decision.opus_judge[c])} | "
        f"{_fmt(decision.sonnet_judge[c])} |"
        for c in CRITERIA
    ]
    lines += [
        "",
        "Rule (spec decision 3): with as many valid plans and no more warnings, production "
        "switches to Sonnet 5.5. The judge scores are context for the reviewer, not part of "
        "the rule.",
    ]
    return "\n".join(lines) + "\n"


# --- baseline update ----------------------------------------------------------------------------


def update_baseline(
    results: Mapping[str, Any],
    *,
    path: Path,
    source: str,
    force: bool = False,
) -> dict[str, Any]:
    """Write `path` from `results` (merged over the existing baseline). Refused, unless
    `force`, for a run with blocking check failures, an aborted run, or a profile other than
    the existing baseline's. Never commits: that is the explicit, separate step."""
    previous = load_json(path) if path.exists() else None
    if previous is not None and not is_baseline(previous):
        raise UsageError(f"{path} is not a baseline file")
    if not force:
        failures = check_findings(results)
        if failures:
            raise UsageError(
                "refusing to update the baseline from a run with blocking failures "
                f"({len(failures)}); fix them, or pass --force if this is really intended"
            )
        if previous is not None and previous.get("profile") != results.get("profile"):
            raise UsageError(
                f"the baseline is for the {previous.get('profile')} profile and the run for "
                f"{results.get('profile')}; pass --force to replace it"
            )
    baseline = baseline_from_results(results, previous=previous, source=source)
    baseline["updated_at"] = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return baseline


# --- command line -------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evals/compare.py", description="Compare an eval run with the baseline."
    )
    parser.add_argument("results", type=Path, help="evals/results/<date>-<sha>.json")
    parser.add_argument(
        "--baseline", type=Path, default=BASELINE_PATH, help="baseline or results file"
    )
    parser.add_argument("--markdown", type=Path, default=None, help="write the report here")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="write the baseline from this run (commit it yourself afterwards)",
    )
    parser.add_argument("--force", action="store_true", help="with --update-baseline only")
    parser.add_argument("--allow-profile-mismatch", action="store_true")
    parser.add_argument(
        "--decide-coordinator",
        action="store_true",
        help="results = Sonnet coordinator run, --baseline = Opus coordinator run",
    )
    return parser


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(EVALS_DIR.parent))
    except ValueError:
        return str(path)


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = load_json(args.results)
    if not is_results(results):
        raise UsageError(f"{args.results} is not an eval results file")
    results_name = _display(args.results)

    if args.decide_coordinator:
        if not args.baseline.exists():
            raise UsageError("--decide-coordinator needs --baseline <Opus coordinator results>")
        report = render_decision(decide_coordinator(load_json(args.baseline), results))
        _emit(report, args.markdown)
        return EXIT_PASS

    if args.update_baseline:
        previous = load_json(args.baseline) if args.baseline.exists() else None
        print(
            render_markdown(
                compare(
                    results,
                    as_baseline(previous) if previous is not None else None,
                    results_name=results_name,
                    baseline_name=_display(args.baseline) if previous is not None else None,
                )
            )
        )
        update_baseline(results, path=args.baseline, source=results_name, force=args.force)
        print(
            f"Baseline written to {_display(args.baseline)}. It changes nothing until you "
            "commit it explicitly (git add evals/baseline.json, then commit)."
        )
        return EXIT_PASS

    baseline: dict[str, Any] | None = None
    baseline_name: str | None = None
    if args.baseline.exists():
        baseline_name = _display(args.baseline)
        baseline = as_baseline(load_json(args.baseline), source=baseline_name)
        if baseline.get("profile") != results.get("profile") and not args.allow_profile_mismatch:
            raise UsageError(
                f"profile mismatch: results {results.get('profile')}, baseline "
                f"{baseline.get('profile')} (pass --allow-profile-mismatch to compare anyway)"
            )
    comparison = compare(results, baseline, results_name=results_name, baseline_name=baseline_name)
    _emit(render_markdown(comparison), args.markdown)
    return EXIT_BLOCKED if comparison.blocked else EXIT_PASS


def _emit(report: str, markdown: Path | None) -> None:
    print(report)
    if markdown is not None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(report, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except UsageError as error:
        print(f"evals/compare.py: {error}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
