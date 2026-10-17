import { afterEach, describe, expect, it, vi } from "vitest";

import evalList from "../components/evals/__fixtures__/list.json";
import evalRun from "../components/evals/__fixtures__/run-accepted.json";
import happyPath from "./plan-events/__fixtures__/happy-path.json";
import {
  ApiError,
  createApiClient,
  loginUrl,
  MonthlyLimitError,
  RequestValidationError,
  UnauthorizedError,
  type ApiClientOptions,
} from "./api";
import { SIGNED_IN_KEY } from "./returning";
import { APP_ERROR_CODES, COVER_UNAVAILABLE_CODE, PLAN_ERROR_CODES } from "./schemas/api";

const PLAN_ID = happyPath.plan_id;
const CURRENT_PAGE = "https://atlas.bellittim.com/plans/6f1c2a7e-3b4d-4e5f-8a9b-0c1d2e3f4a5b?tab=piano#giorno-2";

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function envelope(code: string, message: string, data: Record<string, unknown> | null = null) {
  return { detail: { code, message, data } };
}

function client(response: Response | (() => Promise<Response>), extra: ApiClientOptions = {}) {
  const fetchMock = vi.fn<typeof fetch>(async () => (typeof response === "function" ? response() : response));
  const onUnauthorized = vi.fn();
  const api = createApiClient({
    baseUrl: "https://atlas.api.test/",
    triptrackerUrl: "https://viaggi.test",
    fetch: fetchMock,
    currentUrl: () => CURRENT_PAGE,
    onUnauthorized,
    ...extra,
  });
  return { api, fetchMock, onUnauthorized };
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected the call to fail");
}

describe("requests", () => {
  it("POST /plans sends the JSON body with the session cookie", async () => {
    const { api, fetchMock } = client(json(201, { id: PLAN_ID }));
    const request = {
      origin: "Milano",
      destination: "Lisbona",
      dates: { exact_start: "2026-11-14", exact_end: "2026-11-17" },
      travelers: [{ kind: "adult" as const }, { kind: "adult" as const }],
      budget_eur: 1500,
    };

    await expect(api.createPlan(request)).resolves.toEqual({ id: PLAN_ID });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("https://atlas.api.test/plans");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json", Accept: "application/json" });
    expect(JSON.parse(String(init?.body))).toEqual(request);
  });

  it("POST /plans passes a demo scenario as a query parameter, and none when it is blank", async () => {
    const { api, fetchMock } = client(async () => json(201, { id: PLAN_ID }));

    await api.createPlan({} as never, { demoScenario: "budget_reached" });
    await api.createPlan({} as never, { demoScenario: " a&b " });
    await api.createPlan({} as never, { demoScenario: "  " });
    await api.createPlan({} as never, { demoScenario: null });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "https://atlas.api.test/plans?demo_scenario=budget_reached",
      "https://atlas.api.test/plans?demo_scenario=a%26b",
      "https://atlas.api.test/plans",
      "https://atlas.api.test/plans",
    ]);
  });

  it("GET requests send no body and no Content-Type (no CORS preflight)", async () => {
    const { api, fetchMock } = client(json(200, { plans: [] }));

    await expect(api.listPlans()).resolves.toEqual([]);

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("https://atlas.api.test/plans");
    expect(init?.method).toBe("GET");
    expect(init?.body).toBeUndefined();
    expect(init?.headers).not.toHaveProperty("Content-Type");
    expect(init?.credentials).toBe("include");
  });

  it("parses GET /plans/{id} with the contract schemas", async () => {
    const { api, fetchMock } = client(json(200, happyPath.detail));

    const detail = await api.getPlan(PLAN_ID);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`https://atlas.api.test/plans/${PLAN_ID}`);
    expect(detail.status).toBe("running");
    expect(detail.budget_cents).toBe(60);
    expect(detail.plan).toBeNull();
  });

  it("covers interrupt, continue, trip and health", async () => {
    const interrupt = client(json(202, { id: PLAN_ID, status: "running" }));
    await expect(interrupt.api.interruptPlan(PLAN_ID)).resolves.toEqual({ id: PLAN_ID, status: "running" });
    expect(interrupt.fetchMock.mock.calls[0]?.[0]).toBe(`https://atlas.api.test/plans/${PLAN_ID}/interrupt`);
    expect(interrupt.fetchMock.mock.calls[0]?.[1]?.method).toBe("POST");

    const resume = client(json(202, { id: PLAN_ID, status: "running", budget_cents: 261 }));
    await expect(resume.api.continuePlan(PLAN_ID)).resolves.toMatchObject({ budget_cents: 261 });
    expect(resume.fetchMock.mock.calls[0]?.[0]).toBe(`https://atlas.api.test/plans/${PLAN_ID}/continue`);

    const trip = client(json(200, { id: "trip", days: [] }));
    await expect(trip.api.getTrip(PLAN_ID)).resolves.toEqual({ id: "trip", days: [] });
    expect(trip.fetchMock.mock.calls[0]?.[0]).toBe(`https://atlas.api.test/plans/${PLAN_ID}/trip`);

    const health = client(json(200, { status: "ok" }));
    await expect(health.api.health()).resolves.toEqual({ status: "ok" });
  });

  it("builds the SSE URL, with ?after= to resume", () => {
    const { api } = client(json(200, {}));

    expect(api.eventsUrl(PLAN_ID)).toBe(`https://atlas.api.test/plans/${PLAN_ID}/events`);
    expect(api.eventsUrl(PLAN_ID, null)).toBe(`https://atlas.api.test/plans/${PLAN_ID}/events`);
    expect(api.eventsUrl(PLAN_ID, 0)).toBe(`https://atlas.api.test/plans/${PLAN_ID}/events?after=0`);
    expect(api.eventsUrl(PLAN_ID, 41)).toBe(`https://atlas.api.test/plans/${PLAN_ID}/events?after=41`);
  });
});

