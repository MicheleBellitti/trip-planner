/**
 * Response shapes of the planner API that the backend does not export as JSON Schema.
 *
 * Hand-written from the Pydantic models in backend/app/routes.py (PlanSummary,
 * PlanListResponse, LinkCheck, LinkHealthOut, PlanDetail, CreatePlanResponse, StatusResponse,
 * ContinueResponse, MeResponse, ErrorBody), backend/app/db.py (PlanStatus),
 * backend/app/config.py (AgentProfile) and backend/app/auth.py (AuthErrorCode). Keep them in
 * step with those models; the generated contract schemas (request, UI event, plan) live in
 * ./generated.
 *
 * Objects strip unknown keys (`z.object`): the backend ships first when the contract changes
 * (CLAUDE.md, contract rule 7), so an added field must not break the deployed web app.
 */

import * as z from "zod/mini";

import { PlanSchema } from "./generated/plan";

/** `plans.status` (backend/app/db.py PlanStatus). */
export const PlanStatusSchema = z.enum([
  "running",
  "ready",
  "failed",
  "budget_paused",
  "blocked",
  "interrupted",
]);
export type PlanStatus = z.output<typeof PlanStatusSchema>;

/** Statuses after which the SSE stream sends `event: end` and closes (routes.TERMINAL_STATUSES).
 * `budget_paused` is not terminal: "Continua" resumes the plan. */
export const TERMINAL_PLAN_STATUSES: ReadonlySet<PlanStatus> = new Set([
  "ready",
  "failed",
  "blocked",
  "interrupted",
]);

export function isTerminalStatus(status: PlanStatus): boolean {
  return TERMINAL_PLAN_STATUSES.has(status);
}

/** Which agent roster ran the plan (backend/app/config.py AgentProfile). */
export const AgentProfileSchema = z.enum(["development", "production"]);
export type AgentProfile = z.output<typeof AgentProfileSchema>;

/** Plan ids are UUIDs (uuid4); `z.guid()` accepts any 8-4-4-4-12 hex id, so a receiving client
 * never rejects a valid backend id over RFC variant bits. */
const PlanIdSchema = z.guid();
/** Pydantic `AwareDatetime`, serialized ISO 8601 with an offset (or Z). */
const InstantSchema = z.iso.datetime({ offset: true });

/** Answer of POST /plans (201). */
export const CreatePlanResponseSchema = z.object({ id: PlanIdSchema });
export type CreatePlanResponse = z.output<typeof CreatePlanResponseSchema>;

/** One row of the home page list (GET /plans). */
export const PlanSummarySchema = z.object({
  id: PlanIdSchema,
  /** The plan's title once accepted, else built from the request (Italian). */
  title: z.string(),
  status: PlanStatusSchema,
  /** Cumulative Managed Agents list cost, US cents. */
  cost_cents: z.int().check(z.gte(0)),
  created_at: InstantSchema,
});
export type PlanSummary = z.output<typeof PlanSummarySchema>;

/** GET /plans: newest first, at most 20. */
export const PlanListResponseSchema = z.object({ plans: z.array(PlanSummarySchema) });
export type PlanListResponse = z.output<typeof PlanListResponseSchema>;

/** Whether a booking link may be shown as a "Prenota su <label>" button. */
export const LinkCheckSchema = z.object({
  allowed: z.boolean(),
  provider: z._default(z.nullable(z.string()), null),
  label: z._default(z.nullable(z.string()), null),
  host: z._default(z.nullable(z.string()), null),
});
export type LinkCheck = z.output<typeof LinkCheckSchema>;

/** The link check's verdict on one URL (backend `LinkHealthOut`). `status` is `ok`, `dead` or
 * `unknown` today; it stays a plain string so a new value never rejects the whole detail. */
export const LinkHealthSchema = z.object({
  status: z.string(),
  /** The URL's own origin, set only for a dead link. */
  fallback: z._default(z.nullable(z.string()), null),
  /** True when a booking link may be replaced by `fallback`. */
  fallback_allowed: z._default(z.boolean(), false),
});
export type LinkHealthEntry = z.output<typeof LinkHealthSchema>;
export type LinkHealthMap = Record<string, LinkHealthEntry>;

