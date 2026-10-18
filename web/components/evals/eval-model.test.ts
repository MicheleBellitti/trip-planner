import { describe, expect, it } from "vitest";

import { EvalRunDetailSchema, EvalRunSummarySchema } from "@/lib/schemas/api";

import list from "./__fixtures__/list.json";
import accepted from "./__fixtures__/run-accepted.json";
import real from "./__fixtures__/run-real.json";
import {
  acceptedLabel,
  axisDay,
  checkBlocks,
  checkLabel,
  checkKind,
  checksSummary,
  costAgainstBaseline,
  criterionLabel,
  failingFirst,
  formatJudgeMean,
  formatRunCost,
  formatSeconds,
  judgeOutcome,
  meanAgainstBaseline,
  orderedFindings,
  pageCount,
  pageHref,
  pageItems,
  parsePage,
  planDigest,
  profileLabel,
  requestAnchor,
  requestJudgeMean,
  requestStatusLabel,
  RUN_VERDICT_LABELS,
  runDelta,
  runSeconds,
  runVerdict,
  runVerdictExplanation,
  ruleLabel,
  scoreWord,
  shortSha,
  sortChecks,
  trendDomain,
  trendReference,
  trendSeries,
} from "./eval-model";

const acceptedRun = EvalRunDetailSchema.parse(accepted);
const realRun = EvalRunDetailSchema.parse(real);

describe("the fixtures", () => {
  it("parse with the contract's schemas: the real run, the synthetic one and the list rows", () => {
    expect(realRun.results.requests).toHaveLength(5);
    expect(acceptedRun.results.requests[0]?.plan?.days.length).toBeGreaterThan(0);
    expect(list.map((row) => EvalRunSummarySchema.parse(row).id)).toHaveLength(5);
  });

  it("keep the real run's shape: budget paused, nothing accepted, no comparison", () => {
    expect(realRun.compare_status).toBeNull();
    expect(realRun.comparison).toBeNull();
    expect(realRun.requests_accepted).toBe(0);
    expect(realRun.total_cost_cents).toBe(309);
    expect(realRun.results.requests.every((request) => request.status === "budget_paused")).toBe(true);
  });
});

describe("runVerdict", () => {
  it("names the gate's three answers and the run nobody compared", () => {
    expect(runVerdict({ aborted: false, compare_status: "passed" })).toBe("passed");
    expect(runVerdict({ aborted: false, compare_status: "blocked" })).toBe("blocked");
    expect(runVerdict({ aborted: false, compare_status: "report_only" })).toBe("report_only");
    expect(runVerdict({ aborted: false, compare_status: null })).toBe("unknown");
  });

  it("calls a partial run Interrotto whatever the gate said (compare.py always blocks it)", () => {
    expect(runVerdict({ aborted: true, compare_status: "blocked" })).toBe("aborted");
    expect(runVerdict({ aborted: true, compare_status: null })).toBe("aborted");
  });

  it("has Italian sentence-case words", () => {
    expect(RUN_VERDICT_LABELS).toEqual({
      passed: "Superato",
      blocked: "Bloccato",
      report_only: "Solo report",
      aborted: "Interrotto",
      unknown: "Senza confronto",
    });
  });
});

describe("runVerdictExplanation", () => {
  it("says a blocked run without a baseline had nothing to be compared with", () => {
    expect(runVerdictExplanation("blocked", { report_only: true })).toContain("Non c'è un riferimento");
    expect(runVerdictExplanation("blocked", { report_only: false })).toContain("Il confronto con il riferimento");
    expect(runVerdictExplanation("blocked", null)).toContain("Il confronto con il riferimento");
    expect(runVerdictExplanation("passed", { report_only: true })).toContain("restano entro le soglie");
  });
});

