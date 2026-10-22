/**
 * Pure helpers of the eval history screens: what a run's verdict is called, how its figures read
 * in Italian, which checks come first, how the judge's scores are worded. No React, no I/O, no
 * Intl (the strings are the same on the server and in every browser).
 *
 * The eval files are written by `evals/run.py` and `evals/compare.py` in English (check names,
 * messages, judge reasons); the screens translate the labels they own (check and criterion names,
 * statuses, rules) and show the files' own sentences as they are, marked `lang="en"`.
 */

import { formatCreated, formatUsd } from "@/lib/format";
import { PLAN_STATUS_LABELS } from "@/lib/plan-events/labels";
import { ROUTES } from "@/lib/routes";
import type {
  EvalCheck,
  EvalComparison,
  EvalFinding,
  EvalJudge,
  EvalPlan,
  EvalRequestResult,
  EvalRunSummary,
  PlanStatus,
} from "@/lib/schemas/api";

// --- the run's verdict ------------------------------------------------------------------------

/** What a run says at a glance. `aborted` outranks the gate (compare.py always blocks a partial
 * run, but "Interrotto" says why); `unknown` is a run nobody compared. */
export type RunVerdict = "passed" | "blocked" | "report_only" | "aborted" | "unknown";

export const RUN_VERDICT_LABELS: Record<RunVerdict, string> = {
  passed: "Superato",
  blocked: "Bloccato",
  report_only: "Solo report",
  aborted: "Interrotto",
  unknown: "Senza confronto",
};

/** One sentence under a verdict: what it means for the change the run measured. */
export const RUN_VERDICT_EXPLANATIONS: Record<RunVerdict, string> = {
  passed: "I controlli, i voti e il costo restano entro le soglie del riferimento.",
  blocked: "Il confronto con il riferimento non lascia passare questa modifica.",
  report_only:
    "Non c'è un riferimento approvato: voti e costi non si confrontano, ma i controlli bloccanti valgono comunque.",
  aborted: "Il collaudo è stato fermato prima della fine: i risultati sono parziali e il confronto lo blocca.",
  unknown: "Di questo collaudo non c'è un confronto salvato.",
};

/** The sentence under the verdict. A blocked run whose comparison had no baseline was not
 * measured against one: only its own checks failed, and it says so. */
export function runVerdictExplanation(verdict: RunVerdict, comparison: Pick<EvalComparison, "report_only"> | null): string {
  if (verdict === "blocked" && comparison?.report_only) {
    return "Non c'è un riferimento approvato con cui confrontare, e i controlli bloccanti di alcune richieste non passano.";
  }
  return RUN_VERDICT_EXPLANATIONS[verdict];
}

export function runVerdict(run: Pick<EvalRunSummary, "aborted" | "compare_status">): RunVerdict {
  if (run.aborted) return "aborted";
  return run.compare_status ?? "unknown";
}

// --- figures ----------------------------------------------------------------------------------

/** The commit as people say it: its first seven characters; null when the run did not know it. */
export function shortSha(sha: string | null | undefined): string | null {
  const trimmed = sha?.trim();
  return trimmed ? trimmed.slice(0, 7) : null;
}

/** "2/5 piani accettati", "1/1 piano accettato". */
export function acceptedLabel(accepted: number, total: number): string {
  return `${accepted}/${total} ${total === 1 ? "piano accettato" : "piani accettati"}`;
}

/** "3,09 $" for US cents; null (not a number) reads as no cost. */
export function formatRunCost(cents: number | null | undefined): string | null {
  return typeof cents === "number" && Number.isFinite(cents) ? formatUsd(cents) : null;
}

/** A judge mean or score on the 1 to 5 scale, one decimal, Italian comma: 4.2 -> "4,2", 4 -> "4,0".
 * Null when nothing was scored. */
export function formatJudgeMean(mean: number | null | undefined): string | null {
  if (typeof mean !== "number" || !Number.isFinite(mean)) return null;
  return (Math.round(mean * 10 + 1e-9) / 10).toFixed(1).replace(".", ",");
}

/** Whole seconds as a duration a reader scans: 47 -> "47 s", 158 -> "2 min 38 s", 3700 -> "1 h 1 min". */
export function formatSeconds(seconds: number | null | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return null;
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) {
    const rest = total % 60;
    return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
  }
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes === 0 ? `${hours} h` : `${hours} h ${restMinutes} min`;
}

/** How long a run took, from its two instants; null when it has not finished or the instants do
 * not parse. */
export function runSeconds(startedAt: string, finishedAt: string | null | undefined): number | null {
  if (!finishedAt) return null;
  const start = Date.parse(startedAt);
  const end = Date.parse(finishedAt);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  return (end - start) / 1000;
}