/** GET /plans/{id}: everything the plan page needs besides the event stream. */
export const PlanDetailSchema = z.object({
  id: PlanIdSchema,
  status: PlanStatusSchema,
  title: z.string(),
  agent_profile: AgentProfileSchema,
  created_at: InstantSchema,
  updated_at: InstantSchema,
  /** Cumulative Managed Agents list cost, US cents. */
  cost_cents: z.int().check(z.gte(0)),
  /** The session's current budget cap in US cents: the end of the cost bar; raised by
   * "Continua". Null until the session exists. */
  budget_cents: z._default(z.nullable(z.int().check(z.gte(0))), null),
  /** Italian, for failed/blocked plans. */
  failure_reason: z._default(z.nullable(z.string()), null),
  submit_attempts: z.int().check(z.gte(0)),
  /** How many times "Continua" raised the budget, and how many times it may (MAX_CONTINUES_PER_PLAN):
   * at the cap the plan page offers no "Continua" and says why. Zero from a backend that predates
   * them, which never refuses a "Continua" for this reason. */
  continues: z._default(z.int().check(z.gte(0)), 0),
  continues_limit: z._default(z.int().check(z.gte(0)), 0),
  /** The PlanRequest as submitted (stored JSON; read it with the request schema if needed). */
  request: z.record(z.string(), z.unknown()),
  /** The accepted Plan (schema/plan.json), once submitted. */
  plan: z._default(z.nullable(PlanSchema), null),
  /** Aligned with plan.bookings: the check of each link, null without a link. */
  booking_links: z._default(z.array(z.nullable(LinkCheckSchema)), () => []),
  /** Aligned with plan.alternatives. */
  alternative_links: z._default(z.array(z.nullable(LinkCheckSchema)), () => []),
  /** The link check's verdict per URL of the plan; empty for plans that predate the check. */
  link_health: z._default(z.record(z.string(), LinkHealthSchema), () => ({})),
  /** TripTracker's /import?plan=<id>, only when ready. */
  import_url: z._default(z.nullable(z.string()), null),
});
export type PlanDetail = z.output<typeof PlanDetailSchema>;

/**
 * GET /plans/{id}/cover (backend/app/covers.py `Cover`): a free-licensed photo of the destination
 * and what its license asks us to show. The hosts are pinned here too, so a wrong answer can never
 * point an `<img>` or a link somewhere else: the image is served by upload.wikimedia.org, the file
 * page lives on commons.wikimedia.org, the license text is any http(s) page.
 */
export const CoverSchema = z.object({
  /** The photo, a ~1920 px thumbnail on upload.wikimedia.org (`coverSources` makes the smaller sizes). */
  url: z.url({ protocol: /^https$/, hostname: /^upload\.wikimedia\.org$/ }),
  /** Pixels of the image at `url`. */
  width: z.int().check(z.gt(0)),
  height: z.int().check(z.gt(0)),
  /** Plain text; null when unknown (a public-domain file can have none). */
  author: z._default(z.nullable(z.string()), null),
  /** Short license name, e.g. "CC BY-SA 4.0". */
  license: z.string().check(z.minLength(1)),
  /** Link to the license text; null for public domain. */
  license_url: z._default(z.nullable(z.url({ protocol: /^https?$/ })), null),
  /** The file's page on commons.wikimedia.org. */
  source_page: z.url({ protocol: /^https$/, hostname: /^commons\.wikimedia\.org$/ }),
  /** The file's title, without "File:" and the extension. */
  title: z.string(),
});
export type Cover = z.output<typeof CoverSchema>;

/** Answer of POST /plans/{id}/interrupt (202). */
export const StatusResponseSchema = z.object({
  id: PlanIdSchema,
  /** `running` while the interrupt is on its way, `interrupted` when immediate. */
  status: PlanStatusSchema,
});
export type StatusResponse = z.output<typeof StatusResponseSchema>;

