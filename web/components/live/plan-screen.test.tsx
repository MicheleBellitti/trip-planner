import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import happyDetailJson from "@/components/plan/__fixtures__/happy-path.detail.json";
import { ApiError, MonthlyLimitError, UnauthorizedError, type ApiClient } from "@/lib/api";
import { BRAND_NAME } from "@/lib/brand";
import { CHOICE_PANEL_ID } from "@/lib/choices";
import budgetReached from "@/lib/plan-events/__fixtures__/backend/budget-reached.json";
import choicesRun from "@/lib/plan-events/__fixtures__/backend/choices.json";
import happyPath from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import mcpFailure from "@/lib/plan-events/__fixtures__/backend/mcp-failure.json";
import { PlanDetailSchema, type PlanDetail, type PlanStatus } from "@/lib/schemas/api";
import { UIEventSchema, type UIEvent } from "@/lib/schemas/generated/ui-event";

import { SETTLE_MS } from "./hooks";
import { PLAN_STATE_ID } from "./live-header";
import { PlanScreen } from "./plan-screen";

// The finished plan, the state panels and the choice panel are lazy chunks (real I/O under the
// fake timers): load them before the tests.
beforeAll(async () => {
  await Promise.all([
    import("@/components/plan/PlanView"),
    import("@/components/states/panels"),
    import("@/components/choice/choice-panel"),
  ]);
});

/** Just enough EventSource for the page: open, messages, errors, `end`. */
class MockEventSource {
  static instances: MockEventSource[] = [];
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private listeners = new Map<string, Set<(event: Event) => void>>();

  constructor(readonly url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: Event) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(listener);
  }

  removeEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.readyState = 2;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  send(event: UIEvent): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event), lastEventId: String(event.seq) }));
  }

  drop(): void {
    this.readyState = 0;
    this.onerror?.(new Event("error"));
  }

  end(status: PlanStatus): void {
    for (const listener of this.listeners.get("end") ?? []) {
      listener(new MessageEvent("end", { data: JSON.stringify({ status }) }));
    }
  }
}

const parse = (fixture: { events: unknown[] }) => fixture.events.map((event) => UIEventSchema.parse(event));
const HAPPY = parse(happyPath);
const BUDGET = parse(budgetReached);
const KIWI = parse(mcpFailure);
/** The recorded run that asks twice: seq 53 asks what to see (seq 56 answers), seq 77 what to eat. */
const CHOICES = parse(choicesRun);
const PLAN_ID = happyPath.plan_id;

function detail(status: PlanStatus, extra: Record<string, unknown> = {}): PlanDetail {
  return PlanDetailSchema.parse({
    id: PLAN_ID,
    status,
    title: "Lisbona, 14–18 apr",
    agent_profile: "development",
    created_at: HAPPY[0]?.ts,
    updated_at: HAPPY[0]?.ts,
    cost_cents: 0,
    budget_cents: 60,
    submit_attempts: 0,
    request: {
      origin: "Milano",
      destination: "Lisbona",
      dates: { exact_start: "2027-04-14", exact_end: "2027-04-18" },
      travelers: [{ kind: "adult" }, { kind: "adult" }, { kind: "child", age: 8 }, { kind: "child", age: 11 }],
      budget_eur: 2400,
    },
    ...extra,
  });
}

function fakeClient(overrides: Partial<Record<keyof ApiClient, unknown>> = {}) {
  const client = {
    createPlan: vi.fn(),
    listPlans: vi.fn(),
    getPlan: vi.fn(),
    getTrip: vi.fn().mockResolvedValue(null),
    interruptPlan: vi.fn(),
    continuePlan: vi.fn(),
    health: vi.fn(),
    eventsUrl: (planId: string, after?: number | null) =>
      `https://api.test/plans/${planId}/events${after === null || after === undefined ? "" : `?after=${after}`}`,
    loginUrl: () => "https://viaggi.test/accedi?returnTo=here",
    ...overrides,
  };
  return client as typeof client & ApiClient;
}

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function stream(): MockEventSource {
  const source = MockEventSource.instances.at(-1);
  if (!source) throw new Error("no stream was opened");
  return source;
}

/** Opens the stream and replays `events` as history, then lets the replay settle. */
async function replay(events: UIEvent[]): Promise<MockEventSource> {
  const source = stream();
  act(() => {
    source.open();
    for (const event of events) source.send(event);
  });
  await flush(SETTLE_MS + 100);
  return source;
}

const liveRegion = () => {
  const regions = document.querySelectorAll("[aria-live]");
  expect(regions).toHaveLength(1);
  return regions[0] as HTMLElement;
};