/** "5 ricerche web", "1 ricerca web". */
export function searchesLabel(count: number): string {
  return `${count} ${count === 1 ? "ricerca web" : "ricerche web"}`;
}

/** "5 richieste", "1 richiesta". */
export function requestsLabel(count: number): string {
  return `${count} ${count === 1 ? "richiesta" : "richieste"}`;
}

/** The profile as a word: the roster that ran the plans. Unknown profiles keep their own name. */
export function profileLabel(profile: string): string {
  if (profile === "development") return "sviluppo";
  if (profile === "production") return "produzione";
  return profile || "profilo sconosciuto";
}

// --- checks -----------------------------------------------------------------------------------

export type CheckKind = "pass" | "warn" | "fail" | "error" | "skip";

const CHECK_KINDS: ReadonlySet<string> = new Set(["pass", "warn", "fail", "error", "skip"]);

/** A status from the file as one the screen knows; anything else counts as a warning, so a new
 * status is read rather than hidden. */
export function checkKind(status: string): CheckKind {
  return CHECK_KINDS.has(status) ? (status as CheckKind) : "warn";
}

export const CHECK_STATUS_LABELS: Record<CheckKind, string> = {
  pass: "Superato",
  warn: "Avviso",
  fail: "Non superato",
  error: "Errore",
  skip: "Saltato",
};

/** Failures first, then what is worth reading, then what passed, then what was skipped. */
const CHECK_RANK: Record<CheckKind, number> = { fail: 0, error: 0, warn: 1, pass: 2, skip: 3 };

/** The checks in reading order: failures (blocking ones first), warnings, passes, skips. The
 * file's order is kept inside each group. */
export function sortChecks(checks: readonly EvalCheck[]): EvalCheck[] {
  const rank = (check: EvalCheck) => {
    const kind = checkKind(check.status);
    return CHECK_RANK[kind] * 2 + (check.blocking || (kind !== "fail" && kind !== "error") ? 0 : 1);
  };
  return checks
    .map((check, index) => ({ check, index }))
    .sort((a, b) => rank(a.check) - rank(b.check) || a.index - b.index)
    .map(({ check }) => check);
}

/** Whether a check stopped the run: blocking and failed or errored (checks.py `blocks`). */
export function checkBlocks(check: Pick<EvalCheck, "blocking" | "status">): boolean {
  const kind = checkKind(check.status);
  return check.blocking && (kind === "fail" || kind === "error");
}

/** The checks of `evals/checks.py`, in Italian. */
export const CHECK_LABELS: Record<string, string> = {
  schema_valid: "Il piano e il viaggio rispettano gli schemi",
  book_by_before_scheduled_for: "Ogni scadenza viene prima della data della prenotazione",
  within_budget_or_warned: "Il totale sta nel budget, o il piano lo segnala",
  prices_have_source: "Ogni prezzo ha una fonte e una data",
  links_on_allowed_domains: "Ogni link è su un dominio ammesso",
  no_empty_days: "Nessun giorno vuoto",
  submit_plan_attempts: "Il piano è stato accettato al primo o secondo invio",
  cost_and_searches_vs_estimate: "Costo e ricerche web rispetto alla stima",
  matches_request: "Il piano risponde alla richiesta",
  dead_links: "Nessun link rotto",
  choices_asked: "Domande al viaggiatore",
};

export function checkLabel(name: string): string {
  return CHECK_LABELS[name] ?? name.replace(/_/g, " ");
}

/** How a request's checks read in one line: "2 controlli bloccanti non superati", "9 controlli superati". */
export function checksSummary(checks: readonly EvalCheck[]): string {
  if (checks.length === 0) return "Nessun controllo registrato";
  const blocking = checks.filter(checkBlocks).length;
  if (blocking > 0) return `${blocking} ${blocking === 1 ? "controllo bloccante non superato" : "controlli bloccanti non superati"}`;
  const warnings = checks.filter((check) => checkKind(check.status) === "warn").length;
  const passed = checks.filter((check) => checkKind(check.status) === "pass").length;
  if (warnings > 0) return `${passed} su ${checks.length} superati, ${warnings} ${warnings === 1 ? "avviso" : "avvisi"}`;
  return passed === checks.length
    ? `${passed} ${passed === 1 ? "controllo superato" : "controlli superati"}`
    : `${passed} su ${checks.length} superati`;
}

// --- the judge --------------------------------------------------------------------------------