/** Answer of POST /plans/{id}/continue (202). */
export const ContinueResponseSchema = z.object({
  id: PlanIdSchema,
  status: PlanStatusSchema,
  /** The new session budget, US cents. */
  budget_cents: z.int().check(z.gte(0)),
});
export type ContinueResponse = z.output<typeof ContinueResponseSchema>;

/** GET /health (no authentication). */
export const HealthResponseSchema = z.object({ status: z.literal("ok") });
export type HealthResponse = z.output<typeof HealthResponseSchema>;

/** Data of the SSE `event: end` message: the plan's terminal status. */
export const StreamEndSchema = z.object({ status: PlanStatusSchema });
export type StreamEnd = z.output<typeof StreamEndSchema>;

// --- eval history -----------------------------------------------------------------------------

/**
 * The eval history (backend routes GET /evals/runs and GET /evals/runs/{id}). The results are the
 * JSON `evals/run.py` writes (kind "trip-planner-eval-results", format 1) and the comparison is the
 * JSON `evals/compare.py --json` writes, stored as they arrived. The backend ships first and the
 * eval scripts evolve on their own, so everything the UI does not need to draw is optional with a
 * default, and unknown keys are stripped: an older or newer file must still open.
 */

/** Verdict of the gate against the baseline (`compare.py`), as the backend summarises it. */
export const EvalCompareStatusSchema = z.enum(["passed", "blocked", "report_only"]);
export type EvalCompareStatus = z.output<typeof EvalCompareStatusSchema>;

const NullableString = z._default(z.nullable(z.string()), null);
const NullableNumber = z._default(z.nullable(z.number()), null);
const Count = z.number().check(z.gte(0));

/** One row of GET /evals/runs, and the first part of GET /evals/runs/{id}. Costs are US cents. */
export const EvalRunSummarySchema = z.object({
  id: PlanIdSchema,
  started_at: InstantSchema,
  finished_at: z._default(z.nullable(InstantSchema), null),
  /** The commit the run measured; null when the run could not tell. */
  git_sha: NullableString,
  /** The agent roster: "development" or "production". */
  profile: z.string(),
  aborted: z._default(z.boolean(), false),
  requests_total: Count,
  /** Requests whose plan was accepted (status "ready"). */
  requests_accepted: Count,
  /** Requests whose blocking checks all passed. */
  checks_passed: Count,
  blocking_failures_count: Count,
  total_cost_cents: Count,
  web_search_requests: Count,
  /** Mean of every judge score of the run, 1 to 5; null when nothing was scored. */
  judge_mean: NullableNumber,
  compare_status: z._default(z.nullable(EvalCompareStatusSchema), null),
  /** The baseline the comparison measured against: the mean of its criteria's means, and its mean
   * cost per plan in US cents; null without a baseline (and from a backend older than them). */
  reference_judge_mean: NullableNumber,
  reference_cost_per_plan_cents: NullableNumber,
  /** Why the comparison blocked: its first findings that block (at most 3); `message` is English. */
  blocking_findings: z._default(
    z.array(
      z.object({
        rule: z._default(z.string(), ""),
        message: z._default(z.string(), ""),
        request_id: NullableString,
        request_title: NullableString,
      }),
    ),
    () => [],
  ),
  /** The GitHub Actions run that produced it, when CI uploaded it. */
  workflow_run_url: NullableString,
});
export type EvalRunSummary = z.output<typeof EvalRunSummarySchema>;
export type EvalBlockingFinding = EvalRunSummary["blocking_findings"][number];

/** GET /evals/runs: newest first. `total` counts every stored run, for the list's pages; null from
 * a backend older than the pages, which did not send it. */
export const EvalRunListResponseSchema = z.object({
  runs: z.array(EvalRunSummarySchema),
  total: z._default(z.nullable(Count), null),
});
export type EvalRunListResponse = z.output<typeof EvalRunListResponseSchema>;

/** A check of `evals/checks.py`: pass, warn, fail, error or skip. Unknown statuses are kept. */
export const EvalCheckSchema = z.object({
  name: z.string(),
  status: z.string(),
  blocking: z._default(z.boolean(), false),
  /** English: the check's own words. */
  message: z._default(z.string(), ""),
  details: z._default(z.array(z.string()), () => []),
});
export type EvalCheck = z.output<typeof EvalCheckSchema>;