const COVER_BODY = {
  url: "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/Lisboa.jpg/1920px-Lisboa.jpg",
  width: 1920,
  height: 1231,
  author: "Vitor Oliveira",
  license: "CC BY-SA 2.0",
  license_url: "https://creativecommons.org/licenses/by-sa/2.0",
  source_page: "https://commons.wikimedia.org/wiki/File:Lisboa.jpg",
  title: "Lisboa",
};

describe("getCover", () => {
  it("reads GET /plans/{id}/cover with the cookie and the browser's HTTP cache", async () => {
    const { api, fetchMock } = client(json(200, COVER_BODY));

    await expect(api.getCover(PLAN_ID)).resolves.toEqual(COVER_BODY);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`https://atlas.api.test/plans/${PLAN_ID}/cover`);
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.credentials).toBe("include");
    // The backend sends Cache-Control: private, max-age=3600; the other calls opt out of caching.
    expect(init?.cache).toBe("default");
  });

  it("accepts a public-domain photo with no author and no license link", async () => {
    const { api } = client(json(200, { ...COVER_BODY, author: null, license: "CC0", license_url: null }));

    await expect(api.getCover(PLAN_ID)).resolves.toMatchObject({ author: null, license_url: null });
  });

  it("answers null when the destination has no photo (404 cover_unavailable)", async () => {
    const { api } = client(
      json(404, envelope(COVER_UNAVAILABLE_CODE, "Per questa destinazione non c'è una foto.")),
    );

    await expect(api.getCover(PLAN_ID)).resolves.toBeNull();
  });

  it("still fails for a plan that does not exist, and for server errors", async () => {
    const gone = client(json(404, envelope("plan_not_found", "Questo piano non c'è.")));
    expect((await failure(gone.api.getCover(PLAN_ID))).kind).toBe("not_found");

    const broken = client(json(500, envelope("internal_error", "Errore.")));
    expect((await failure(broken.api.getCover(PLAN_ID))).kind).toBe("server");
  });

  it("refuses an image or a source page on another host, or a javascript: license link", async () => {
    for (const body of [
      { ...COVER_BODY, url: "https://evil.example/Lisboa.jpg" },
      { ...COVER_BODY, url: "http://upload.wikimedia.org/Lisboa.jpg" },
      { ...COVER_BODY, source_page: "https://evil.example/File:Lisboa.jpg" },
      { ...COVER_BODY, license_url: "javascript:alert(1)" },
      { ...COVER_BODY, width: 0 },
    ]) {
      const { api } = client(json(200, body));
      expect((await failure(api.getCover(PLAN_ID))).kind).toBe("invalid_response");
    }
  });
});

