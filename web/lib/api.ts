/**
 * Typed client of the planner backend (backend/app/routes.py), for the browser.
 *
 * - Every call sends the session cookie (`credentials: "include"`): the app's own
 *   (`__Secure-atlas.session_token`, lib/auth.ts) or TripTracker's, by NEXT_PUBLIC_AUTH_MODE. The
 *   backend lives on another origin (atlas.api.bellittim.com), so nothing else carries the user.
 * - Every response is validated with Zod; a 2xx body that does not match the contract is an
 *   `ApiError` of kind `invalid_response`, never data the UI trusts.
 * - Errors use the envelope `{"detail": {"code", "message", "data"}}` with an Italian `message`,
 *   shown as is. FastAPI's 422 keeps its own shape (`{"detail": [issues]}`) for the form.
 * - A 2xx marks the browser as signed in (lib/returning.ts) and a 401 clears the mark: "/" skips the
 *   landing for a returning visitor.
 * - 401 sends the browser to the login, which brings the user back here (`loginUrl`): this app's
 *   `/login?returnTo=<current page URL, encoded>` in atlas mode, TripTracker's
 *   `<NEXT_PUBLIC_TRIPTRACKER_URL>/accedi?returnTo=...` otherwise.
 * - 403 `admin_only`: the eval history is for the backend's ADMIN_EMAILS; `me()` says whether
 *   the signed-in user is one (the header shows "Valutazioni" only to them).
 * - 429 `monthly_limit_reached` carries the month's spend and limit (US cents).
 * - 503 `planner_unavailable`: the planner can't start plans (nothing was spent).
 * - 404 `demo_unavailable`: `createPlan`'s development-only `demoScenario` reached a backend
 *   without DEMO_MODE.
 * - 404 `eval_run_not_found`: `getEvalRun` asked for a run the history does not have (the eval
 *   history is read with the same cookie as the plans; CI uploads it with its own token).
 * - 404 `cover_unavailable`: the destination has no free photo; `getCover` answers null.
 */

import { getAuthMode, getConfig, stripTrailingSlash, type AuthMode } from "./config";
import { formatUsd } from "./format";
import { markSignedIn, markSignedOut } from "./returning";
import { ROUTES } from "./routes";
import {
  ContinueResponseSchema,
  COVER_UNAVAILABLE_CODE,
  CoverSchema,
  CreatePlanResponseSchema,
  ErrorResponseSchema,
  EvalRunDetailSchema,
  EvalRunListResponseSchema,
  HealthResponseSchema,
  MeSchema,
  MonthlyLimitDataSchema,
  PlanDetailSchema,
  PlanListResponseSchema,
  QuotaSchema,
  StatusResponseSchema,
  ValidationErrorResponseSchema,
  type ContinueResponse,
  type Cover,
  type CreatePlanResponse,
  type EvalRunDetail,
  type EvalRunListResponse,
  type HealthResponse,
  type Me,
  type PlanDetail,
  type PlanSummary,
  type Quota,
  type StatusResponse,
  type ValidationIssue,
} from "./schemas/api";
import type { PlanRequestInput } from "./schemas/generated/request";

export type ApiErrorKind =
  /** 401: not signed in; the browser is being sent to the login. */
  | "unauthorized"
  /** 403: signed in but not allowed (email_not_allowed), not an admin (admin_only, the eval
   * history), or a request from a wrong Origin. */
  | "forbidden"
  /** 404: the plan does not exist or is another user's. */
  | "not_found"
  /** 409: plan_not_ready, invalid_plan_state. */
  | "conflict"
  /** 422: the request body was rejected; `RequestValidationError.issues` has the fields. */
  | "validation"
  /** 429 monthly_limit_reached: `MonthlyLimitError` has the spend and the limit. */
  | "monthly_limit"
  /** 429 quota_plans_reached or quota_cents_reached: the user's own month is used up;
   * `QuotaReachedError` has the figures and when it resets. */
  | "quota_reached"
  /** 429 too_many_requests: a burst from this user or address; `retryAfterSeconds` says when. */
  | "rate_limited"
  /** 503 planner_busy: every slot is running a plan; nothing was spent, retry in a minute. */
  | "planner_busy"
  /** 409 continue_limit_reached: this plan had all the "Continua" it may have. */
  | "continue_limit"
  /** 502 agents_unavailable: the Managed Agents API failed; the plan did not start. */
  | "agents_unavailable"
  /** 503 planner_unavailable: no API key, lockfile or trip.json; nothing was spent. */
  | "planner_unavailable"
  /** 503 auth_unavailable: the backend could not check who the user is. */
  | "auth_unavailable"
  /** The request never got an answer: offline, DNS, CORS, the backend is down. */
  | "network"
  /** A 2xx answer whose body does not match the contract. */
  | "invalid_response"
  /** Any other 5xx. */
  | "server"
  /** Anything else. */
  | "unknown";