/** The judge's verdict on one plan (`evals/judge.py`): per criterion a 1 to 5 score and an English
 * reason, only when `status` is "ok". */
export const EvalJudgeSchema = z.object({
  status: z._default(z.string(), "skipped"),
  model: NullableString,
  scores: z._default(
    z.nullable(z.record(z.string(), z.object({ score: z.number(), reason: z._default(z.string(), "") }))),
    null,
  ),
  error: NullableString,
  cost_cents: NullableNumber,
});
export type EvalJudge = z.output<typeof EvalJudgeSchema>;

/** The accepted plan inside an eval entry: only what the history shows (the full contract is
 * `PlanSchema`, which a stored plan may predate). */
export const EvalPlanSchema = z.object({
  title: z._default(z.string(), ""),
  days: z._default(z.array(z.unknown()), () => []),
  bookings: z._default(z.array(z.unknown()), () => []),
});
export type EvalPlan = z.output<typeof EvalPlanSchema>;

/** One reference request of the run, with its checks and verdict. */
export const EvalRequestResultSchema = z.object({
  id: z.string(),
  title: z._default(z.string(), ""),
  tags: z._default(z.array(z.string()), () => []),
  /** The PlanRequest as sent. */
  request: z._default(z.record(z.string(), z.unknown()), () => ({})),
  plan_id: NullableString,
  /** `plans.status` when the run stopped following the plan; null when it never started. */
  status: NullableString,
  failure_reason: NullableString,
  submit_attempts: NullableNumber,
  cost_cents: NullableNumber,
  web_search_requests: NullableNumber,
  checks: z._default(z.array(EvalCheckSchema), () => []),
  checks_passed: z._default(z.boolean(), false),
  blocking_failures: z._default(z.array(z.string()), () => []),
  warnings_count: NullableNumber,
  judge: z._default(z.nullable(EvalJudgeSchema), null),
  plan: z._default(z.nullable(EvalPlanSchema), null),
  timed_out: z._default(z.boolean(), false),
  error: NullableString,
  duration_seconds: NullableNumber,
});
export type EvalRequestResult = z.output<typeof EvalRequestResultSchema>;

/** The Managed Agents versions a run used (`agent_versions` of the plans table, once per run). */
export const EvalAgentVersionsSchema = z.object({
  profile: NullableString,
  coordinator: z._default(z.nullable(z.object({ id: z.string(), version: z._default(z.unknown(), null) })), null),
  subagents: z._default(
    z.record(z.string(), z.object({ id: z.string(), version: z._default(z.unknown(), null) })),
    () => ({}),
  ),
  skills: z._default(
    z.record(z.string(), z.object({ id: z.string(), version: z._default(z.unknown(), null) })),
    () => ({}),
  ),
  environment_id: NullableString,
  lockfile_sha256: NullableString,
  git_sha: NullableString,
});
export type EvalAgentVersions = z.output<typeof EvalAgentVersionsSchema>;

/** The `evals/run.py` document. */
export const EvalResultsSchema = z.object({
  date: NullableString,
  started_at: InstantSchema,
  finished_at: z._default(z.nullable(InstantSchema), null),
  git_sha: NullableString,
  profile: z._default(z.string(), ""),
  aborted: z._default(z.boolean(), false),
  dataset: z._default(
    z.nullable(
      z.object({
        version: NullableNumber,
        selected: z._default(z.array(z.string()), () => []),
        tags: z._default(z.array(z.string()), () => []),
      }),
    ),
    null,
  ),
  /** The spec's per-plan estimate: cost in US cents and web searches. */
  estimate: z._default(
    z.nullable(z.object({ cost_cents: NullableNumber, web_search_requests: NullableNumber })),
    null,
  ),
  agent_versions: z._default(z.nullable(EvalAgentVersionsSchema), null),
  judge: z._default(
    z.nullable(
      z.object({
        enabled: z._default(z.boolean(), true),
        model: NullableString,
        cap_cents: NullableNumber,
        spent_cents: NullableNumber,
      }),
    ),
    null,
  ),
  requests: z._default(z.array(EvalRequestResultSchema), () => []),
});
export type EvalResults = z.output<typeof EvalResultsSchema>;