describe("figures", () => {
  it("shortens a commit to seven characters and says nothing for a run that did not know it", () => {
    expect(shortSha("5d22125b035243839e5ce2ece301861aaf5e4977")).toBe("5d22125");
    expect(shortSha(null)).toBeNull();
    expect(shortSha("  ")).toBeNull();
  });

  it("writes the accepted plans as x/y with the right number", () => {
    expect(acceptedLabel(3, 5)).toBe("3/5 piani accettati");
    expect(acceptedLabel(0, 5)).toBe("0/5 piani accettati");
    expect(acceptedLabel(1, 1)).toBe("1/1 piano accettato");
  });

  it("writes the cost in dollars, Italian format", () => {
    expect(formatRunCost(309)).toBe("3,09 $");
    expect(formatRunCost(0)).toBe("0,00 $");
    expect(formatRunCost(126400)).toBe("1.264,00 $");
    expect(formatRunCost(null)).toBeNull();
  });

  it("writes a judge mean with one decimal and a comma", () => {
    expect(formatJudgeMean(4.2)).toBe("4,2");
    expect(formatJudgeMean(4)).toBe("4,0");
    expect(formatJudgeMean(3.55)).toBe("3,6");
    expect(formatJudgeMean(null)).toBeNull();
  });

  it("writes durations a reader scans", () => {
    expect(formatSeconds(47.2)).toBe("47 s");
    expect(formatSeconds(158)).toBe("2 min 38 s");
    expect(formatSeconds(120)).toBe("2 min");
    expect(formatSeconds(3700)).toBe("1 h 1 min");
    expect(formatSeconds(7200)).toBe("2 h");
    expect(formatSeconds(-1)).toBeNull();
    expect(formatSeconds(null)).toBeNull();
  });

  it("measures a run from its two instants", () => {
    expect(runSeconds("2026-10-12T22:49:40.848706+02:00", "2026-10-12T22:52:22.043410+02:00")).toBeCloseTo(161.2, 1);
    expect(runSeconds("2026-10-12T22:49:40+02:00", null)).toBeNull();
    expect(runSeconds("2026-10-12T22:49:40+02:00", "2026-10-12T22:00:00+02:00")).toBeNull();
  });

  it("names the profiles", () => {
    expect(profileLabel("development")).toBe("sviluppo");
    expect(profileLabel("production")).toBe("produzione");
    expect(profileLabel("staging")).toBe("staging");
  });
});

describe("checks", () => {
  const checks = realRun.results.requests[0]!.checks;

  it("puts failures first, then warnings, passes and skips, keeping the file's order inside a group", () => {
    const sorted = sortChecks([
      { name: "a", status: "skip", blocking: true, message: "", details: [] },
      { name: "b", status: "pass", blocking: true, message: "", details: [] },
      { name: "c", status: "warn", blocking: false, message: "", details: [] },
      { name: "d", status: "fail", blocking: true, message: "", details: [] },
      { name: "e", status: "pass", blocking: true, message: "", details: [] },
      { name: "f", status: "error", blocking: true, message: "", details: [] },
    ]);
    expect(sorted.map((check) => check.name)).toEqual(["d", "f", "c", "b", "e", "a"]);
  });

  it("lists the real request's failures before its warning and its skips", () => {
    expect(sortChecks(checks).map((check) => `${check.name}:${check.status}`)).toEqual([
      "schema_valid:fail",
      "submit_plan_attempts:fail",
      "cost_and_searches_vs_estimate:warn",
      "book_by_before_scheduled_for:skip",
      "within_budget_or_warned:skip",
      "prices_have_source:skip",
      "links_on_allowed_domains:skip",
      "no_empty_days:skip",
      "matches_request:skip",
    ]);
  });

  it("says a check blocks only when it is blocking and failed or errored", () => {
    expect(checkBlocks({ blocking: true, status: "fail" })).toBe(true);
    expect(checkBlocks({ blocking: true, status: "error" })).toBe(true);
    expect(checkBlocks({ blocking: false, status: "fail" })).toBe(false);
    expect(checkBlocks({ blocking: true, status: "warn" })).toBe(false);
    expect(checkBlocks({ blocking: true, status: "skip" })).toBe(false);
  });

  it("reads an unknown status as a warning rather than hiding it", () => {
    expect(checkKind("pass")).toBe("pass");
    expect(checkKind("flaky")).toBe("warn");
  });

  it("translates the checks of checks.py and spells out an unknown one", () => {
    expect(checkLabel("prices_have_source")).toBe("Ogni prezzo ha una fonte e una data");
    expect(checkLabel("some_new_check")).toBe("some new check");
  });

  it("sums a request's checks up in a line", () => {
    expect(checksSummary(checks)).toBe("2 controlli bloccanti non superati");
    expect(checksSummary(acceptedRun.results.requests[0]!.checks)).toBe("9 controlli superati");
    expect(checksSummary([])).toBe("Nessun controllo registrato");
  });
});

