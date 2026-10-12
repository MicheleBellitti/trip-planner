/**
 * Typed client of the planner backend (backend/app/routes.py), for the browser.
 *
 * - Every call sends the TripTracker session cookie (`credentials: "include"`); the backend
 *   lives on another origin (pianifica.api.bellittim.com), so nothing else carries the user.
 * - Every response is validated with Zod; a 2xx body that does not match the contract is an
 *   `ApiError` of kind `invalid_response`, never data the UI trusts.
 * - Errors use the envelope `{"detail": {"code", "message", "data"}}` with an Italian `message`,
 *   shown as is. FastAPI's 422 keeps its own shape (`{"detail": [issues]}`) for the form.
 * - 401 sends the browser to TripTracker's login, which brings the user back here:
 *   `<NEXT_PUBLIC_TRIPTRACKER_URL>/accedi?returnTo=<current page URL, encoded>`.
 * - 429 `monthly_limit_reached` carries the month's spend and limit (US cents).
 * - 503 `planner_unavailable`: the planner can't start plans (nothing was spent).
 * - 404 `demo_unavailable`: `createPlan`'s development-only `demoScenario` reached a backend
 *   without DEMO_MODE.
 * - 404 `cover_unavailable`: the destination has no free photo; `getCover` answers null.
 */

import { getConfig, stripTrailingSlash } from "./config";
import { formatUsd } from "./format";
import {
  ContinueResponseSchema,
  COVER_UNAVAILABLE_CODE,
  CoverSchema,
  CreatePlanResponseSchema,
  ErrorResponseSchema,
  HealthResponseSchema,
  MonthlyLimitDataSchema,
  PlanDetailSchema,
  PlanListResponseSchema,
  StatusResponseSchema,
  ValidationErrorResponseSchema,
  type ContinueResponse,
  type Cover,
  type CreatePlanResponse,
  type HealthResponse,
  type PlanDetail,
  type PlanSummary,
  type StatusResponse,
  type ValidationIssue,
} from "./schemas/api";
import type { PlanRequestInput } from "./schemas/generated/request";

export type ApiErrorKind =
  /** 401: not signed in to TripTracker; the browser is being sent to its login. */
  | "unauthorized"
  /** 403: signed in but not allowed (email_not_allowed), or a request from a wrong Origin. */
  | "forbidden"
  /** 404: the plan does not exist or is another user's. */
  | "not_found"
  /** 409: plan_not_ready, invalid_plan_state. */
  | "conflict"
  /** 422: the request body was rejected; `RequestValidationError.issues` has the fields. */
  | "validation"
  /** 429 monthly_limit_reached: `MonthlyLimitError` has the spend and the limit. */
  | "monthly_limit"
  /** 502 agents_unavailable: the Managed Agents API failed; the plan did not start. */
  | "agents_unavailable"
  /** 503 planner_unavailable: no API key, lockfile or trip.json; nothing was spent. */
  | "planner_unavailable"
  /** 503 auth_unavailable: TripTracker could not be asked who the user is. */
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
  unauthorized: "Accedi a TripTracker per usare il planner.",
  forbidden: "Questo account non è abilitato al planner.",
  not_found: "Questo piano non c'è.",
  conflict: "Il piano non è in uno stato che lo permette.",
  validation: "Controlla i campi evidenziati.",
  monthly_limit: "Questo mese è stato raggiunto il limite di spesa: il prossimo piano si potrà creare il mese prossimo.",
  agents_unavailable: "Gli agenti non rispondono: il piano non è partito. Riprova tra qualche minuto.",
  planner_unavailable:
    "Il planner non è pronto in questo momento: nessun costo è stato addebitato. Riprova più tardi.",
  auth_unavailable: "Non riesco a verificare l'accesso con TripTracker. Riprova tra poco.",
  network: "Non riesco a raggiungere il planner. Controlla la connessione e riprova.",
  invalid_response: "Il planner ha risposto in un modo inatteso. Riprova più tardi.",
  server: "Il planner ha avuto un problema. Riprova più tardi.",
  unknown: "Qualcosa è andato storto. Riprova.",
};

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

/** 401: the browser is on its way to TripTracker's login (`loginUrl`). Callers just stop. */
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

/** `<triptracker>/accedi?returnTo=<returnTo>`: TripTracker sends the user back after login
 * (only to trusted origins, on its side). */
export function loginUrl(triptrackerUrl: string, returnTo: string): string {
  return `${stripTrailingSlash(triptrackerUrl)}/accedi?returnTo=${encodeURIComponent(returnTo)}`;
}

export interface ApiClientOptions {
  /** Backend base URL; defaults to NEXT_PUBLIC_API_URL, read at call time. */
  baseUrl?: string;
  /** TripTracker origin; defaults to NEXT_PUBLIC_TRIPTRACKER_URL, read at call time. */
  triptrackerUrl?: string;
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
  /** GET /health (no authentication). */
  health(options?: RequestOptions): Promise<HealthResponse>;
  /** URL of GET /plans/{id}/events (SSE) for `new EventSource(url, {withCredentials: true})`;
   * `after` resumes after that seq on a fresh connection (EventSource only sends Last-Event-ID
   * on its own reconnections). */
  eventsUrl(planId: string, after?: number | null): string;
  /** TripTracker's login URL that returns to the current page. */
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

function kindForStatus(status: number, code: string | null): ApiErrorKind {
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 502) return "agents_unavailable";
  if (status === 503) return code === "auth_unavailable" ? "auth_unavailable" : "planner_unavailable";
  if (status >= 500) return "server";
  return "unknown";
}

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const baseUrl = () => stripTrailingSlash(options.baseUrl ?? getConfig().apiUrl);
  const triptrackerUrl = () => options.triptrackerUrl ?? getConfig().triptrackerUrl;
  const doFetch: typeof fetch = (...args) => (options.fetch ?? globalThis.fetch)(...args);
  const currentUrl = options.currentUrl ?? (() => window.location.href);
  const onUnauthorized = options.onUnauthorized ?? ((url: string) => window.location.assign(url));
  const planPath = (planId: string) => `/plans/${encodeURIComponent(planId)}`;
  const login = () => loginUrl(triptrackerUrl(), currentUrl());

  function errorFromResponse(status: number, payload: unknown): ApiError {
    if (status === 422) {
      const validation = ValidationErrorResponseSchema.safeParse(payload);
      return new RequestValidationError(status, validation.success ? validation.data.detail : []);
    }
    const envelope = ErrorResponseSchema.safeParse(payload);
    const body = envelope.success ? envelope.data.detail : null;
    const init = { status, code: body?.code ?? null, message: body?.message ?? null, data: body?.data ?? null };
    if (status === 401) {
      const url = login();
      onUnauthorized(url);
      return new UnauthorizedError(init, url);
    }
    if (status === 429 && init.code === "monthly_limit_reached") {
      return new MonthlyLimitError(init);
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
      throw errorFromResponse(response.status, payload);
    }
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