/** One finding of the gate. `rule` is compare.py's own name ("deterministic checks", "judge
 * criteria", "mean cost per plan", "run"); `message` is English. */
export const EvalFindingSchema = z.pipe(
  z.object({
    rule: z._default(z.string(), ""),
    blocking: z._default(z.boolean(), false),
    /** Whether the finding blocks this comparison (a "blocking" rule is only a warning when
     * there is no baseline, or the run is report-only); older documents have no such key. */
    blocks: z._default(z.nullable(z.boolean()), null),
    message: z._default(z.string(), ""),
    request_id: NullableString,
  }),
  z.transform((finding) => ({
    rule: finding.rule,
    blocking: finding.blocks ?? finding.blocking,
    message: finding.message,
    request_id: finding.request_id,
  })),
);
export type EvalFinding = z.output<typeof EvalFindingSchema>;

/** The `evals/compare.py --json` document: the gate's findings and the figures behind them. */
export const EvalComparisonSchema = z.object({
  baseline_name: NullableString,
  /** No baseline: only the checks and the run itself can block. */
  report_only: z._default(z.boolean(), false),
  findings: z._default(z.array(EvalFindingSchema), () => []),
  notes: z._default(z.array(z.string()), () => []),
  criteria: z._default(
    z.array(
      z.object({
        criterion: z.string(),
        baseline_mean: NullableNumber,
        current_mean: NullableNumber,
        compared: z._default(z.number(), 0),
      }),
    ),
    () => [],
  ),
  /** Mean cost per plan, in US cents (compare.CostDelta). */
  cost: z._default(
    z.nullable(
      z.object({
        baseline_mean_cents: NullableNumber,
        current_mean_cents: NullableNumber,
        compared: z._default(z.number(), 0),
      }),
    ),
    null,
  ),
});
export type EvalComparison = z.output<typeof EvalComparisonSchema>;

/** GET /evals/runs/{id}: the list fields, the stored results and the stored comparison, and the
 * neighbouring runs. */
export const EvalRunDetailSchema = z.object({
  ...EvalRunSummarySchema.shape,
  results: EvalResultsSchema,
  comparison: z._default(z.nullable(EvalComparisonSchema), null),
  /** The runs just before (older) and after (newer) it in the list, as list rows; null at the ends
   * and from a backend older than them. */
  previous_run: z._default(z.nullable(EvalRunSummarySchema), null),
  next_run: z._default(z.nullable(EvalRunSummarySchema), null),
});
export type EvalRunDetail = z.output<typeof EvalRunDetailSchema>;

// --- errors -----------------------------------------------------------------------------------

/** `detail.code` values of errors the framework raises rather than a route (main.AppErrorCode):
 * a path no route has, a method the path doesn't take, an unparseable body, an unhandled
 * exception, any other status. The client falls back to the HTTP status for codes it doesn't
 * know. */
export const APP_ERROR_CODES = ["not_found", "method_not_allowed", "bad_request", "internal_error", "http_error"] as const;

/** `detail.code` values a plan endpoint can answer with: its own (routes.PlanErrorCode, with
 * `demo_unavailable` for `?demo_scenario=` without DEMO_MODE) and the framework's
 * (APP_ERROR_CODES). Auth failures are AUTH_ERROR_CODES. */
export const PLAN_ERROR_CODES = [
  "plan_not_found",
  "plan_not_ready",
  "invalid_plan_state",
  "monthly_limit_reached",
  "quota_plans_reached",
  "quota_cents_reached",
  "too_many_requests",
  "planner_busy",
  "continue_limit_reached",
  "planner_unavailable",
  "agents_unavailable",
  "request_too_large",
  "demo_unavailable",
  ...APP_ERROR_CODES,
] as const;

