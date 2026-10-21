import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { BRAND_NAME } from "@/lib/brand";
import { DEMO_REQUEST } from "@/lib/demo/request";
import { REPLAY_TARGET_MS, replaySchedule } from "@/lib/demo/schedule";
import { AUTO_PICK_SHOW_MS, DEMO_CHOICE_WINDOW_MS, REPLAY_SETTLE_MS } from "@/lib/demo/use-replay-events";
import backend from "@/lib/plan-events/__fixtures__/backend/choices.json";
import { SETTLE_MS } from "@/components/live/hooks";
import { PLAN_STATE_ID } from "@/components/live/live-header";
import { ROUTES, WAITLIST_HREF } from "@/lib/routes";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { DemoPlanScreen } from "./demo-plan-screen";

// The demo never reaches the backend: neither API client may even be evaluated (spec, "Demo").
vi.mock("@/lib/api", () => {
  throw new Error("@/lib/api evaluated");
});
vi.mock("@/components/live/live-api", () => {
  throw new Error("live-api evaluated");
});

const network = { fetch: vi.fn(), EventSource: vi.fn() };

beforeAll(async () => {
  // The finished plan's and the choice's lazy chunks, loaded once outside the fake clock.
  await Promise.all([import("@/components/plan/PlanView"), import("@/components/choice/choice-panel")]);
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", network.fetch);
  vi.stubGlobal("EventSource", network.EventSource);
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
  vi.unstubAllGlobals();
  network.fetch.mockReset();
  network.EventSource.mockReset();
});

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** The recording replayed: the compressed schedule, and each of its two questions held for its
 * window and the recorded picks. */
const EVENTS = backend.events as unknown as UIEvent[];
const OFFSETS = replaySchedule(EVENTS);
const at = (seq: number) => OFFSETS[EVENTS.findIndex((event) => event.seq === seq)]!;
const HOLD = DEMO_CHOICE_WINDOW_MS + AUTO_PICK_SHOW_MS;
const WHOLE_RUN = REPLAY_SETTLE_MS + REPLAY_TARGET_MS + 2 * HOLD + 2_000;
const finishedPlan = () => screen.queryAllByText(/Cinque giorni a Lisbona/);
const SEE = "Cosa ti va di vedere?";
const EAT = "Che cucina cerchi?";
const question = (name: string) => screen.queryByRole("region", { name });
const coordinator = () => document.querySelector('section[data-agent="coordinator"]') as HTMLElement;
const DEMO_RULE = "Se non scegli entro 15 secondi, la corsa prosegue con le scelte registrate.";
const PAGE_TITLE = `Corsa dimostrativa · ${BRAND_NAME}`;