describe("the judge", () => {
  it("lists the scored criteria in the rubric's order, in Italian", () => {
    const outcome = judgeOutcome(acceptedRun.results.requests[0]!.judge);
    expect(outcome.kind).toBe("scores");
    if (outcome.kind !== "scores") return;
    expect(outcome.rows.map((row) => row.label)).toEqual([
      "Coerenza degli orari",
      "Realismo degli spostamenti",
      "Rispetto delle preferenze",
      "Qualità delle alternative",
      "Chiarezza del riassunto",
    ]);
    expect(outcome.rows[0]).toMatchObject({ key: "time_coherence", score: 5 });
    expect(outcome.rows[0]?.reason).toContain("realistic hour by hour");
  });

  it("keeps a criterion it does not know, after the known ones", () => {
    const outcome = judgeOutcome({
      status: "ok",
      model: null,
      error: null,
      cost_cents: null,
      scores: { novelty: { score: 3, reason: "x" }, summary_clarity: { score: 4, reason: "y" } },
    });
    expect(outcome.kind === "scores" && outcome.rows.map((row) => row.key)).toEqual(["summary_clarity", "novelty"]);
    expect(criterionLabel("novelty")).toBe("novelty");
  });

  it("says why there are no scores: not asked, or failed", () => {
    const skipped = judgeOutcome(realRun.results.requests[0]!.judge);
    expect(skipped).toEqual({
      kind: "none",
      reason: "Il giudice non ha valutato questo piano.",
      detail: "no accepted plan to judge",
    });
    const failed = judgeOutcome(acceptedRun.results.requests[2]!.judge);
    expect(failed).toMatchObject({ kind: "none", reason: "Il giudice non ha dato i voti." });
    expect(judgeOutcome(null)).toMatchObject({ kind: "none" });
  });

  it("averages a request's scores and words the rubric's scale", () => {
    expect(requestJudgeMean(acceptedRun.results.requests[0]!.judge)).toBeCloseTo(4.4, 5);
    expect(requestJudgeMean(null)).toBeNull();
    expect([1, 2, 3, 4, 5].map(scoreWord)).toEqual(["Inutilizzabile", "Scarso", "Accettabile", "Buono", "Ottimo"]);
  });
});

describe("requests", () => {
  it("words the planner's status, and a request that never started", () => {
    expect(requestStatusLabel("ready")).toBe("Pronto");
    expect(requestStatusLabel("budget_paused")).toBe("Limite raggiunto");
    expect(requestStatusLabel(null)).toBe("Mai partita");
    expect(requestStatusLabel("something_new")).toBe("something_new");
  });

  it("sums the accepted plan up: its title, days and bookings", () => {
    const plan = acceptedRun.results.requests[0]!.plan!;
    expect(planDigest(plan)).toEqual({
      title: "Weekend a Lisbona, 12-14 novembre 2027",
      days: "3 giorni",
      bookings: `${plan.bookings.length} prenotazioni`,
    });
    expect(planDigest({ title: "x", days: [1], bookings: [1] })).toMatchObject({ days: "1 giorno", bookings: "1 prenotazione" });
  });

  it("makes a safe anchor from the request's id", () => {
    expect(requestAnchor("sea-week-family")).toBe("richiesta-sea-week-family");
    expect(requestAnchor("a b/c")).toBe("richiesta-a-b-c");
  });

  it("puts the requests that stopped the gate first and keeps the file's order otherwise", () => {
    const order = failingFirst(acceptedRun.results.requests).map((request) => request.id);
    expect(order[order.length - 1]).toBe("city-weekend-lisbon");
    expect(order.slice(0, 4)).toEqual(["sea-week-family", "suggest-low-budget", "train-trip-florence", "flexible-dates-budapest"]);
  });
});