describe("errors", () => {
  it("401 redirects to TripTracker's login with the current page, encoded", async () => {
    const { api, onUnauthorized } = client(
      json(401, envelope("not_authenticated", "Accedi a TripTracker per usare il planner.")),
    );

    const error = await failure(api.listPlans());

    const expected = `https://viaggi.test/accedi?returnTo=${encodeURIComponent(CURRENT_PAGE)}`;
    expect(error).toBeInstanceOf(UnauthorizedError);
    expect(error.kind).toBe("unauthorized");
    expect((error as UnauthorizedError).loginUrl).toBe(expected);
    expect(onUnauthorized).toHaveBeenCalledWith(expected);
    expect(expected).toContain("returnTo=https%3A%2F%2Fatlas.bellittim.com%2Fplans%2F");
    expect(expected).toContain("%3Ftab%3Dpiano%23giorno-2");
  });

  it("401 without an envelope still redirects", async () => {
    const { api, onUnauthorized } = client(new Response("", { status: 401 }));

    const error = await failure(api.getPlan(PLAN_ID));

    expect(error.kind).toBe("unauthorized");
    expect(error.message).toBe("Accedi a TripTracker per usare il planner.");
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("the default 401 handler navigates the window", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, href: CURRENT_PAGE, assign });
    const api = createApiClient({
      baseUrl: "https://atlas.api.test",
      triptrackerUrl: "https://viaggi.test/",
      fetch: async () => json(401, envelope("not_authenticated", "Accedi.")),
    });

    await failure(api.listPlans());

    expect(assign).toHaveBeenCalledWith(`https://viaggi.test/accedi?returnTo=${encodeURIComponent(CURRENT_PAGE)}`);
  });

  it("429 monthly limit carries the spend and the limit", async () => {
    const message = "Questo mese sono già stati spesi 48,20 $ su 50,00 $: il prossimo piano si potrà creare il mese prossimo.";
    const { api } = client(
      json(429, envelope("monthly_limit_reached", message, { spent_cents: 4820, limit_cents: 5000 })),
    );

    const error = await failure(api.createPlan({} as never));

    expect(error).toBeInstanceOf(MonthlyLimitError);
    expect(error.kind).toBe("monthly_limit");
    expect(error.status).toBe(429);
    expect((error as MonthlyLimitError).spentCents).toBe(4820);
    expect((error as MonthlyLimitError).limitCents).toBe(5000);
    expect(error.message).toBe(message);
  });

  it("429 monthly limit without a message builds one from the figures", async () => {
    const { api } = client(json(429, envelope("monthly_limit_reached", "", { spent_cents: 4820, limit_cents: 5000 })));

    const error = await failure(api.continuePlan(PLAN_ID));

    expect(error.message).toBe(
      "Questo mese sono già stati spesi 48,20 $ su 50,00 $: il prossimo piano si potrà creare il mese prossimo.",
    );
  });

  it("503 planner unavailable", async () => {
    const message = "Il planner non è pronto in questo momento: nessun costo è stato addebitato. Riprova più tardi.";
    const { api } = client(json(503, envelope("planner_unavailable", message)));

    const error = await failure(api.createPlan({} as never));

    expect(error.kind).toBe("planner_unavailable");
    expect(error.code).toBe("planner_unavailable");
    expect(error.message).toBe(message);
  });

  it("503 from the auth check is told apart", async () => {
    const { api } = client(json(503, envelope("auth_unavailable", "Non riesco a verificare l'accesso con TripTracker.")));

    expect((await failure(api.listPlans())).kind).toBe("auth_unavailable");
  });

  it("503 without a body (a proxy) is still 'planner unavailable', in Italian", async () => {
    const { api } = client(new Response("<html>Bad gateway</html>", { status: 503 }));

    const error = await failure(api.listPlans());

    expect(error.kind).toBe("planner_unavailable");
    expect(error.message).toMatch(/^Il planner non è pronto/);
  });

  it.each([
    [403, "email_not_allowed", "forbidden"],
    [404, "plan_not_found", "not_found"],
    [409, "invalid_plan_state", "conflict"],
    [502, "agents_unavailable", "agents_unavailable"],
    [500, "boom", "server"],
    [418, "teapot", "unknown"],
  ])("status %i (%s) is a %s error with the backend's message", async (status, code, kind) => {
    const { api } = client(json(status, envelope(code, "Messaggio dal backend.")));

    const error = await failure(api.interruptPlan(PLAN_ID));

    expect(error.kind).toBe(kind);
    expect(error.code).toBe(code);
    expect(error.message).toBe("Messaggio dal backend.");
  });

  it("404 demo_unavailable keeps its code and the backend's message", async () => {
    const message = "La modalità demo non è attiva su questo server.";
    const { api } = client(json(404, envelope("demo_unavailable", message)));

    const error = await failure(api.createPlan({} as never, { demoScenario: "happy_path" }));

    expect(error.kind).toBe("not_found");
    expect(error.code).toBe("demo_unavailable");
    expect(error.message).toBe(message);
  });

  it("knows every plan, framework and auth error code of the backend", () => {
    expect(PLAN_ERROR_CODES).toContain("demo_unavailable");
    expect(APP_ERROR_CODES).toEqual(["not_found", "method_not_allowed", "bad_request", "internal_error", "http_error"]);
    expect(PLAN_ERROR_CODES).toEqual(expect.arrayContaining([...APP_ERROR_CODES]));
  });

  it("422 keeps FastAPI's issues for the form", async () => {
    const issues = [
      { type: "destination_required", loc: ["body", "destination"], msg: "give a destination", input: null },
      { type: "child_age_required", loc: ["body", "travelers", 1, "age"], msg: "a child needs an age", input: null },
    ];
    const { api } = client(json(422, { detail: issues }));

    const error = await failure(api.createPlan({} as never));

    expect(error).toBeInstanceOf(RequestValidationError);
    expect(error.kind).toBe("validation");
    expect((error as RequestValidationError).issues.map((issue) => issue.loc)).toEqual([
      ["body", "destination"],
      ["body", "travelers", 1, "age"],
    ]);
  });

  it("a failed fetch is a network error in Italian", async () => {
    const { api } = client(async () => {
      throw new TypeError("Failed to fetch");
    });

    const error = await failure(api.listPlans());

    expect(error.kind).toBe("network");
    expect(error.status).toBe(0);
    expect(error.message).toBe("Non riesco a raggiungere il planner. Controlla la connessione e riprova.");
  });

  it("an aborted request is rethrown as is", async () => {
    const controller = new AbortController();
    controller.abort();
    const { api } = client(async () => {
      throw new DOMException("aborted", "AbortError");
    });

    await expect(api.listPlans({ signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
  });

  it("a 2xx body that breaks the contract is an invalid response", async () => {
    const { api } = client(json(200, { plans: [{ id: PLAN_ID, title: "x", status: "exploded" }] }));

    const error = await failure(api.listPlans());

    expect(error.kind).toBe("invalid_response");
    expect(error.status).toBe(200);
  });
});

describe("loginUrl", () => {
  it("encodes the return URL and tolerates a trailing slash", () => {
    expect(loginUrl("https://viaggi.bellittim.com/", "https://atlas.bellittim.com/new?x=1&y=2")).toBe(
      "https://viaggi.bellittim.com/accedi?returnTo=https%3A%2F%2Fatlas.bellittim.com%2Fnew%3Fx%3D1%26y%3D2",
    );
  });
});

describe("the eval history", () => {
  it("GET /evals/runs sends the limit and answers the rows, newest first as the backend sent them", async () => {
    const { api, fetchMock } = client(json(200, { runs: evalList, total: 12 }));

    const { runs, total } = await api.listEvalRuns({ limit: 20 });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://atlas.api.test/evals/runs?limit=20");
    expect(fetchMock.mock.calls[0]?.[1]?.credentials).toBe("include");
    expect(runs.map((run) => run.id)).toEqual(evalList.map((run) => run.id));
    expect(runs[0]).toMatchObject({ compare_status: null, requests_total: 5, total_cost_cents: 309 });
    expect(total).toBe(12);
  });

  it("GET /evals/runs sends the offset of a later page", async () => {
    const { api, fetchMock } = client(json(200, { runs: [], total: 12 }));

    await api.listEvalRuns({ limit: 10, offset: 10 });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://atlas.api.test/evals/runs?limit=10&offset=10");
  });

  it("GET /evals/runs without a limit sends none, and an empty history is an empty list", async () => {
    const { api, fetchMock } = client(json(200, { runs: [], total: 0 }));

    await expect(api.listEvalRuns()).resolves.toEqual({ runs: [], total: 0 });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://atlas.api.test/evals/runs");
  });

  it("an older backend that does not count the runs answers a null total", async () => {
    const { api } = client(json(200, { runs: evalList }));

    expect((await api.listEvalRuns()).total).toBeNull();
  });

  it("GET /evals/runs/{id} parses the stored results and comparison", async () => {
    const { api, fetchMock } = client(json(200, evalRun));

    const run = await api.getEvalRun(evalRun.id);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`https://atlas.api.test/evals/runs/${evalRun.id}`);
    expect(run.compare_status).toBe("blocked");
    expect(run.results.requests).toHaveLength(5);
    expect(run.comparison?.findings.filter((finding) => finding.blocking)).toHaveLength(3);
  });

  it("opens a stored run whose results leave out what the screens can do without", async () => {
    const { api } = client(
      json(200, {
        ...evalRun,
        comparison: null,
        results: { started_at: evalRun.started_at, requests: [{ id: "only-an-id" }] },
      }),
    );

    const run = await api.getEvalRun(evalRun.id);

    expect(run.results.requests[0]).toMatchObject({ id: "only-an-id", checks: [], tags: [], judge: null, plan: null });
    expect(run.results.agent_versions).toBeNull();
  });

  it("reads a run's baseline, blocking findings and neighbours, and their absence from an older backend", async () => {
    const neighbour = { ...evalList[1]!, reference_judge_mean: 4.1, blocking_findings: [] };
    const { api } = client(
      json(200, {
        ...evalRun,
        reference_judge_mean: 4.1,
        reference_cost_per_plan_cents: 52.5,
        blocking_findings: [
          { rule: "deterministic checks", message: "2 prices without a source_url", request_id: "sea-week-family", request_title: "Settimana al mare" },
        ],
        previous_run: neighbour,
        next_run: null,
      }),
    );

    const run = await api.getEvalRun(evalRun.id);

    expect(run.reference_cost_per_plan_cents).toBe(52.5);
    expect(run.blocking_findings[0]).toMatchObject({ request_id: "sea-week-family", request_title: "Settimana al mare" });
    expect(run.previous_run?.reference_judge_mean).toBe(4.1);
    expect(run.next_run).toBeNull();

    const older = client(json(200, evalRun));
    const plain = await older.api.getEvalRun(evalRun.id);
    expect(plain).toMatchObject({ reference_judge_mean: null, reference_cost_per_plan_cents: null, blocking_findings: [], previous_run: null, next_run: null });
  });

  it("a run the backend does not have is its own Italian sentence, not 'Questo piano non c'è'", async () => {
    const own = client(json(404, envelope("eval_run_not_found", "Questa valutazione non esiste.")));
    expect((await failure(own.api.getEvalRun(evalRun.id))).message).toBe("Questa valutazione non esiste.");

    const bare = client(new Response("", { status: 404 }));
    expect((await failure(bare.api.getEvalRun(evalRun.id))).message).toBe("Questa valutazione non c'è.");
  });

  it("an older backend without the routes says the history is not available", async () => {
    const { api } = client(json(404, envelope("not_found", "Non c'è.")));

    const error = await failure(api.listEvalRuns());

    expect(error.kind).toBe("not_found");
    expect(error.message).toBe("La cronologia delle valutazioni non è disponibile su questo planner.");
  });

  it("401 sends the browser to the login like every other call", async () => {
    const { api, onUnauthorized } = client(json(401, envelope("not_authenticated", "Accedi.")));

    expect((await failure(api.listEvalRuns())).kind).toBe("unauthorized");
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("a 2xx body that breaks the contract is an invalid response", async () => {
    const { api } = client(json(200, { runs: [{ id: "not-a-uuid" }] }));

    expect((await failure(api.listEvalRuns())).kind).toBe("invalid_response");
  });
});

describe("the returning-visitor mark", () => {
  afterEach(() => localStorage.clear());

  it("is set by a successful authenticated call", async () => {
    const { api } = client(json(200, { plans: [] }));
    await api.listPlans();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBe("1");
  });

  it("is not set by the health check, which needs no sign-in", async () => {
    const { api } = client(json(200, { status: "ok" }));
    await api.health();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
  });

  it("is cleared by a 401, so an expired session sees the landing next time", async () => {
    localStorage.setItem(SIGNED_IN_KEY, "1");
    const { api } = client(json(401, envelope("not_authenticated", "Accedi a TripTracker per usare il planner.")));
    await failure(api.listPlans());
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
  });
});