/** `detail.code` of GET /plans/{id}/cover when there is no photo to show (covers.CoverErrorCode):
 * no destination yet, no free image, or Wikimedia unreachable. It is a normal outcome, not a
 * failure: `getCover` answers null. */
export const COVER_UNAVAILABLE_CODE = "cover_unavailable";

/** `detail.code` values of auth failures (auth.AuthErrorCode). */
export const AUTH_ERROR_CODES = [
  "not_authenticated",
  "email_not_allowed",
  "bad_origin",
  "admin_only",
  "auth_unavailable",
] as const;

/** 403 of the eval history for a signed-in user who is not one of the backend's ADMIN_EMAILS. */
export const ADMIN_ONLY_CODE = "admin_only";

/** GET /me (routes.MeResponse): who the cookie belongs to, and whether they may read the evals. */
/** One user's month against the per-user quota (routes.QuotaView): what GET /me shows before the
 * limit and what a 429 `quota_*_reached` carries as `data`. Cents are US cents of Managed Agents
 * list cost: the recorded cost plus the unspent budget of the plans still running. */
export const QuotaSchema = z.object({
  plans_used: z.int().check(z.gte(0)),
  plans_limit: z.int().check(z.gte(0)),
  cents_used: z.int().check(z.gte(0)),
  cents_limit: z.int().check(z.gte(0)),
  /** The first instant of the next month (Europe/Rome). */
  resets_at: InstantSchema,
  /** What a new plan reserves (the session budget): a start is refused when `cents_used +
   * next_plan_cents > cents_limit`. Absent from a backend that predates it. */
  next_plan_cents: z.optional(z.int().check(z.gte(0))),
  /** What a "Continua" adds (200): refused when `cents_used + continue_cents > cents_limit`. */
  continue_cents: z.optional(z.int().check(z.gte(0))),
});
export type Quota = z.output<typeof QuotaSchema>;

export const MeSchema = z.object({
  email: z.string(),
  is_admin: z.boolean(),
  /** Null for the users exempt from the quota (admins), and from a backend that predates it. */
  quota: z._default(z.nullable(QuotaSchema), null),
});
export type Me = z.output<typeof MeSchema>;

export type PlanErrorCode = (typeof PLAN_ERROR_CODES)[number];
export type AuthErrorCode = (typeof AUTH_ERROR_CODES)[number];
export type AppErrorCode = (typeof APP_ERROR_CODES)[number];

/** The API error envelope's body, under `detail` (routes.ErrorBody). */
export const ErrorBodySchema = z.object({
  /** Stable machine code (PlanErrorCode, AuthErrorCode or AppErrorCode; unknown codes are kept
   * as strings). */
  code: z.string(),
  /** What happened and what to do, in Italian. */
  message: z.string(),
  /** Code-specific figures, e.g. {spent_cents, limit_cents} for monthly_limit_reached. */
  data: z._default(z.nullable(z.record(z.string(), z.unknown())), null),
});
export type ErrorBody = z.output<typeof ErrorBodySchema>;

/** `{"detail": {...}}`: every error except request validation (422). */
export const ErrorResponseSchema = z.object({ detail: ErrorBodySchema });

/** Data of `monthly_limit_reached` (429). */
export const MonthlyLimitDataSchema = z.object({
  spent_cents: z.int().check(z.gte(0)),
  limit_cents: z.int().check(z.gte(0)),
});

/** One entry of FastAPI's 422 body: `{"detail": [{type, loc, msg, input?, ctx?}]}`. `type` is a
 * request error code (planRequestErrorCodes) or a pydantic type; `loc` starts with "body". */
export const ValidationIssueSchema = z.object({
  type: z.string(),
  loc: z.array(z.union([z.string(), z.int()])),
  msg: z.string(),
  input: z.optional(z.unknown()),
  ctx: z.optional(z.nullable(z.record(z.string(), z.unknown()))),
});
export type ValidationIssue = z.output<typeof ValidationIssueSchema>;

export const ValidationErrorResponseSchema = z.object({ detail: z.array(ValidationIssueSchema) });