describe("the comparison", () => {
  const comparison = acceptedRun.comparison!;

  it("lists the blocking findings before the ones that only report", () => {
    const findings = orderedFindings({
      findings: [
        { rule: "mean cost per plan", blocking: false, message: "a", request_id: null },
        { rule: "run", blocking: true, message: "b", request_id: null },
      ],
    });
    expect(findings.map((finding) => finding.message)).toEqual(["b", "a"]);
    expect(orderedFindings(comparison)[0]?.blocking).toBe(true);
  });

  it("translates compare.py's rules", () => {
    expect(ruleLabel("deterministic checks")).toBe("Controlli");
    expect(ruleLabel("judge criteria")).toBe("Voti del giudice");
    expect(ruleLabel("mean cost per plan")).toBe("Costo medio per piano");
    expect(ruleLabel("run")).toBe("Esecuzione");
    expect(ruleLabel("something else")).toBe("something else");
  });

  it("writes a figure against the baseline", () => {
    expect(meanAgainstBaseline(3, 4)).toBe("3,0 (era 4,0)");
    expect(meanAgainstBaseline(3, null)).toBe("3,0");
    expect(meanAgainstBaseline(null, 4)).toBe("nessun voto (era 4,0)");
    expect(costAgainstBaseline(55, 50)).toBe("0,55 $ (era 0,50 $)");
    expect(costAgainstBaseline(null, 50)).toBe("costo non registrato");
  });
});