describe("DemoPlanScreen", () => {
  it("plays the whole recording by itself, pausing on both questions, to the finished plan, never reaching the backend", async () => {
    document.title = PAGE_TITLE;
    render(<DemoPlanScreen />);
    expect(screen.getByText("Corsa dimostrativa: dati di esempio, gratis per te")).toBeTruthy();
    expect(finishedPlan()).toHaveLength(0);

    // The first question: the cards, and the tab says it is the visitor's turn.
    await advance(REPLAY_SETTLE_MS + at(53) + 100);
    expect(question(SEE)).not.toBeNull();
    expect(document.title).toBe(`Tocca a te · ${PAGE_TITLE}`);
    // It waits for the visitor (the coordinator's waiting idle lands, the answer does not)...
    await advance(DEMO_CHOICE_WINDOW_MS - 1_000);
    expect(question(SEE)).not.toBeNull();
    expect(coordinator().textContent).not.toContain("Hai scelto");
    // ...then the recording picks, and its answer becomes the coordinator's station.
    await advance(AUTO_PICK_SHOW_MS + 1_000);
    expect(question(SEE)).toBeNull();
    expect(coordinator().textContent).toContain("Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra");
    expect(document.title).toBe(PAGE_TITLE);

    // The second question, the same way.
    await advance(at(77) - at(56));
    expect(question(EAT)).not.toBeNull();
    expect(document.title).toBe(`Tocca a te · ${PAGE_TITLE}`);
    await advance(HOLD + 100);
    expect(question(EAT)).toBeNull();
    expect(coordinator().textContent).toContain("Hai scelto: Tascas di quartiere, Pesce alla griglia");
    expect(document.title).toBe(PAGE_TITLE);

    await advance(WHOLE_RUN);
    expect(finishedPlan().length).toBeGreaterThan(0);
    expect(network.fetch).not.toHaveBeenCalled();
    expect(network.EventSource).not.toHaveBeenCalled();
  });

  it("a visitor's picks become the coordinator's station, and the notice says the plan does not change", async () => {
    render(<DemoPlanScreen />);
    await advance(REPLAY_SETTLE_MS + at(53) + 100);
    fireEvent.click(screen.getByRole("checkbox", { name: "Torre di Belém e Mosteiro dos Jerónimos" }));
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    fireEvent.click(screen.getByRole("button", { name: "Continua con questa" }));
    await advance(50);
    expect(question(SEE)).toBeNull();
    expect(coordinator().textContent).toContain("Hai scelto: Torre di Belém e Mosteiro dos Jerónimos");
    expect(document.activeElement?.id).toBe(PLAN_STATE_ID);
    // The state is in the sticky header: the focus must not scroll the page away from the work.
    const toState = focus.mock.contexts.findIndex((element) => (element as HTMLElement).id === PLAN_STATE_ID);
    expect(focus.mock.calls[toState]).toEqual([{ preventScroll: true }]);
    focus.mockRestore();

    await advance(WHOLE_RUN);
    expect(finishedPlan().length).toBeGreaterThan(0);
    expect(document.body.textContent).toContain(
      "Una corsa registrata: prezzi e disponibilità sono un esempio, e le scelte non cambiano il piano. I link portano ai siti veri.",
    );
  });

  it("the countdown shows 0:15 and the demo's rule, and both go once a card is picked", async () => {
    render(<DemoPlanScreen />);
    await advance(REPLAY_SETTLE_MS + at(53));
    const panel = question(SEE)!;
    expect(panel.textContent).toContain("Tempo per scegliere: 0:15");
    expect(within(panel).getByText(`Scegli quelle che ti piacciono, anche più di una. ${DEMO_RULE}`)).toBeTruthy();
    // At 2× too, it counts down in real seconds (the clock ticks every 250 ms: a little past 5 s).
    fireEvent.click(screen.getByRole("button", { name: "2×, velocità doppia" }));
    await advance(5_250);
    expect(panel.textContent).toContain("Tempo per scegliere: 0:10");

    fireEvent.click(screen.getByRole("checkbox", { name: "Oceanário de Lisboa" }));
    expect(panel.textContent).not.toContain("Tempo per scegliere");
    expect(within(panel).getByText("Scegli quelle che ti piacciono, anche più di una.")).toBeTruthy();
    // The replay now waits for the visitor, however long they take.
    await advance(60_000);
    expect(question(SEE)).not.toBeNull();
    expect(coordinator().textContent).not.toContain("Hai scelto");
  });

  it("lands the recorded answers on 'Salta al piano' during a question, and gives the tab its title back", async () => {
    document.title = PAGE_TITLE;
    render(<DemoPlanScreen />);
    await advance(REPLAY_SETTLE_MS + at(53) + 2_000);
    expect(document.title).toBe(`Tocca a te · ${PAGE_TITLE}`);
    fireEvent.click(screen.getByRole("button", { name: "Salta al piano" }));
    await advance(50);
    expect(finishedPlan().length).toBeGreaterThan(0);
    expect(question(SEE)).toBeNull();
    expect(document.title).toBe(PAGE_TITLE);
  });

  it("leaves alone a tab title the next page set while a question waited", async () => {
    document.title = PAGE_TITLE;
    const { unmount } = render(<DemoPlanScreen />);
    await advance(REPLAY_SETTLE_MS + at(53) + 100);
    expect(document.title).toBe(`Tocca a te · ${PAGE_TITLE}`);
    // A client-side navigation: the next page names the tab before the demo lets go of it.
    document.title = `Nuovo piano · ${BRAND_NAME}`;
    unmount();
    expect(document.title).toBe(`Nuovo piano · ${BRAND_NAME}`);
  });

  it("draws in the very first replayed station: it lands after the live baseline settles", async () => {
    render(<DemoPlanScreen />);
    // The baseline's moment, then the replay's first tick, each in its own step (React renders
    // between them, as a browser does between timers that are not due together). Were both due in
    // the same millisecond, the baseline would count the first events as history: the first
    // stations would not draw in (and a lane change among them would go unspoken).
    await advance(SETTLE_MS + 1);
    await advance(REPLAY_SETTLE_MS - SETTLE_MS + 50);
    expect(document.querySelectorAll("[class*='animate-arrive']").length).toBeGreaterThan(0);
  });

  it("jumps to the finished plan on 'Salta al piano'", async () => {
    render(<DemoPlanScreen />);
    await advance(REPLAY_SETTLE_MS + 2_000);
    fireEvent.click(screen.getByRole("button", { name: "Salta al piano" }));
    await advance(50);
    expect(finishedPlan().length).toBeGreaterThan(0);
  });

  it("after 'Ricomincia', draws the run again and announces it live", async () => {
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    fireEvent.click(screen.getByRole("button", { name: "Ricomincia" }));
    // In steps, as time passes: the live baseline settles between them, as it does in a browser.
    for (let step = 0; step < 4; step += 1) await advance(2_000);
    const live = document.querySelector("[aria-live='polite']");
    expect(live?.textContent).toMatch(/: al lavoro/);
    // From the start again: a few seconds in, at the first wave.
    expect(document.body.textContent).toMatch(/Trascorsi 0:0\d/);
    expect(document.body.textContent).toContain("Ondata 1");
  });

  it("runs twice as fast once '2×' is pressed mid-run", async () => {
    render(<DemoPlanScreen />);
    await advance(REPLAY_SETTLE_MS + 5_000);
    fireEvent.click(screen.getByRole("button", { name: "2×, velocità doppia" }));
    await advance(5_000);
    // 5 s at 1× and 5 s at 2×: about 15 s of the run.
    const elapsed = /Trascorsi 0:(\d+)/.exec(document.body.textContent ?? "");
    expect(Number(elapsed?.[1])).toBeGreaterThanOrEqual(14);
    expect(Number(elapsed?.[1])).toBeLessThanOrEqual(16);
  });

  it("starts again from the first station on 'Ricomincia'", async () => {
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    fireEvent.click(screen.getByRole("button", { name: "Ricomincia" }));
    await advance(50);
    expect(finishedPlan()).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Salta al piano" })).toBeTruthy();
    await advance(WHOLE_RUN);
    expect(finishedPlan().length).toBeGreaterThan(0);
    expect(network.fetch).not.toHaveBeenCalled();
  });

  it("has one theme toggle, the run's own (the public header leaves it to the control bar)", () => {
    render(<DemoPlanScreen />);
    expect(screen.getAllByRole("button", { name: /tema/ })).toHaveLength(1);
  });

  it("toggles 2× as a pressed button", async () => {
    render(<DemoPlanScreen />);
    const fast = screen.getByRole("button", { name: "2×, velocità doppia" });
    expect(fast.textContent).toBe("2×");
    expect(fast.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(fast);
    expect(screen.getByRole("button", { name: "2×, velocità doppia" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("tells the request the run was given: the header, the coordinator and the budget agree", async () => {
    render(<DemoPlanScreen />);
    expect(document.body.textContent).toMatch(/2 bambini \(9 e 6 anni\), budget 2\.800\s€/);
    await advance(WHOLE_RUN);
    expect(document.body.textContent).toMatch(/sotto il budget di 2\.800\s€/);
  });

  it("is the request recorded in the run's first message", () => {
    const text = (backend.events[1]!.detail as { text: string }).text;
    const recorded = JSON.parse(/```json\n([\s\S]*?)\n```/.exec(text)![1]!) as {
      travelers: { kind: string; age?: number }[];
      budget_eur: number;
      preferences: string;
      dates: { exact_start: string; exact_end: string };
    };
    expect(DEMO_REQUEST.travelers.map((t) => t.age ?? null)).toEqual(recorded.travelers.map((t) => t.age ?? null));
    expect(DEMO_REQUEST.budget_eur).toBe(recorded.budget_eur);
    expect(DEMO_REQUEST.preferences).toBe(recorded.preferences);
    expect(DEMO_REQUEST.dates.exact_start).toBe(recorded.dates.exact_start);
    expect(DEMO_REQUEST.dates.exact_end).toBe(recorded.dates.exact_end);
  });

  it("ends with no TripTracker link and the example-prices notice", async () => {
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    expect(screen.queryByRole("link", { name: /TripTracker/ })).toBeNull();
    expect(document.body.textContent).toContain("prezzi e disponibilità sono un esempio");
  });
  it("ends with its own ask in the bar: the waitlist for a visitor, honest about the invitation", async () => {
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    const bar = screen.getByRole("group", { name: "Stato del piano" });
    expect(within(bar).getByRole("link", { name: "Mettiti in lista" }).getAttribute("href")).toBe(WAITLIST_HREF);
    expect(within(bar).queryByRole("link", { name: "Pianifica il tuo viaggio" })).toBeNull();
    expect(bar.textContent).toContain(`${BRAND_NAME} è su invito`);
  });

  it("hands a visitor the waitlist and the invited 'Accedi', and never names TripTracker", async () => {
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    expect(document.body.textContent).toContain(
      `${BRAND_NAME} è su invito. Mettiti in lista e ti scriviamo quando c'è posto; se hai già un invito, accedi.`,
    );
    const handoff = screen.getAllByRole("region", { name: "Il tuo viaggio" });
    for (const region of handoff) expect(region.textContent).not.toContain("TripTracker");
    const waitlist = screen.getAllByRole("link", { name: "Mettiti in lista" });
    for (const link of waitlist) expect(link.getAttribute("href")).toBe(WAITLIST_HREF);
    const signIn = screen.getAllByRole("link", { name: "Accedi" });
    expect(signIn.length).toBeGreaterThan(0);
    for (const link of signIn) expect([ROUTES.login, ROUTES.plans]).toContain(link.getAttribute("href"));
    expect(signIn.some((link) => link.getAttribute("href") === ROUTES.login)).toBe(true);
  });

  it("offers 'Pianifica il tuo viaggio' to a browser that has signed in before", async () => {
    localStorage.setItem("atlas-signed-in", "1");
    try {
      render(<DemoPlanScreen />);
      await advance(WHOLE_RUN);
      const bar = screen.getByRole("group", { name: "Stato del piano" });
      expect(within(bar).getByRole("link", { name: "Pianifica il tuo viaggio" }).getAttribute("href")).toBe(ROUTES.newPlan);
    } finally {
      localStorage.removeItem("atlas-signed-in");
    }
  });

  it("gives the recorded run's real duration when it ends, not the replay's", async () => {
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    expect(screen.getByRole("group", { name: "Stato del piano" }).textContent).toMatch(
      /Corsa registrata: durata 1:33 · costo 0,41\s\$/,
    );
  });

  it("reads the deadlines on the recording's date, so the showcase never goes stale", async () => {
    vi.setSystemTime(Date.parse("2027-03-01T10:00:00+01:00"));
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    expect(document.body.textContent).not.toMatch(/Scadenza passata|In scadenza/);
  });

  it("brings the focus back to the plan's state after 'Ricomincia'", async () => {
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    fireEvent.click(screen.getByRole("button", { name: "Ricomincia" }));
    await advance(50);
    expect(document.activeElement?.id).toBe(PLAN_STATE_ID);
  });
});
