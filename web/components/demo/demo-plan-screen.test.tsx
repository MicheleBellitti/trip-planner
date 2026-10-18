import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { BRAND_NAME } from "@/lib/brand";
import { DEMO_REQUEST } from "@/lib/demo/request";
import { REPLAY_TARGET_MS } from "@/lib/demo/schedule";
import { REPLAY_SETTLE_MS } from "@/lib/demo/use-replay-events";
import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import { SETTLE_MS } from "@/components/live/hooks";
import { PLAN_STATE_ID } from "@/components/live/live-header";
import { ROUTES, WAITLIST_HREF } from "@/lib/routes";

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
  // The finished plan's lazy chunk, loaded once outside the fake clock.
  await import("@/components/plan/PlanView");
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

const WHOLE_RUN = REPLAY_SETTLE_MS + REPLAY_TARGET_MS + 2_000;
const finishedPlan = () => screen.queryAllByText(/Cinque giorni a Lisbona/);

describe("DemoPlanScreen", () => {
  it("plays the recorded run by itself to the finished plan, never reaching the backend", async () => {
    render(<DemoPlanScreen />);
    expect(screen.getByText("Corsa dimostrativa: dati di esempio, gratis per te")).toBeTruthy();
    expect(finishedPlan()).toHaveLength(0);
    await advance(WHOLE_RUN);
    expect(finishedPlan().length).toBeGreaterThan(0);
    expect(network.fetch).not.toHaveBeenCalled();
    expect(network.EventSource).not.toHaveBeenCalled();
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
      /Corsa registrata: durata 1:17 · costo 0,41\s\$/,
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