describe("the dashboard", () => {
  const runs = list.map((row) => EvalRunSummarySchema.parse(row));
  const [newest, second] = runs as [(typeof runs)[number], (typeof runs)[number]];

  it("says how a figure moved since the previous run, and whether that is better", () => {
    expect(runDelta("accepted", { ...newest, requests_accepted: 5 }, { ...second, requests_accepted: 2 })).toEqual({
      text: "+3",
      trend: "better",
    });
    expect(runDelta("checks", { ...newest, checks_passed: 1 }, { ...second, checks_passed: 4 })).toEqual({
      text: "\u22123",
      trend: "worse",
    });
    expect(runDelta("judge", { ...newest, judge_mean: 4.4 }, { ...second, judge_mean: 4.2 })).toEqual({
      text: "+0,2",
      trend: "better",
    });
  });

  it("counts a cheaper run as better, in dollars", () => {
    expect(runDelta("cost", { ...newest, total_cost_cents: 271 }, { ...second, total_cost_cents: 288 })).toEqual({
      text: "\u22120,17 $",
      trend: "better",
    });
    expect(runDelta("cost", { ...newest, total_cost_cents: 300 }, { ...second, total_cost_cents: 288 })).toEqual({
      text: "+0,12 $",
      trend: "worse",
    });
  });

  it("calls a change that rounds to nothing unchanged, and has no delta without both figures", () => {
    expect(runDelta("judge", { ...newest, judge_mean: 4.24 }, { ...second, judge_mean: 4.2 })).toEqual({
      text: "invariato",
      trend: "same",
    });
    expect(runDelta("judge", { ...newest, judge_mean: 4.2 }, { ...second, judge_mean: null })).toBeNull();
    expect(runDelta("accepted", newest, null)).toBeNull();
  });

  it("draws a metric over the runs oldest first, with each run's verdict and a gap where it has no value", () => {
    const series = trendSeries(runs, "judge");
    expect(series.map((point) => point.id)).toEqual([...runs].reverse().map((run) => run.id));
    expect(series.map((point) => point.value)).toEqual([4.55, null, 4.2, 4.0, null]);
    expect(series.map((point) => point.verdict)).toEqual(["report_only", "aborted", "passed", "blocked", "unknown"]);
    expect(series[2]?.label).toBe("4,2");
    expect(trendSeries(runs, "cost")[0]?.label).toBe("12,64 $");
    expect(trendSeries(runs, "accepted")[0]).toMatchObject({ value: 4, label: "4/5" });
  });

  it("scales each chart on clean bounds: the judge's whole points around its means, every request, the next whole dollar", () => {
    // Means 4,55, 4,2 and 4,0: between 4 and 5, so a move of a few tenths shows.
    expect(trendDomain(runs, "judge")).toEqual([4, 5]);
    expect(trendDomain([{ ...newest, judge_mean: 4 }], "judge")).toEqual([3, 5]);
    expect(trendDomain([{ ...newest, judge_mean: 1.2 }, { ...second, judge_mean: 1.4 }], "judge")).toEqual([1, 2]);
    expect(trendDomain([{ ...newest, judge_mean: null }], "judge")).toEqual([1, 5]);
    expect(trendDomain(runs, "accepted")).toEqual([0, 5]);
    expect(trendDomain(runs, "cost")).toEqual([0, 1300]);
    expect(trendDomain([{ ...newest, total_cost_cents: 0 }], "cost")).toEqual([0, 100]);
  });

  it("names a chart's ends by the day, without the time", () => {
    const now = Date.parse("2026-10-12T21:00:00Z");
    expect(axisDay("2026-10-12T20:12:04+02:00", now)).toBe("Oggi");
    expect(axisDay("2026-10-11T11:04:55+02:00", now)).toBe("Ieri");
    expect(axisDay("2026-10-08T08:15:00+02:00", now)).toBe("8 ott");
    expect(axisDay("2025-12-30T08:15:00+01:00", now)).toBe("30 dic 2025");
  });

  it("draws the cost per plan, so runs with more or fewer requests compare", () => {
    const series = trendSeries(runs, "cost_per_plan");
    expect(series.map((point) => point.label)).toEqual(["2,53 $", "0,32 $", "0,54 $", "0,58 $", "0,62 $"]);
    expect(trendSeries([{ ...newest, requests_total: 0 }], "cost_per_plan")[0]?.value).toBeNull();
  });

  it("takes the reference from the newest run that has one, and only for the judge and the cost per plan", () => {
    const withBaselines = [
      { ...newest, reference_judge_mean: 4.1, reference_cost_per_plan_cents: null },
      { ...second, reference_judge_mean: 3.9, reference_cost_per_plan_cents: 52.5 },
    ];
    expect(trendReference(withBaselines, "judge")).toEqual({ value: 4.1, label: "riferimento 4,1" });
    expect(trendReference(withBaselines, "cost_per_plan")).toEqual({ value: 52.5, label: "riferimento 0,53 $" });
    expect(trendReference(withBaselines, "accepted")).toBeNull();
    expect(trendReference(runs, "judge")).toBeNull();
  });

  it("scales the cost per plan tightly on ten cents, the reference included", () => {
    expect(trendDomain(runs, "cost_per_plan")).toEqual([30, 260]);
    const two = [
      { ...newest, total_cost_cents: 309 },
      { ...second, total_cost_cents: 288 },
    ];
    expect(trendDomain(two, "cost_per_plan")).toEqual([50, 70]);
    expect(trendDomain(two, "cost_per_plan", 40)).toEqual([40, 70]);
    expect(trendDomain([{ ...newest, total_cost_cents: 300, requests_total: 5 }], "cost_per_plan")).toEqual([60, 70]);
    expect(trendDomain([{ ...newest, judge_mean: 4.2 }], "judge", 3.4)).toEqual([3, 5]);
  });

  it("keeps the newest runs when there are more than the chart holds", () => {
    const series = trendSeries(runs, "cost", 3);
    expect(series.map((point) => point.id)).toEqual(runs.slice(0, 3).reverse().map((run) => run.id));
  });
});

describe("the list's pages", () => {
  it("reads the page from the address, the first one for anything that is not a page", () => {
    expect(parsePage("3")).toBe(3);
    expect(parsePage(["2", "5"])).toBe(2);
    for (const value of [undefined, "", "0", "-1", "1.5", "abc", "2x"]) expect(parsePage(value)).toBe(1);
  });

  it("links the first page to the bare list and the others by number", () => {
    expect(pageHref(1)).toBe("/evals");
    expect(pageHref(4)).toBe("/evals?pagina=4");
  });

  it("counts the pages, at least one", () => {
    expect(pageCount(0, 10)).toBe(1);
    expect(pageCount(10, 10)).toBe(1);
    expect(pageCount(11, 10)).toBe(2);
  });

  it("numbers every page when they are few, and folds the far ones into gaps when they are many", () => {
    expect(pageItems(2, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(pageItems(1, 12)).toEqual([1, 2, 3, "gap", 12]);
    expect(pageItems(6, 12)).toEqual([1, "gap", 5, 6, 7, "gap", 12]);
    expect(pageItems(12, 12)).toEqual([1, "gap", 10, 11, 12]);
    expect(pageItems(3, 12)).toEqual([1, 2, 3, 4, "gap", 12]);
  });
});