/** Italian copy for errors the backend did not describe itself (no envelope, network, ...). */
export const API_ERROR_MESSAGES: Record<ApiErrorKind, string> = {
  unauthorized: "Accedi per usare il planner.",
  forbidden: "Questo account non è abilitato al planner.",
  not_found: "Questo piano non c'è.",
  conflict: "Il piano non è in uno stato che lo permette.",
  validation: "Controlla i campi evidenziati.",
  monthly_limit: "Questo mese è stato raggiunto il limite di spesa: il prossimo piano si potrà creare il mese prossimo.",
  quota_reached: "Questo mese hai usato tutti i piani a tua disposizione: il prossimo si potrà creare il mese prossimo.",
  rate_limited: "Troppe richieste in poco tempo: aspetta un momento e riprova.",
  planner_busy: "Il planner è al completo in questo momento: riprova tra qualche minuto. Nessun costo è stato addebitato.",
  continue_limit: "Questo piano ha già usato tutte le sue proroghe: il budget non si può aumentare ancora.",
  agents_unavailable: "Gli agenti non rispondono: il piano non è partito. Riprova tra qualche minuto.",
  planner_unavailable:
    "Il planner non è pronto in questo momento: nessun costo è stato addebitato. Riprova più tardi.",
  auth_unavailable: "Non riesco a verificare l'accesso. Riprova tra poco.",
  network: "Non riesco a raggiungere il planner. Controlla la connessione e riprova.",
  invalid_response: "Il planner ha risposto in un modo inatteso. Riprova più tardi.",
  server: "Il planner ha avuto un problema. Riprova più tardi.",
  unknown: "Qualcosa è andato storto. Riprova.",
};

/** A 404 of the eval history that is not the backend's own `eval_run_not_found` would otherwise
 * read "Questo piano non c'è": either the route does not exist (an older backend) or the answer
 * had no envelope. */
function evalNotFound(error: unknown): unknown {
  if (!(error instanceof ApiError) || error.kind !== "not_found" || error.code === "eval_run_not_found") return error;
  return new ApiError({
    kind: "not_found",
    status: error.status,
    code: error.code,
    message:
      error.code === "not_found"
        ? "La cronologia delle valutazioni non è disponibile su questo planner."
        : "Questa valutazione non c'è.",
  });
}

interface ApiErrorInit {
  kind: ApiErrorKind;
  status: number;
  code?: string | null;
  message?: string | null;
  data?: Record<string, unknown> | null;
}

/** Every failure of the client. `message` is Italian and can be shown to the user. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  /** HTTP status; 0 when no response arrived. */
  readonly status: number;
  /** The envelope's `detail.code`, when there was one. */
  readonly code: string | null;
  readonly data: Record<string, unknown> | null;

  constructor(init: ApiErrorInit) {
    super(init.message || API_ERROR_MESSAGES[init.kind]);
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status;
    this.code = init.code ?? null;
    this.data = init.data ?? null;
  }
}

/** 401: the browser is on its way to the login (`loginUrl`). Callers just stop. */
export class UnauthorizedError extends ApiError {
  readonly loginUrl: string;

  constructor(init: Omit<ApiErrorInit, "kind">, loginUrl: string) {
    super({ ...init, kind: "unauthorized" });
    this.name = "UnauthorizedError";
    this.loginUrl = loginUrl;
  }
}

/** 429 monthly_limit_reached. Amounts are US cents of Managed Agents list cost. */
export class MonthlyLimitError extends ApiError {
  readonly spentCents: number | null;
  readonly limitCents: number | null;

  constructor(init: Omit<ApiErrorInit, "kind">) {
    const figures = MonthlyLimitDataSchema.safeParse(init.data ?? null);
    const fallback = figures.success
      ? `Questo mese sono già stati spesi ${formatUsd(figures.data.spent_cents)} su ` +
        `${formatUsd(figures.data.limit_cents)}: il prossimo piano si potrà creare il mese prossimo.`
      : null;
    super({ ...init, kind: "monthly_limit", message: init.message || fallback });
    this.name = "MonthlyLimitError";
    this.spentCents = figures.success ? figures.data.spent_cents : null;
    this.limitCents = figures.success ? figures.data.limit_cents : null;
  }
}