beforeEach(() => {
  vi.useFakeTimers();
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("PlanScreen, running", () => {
  it("shows the title, the request, the state, the cost and the five lanes in the spec's order", async () => {
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(detail("running")) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(HAPPY.slice(0, 30));

    expect(screen.getByRole("heading", { level: 1, name: "Lisbona, 14–18 apr" })).toBeTruthy();
    expect(screen.getByText("Da Milano, 2 adulti e 2 bambini (8 e 11 anni), budget 2.400 €")).toBeTruthy();
    expect(screen.getByText("In corso")).toBeTruthy();
    // The backend reports the cost when a session turn ends: until then the meter says so.
    expect(screen.getByText("Costo non ancora aggiornato")).toBeTruthy();
    expect(screen.queryByRole("meter")).toBeNull();
    const lanes = screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent?.split(",")[0]);
    expect(lanes).toEqual(["Coordinatore", "Voli", "Alloggio", "Attività", "Spostamenti"]);
    // The waves are named stations on the coordinator's line.
    expect(screen.getByText("Ondata 1")).toBeTruthy();
  });

  it("opens the lane at work on the phone, keeps the others to one line, and toggles by keyboard", async () => {
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(detail("running")) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const call = HAPPY.find((event) => event.kind === "tool" && event.title.startsWith("Expedia · voli"));
    await replay(HAPPY.filter((event) => event.seq <= (call?.seq ?? 0)));

    const toggle = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name},`) });
    expect(toggle("Voli").getAttribute("aria-expanded")).toBe("true");
    expect(toggle("Spostamenti").getAttribute("aria-expanded")).toBe("false");
    // The closed lane's body is out of the tab order.
    const body = document.getElementById(toggle("Spostamenti").getAttribute("aria-controls") ?? "");
    expect(body?.hasAttribute("inert")).toBe(true);
    // The live tool is the plate at the end of the line, with its running time.
    const current = document.querySelector('[data-agent="flights"] li[aria-current="step"]');
    expect(current?.textContent).toContain("Expedia · voli MXP→LIS · 14–18 apr");
    expect(current?.textContent).toContain("in corso da");

    fireEvent.click(toggle("Spostamenti"));
    expect(toggle("Spostamenti").getAttribute("aria-expanded")).toBe("true");
    expect(body?.hasAttribute("inert")).toBe(false);
  });

  describe("the phone's open card while the work moves on", () => {
    /** A browser that reports every lane card on screen (or none): jsdom has no layout. */
    function stubIntersection(onScreen: boolean) {
      vi.stubGlobal(
        "IntersectionObserver",
        class {
          constructor(private readonly callback: (entries: unknown[]) => void) {}
          observe(target: Element) {
            this.callback([{ target, isIntersecting: onScreen, boundingClientRect: { top: 100 } }]);
          }
          disconnect() {}
        },
      );
    }
    const upTo = (seq: number) => HAPPY.filter((event) => event.seq <= seq);
    const toggle = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name},`) });
    const nowRow = () => screen.getByRole("button", { name: /^Ora: / });

    async function openOnFlights() {
      const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(detail("running")) });
      render(<PlanScreen planId={PLAN_ID} client={client} />);
      await flush();
      const source = await replay(upTo(23));
      expect(toggle("Voli").getAttribute("aria-expanded")).toBe("true");
      return source;
    }
    /** Flights deliver (seq 43): the work is elsewhere now. */
    async function moveOn(source: MockEventSource) {
      act(() => {
        for (const event of HAPPY.filter((candidate) => candidate.seq > 23 && candidate.seq <= 43)) source.send(event);
      });
      await flush(50);
    }

    afterEach(() => vi.unstubAllGlobals());

    it("never closes a card that is on screen: a quiet row says where the work is instead", async () => {
      stubIntersection(true);
      const source = await openOnFlights();
      expect(nowRow().textContent).toContain("Voli");
      await moveOn(source);
      expect(toggle("Voli").getAttribute("aria-expanded")).toBe("true");
      expect(nowRow().textContent).not.toContain("Voli");
      expect(nowRow().textContent).toMatch(/Ora: (Alloggio|Attività)/);
      // The row opens that lane on a tap, and the lane stays open: the viewer asked for it.
      const target = nowRow().textContent?.includes("Alloggio") ? "Alloggio" : "Attività";
      vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), media: query, addEventListener: () => {}, removeEventListener: () => {} }));
      Element.prototype.scrollIntoView = vi.fn();
      fireEvent.click(nowRow());
      expect(toggle(target).getAttribute("aria-expanded")).toBe("true");
    });

    it("does not move the open card once the viewer has scrolled, even out of view", async () => {
      stubIntersection(false);
      const source = await openOnFlights();
      act(() => {
        window.dispatchEvent(new Event("wheel"));
      });
      await moveOn(source);
      expect(toggle("Voli").getAttribute("aria-expanded")).toBe("true");
      expect(nowRow().textContent).not.toContain("Voli");
    });

    it("follows the work when nobody has touched the page and the open card is out of view", async () => {
      stubIntersection(false);
      const source = await openOnFlights();
      await moveOn(source);
      expect(toggle("Voli").getAttribute("aria-expanded")).toBe("false");
      expect(nowRow().textContent).toMatch(/Ora: (Alloggio|Attività)/);
      const target = nowRow().textContent?.includes("Alloggio") ? "Alloggio" : "Attività";
      expect(toggle(target).getAttribute("aria-expanded")).toBe("true");
    });
  });

  it("announces lane state changes that happen live, and nothing of the replayed history", async () => {
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(detail("running")) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const flightsDone = HAPPY.find((event) => event.agent === "flights" && event.title === "Turno concluso");
    const source = await replay(HAPPY.filter((event) => event.seq < (flightsDone?.seq ?? 0)));
    expect(liveRegion().textContent).toBe("");

    act(() => {
      if (flightsDone) source.send(flightsDone);
    });
    await flush(100);
    expect(liveRegion().textContent).toBe("Voli: finito");
    // A tool call is never announced.
    const next = HAPPY.find((event) => event.seq > (flightsDone?.seq ?? 0) && event.kind === "tool");
    act(() => {
      if (next) source.send(next);
    });
    await flush(100);
    expect(liveRegion().textContent).toBe("Voli: finito");
  });

  it("interrupts after an inline confirmation and says the plan is stopping", async () => {
    const client = fakeClient({
      getPlan: vi.fn().mockResolvedValue(detail("running")),
      interruptPlan: vi.fn().mockResolvedValue({ id: PLAN_ID, status: "running" }),
    });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(HAPPY.slice(0, 20));

    fireEvent.click(screen.getByRole("button", { name: "Interrompi" }));
    const confirm = screen.getByRole("group", { name: /^Interrompere il piano\?/ });
    expect(document.activeElement?.textContent).toBe("Annulla");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("group", { name: /^Interrompere il piano\?/ })).toBeNull();
    expect(client.interruptPlan).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Interrompi" }));
    fireEvent.click(within(screen.getByRole("group", { name: /^Interrompere/ })).getByRole("button", { name: "Interrompi il piano" }));
    await flush();
    expect(client.interruptPlan).toHaveBeenCalledWith(PLAN_ID);
    expect(screen.getByText("In interruzione")).toBeTruthy();
    expect(confirm.isConnected).toBe(false);
  });

  it("keeps the confirmation open with the reason when the interrupt fails", async () => {
    const client = fakeClient({
      getPlan: vi.fn().mockResolvedValue(detail("running")),
      interruptPlan: vi.fn().mockRejectedValue(new ApiError({ kind: "agents_unavailable", status: 502 })),
    });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(HAPPY.slice(0, 20));
    fireEvent.click(screen.getByRole("button", { name: "Interrompi" }));
    fireEvent.click(screen.getByRole("button", { name: "Interrompi il piano" }));
    await flush();
    expect(screen.getByRole("alert").textContent).toContain("Gli agenti non rispondono");
  });

  it("shows a discreet line while the stream reconnects, and none when it is back", async () => {
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(detail("running")) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(HAPPY.slice(0, 20));
    act(() => source.drop());
    expect(screen.getByText("Stream in riconnessione. Gli eventi persi arrivano da soli.")).toBeTruthy();
    act(() => source.open());
    expect(screen.queryByText(/Stream in riconnessione/)).toBeNull();
  });

  it("marks the last known state as not updated while offline", async () => {
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(detail("running")) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(HAPPY.slice(0, 20));
    online.mockReturnValue(false);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(screen.getByText(/^Non aggiornato: sei offline, ultimo stato alle \d\d:\d\d\./)).toBeTruthy();
    online.mockReturnValue(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(screen.queryByText(/Non aggiornato/)).toBeNull();
  });

  it("puts a source that did not answer on its lane as a notice, not as a plan error", async () => {
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(detail("running")) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(KIWI.filter((event) => event.seq <= 30));
    const flights = document.querySelector('section[data-agent="flights"]') as HTMLElement;
    const notice = within(flights).getByText("Fonte Kiwi.com non raggiungibile: il piano prosegue con le altre fonti");
    expect(notice.closest('[data-tone="warning"]')).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("marks inter-agent messages as English and opens them to the full text", async () => {
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(detail("running")) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(HAPPY.slice(0, 20));
    const flights = document.querySelector('section[data-agent="flights"]') as HTMLElement;
    const summary = within(flights).getByText("coordinatore → voli", { exact: false, selector: "summary *" });
    const details = summary.closest("details");
    expect(details?.querySelector('[lang="en"]')?.textContent).toMatch(/^Find round-trip flights/);
  });
});

describe("PlanScreen, other states", () => {
  it("says how much was spent at the budget and continues with 2 $ more", async () => {
    const paused = detail("budget_paused", { cost_cents: 61, updated_at: BUDGET.at(-1)?.ts });
    let resumed = false;
    const client = fakeClient({
      getPlan: vi.fn(async () =>
        resumed ? detail("running", { budget_cents: 261, cost_cents: 61, updated_at: new Date().toISOString() }) : paused,
      ),
      continuePlan: vi.fn(async () => {
        resumed = true;
        return { id: PLAN_ID, status: "running", budget_cents: 261 };
      }),
    });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(BUDGET.filter((event) => event.seq <= 34));
    expect(screen.getByText(/La sessione ha speso 0,61 \$: il budget di 0,60 \$ è finito/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continua con 2 $ in più" }));
    await flush();
    expect(client.continuePlan).toHaveBeenCalledWith(PLAN_ID);
    expect(screen.queryByRole("button", { name: "Continua con 2 $ in più" })).toBeNull();
    expect(screen.getByText("limite 2,61 $")).toBeTruthy();
  });

  it("at the cap of 'Continua' offers a new plan instead, from the plan detail's counts", async () => {
    // Pinned here, at the screen, so moving the panel's props (PR #15 splits PlanScreen) cannot
    // drop `continues` / `continues_limit` silently.
    const paused = detail("budget_paused", { cost_cents: 61, continues: 2, continues_limit: 2, updated_at: BUDGET.at(-1)?.ts });
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(paused) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(BUDGET.filter((event) => event.seq <= 34));
    expect(screen.getByRole("heading", { name: "Budget della sessione raggiunto" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Continua con 2 $ in più" })).toBeNull();
    expect(screen.getByRole("link", { name: "Crea un nuovo piano" })).toBeTruthy();
    expect(screen.getByText(/ha già avuto 2 volte i suoi 2 \$ in più/)).toBeTruthy();
  });

  it("says the plan's own new state in the live region when a watcher would otherwise miss it", async () => {
    const paused = detail("budget_paused", { cost_cents: 61, updated_at: BUDGET.at(-1)?.ts });
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValueOnce(detail("running")).mockResolvedValue(paused) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(BUDGET.filter((event) => event.seq <= 20));
    expect(liveRegion().textContent).toBe("");
    act(() => {
      for (const event of BUDGET.filter((candidate) => candidate.seq > 20 && candidate.seq <= 34)) source.send(event);
    });
    await flush(800);
    expect(liveRegion().textContent).toContain("Piano: limite raggiunto");
  });

  it("explains the monthly limit (429) and leaves only the interrupt", async () => {
    const paused = detail("budget_paused", { cost_cents: 61 });
    const client = fakeClient({
      getPlan: vi.fn().mockResolvedValue(paused),
      continuePlan: vi.fn().mockRejectedValue(
        new MonthlyLimitError({ status: 429, code: "monthly_limit_reached", data: { spent_cents: 9800, limit_cents: 10000 } }),
      ),
    });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(BUDGET.filter((event) => event.seq <= 34));
    const button = screen.getByRole("button", { name: "Continua con 2 $ in più" });
    fireEvent.click(button);
    await flush();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Limite mensile raggiunto");
    expect(alert.textContent).toContain("Questo mese il planner ha già impegnato 98,00 $ su 100,00 $");
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Interrompi" })).toBeTruthy();
  });

  it("says what happened, what was saved and what can be done when the plan failed", async () => {
    const failed = detail("failed", { failure_reason: "Il piano è stato respinto 3 volte: non superava i controlli.", cost_cents: 32 });
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(failed) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(HAPPY.slice(0, 30));
    act(() => source.end("failed"));
    await flush(500);
    const panel = screen.getByRole("region", { name: "Piano non riuscito" });
    expect(within(panel).getByText("Il piano è stato respinto 3 volte: non superava i controlli.")).toBeTruthy();
    expect(within(panel).getByText(/Costo della sessione: 0,32 \$\./)).toBeTruthy();
    expect(within(panel).getByRole("link", { name: /Crea un nuovo piano/ }).getAttribute("href")).toBe("/new");
    expect(screen.queryByRole("button", { name: "Interrompi" })).toBeNull();
  });

  it("offers to sign in again, back to this page, when the session expired before anything loaded", async () => {
    const client = fakeClient({
      getPlan: vi.fn().mockRejectedValue(new UnauthorizedError({ status: 401 }, "https://viaggi.test/accedi?returnTo=here")),
    });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    expect(screen.getByRole("heading", { name: "Sessione scaduta" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Accedi di nuovo" }).getAttribute("href")).toBe(
      "https://viaggi.test/accedi?returnTo=here",
    );
  });

  it("keeps the last known state when the session expires during the run", async () => {
    const getPlan = vi
      .fn()
      .mockResolvedValueOnce(detail("running"))
      .mockRejectedValue(new UnauthorizedError({ status: 401 }, "https://viaggi.test/accedi?returnTo=here"));
    const client = fakeClient({ getPlan });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(HAPPY.slice(0, 20));
    // The browser gives up on the stream (HTTP 401): the page asks who the user is first.
    act(() => {
      source.readyState = 2;
      source.onerror?.(new Event("error"));
    });
    await flush(2000);
    expect(screen.getByText(/^Sessione scaduta: quello che vedi non si aggiorna più\./)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Accedi di nuovo" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "Lisbona, 14–18 apr" })).toBeTruthy();
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it("says when the plan does not exist", async () => {
    const client = fakeClient({ getPlan: vi.fn().mockRejectedValue(new ApiError({ kind: "not_found", status: 404 })) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    expect(screen.getByRole("heading", { name: "Questo piano non c'è" })).toBeTruthy();
  });

  it("shows the finished plan with the run's timeline closed under it", async () => {
    const ready = PlanDetailSchema.parse({ ...structuredClone(happyDetailJson), id: PLAN_ID });
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(ready) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(HAPPY);
    act(() => source.end("ready"));
    await flush(500);
    expect(screen.getByRole("heading", { level: 2, name: "Prenotazioni" })).toBeTruthy();
    const run = screen.getByText("Il lavoro degli agenti").closest("details");
    expect(run?.open).toBe(false);
    expect(run?.querySelectorAll("section[data-agent]")).toHaveLength(5);
    expect(screen.getByText("Pronto")).toBeTruthy();
  });

  it("brings the plan into view and focuses its summary when it arrives under someone watching the run", async () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    const ready = PlanDetailSchema.parse({ ...structuredClone(happyDetailJson), id: PLAN_ID });
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValueOnce(detail("running")).mockResolvedValue(ready) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(HAPPY.slice(0, 60));
    expect(screen.queryByRole("heading", { level: 2, name: "Sintesi del piano" })).toBeNull();
    act(() => source.end("ready"));
    await flush(500);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: "Sintesi del piano" }));
    // The one live region still speaks lane states only.
    expect(document.querySelectorAll("[aria-live]")).toHaveLength(1);
    vi.unstubAllGlobals();
  });

  it("does not move the focus when a finished plan is simply opened", async () => {
    const ready = PlanDetailSchema.parse({ ...structuredClone(happyDetailJson), id: PLAN_ID });
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(ready) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush(500);
    expect(screen.getByRole("heading", { level: 2, name: "Prenotazioni" })).toBeTruthy();
    expect(document.activeElement).toBe(document.body);
  });

  it("says a blocked plan's agent and tool, and stops the lane it waited on", async () => {
    const blocked = PlanDetailSchema.parse({
      ...structuredClone(happyDetailJson),
      id: PLAN_ID,
      status: "blocked",
      plan: null,
      failure_reason: "Gli agenti aspettano una conferma che nessuno darà.",
    });
    const client = fakeClient({ getPlan: vi.fn().mockResolvedValue(blocked) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const at = (second: number) => `2026-10-12T10:00:${String(second).padStart(2, "0")}+02:00`;
    const make = (seq: number, agent: UIEvent["agent"], kind: UIEvent["kind"], title: string, detailValue: UIEvent["detail"]): UIEvent => ({
      seq,
      ts: at(seq),
      agent,
      kind,
      title,
      detail: detailValue,
      cost_cents: null,
    });
    await replay([
      make(0, "coordinator", "status", "Piano avviato", null),
      make(1, "flights", "status", "Incarico a voli", { event_type: "session.thread_created", lane_state: "working" }),
      make(2, "flights", "tool", "lastminute.com · voli MXP→LIS · 14–18 apr (attende conferma)", {
        event_type: "agent.mcp_tool_use",
        server: "lastminute",
        tool_use_id: "t1",
      }),
      make(3, "flights", "status", "In attesa di una risposta", {
        event_type: "session.thread_status_idle",
        stop_reason: "requires_action",
        event_ids: ["t1"],
        lane_state: "waiting",
      }),
    ]);
    expect(
      screen.getByText(
        "L'agente Voli aspettava il permesso per usare lastminute.com, che questa app non può dare. Il piano non può continuare.",
      ),
    ).toBeTruthy();
    const flights = document.querySelector('section[data-agent="flights"]') as HTMLElement;
    expect(flights.dataset.state).toBe("stopped");
    expect(within(flights).getByText("Aspettava il permesso per usare lastminute.com.")).toBeTruthy();
  });
});

describe("PlanScreen, the traveller's choice", () => {
  const ASKED = CHOICES.find((event) => event.seq === 53);
  if (!ASKED || ASKED.detail?.phase !== "asked") throw new Error("choices.json lost its first question");
  /** The backend's PendingChoice, as GET /plans/{id} carries it while the question waits. */
  const PENDING = ASKED.detail.choice as { id: string; asked_at: string; deadline_at: string };
  const CHOICE_ID = PENDING.id;
  const ASKED_AT = Date.parse(PENDING.asked_at);
  const QUESTION = "Cosa ti va di vedere?";
  const TITLE = "Lisbona, 14–18 apr";

  const upTo = (seq: number) => CHOICES.filter((event) => event.seq <= seq);
  const between = (from: number, to: number) => CHOICES.filter((event) => event.seq >= from && event.seq <= to);
  const panel = () => screen.queryByRole("region", { name: QUESTION });
  const heading = () => screen.getByRole("heading", { level: 2, name: QUESTION });
  const box = (name: string) => screen.getByRole("checkbox", { name });
  const coordinator = () => document.querySelector('section[data-agent="coordinator"]') as HTMLElement;

  /** The run's own plan: it starts with the recording, and the question may be waiting. */
  function running(extra: Record<string, unknown> = {}): PlanDetail {
    return detail("running", { created_at: CHOICES[0]?.ts, updated_at: CHOICES[0]?.ts, ...extra });
  }

  // Ten seconds into the first question's four minutes.
  beforeEach(() => {
    vi.setSystemTime(ASKED_AT + 10_000);
  });

  it("shows the cards when the question arrives, focuses the heading, and prefixes the tab title 'Tocca a te ·'", async () => {
    const client = fakeClient({ getPlan: vi.fn(async () => running()) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(upTo(52));
    expect(panel()).toBeNull();
    expect(document.title).toBe(`${TITLE} · ${BRAND_NAME}`);

    act(() => {
      for (const event of between(53, 55)) source.send(event);
    });
    await flush(100);
    expect(panel()?.id).toBe(CHOICE_PANEL_ID);
    expect(document.activeElement).toBe(heading());
    // The eyebrow names the request's destination.
    expect(screen.getByText("Attività ha trovato 3 idee per Lisbona")).toBeTruthy();
    expect(screen.getByText("Scegli quelle che ti piacciono, anche più di una. Se non scegli entro 4 minuti, scelgo io.")).toBeTruthy();
    expect(document.title).toBe(`Tocca a te · ${TITLE} · ${BRAND_NAME}`);
  });

  it("sends the picks and hides the cards at once; the answered event then draws the station", async () => {
    const answerChoice = vi.fn().mockResolvedValue({ id: CHOICE_ID, answered_by: "traveller", selected: ["a1", "a2"] });
    const client = fakeClient({ getPlan: vi.fn(async () => running()), answerChoice });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(upTo(55));
    expect(panel()).not.toBeNull();

    fireEvent.click(box("Oceanário de Lisboa"));
    fireEvent.click(box("Palácio da Pena a Sintra"));
    fireEvent.click(screen.getByRole("button", { name: "Continua con queste" }));
    await flush(50);
    expect(answerChoice).toHaveBeenCalledTimes(1);
    expect(answerChoice).toHaveBeenCalledWith(PLAN_ID, CHOICE_ID, { selected: ["a1", "a2"] });
    // Gone before the stream confirms it; the focus lands on the plan's state, not on the body.
    expect(panel()).toBeNull();
    expect(document.activeElement?.id).toBe(PLAN_STATE_ID);
    expect(document.title).toBe(`${TITLE} · ${BRAND_NAME}`);

    act(() => {
      for (const event of between(56, 58)) source.send(event);
    });
    await flush(100);
    // The station on the coordinator's line, and its line under the name (its receipt while the
    // card is closed on the phone).
    expect(within(coordinator()).getAllByText("Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra")).toHaveLength(2);
    expect(panel()).toBeNull();
    // A screen reader hears the answer land, through the page's one live region.
    expect(liveRegion().textContent).toContain("Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra");
  });

  it("moves the focus to the plan's state without scrolling the page once the answer went", async () => {
    // The state sits in the sticky header, on screen while the plan runs: a plain focus() would
    // throw the page to its top (Chrome scrolls to a sticky element's place in the flow).
    const answerChoice = vi.fn().mockResolvedValue({ id: CHOICE_ID, answered_by: "skip", selected: [] });
    const client = fakeClient({ getPlan: vi.fn(async () => running()), answerChoice });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(upTo(55));
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    try {
      fireEvent.click(screen.getByRole("button", { name: "Scegli tu" }));
      await flush(50);
      expect(answerChoice).toHaveBeenCalledWith(PLAN_ID, CHOICE_ID, { skip: true });
      expect(document.activeElement?.id).toBe(PLAN_STATE_ID);
      const toState = focus.mock.contexts.findIndex((element) => (element as HTMLElement).id === PLAN_STATE_ID);
      expect(focus.mock.calls[toState]).toEqual([{ preventScroll: true }]);
    } finally {
      focus.mockRestore();
    }
  });

  it("shows the cards from GET /plans/{id} before the stream opens", async () => {
    // Every read is the same stale snapshot: the question still pending.
    const getPlan = vi.fn(async () => running({ pending_choice: PENDING }));
    const client = fakeClient({ getPlan });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    expect(stream().readyState).toBe(0);
    expect(panel()?.id).toBe(CHOICE_PANEL_ID);
    expect(document.activeElement).toBe(heading());
    expect(document.title).toBe(`Tocca a te · ${TITLE} · ${BRAND_NAME}`);

    // The replay brings the answer: the cards go, and the snapshot read again never brings them back.
    await replay(upTo(60));
    await flush(1000);
    expect(getPlan.mock.calls.length).toBeGreaterThan(1);
    expect(panel()).toBeNull();
    expect(document.title).toBe(`${TITLE} · ${BRAND_NAME}`);
  });

  /** What the countdown says, its hidden words included. */
  const countdown = () => screen.getByText("Tempo per scegliere:", { exact: false }).parentElement?.textContent;

  it("counts a question that arrives live from when the page shows it: a browser clock 5 minutes fast still gets the whole window", async () => {
    vi.setSystemTime(Date.parse(PENDING.deadline_at) + 5 * 60_000);
    const client = fakeClient({ getPlan: vi.fn(async () => running()) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(upTo(52));

    act(() => {
      for (const event of between(53, 55)) source.send(event);
    });
    await flush(100);
    expect(panel()).not.toBeNull();
    expect(countdown()).toBe("Tempo per scegliere: 4:00");
    expect(screen.queryByText("Tempo scaduto: scelgo io.")).toBeNull();
    fireEvent.click(box("Oceanário de Lisboa"));
    expect((box("Oceanário de Lisboa") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("button", { name: "Scegli tu" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Continua con questa" }) as HTMLButtonElement).disabled).toBe(false);

    // It counts down from there, and the page says the last minute on the same clock.
    await flush(60_000);
    expect(countdown()).toBe("Tempo per scegliere: 3:00");
    expect(liveRegion().textContent).not.toContain("Manca un minuto per scegliere.");
    await flush(120_000);
    expect(liveRegion().textContent).toContain("Manca un minuto per scegliere.");
    // At zero the controls rest, as ever.
    await flush(60_000);
    expect(screen.getByText("Tempo scaduto: scelgo io.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Scegli tu" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps the backend's deadline_at for a question first seen in the snapshot or the replayed history", async () => {
    // A minute into the question's four.
    vi.setSystemTime(ASKED_AT + 60_000);
    const client = fakeClient({ getPlan: vi.fn(async () => running({ pending_choice: PENDING })) });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    expect(panel()).not.toBeNull();
    expect(countdown()).toBe("Tempo per scegliere: 3:00");
    // The replay brings its asked event (a new object, the same id): still the backend's deadline.
    await replay(upTo(55));
    expect(countdown()).toMatch(/^Tempo per scegliere: (3:00|2:59)$/);
    cleanup();

    // Without the snapshot, a question that comes with the replayed history: the same.
    const replayed = fakeClient({ getPlan: vi.fn(async () => running()) });
    render(<PlanScreen planId={PLAN_ID} client={replayed} />);
    await flush();
    await replay(upTo(55));
    expect(panel()).not.toBeNull();
    expect(countdown()).toMatch(/^Tempo per scegliere: (3:00|2:59)$/);
  });

  it("a 404 choice_not_found closes the panel with the backend's words; a 404 plan_not_found is an error", async () => {
    const getPlan = vi.fn(async () => running());
    const answerChoice = vi.fn().mockRejectedValue(
      new ApiError({ kind: "not_found", status: 404, code: "choice_not_found", message: "Questa domanda non c'è." }),
    );
    const client = fakeClient({ getPlan, answerChoice });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(upTo(55));
    await flush(1000);
    const reads = getPlan.mock.calls.length;

    fireEvent.click(box("Oceanário de Lisboa"));
    fireEvent.click(screen.getByRole("button", { name: "Continua con questa" }));
    await flush(50);
    const region = panel();
    expect(region).not.toBeNull();
    expect(within(region!).getByText("Questa domanda non c'è.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Scegli tu" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    // The page catches up with the plan.
    expect(getPlan.mock.calls.length).toBe(reads + 1);
    cleanup();

    const gone = fakeClient({
      getPlan: vi.fn(async () => running()),
      answerChoice: vi.fn().mockRejectedValue(
        new ApiError({ kind: "not_found", status: 404, code: "plan_not_found", message: "Questo piano non c'è." }),
      ),
    });
    render(<PlanScreen planId={PLAN_ID} client={gone} />);
    await flush();
    await replay(upTo(55));
    fireEvent.click(box("Oceanário de Lisboa"));
    fireEvent.click(screen.getByRole("button", { name: "Continua con questa" }));
    await flush(50);
    expect(screen.getByRole("alert").textContent).toContain("Questo piano non c'è.");
    expect(screen.getByRole("button", { name: "Scegli tu" })).toBeTruthy();
  });

  it("a 409 choice_closed closes the panel with the backend's words", async () => {
    const getPlan = vi.fn(async () => running());
    const answerChoice = vi.fn().mockRejectedValue(
      new ApiError({
        kind: "conflict",
        status: 409,
        code: "choice_closed",
        message: "Questa scelta è già chiusa: il piano va avanti.",
        data: { answered_by: "timeout" },
      }),
    );
    const client = fakeClient({ getPlan, answerChoice });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    await replay(upTo(55));
    await flush(1000);
    const reads = getPlan.mock.calls.length;

    fireEvent.click(box("Oceanário de Lisboa"));
    fireEvent.click(screen.getByRole("button", { name: "Continua con questa" }));
    await flush(50);
    const region = panel();
    expect(region).not.toBeNull();
    expect(within(region!).getByText("Questa scelta è già chiusa: il piano va avanti.")).toBeTruthy();
    // No buttons to press again, and never a generic error.
    expect(screen.queryByRole("button", { name: "Scegli tu" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Continua con quest[ae]$/ })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    // The page catches up with the plan.
    expect(getPlan.mock.calls.length).toBe(reads + 1);
  });

  it("hides the cards while interrupting and on budget_paused, and shows them again after Continua", async () => {
    const pausedAt = new Date(ASKED_AT + 2_000).toISOString();
    const resumedAt = new Date(ASKED_AT + 5_000).toISOString();
    let phase: "running" | "paused" | "resumed" = "running";
    const client = fakeClient({
      getPlan: vi.fn(async () => {
        if (phase === "paused") return detail("budget_paused", { created_at: CHOICES[0]?.ts, cost_cents: 61, updated_at: pausedAt });
        if (phase === "resumed") return running({ budget_cents: 261, cost_cents: 61, updated_at: resumedAt, pending_choice: PENDING });
        return running({ pending_choice: PENDING });
      }),
      continuePlan: vi.fn(async () => {
        phase = "resumed";
        return { id: PLAN_ID, status: "running", budget_cents: 261 };
      }),
      interruptPlan: vi.fn().mockResolvedValue({ id: PLAN_ID, status: "running" }),
    });
    render(<PlanScreen planId={PLAN_ID} client={client} />);
    await flush();
    const source = await replay(upTo(55));
    expect(panel()).not.toBeNull();

    // The session stops at its cost cap: the cards go with the run.
    phase = "paused";
    act(() => {
      source.send({
        seq: 56,
        ts: pausedAt,
        agent: "coordinator",
        kind: "status",
        title: "Fermo: budget della sessione raggiunto",
        detail: { event_type: "session.status_idle", stop_reason: "budget_reached", lane_state: "waiting" },
        cost_cents: 61,
      });
    });
    await flush(1000);
    expect(screen.getByRole("heading", { name: "Budget della sessione raggiunto" })).toBeTruthy();
    expect(panel()).toBeNull();
    expect(document.title).toBe(`${TITLE} · ${BRAND_NAME}`);

    // "Continua": the same question is back, with its own deadline.
    fireEvent.click(screen.getByRole("button", { name: "Continua con 2 $ in più" }));
    await flush(100);
    expect(panel()).not.toBeNull();
    expect(screen.getByText("Scegli quelle che ti piacciono, anche più di una. Se non scegli entro 4 minuti, scelgo io.")).toBeTruthy();
    expect(screen.getByText("Tempo per scegliere:", { exact: false }).parentElement?.textContent).toMatch(
      /^Tempo per scegliere: 3:4\d$/,
    );
    expect(document.title).toBe(`Tocca a te · ${TITLE} · ${BRAND_NAME}`);

    // "Interrompi il piano": the cards go as soon as it is confirmed, before the plan stops.
    fireEvent.click(screen.getByRole("button", { name: "Interrompi" }));
    fireEvent.click(screen.getByRole("button", { name: "Interrompi il piano" }));
    await flush(50);
    expect(screen.getByText("In interruzione")).toBeTruthy();
    expect(panel()).toBeNull();
    expect(document.title).toBe(`${TITLE} · ${BRAND_NAME}`);
  });
});