/** The judge's criteria, in the rubric's order (`evals/judge.py` CRITERIA). */
export const CRITERIA = [
  "time_coherence",
  "realistic_transfers",
  "preference_respect",
  "alternatives_quality",
  "summary_clarity",
] as const;

export const CRITERION_LABELS: Record<string, string> = {
  time_coherence: "Coerenza degli orari",
  realistic_transfers: "Realismo degli spostamenti",
  preference_respect: "Rispetto delle preferenze",
  alternatives_quality: "Qualità delle alternative",
  summary_clarity: "Chiarezza del riassunto",
};

export function criterionLabel(criterion: string): string {
  return CRITERION_LABELS[criterion] ?? criterion.replace(/_/g, " ");
}

/** The rubric's scale in words (evals/rubric.md): what a score means. */
export const SCORE_WORDS: Record<number, string> = {
  1: "Inutilizzabile",
  2: "Scarso",
  3: "Accettabile",
  4: "Buono",
  5: "Ottimo",
};

export function scoreWord(score: number): string {
  return SCORE_WORDS[Math.min(5, Math.max(1, Math.round(score)))] ?? "";
}

export interface CriterionRow {
  key: string;
  label: string;
  score: number;
  reason: string;
}

/** What the judge said about a request: the scored criteria in the rubric's order (unknown ones
 * after), or why there are none. */
export type JudgeOutcome =
  | { kind: "scores"; rows: CriterionRow[] }
  /** `reason` is Italian; `detail` is the file's own English sentence ("no accepted plan to judge"). */
  | { kind: "none"; reason: string; detail: string | null };

const JUDGE_STATUS_REASONS: Record<string, string> = {
  skipped: "Il giudice non ha valutato questo piano.",
  error: "Il giudice non ha dato i voti.",
};

export function judgeOutcome(judge: EvalJudge | null | undefined): JudgeOutcome {
  const scores = judge?.scores;
  if (scores && Object.keys(scores).length > 0) {
    const keys = Object.keys(scores);
    const ordered = [
      ...CRITERIA.filter((key) => key in scores),
      ...keys.filter((key) => !(CRITERIA as readonly string[]).includes(key)),
    ];
    return {
      kind: "scores",
      rows: ordered.map((key) => ({
        key,
        label: criterionLabel(key),
        score: scores[key]!.score,
        reason: scores[key]!.reason,
      })),
    };
  }
  const reason = JUDGE_STATUS_REASONS[judge?.status ?? "skipped"] ?? JUDGE_STATUS_REASONS.error!;
  return { kind: "none", reason, detail: judge?.error?.trim() || null };
}

/** The mean of one request's scores, null without any. */
export function requestJudgeMean(judge: EvalJudge | null | undefined): number | null {
  const outcome = judgeOutcome(judge);
  if (outcome.kind !== "scores" || outcome.rows.length === 0) return null;
  return outcome.rows.reduce((sum, row) => sum + row.score, 0) / outcome.rows.length;
}

// --- a request --------------------------------------------------------------------------------

/** The plan status of a request in Italian: the planner's own words, or "Mai partita" when the
 * run never got a plan going. */
export function requestStatusLabel(status: string | null | undefined): string {
  if (!status) return "Mai partita";
  return status in PLAN_STATUS_LABELS ? PLAN_STATUS_LABELS[status as PlanStatus] : status;
}

/** What the accepted plan holds, for one line: "Weekend a Lisbona, 12-14 novembre 2027", "3 giorni, 5 prenotazioni". */
export function planDigest(plan: EvalPlan): { title: string; days: string; bookings: string } {
  const days = plan.days.length;
  const bookings = plan.bookings.length;
  return {
    title: plan.title,
    days: `${days} ${days === 1 ? "giorno" : "giorni"}`,
    bookings: `${bookings} ${bookings === 1 ? "prenotazione" : "prenotazioni"}`,
  };
}