/** 429 quota_plans_reached or quota_cents_reached: the user's own month is used up. `quota` is the
 * backend's figures when it sent them (US cents, and when the month turns). */
export class QuotaReachedError extends ApiError {
  readonly quota: Quota | null;
  readonly limit: "plans" | "cents";

  constructor(init: Omit<ApiErrorInit, "kind">) {
    const figures = QuotaSchema.safeParse(init.data ?? null);
    super({ ...init, kind: "quota_reached", message: init.message || API_ERROR_MESSAGES.quota_reached });
    this.name = "QuotaReachedError";
    this.quota = figures.success ? figures.data : null;
    this.limit = init.code === "quota_cents_reached" ? "cents" : "plans";
  }
}

/** 429 too_many_requests: `retryAfterSeconds` from the body (or the Retry-After header). */
export class RateLimitedError extends ApiError {
  readonly retryAfterSeconds: number | null;

  constructor(init: Omit<ApiErrorInit, "kind">, retryAfterSeconds: number | null) {
    super({ ...init, kind: "rate_limited", message: init.message || API_ERROR_MESSAGES.rate_limited });
    this.name = "RateLimitedError";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** 422: FastAPI's validation issues (`loc` starts with "body"); request-form.ts maps them to
 * the form's fields. */
export class RequestValidationError extends ApiError {
  readonly issues: ValidationIssue[];

  constructor(status: number, issues: ValidationIssue[]) {
    super({ kind: "validation", status });
    this.name = "RequestValidationError";
    this.issues = issues;
  }
}

/** Where a 401 sends the browser (lib/config.ts `AuthMode`). */
export type LoginTarget = { mode: "triptracker"; triptrackerUrl: string } | { mode: "atlas" };

/**
 * The login page that brings the user back to `returnTo` afterwards. TripTracker:
 * `<triptracker>/accedi?returnTo=<returnTo>` (it sends the user back only to trusted origins, on
 * its side). Atlas: this app's `/login?returnTo=<returnTo>` (the page accepts same-origin targets
 * only, lib/return-to.ts). `returnTo` is the full current URL in both cases.
 */
export function loginUrl(target: LoginTarget, returnTo: string): string {
  const query = `returnTo=${encodeURIComponent(returnTo)}`;
  if (target.mode === "atlas") return `${ROUTES.login}?${query}`;
  return `${stripTrailingSlash(target.triptrackerUrl)}/accedi?${query}`;
}

export interface ApiClientOptions {
  /** Backend base URL; defaults to NEXT_PUBLIC_API_URL, read at call time. */
  baseUrl?: string;
  /** TripTracker origin; defaults to NEXT_PUBLIC_TRIPTRACKER_URL, read at call time. */
  triptrackerUrl?: string;
  /** Whose login a 401 leads to; defaults to NEXT_PUBLIC_AUTH_MODE, read at call time. */
  authMode?: AuthMode;
  /** Defaults to the global fetch. */
  fetch?: typeof fetch;
  /** The page to come back to after login; defaults to `window.location.href`. */
  currentUrl?: () => string;
  /** What to do on 401; defaults to `window.location.assign(loginUrl)`. */
  onUnauthorized?: (loginUrl: string) => void;
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface CreatePlanOptions extends RequestOptions {
  /** Development only: the scripted session a DEMO_MODE backend replays
   * (`?demo_scenario=<name>`, a file of backend/tests/fixtures/ma). Without DEMO_MODE the
   * backend answers 404 `demo_unavailable`; an unknown name is a 422 on
   * `["query", "demo_scenario"]`. Empty or absent sends no parameter. */
  demoScenario?: string | null;
}

export interface ApiClient {
  /** POST /plans: validate the request and start a plan (`demoScenario`: development only). */
  createPlan(request: PlanRequestInput, options?: CreatePlanOptions): Promise<CreatePlanResponse>;
  /** GET /plans: the user's 20 most recent plans, newest first. */
  listPlans(options?: RequestOptions): Promise<PlanSummary[]>;
  /** GET /plans/{id}: status, accepted plan, link checks, import URL. */
  getPlan(planId: string, options?: RequestOptions): Promise<PlanDetail>;
  /** GET /plans/{id}/trip: the TripTracker Trip (TripTracker's /import validates it). */
  getTrip(planId: string, options?: RequestOptions): Promise<unknown>;
  /** GET /plans/{id}/cover: the destination's photo with its author and license, or null when
   * there is none (404 `cover_unavailable`). Unlike the other calls it uses the browser's HTTP
   * cache: the backend answers `Cache-Control: private, max-age=3600`. */
  getCover(planId: string, options?: RequestOptions): Promise<Cover | null>;
  /** POST /plans/{id}/interrupt ("Interrompi"). */
  interruptPlan(planId: string, options?: RequestOptions): Promise<StatusResponse>;
  /** POST /plans/{id}/continue ("Continua con 2 $ in più"). */
  continuePlan(planId: string, options?: RequestOptions): Promise<ContinueResponse>;
  /** GET /evals/runs: a page of the eval history, newest first (at most `limit`, default 50, after
   * the newest `offset`), and how many runs there are. */
  listEvalRuns(options?: RequestOptions & { limit?: number; offset?: number }): Promise<EvalRunListResponse>;
  /** GET /evals/runs/{id}: one run with its stored results and comparison. */
  getEvalRun(runId: string, options?: RequestOptions): Promise<EvalRunDetail>;
  /** GET /me: the signed-in address and whether it may read the eval history. */
  me(options?: RequestOptions): Promise<Me>;
  /** GET /health (no authentication). */
  health(options?: RequestOptions): Promise<HealthResponse>;
  /** URL of GET /plans/{id}/events (SSE) for `new EventSource(url, {withCredentials: true})`;
   * `after` resumes after that seq on a fresh connection (EventSource only sends Last-Event-ID
   * on its own reconnections). */
  eventsUrl(planId: string, after?: number | null): string;
  /** The login URL that returns to the current page (this app's or TripTracker's, by mode). */
  loginUrl(): string;
}

/** What `send` needs from a schema: Zod schemas fit, and so does `ANY_JSON`. */
interface Parser<T> {
  safeParse(value: unknown): { success: true; data: T } | { success: false };
}

/** GET /plans/{id}/trip: the Trip belongs to TripTracker, whose /import validates it. */
const ANY_JSON: Parser<unknown> = { safeParse: (value) => ({ success: true, data: value }) };

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => "");
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

/** A 429's wait: the body's `retry_after_seconds`, else the Retry-After header's seconds. */
function retryAfterSeconds(data: Record<string, unknown> | null | undefined, header: string | null): number | null {
  const fromBody = data?.retry_after_seconds;
  if (typeof fromBody === "number" && Number.isFinite(fromBody)) return Math.max(0, Math.round(fromBody));
  if (header && /^\d+$/.test(header.trim())) return Number(header.trim());
  return null;
}

function kindForStatus(status: number, code: string | null): ApiErrorKind {
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return code === "continue_limit_reached" ? "continue_limit" : "conflict";
  if (status === 502) return "agents_unavailable";
  if (status === 503 && code === "planner_busy") return "planner_busy";
  if (status === 503) return code === "auth_unavailable" ? "auth_unavailable" : "planner_unavailable";
  if (status >= 500) return "server";
  return "unknown";
}

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const baseUrl = () => stripTrailingSlash(options.baseUrl ?? getConfig().apiUrl);
  const loginTarget = (): LoginTarget => {
    const mode = options.authMode ?? getAuthMode();
    if (mode === "atlas") return { mode };
    return { mode, triptrackerUrl: options.triptrackerUrl ?? getConfig().triptrackerUrl };
  };
  const doFetch: typeof fetch = (...args) => (options.fetch ?? globalThis.fetch)(...args);
  const currentUrl = options.currentUrl ?? (() => window.location.href);
  const onUnauthorized = options.onUnauthorized ?? ((url: string) => window.location.assign(url));
  const planPath = (planId: string) => `/plans/${encodeURIComponent(planId)}`;
  const login = () => loginUrl(loginTarget(), currentUrl());

  function errorFromResponse(status: number, payload: unknown, retryAfterHeader: string | null = null): ApiError {
    if (status === 422) {
      const validation = ValidationErrorResponseSchema.safeParse(payload);
      return new RequestValidationError(status, validation.success ? validation.data.detail : []);
    }
    const envelope = ErrorResponseSchema.safeParse(payload);
    const body = envelope.success ? envelope.data.detail : null;
    const init = { status, code: body?.code ?? null, message: body?.message ?? null, data: body?.data ?? null };
    if (status === 401) {
      markSignedOut();
      const url = login();
      onUnauthorized(url);
      return new UnauthorizedError(init, url);
    }
    if (status === 429 && init.code === "monthly_limit_reached") {
      return new MonthlyLimitError(init);
    }
    if (status === 429 && (init.code === "quota_plans_reached" || init.code === "quota_cents_reached")) {
      return new QuotaReachedError(init);
    }
    if (status === 429) {
      return new RateLimitedError(init, retryAfterSeconds(init.data, retryAfterHeader));
    }
    return new ApiError({ ...init, kind: kindForStatus(status, init.code) });
  }

  async function send<T>(
    method: "GET" | "POST",
    path: string,
    parser: Parser<T>,
    { body, signal, cache = "no-store" }: { body?: unknown; signal?: AbortSignal; cache?: RequestCache } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const init: RequestInit = { method, credentials: "include", cache, headers, signal };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    // Outside the try: a missing NEXT_PUBLIC_API_URL is a deployment bug, not a network error.
    const url = `${baseUrl()}${path}`;
    let response: Response;
    try {
      response = await doFetch(url, init);
    } catch (error) {
      if (isAbortError(error) || signal?.aborted) throw error;
      throw new ApiError({ kind: "network", status: 0 });
    }
    const payload = await readJson(response);
    if (!response.ok) {
      throw errorFromResponse(response.status, payload, response.headers.get("retry-after"));
    }
    // Any 2xx from an authenticated endpoint proves a session: "/" may skip the landing next time.
    if (path !== "/health") markSignedIn();
    const parsed = parser.safeParse(payload);
    if (!parsed.success) {
      throw new ApiError({ kind: "invalid_response", status: response.status });
    }
    return parsed.data;
  }

  return {
    createPlan: (request, opts) => {
      const scenario = opts?.demoScenario?.trim();
      const query = scenario ? `?demo_scenario=${encodeURIComponent(scenario)}` : "";
      return send("POST", `/plans${query}`, CreatePlanResponseSchema, { body: request, signal: opts?.signal });
    },
    listPlans: async (opts) =>
      (await send("GET", "/plans", PlanListResponseSchema, { signal: opts?.signal })).plans,
    getPlan: (planId, opts) => send("GET", planPath(planId), PlanDetailSchema, { signal: opts?.signal }),
    getTrip: (planId, opts) => send("GET", `${planPath(planId)}/trip`, ANY_JSON, { signal: opts?.signal }),
    getCover: async (planId, opts) => {
      try {
        return await send("GET", `${planPath(planId)}/cover`, CoverSchema, { signal: opts?.signal, cache: "default" });
      } catch (error) {
        if (error instanceof ApiError && error.status === 404 && error.code === COVER_UNAVAILABLE_CODE) return null;
        throw error;
      }
    },
    interruptPlan: (planId, opts) =>
      send("POST", `${planPath(planId)}/interrupt`, StatusResponseSchema, { signal: opts?.signal }),
    continuePlan: (planId, opts) =>
      send("POST", `${planPath(planId)}/continue`, ContinueResponseSchema, { signal: opts?.signal }),
    listEvalRuns: async (opts) => {
      const query = new URLSearchParams();
      if (opts?.limit !== undefined) query.set("limit", `${Math.max(1, Math.floor(opts.limit))}`);
      if (opts?.offset) query.set("offset", `${Math.max(0, Math.floor(opts.offset))}`);
      const search = query.size > 0 ? `?${query}` : "";
      try {
        return await send("GET", `/evals/runs${search}`, EvalRunListResponseSchema, { signal: opts?.signal });
      } catch (error) {
        throw evalNotFound(error);
      }
    },
    getEvalRun: async (runId, opts) => {
      try {
        return await send("GET", `/evals/runs/${encodeURIComponent(runId)}`, EvalRunDetailSchema, {
          signal: opts?.signal,
        });
      } catch (error) {
        throw evalNotFound(error);
      }
    },
    me: (opts) => send("GET", "/me", MeSchema, { signal: opts?.signal }),
    health: (opts) => send("GET", "/health", HealthResponseSchema, { signal: opts?.signal }),
    eventsUrl: (planId, after) => {
      const url = `${baseUrl()}${planPath(planId)}/events`;
      return after === undefined || after === null ? url : `${url}?after=${after}`;
    },
    loginUrl: login,
  };
}

/** The app's client, configured from NEXT_PUBLIC_* variables. */
export const api: ApiClient = createApiClient();
