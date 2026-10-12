/**
 * Response shapes of the planner API that the backend does not export as JSON Schema.
 *
 * Hand-written from the Pydantic models in backend/app/routes.py (PlanSummary,
 * PlanListResponse, LinkCheck, PlanDetail, CreatePlanResponse, StatusResponse,
 * ContinueResponse, ErrorBody), backend/app/db.py (PlanStatus), backend/app/config.py
 * (AgentProfile) and backend/app/auth.py (AuthErrorCode). Keep them in step with those models;
 * the generated contract schemas (request, UI event, plan) live in ./generated.
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
  /** The PlanRequest as submitted (stored JSON; read it with the request schema if needed). */
  request: z.record(z.string(), z.unknown()),
  /** The accepted Plan (schema/plan.json), once submitted. */
  plan: z._default(z.nullable(PlanSchema), null),
  /** Aligned with plan.bookings: the check of each link, null without a link. */
  booking_links: z._default(z.array(z.nullable(LinkCheckSchema)), () => []),
  /** Aligned with plan.alternatives. */
  alternative_links: z._default(z.array(z.nullable(LinkCheckSchema)), () => []),
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
  "auth_unavailable",
] as const;

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
