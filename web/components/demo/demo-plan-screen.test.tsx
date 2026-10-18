import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { DEMO_REQUEST } from "@/lib/demo/request";
import { REPLAY_TARGET_MS } from "@/lib/demo/schedule";
import { REPLAY_SETTLE_MS } from "@/lib/demo/use-replay-events";
import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import { PLAN_STATE_ID } from "@/components/live/live-header";
import { ROUTES } from "@/lib/routes";

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

  it("jumps to the finished plan on 'Salta al piano'", async () => {
    render(<DemoPlanScreen />);
    await advance(REPLAY_SETTLE_MS + 2_000);
    fireEvent.click(screen.getByRole("button", { name: "Salta al piano" }));
    await advance(50);
    expect(finishedPlan().length).toBeGreaterThan(0);
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
    const fast = screen.getByRole("button", { name: "Velocità doppia" });
    expect(fast.textContent).toBe("2×");
    expect(fast.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(fast);
    expect(screen.getByRole("button", { name: "Velocità doppia" }).getAttribute("aria-pressed")).toBe("true");
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
  it("ends with its own ask in the bar: 'Accedi' for a visitor, honest about the invitation", async () => {
    render(<DemoPlanScreen />);
    await advance(WHOLE_RUN);
    const bar = screen.getByRole("group", { name: "Stato del piano" });
    expect(within(bar).getByRole("link", { name: "Accedi" }).getAttribute("href")).toBe(ROUTES.plans);
    expect(within(bar).queryByRole("link", { name: "Pianifica il tuo viaggio" })).toBeNull();
    expect(bar.textContent).toContain("Atlas è su invito");
    expect(document.body.textContent).toContain("Atlas è su invito: con un invito");
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