/** A request's id as an anchor on the run page. */
export function requestAnchor(id: string): string {
  return `richiesta-${id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

/** Requests whose blocking checks failed, first: the ones a reader has to look at. The file's
 * order is kept inside each group. */
export function failingFirst(requests: readonly EvalRequestResult[]): EvalRequestResult[] {
  return requests
    .map((request, index) => ({ request, index }))
    .sort((a, b) => Number(a.request.checks_passed) - Number(b.request.checks_passed) || a.index - b.index)
    .map(({ request }) => request);
}

// --- the comparison ---------------------------------------------------------------------------

/** compare.py's rule names, in Italian. */
export const RULE_LABELS: Record<string, string> = {
  "deterministic checks": "Controlli",
  "judge criteria": "Voti del giudice",
  "mean cost per plan": "Costo medio per piano",
  run: "Esecuzione",
};

export function ruleLabel(rule: string): string {
  return RULE_LABELS[rule] ?? (rule || "Regola");
}

/** The findings that block, then the ones that only report. */
export function orderedFindings(comparison: Pick<EvalComparison, "findings">): EvalFinding[] {
  return [...comparison.findings].sort((a, b) => Number(b.blocking) - Number(a.blocking));
}

/** A criterion's change against the baseline, "3,0 (era 4,0)", or the current mean alone. */
export function meanAgainstBaseline(current: number | null, baseline: number | null): string {
  const now = formatJudgeMean(current);
  const was = formatJudgeMean(baseline);
  if (now === null) return was === null ? "nessun voto" : `nessun voto (era ${was})`;
  return was === null ? now : `${now} (era ${was})`;
}

/** The mean cost per plan against the baseline, in dollars: "0,55 $ (era 0,50 $)". */
export function costAgainstBaseline(current: number | null, baseline: number | null): string {
  const now = formatRunCost(current);
  const was = formatRunCost(baseline);
  if (now === null) return "costo non registrato";
  return was === null ? now : `${now} (era ${was})`;
}

// --- the dashboard ----------------------------------------------------------------------------

/** The figures the dashboard follows from run to run. `cost` is the run's total, `cost_per_plan`
 * that total over its requests (what the baseline measures, and comparable when the dataset
 * grows). */
export type RunMetric = "accepted" | "checks" | "judge" | "cost" | "cost_per_plan";

/** How many runs the trend charts draw: the newest ones. */
export const TREND_RUNS = 20;

const MINUS = "−";

function metricValue(run: EvalRunSummary, metric: RunMetric): number | null {
  const value =
    metric === "accepted"
      ? run.requests_accepted
      : metric === "checks"
        ? run.checks_passed
        : metric === "judge"
          ? run.judge_mean
          : metric === "cost"
            ? run.total_cost_cents
            : run.requests_total > 0
              ? run.total_cost_cents / run.requests_total
              : null;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A figure as the dashboard writes it: "4/5" plans, "4,2" for the judge, "2,88 $". */
function metricLabel(run: EvalRunSummary, metric: RunMetric, value: number): string {
  if (metric === "accepted") return `${value}/${run.requests_total}`;
  if (metric === "checks") return `${value}/${run.requests_total}`;
  if (metric === "judge") return formatJudgeMean(value) ?? "";
  return formatUsd(Math.round(value));
}

export interface RunDelta {
  /** "+3", "−0,2", "−0,17 $", or "invariato". */
  text: string;
  trend: "better" | "worse" | "same";
}

/** How `metric` moved from the previous run to the latest one, signed with a true minus, and
 * whether that is good news: more plans, checks and judge points are better, a higher cost is
 * worse. A change that rounds to nothing as written is "invariato". Null without both figures. */
export function runDelta(metric: RunMetric, latest: EvalRunSummary, previous: EvalRunSummary | null): RunDelta | null {
  if (!previous) return null;
  const now = metricValue(latest, metric);
  const was = metricValue(previous, metric);
  if (now === null || was === null) return null;
  const change = metric === "judge" ? Math.round((now - was) * 10 + 1e-9 * Math.sign(now - was)) / 10 : now - was;
  if (change === 0) return { text: "invariato", trend: "same" };
  const size = Math.abs(change);
  const written = metric === "judge" ? (formatJudgeMean(size) ?? "") : metric === "cost" ? formatUsd(size) : `${size}`;
  const up = change > 0;
  return {
    text: `${up ? "+" : MINUS}${written}`,
    trend: up === (metric !== "cost") ? "better" : "worse",
  };
}

export interface TrendPoint {
  id: string;
  startedAt: string;
  verdict: RunVerdict;
  /** Null where the run has no such figure (no judge mean): the line breaks there. */
  value: number | null;
  label: string | null;
}

/** One metric over the newest `limit` runs, oldest first (time runs left to right). `runs` is the
 * list as the API returns it, newest first. */
export function trendSeries(runs: readonly EvalRunSummary[], metric: RunMetric, limit = TREND_RUNS): TrendPoint[] {
  return runs
    .slice(0, limit)
    .reverse()
    .map((run) => {
      const value = metricValue(run, metric);
      return {
        id: run.id,
        startedAt: run.started_at,
        verdict: runVerdict(run),
        value,
        label: value === null ? null : metricLabel(run, metric, value),
      };
    });
}

/** The verdicts over the newest `limit` runs, oldest first, for the "Esito" line: every run is a
 * station (value 0), its label the verdict's word. */
export function verdictSeries(runs: readonly EvalRunSummary[], limit = TREND_RUNS): TrendPoint[] {
  return runs
    .slice(0, limit)
    .reverse()
    .map((run) => {
      const verdict = runVerdict(run);
      return { id: run.id, startedAt: run.started_at, verdict, value: 0, label: RUN_VERDICT_LABELS[verdict] };
    });
}

/** The vertical bounds of a metric's chart, on clean numbers, with the reference inside them: for
 * the judge, the whole points around its means (at least one point apart, inside 1 to 5); for the
 * cost per plan, the ten cents around it (at least ten apart), so a move of a few tenths or a few
 * cents shows on both; zero to the most requests a run had; zero to the next whole dollar above
 * the dearest run. */
export function trendDomain(
  runs: readonly EvalRunSummary[],
  metric: RunMetric,
  reference: number | null = null,
): [number, number] {
  const values = [
    ...runs.map((run) => metricValue(run, metric)).filter((value): value is number => value !== null),
    ...(reference === null ? [] : [reference]),
  ];
  if (metric === "cost_per_plan") {
    if (values.length === 0) return [0, 100];
    const low = Math.floor(Math.min(...values) / 10) * 10;
    const high = Math.ceil(Math.max(...values) / 10) * 10;
    return [low, Math.max(high, low + 10)];
  }
  if (metric === "judge") {
    if (values.length === 0) return [1, 5];
    const low = Math.max(1, Math.floor(Math.min(...values)));
    const high = Math.min(5, Math.ceil(Math.max(...values)));
    return low < high ? [low, high] : [Math.max(1, low - 1), Math.min(5, high + 1)];
  }
  if (metric === "cost") {
    const dearest = Math.max(0, ...runs.map((run) => metricValue(run, "cost") ?? 0));
    return [0, Math.max(100, Math.ceil(dearest / 100) * 100)];
  }
  return [0, Math.max(1, ...runs.map((run) => run.requests_total))];
}

export interface TrendReference {
  value: number;
  /** "riferimento 4,1", "riferimento 0,53 $". */
  label: string;
}

/** The baseline a chart is read against: the newest run's that has one (the gate measures each run
 * against the baseline of its day), for the judge's mean and the cost per plan only. */
export function trendReference(runs: readonly EvalRunSummary[], metric: RunMetric): TrendReference | null {
  if (metric !== "judge" && metric !== "cost_per_plan") return null;
  for (const run of runs) {
    const value = metric === "judge" ? run.reference_judge_mean : run.reference_cost_per_plan_cents;
    if (typeof value === "number" && Number.isFinite(value)) {
      const written = metric === "judge" ? formatJudgeMean(value) : formatUsd(Math.round(value));
      return { value, label: `riferimento ${written}` };
    }
  }
  return null;
}

/** A chart's end named by its day: "Oggi", "Ieri", "8 ott", "30 dic 2025" (the list's own words,
 * without the time). For the browser only (Intl), like formatCreated. */
export function axisDay(iso: string, nowMs: number): string {
  return formatCreated(iso, nowMs).split(",")[0] ?? iso;
}

// --- the list's pages -------------------------------------------------------------------------

/** Runs per page of the list. */
export const PAGE_SIZE = 10;

/** `?pagina=` as a page number: a positive whole number, else the first page. */
export function parsePage(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || !/^\d+$/.test(raw)) return 1;
  const page = Number(raw);
  return page >= 1 && Number.isSafeInteger(page) ? page : 1;
}

/** How many pages `total` runs fill; at least one, so an empty history still has its page. */
export function pageCount(total: number, size = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / size));
}

/** The pager's items: every page when there are at most seven, else the first, the last and three
 * around the current one, with a gap for each run of hidden pages (a gap never hides one page
 * alone: that page is shown instead). */
export function pageItems(current: number, count: number): (number | "gap")[] {
  if (count <= 7) return Array.from({ length: count }, (_, index) => index + 1);
  const start = Math.min(Math.max(current - 1, 1), count - 2);
  const shown = [...new Set([1, start, start + 1, start + 2, count])].sort((a, b) => a - b);
  const items: (number | "gap")[] = [];
  for (const page of shown) {
    const last = items.at(-1);
    if (typeof last === "number" && page - last === 2) items.push(last + 1);
    else if (typeof last === "number" && page - last > 2) items.push("gap");
    items.push(page);
  }
  return items;
}

/** A page of the list: the bare list for the first, `?pagina=N` for the others. */
export function pageHref(page: number): string {
  return page <= 1 ? ROUTES.evals : `${ROUTES.evals}?pagina=${page}`;
}
