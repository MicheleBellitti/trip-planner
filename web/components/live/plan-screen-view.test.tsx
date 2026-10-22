import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChoiceControls } from "@/components/choice/choice-panel";
import detailJson from "@/components/plan/__fixtures__/happy-path.detail.json";
import tripJson from "@/components/plan/__fixtures__/happy-path.trip.json";
import { readAskedChoice, readChoiceAnswer } from "@/lib/choices";
import choicesRun from "@/lib/plan-events/__fixtures__/backend/choices.json";
import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import { planEventsReducer, reducePlanEvents, type PlanLiveState } from "@/lib/plan-events/reducer";
import { PlanDetailSchema } from "@/lib/schemas/api";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { SETTLE_MS } from "./hooks";
import { PLAN_STATE_ID } from "./live-header";
import { PlanScreenView } from "./plan-screen-view";

// The view is shared with the demo, which must never reach the backend: neither API client may
// even be evaluated in its module graph.
vi.mock("@/lib/api", () => {
  throw new Error("@/lib/api evaluated");
});
vi.mock("@/components/live/live-api", () => {
  throw new Error("live-api evaluated");
});
// The answer reader, watched: how often the view reads the answered events.
vi.mock("@/lib/choices", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/choices")>();
  return { ...original, readChoiceAnswer: vi.fn(original.readChoiceAnswer) };
});

afterEach(cleanup);

const events = backend.events as unknown as UIEvent[];
const first = events[0]!.ts;
const snapshot = {
  status: "running" as const,
  cost_cents: 0,
  budget_cents: 60,
  created_at: first,
  updated_at: first,
  failure_reason: null,
  submit_attempts: 0,
};

describe("PlanScreenView", () => {
  it("draws a running plan's lanes under the header it is given, without any API client", () => {
    const state = reducePlanEvents(events.slice(0, 40), { detail: snapshot });
    render(
      <PlanScreenView
        state={state}
        detail={null}
        clock={Date.parse(events[39]!.ts)}
        stale={false}
        connection="open"
        header={<div data-testid="header" />}
      />,
    );
    expect(screen.getByTestId("header")).toBeTruthy();
    expect(screen.getAllByText("Coordinatore").length).toBeGreaterThan(0);
  });

  it("draws the finished plan from the detail and trip it is given, the cover from its loader", async () => {
    const state = reducePlanEvents(events, { detail: snapshot, end: "ready" });
    const detail = PlanDetailSchema.parse(detailJson);
    const loadCover = vi.fn(async () => null);
    render(
      <PlanScreenView
        state={state}
        detail={detail}
        clock={Date.parse(events.at(-1)!.ts)}
        stale={false}
        connection="closed"
        header={<div />}
        trip={tripJson}
        planView={{ loadCover }}
      />,
    );
    expect((await screen.findAllByText(/Cinque giorni a Lisbona/)).length).toBeGreaterThan(0);
    expect(loadCover).toHaveBeenCalled();
  });
});

describe("PlanScreenView, a question for the traveller", () => {
  /** The recorded run that asks twice: seq 53 what to see, seq 77 what to eat. */
  const run = choicesRun.events as unknown as UIEvent[];
  const askedAt = (seq: number) => {
    const choice = readAskedChoice(run.find((event) => event.seq === seq)?.detail ?? null);
    if (!choice) throw new Error(`choices.json lost its question at seq ${seq}`);
    return choice;
  };
  const activities = askedAt(53);
  const food = askedAt(77);
  const DEADLINE = Date.parse(activities.deadlineAt);
  const FOOD_DEADLINE = Date.parse(food.deadlineAt);
  const MINUTE = "Manca un minuto per scegliere.";

  /** The run up to `seq`, with the plan running (the request's destination is Lisbona). */
  const stateAt = (seq: number) =>
    reducePlanEvents(
      run.filter((event) => event.seq <= seq),
      { detail: { ...snapshot, created_at: run[0]!.ts, updated_at: run[0]!.ts } },
    );
  // The run's own timestamps: the snapshot's updated_at is a server time the countdown's skew reads.
  const detail = PlanDetailSchema.parse({ ...detailJson, status: "running", plan: null, created_at: run[0]!.ts, updated_at: run[0]!.ts });
  const controls = (extra: Partial<ChoiceControls> = {}): ChoiceControls => ({ answer: vi.fn(async () => null), ...extra });
  /** When event `seq` landed, on an accurate clock: a first render there sets the skew to zero. */
  const landed = (seq: number) => Date.parse(run.find((event) => event.seq === seq)!.ts);

  function view(seq: number, clock: number | null, choice: ChoiceControls = controls()) {
    return (
      <PlanScreenView
        state={stateAt(seq)}
        detail={detail}
        clock={clock}
        stale={false}
        connection="open"
        header={<div />}
        choice={choice}
      />
    );
  }

  const liveRegion = () => {
    const regions = document.querySelectorAll("[aria-live]");
    expect(regions).toHaveLength(1);
    return regions[0] as HTMLElement;
  };

  it("on the phone the panel comes before the lanes, from 1080 px after them", async () => {
    render(view(55, DEADLINE - 200_000));
    const phone = await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    const main = screen.getByRole("main");
    expect(main.firstElementChild?.contains(phone)).toBe(true);
    const lanes = () => document.getElementById("lanes-heading")?.closest("section") as HTMLElement;
    expect(main.contains(lanes())).toBe(true);
    expect(phone.compareDocumentPosition(lanes()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Attività ha trovato 3 idee per Lisbona")).toBeTruthy();
    cleanup();

    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(min-width: 67.5rem)",
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    render(view(55, DEADLINE - 200_000));
    const desktop = await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    expect(desktop.compareDocumentPosition(lanes()) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    expect(screen.getByRole("main").contains(desktop)).toBe(true);
  });

  it("announces once when a minute is left", async () => {
    const { rerender } = render(view(55, null));
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    expect(liveRegion().textContent).toBe("");
    rerender(view(55, landed(55)));
    expect(liveRegion().textContent).toBe("");
    rerender(view(55, DEADLINE - 61_000));
    expect(liveRegion().textContent).toBe("");

    rerender(view(55, DEADLINE - 60_000));
    expect(liveRegion().textContent).toBe(MINUTE);
    const said = liveRegion().querySelector("span");
    rerender(view(55, DEADLINE - 59_000));
    rerender(view(55, DEADLINE - 10_000));
    // The same words, never added again: a screen reader hears them once.
    expect(liveRegion().textContent).toBe(MINUTE);
    expect(liveRegion().querySelector("span")).toBe(said);

    // Answered: the words leave with the cards. The next question has its own minute.
    rerender(view(60, DEADLINE - 5_000));
    expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
    expect(liveRegion().textContent).toBe("");
    rerender(view(79, FOOD_DEADLINE - 120_000));
    await screen.findByRole("region", { name: "Che cucina cerchi?" });
    expect(liveRegion().textContent).toBe("");
    rerender(view(79, FOOD_DEADLINE - 30_000));
    expect(liveRegion().textContent).toBe(MINUTE);
    cleanup();

    // A window of a minute or less (the demo's 15 s) is never announced.
    const asked = Date.parse(activities.askedAt);
    render(view(55, asked + 5_000, controls({ deadlineAt: asked + 15_000, windowMs: 15_000 })));
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    expect(liveRegion().textContent).toBe("");
  });

  it("says the minute once: the note leaves with the live region's next words", async () => {
    // The question open (up to 55), then alloggio finishing while it waits (59 to 65), applied to
    // it as the stream does (a lane change is a new announcement).
    const open = reducePlanEvents(
      run.filter((event) => event.seq <= 55),
      { detail: { ...snapshot, created_at: run[0]!.ts, updated_at: run[0]!.ts } },
    );
    const lodgingDone = planEventsReducer(open, { type: "events", events: run.filter((event) => event.seq >= 59 && event.seq <= 65) });
    const at = (state: PlanLiveState, clock: number) => (
      <PlanScreenView
        state={state}
        detail={detail}
        clock={clock}
        stale={false}
        connection="open"
        header={<div />}
        choice={controls()}
      />
    );
    const { rerender } = render(at(open, landed(55)));
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    rerender(at(open, DEADLINE - 70_000));
    // The live baseline settles: from here on lane changes are spoken.
    await act(async () => {
      await new Promise((done) => setTimeout(done, SETTLE_MS + 50));
    });
    rerender(at(open, DEADLINE - 60_000));
    expect(liveRegion().textContent).toBe(MINUTE);
    // The region is atomic: a note that stayed would be read again with "Alloggio: finito".
    rerender(at(lodgingDone, DEADLINE - 50_000));
    expect(liveRegion().textContent).toContain("Alloggio");
    expect(liveRegion().textContent).not.toContain(MINUTE);
  });

  it("says once, in the one live region, how a question it showed closed", async () => {
    const open = stateAt(55);
    // The deadline answers the first question (the recording's answer at seq 56, turned into a timeout).
    const recorded = run.find((event) => event.seq === 56)!;
    const timeout: UIEvent = {
      ...recorded,
      title: "Tempo scaduto: sceglie Atlas",
      detail: { ...recorded.detail, answered_by: "timeout", selected: [] },
    };
    const closed = planEventsReducer(open, { type: "events", events: [timeout] });
    const later = planEventsReducer(closed, { type: "events", events: run.filter((event) => event.seq >= 59 && event.seq <= 65) });
    const at = (state: PlanLiveState, clock: number) => (
      <PlanScreenView
        state={state}
        detail={detail}
        clock={clock}
        stale={false}
        connection="open"
        header={<div />}
        choice={controls()}
      />
    );
    const SAID = "Tempo scaduto: sceglie Atlas";

    // Before the live baseline settles the stream is replaying history: nothing of it is spoken.
    const replayed = render(at(open, DEADLINE - 30_000));
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    replayed.rerender(at(closed, DEADLINE + 1_000));
    expect(liveRegion().textContent).not.toContain(SAID);
    cleanup();

    const { rerender } = render(at(open, landed(55)));
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    rerender(at(open, DEADLINE - 30_000));
    await act(async () => {
      await new Promise((done) => setTimeout(done, SETTLE_MS + 50));
    });
    expect(liveRegion().textContent).toBe(MINUTE);
    rerender(at(closed, DEADLINE + 1_000));
    expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
    // The answered station's own title, in place of the minute's note.
    expect(liveRegion().textContent).toContain(SAID);
    expect(liveRegion().textContent).not.toContain(MINUTE);
    const said = [...liveRegion().querySelectorAll("span")].find((span) => span.textContent === SAID);
    rerender(at(closed, DEADLINE + 2_000));
    expect([...liveRegion().querySelectorAll("span")].find((span) => span.textContent === SAID)).toBe(said);
    // It leaves with the region's next words, and never comes back.
    rerender(at(later, DEADLINE + 3_000));
    expect(liveRegion().textContent).toContain("Alloggio");
    expect(liveRegion().textContent).not.toContain(SAID);
    rerender(at(later, DEADLINE + 4_000));
    expect(liveRegion().textContent).not.toContain(SAID);
  });

  it("says how a question closed when its answer and the next question land together, and the next one takes the focus", async () => {
    const open = stateAt(55);
    // One batch: the first question's answer (56) and the second question (77), as after a reconnect.
    const both = planEventsReducer(open, { type: "events", events: run.filter((event) => event.seq >= 56 && event.seq <= 79) });
    const at = (state: PlanLiveState, clock: number) => (
      <PlanScreenView
        state={state}
        detail={detail}
        clock={clock}
        stale={false}
        connection="open"
        header={<div />}
        choice={controls()}
      />
    );
    const SAID = "Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra";
    const { rerender } = render(at(open, landed(55)));
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    await act(async () => {
      await new Promise((done) => setTimeout(done, SETTLE_MS + 50));
    });

    rerender(at(both, landed(79)));
    const next = await screen.findByRole("region", { name: "Che cucina cerchi?" });
    expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
    // The first question's receipt, once, in the one live region...
    expect([...liveRegion().querySelectorAll("span")].filter((span) => span.textContent === SAID)).toHaveLength(1);
    // ...while the second question's heading takes the focus.
    expect(document.activeElement).toBe(within(next).getByRole("heading", { level: 2 }));
    rerender(at(both, landed(79) + 1_000));
    expect([...liveRegion().querySelectorAll("span")].filter((span) => span.textContent === SAID)).toHaveLength(1);
  });

  it("reads the answered titles once per change of the events, never per clock tick", async () => {
    const state = stateAt(55);
    const closed = new Set([activities.id]);
    // One controls object, as the live page's (memoized): a new one would redraw the lanes.
    const choice = controls();
    const at = (clock: number, closedChoices?: ReadonlySet<string>) => (
      <PlanScreenView
        state={state}
        detail={detail}
        clock={clock}
        stale={false}
        connection="open"
        header={<div />}
        choice={choice}
        closedChoices={closedChoices}
      />
    );
    const { rerender } = render(at(landed(55)));
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    // The page answered: the question hides until its answered event arrives, and the page waits.
    rerender(at(landed(55) + 1_000, closed));
    expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
    const reads = vi.mocked(readChoiceAnswer);
    reads.mockClear();
    for (let tick = 2; tick <= 6; tick += 1) rerender(at(landed(55) + tick * 1_000, closed));
    expect(reads).not.toHaveBeenCalled();
  });

  it("hands the focus to the plan's state when the question leaves with it", async () => {
    const { rerender } = render(view(55, DEADLINE - 200_000));
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    expect(document.activeElement?.id).toBe("scelta-domanda");
    // The deadline answers (the answered event lands): the heading goes, the focus does not fall to
    // the page.
    rerender(view(60, DEADLINE + 1_000));
    expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
    expect(document.activeElement?.id).toBe(PLAN_STATE_ID);
    cleanup();

    // A focus the traveller moved elsewhere stays there.
    const elsewhere = render(
      <>
        <button type="button">Altrove</button>
        {view(55, DEADLINE - 200_000)}
      </>,
    );
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    screen.getByRole("button", { name: "Altrove" }).focus();
    elsewhere.rerender(
      <>
        <button type="button">Altrove</button>
        {view(60, DEADLINE + 1_000)}
      </>,
    );
    expect(document.activeElement?.textContent).toBe("Altrove");
  });

  it("holds the demo's camera while its question shows, and lets it aim again once answered", async () => {
    const aimed = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = aimed;
    try {
      // The question waiting (up to 55), then alloggio's next stations (59, 60) with the question
      // still open, then the answer (56) too.
      const waiting = run.filter((event) => event.seq <= 55);
      const working = [...waiting, ...run.filter((event) => event.seq === 59 || event.seq === 60)];
      const answered = run.filter((event) => event.seq <= 60);
      const shown = (events: UIEvent[], choice?: ChoiceControls) => (
        <PlanScreenView
          state={reducePlanEvents(events, { detail: { ...snapshot, created_at: run[0]!.ts, updated_at: run[0]!.ts } })}
          detail={detail}
          clock={Date.parse(events.at(-1)!.ts)}
          stale={false}
          connection="open"
          header={<div />}
          followLanes="show"
          choice={choice}
        />
      );
      // Without the cards on screen the camera follows alloggio's new stations...
      const first = render(shown(waiting));
      aimed.mockClear();
      first.rerender(shown(working));
      expect(aimed).toHaveBeenCalled();
      cleanup();

      // ...with them it holds still, and aims again once the answer lands and they go.
      const { rerender } = render(shown(waiting, controls()));
      await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
      aimed.mockClear();
      rerender(shown(working, controls()));
      expect(aimed).not.toHaveBeenCalled();
      rerender(shown(answered, controls()));
      expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
      expect(aimed).toHaveBeenCalled();
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it("shows no cards without the controls, or once the page has answered, and no plate linking to them", async () => {
    const props = { state: stateAt(55), detail, clock: DEADLINE - 200_000, stale: false, connection: "open" as const, header: <div /> };
    const plate = () => document.querySelector('section[data-agent="coordinator"] a[href="#scelta"]');
    const { rerender } = render(<PlanScreenView {...props} choice={controls()} />);
    await screen.findByRole("region", { name: "Cosa ti va di vedere?" });
    expect(plate()?.textContent).toContain("Tocca a te: scegli cosa vedere");
    rerender(<PlanScreenView {...props} />);
    expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
    expect(plate()).toBeNull();
    rerender(<PlanScreenView {...props} choice={controls()} closedChoices={new Set([activities.id])} />);
    expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
    expect(plate()).toBeNull();
    // Nor while the viewer is interrupting.
    rerender(<PlanScreenView {...props} choice={controls()} interrupting />);
    expect(screen.queryByRole("region", { name: "Cosa ti va di vedere?" })).toBeNull();
    expect(plate()).toBeNull();
    expect(document.querySelector('section[data-agent="coordinator"]')?.textContent).not.toContain("Tocca a te");
  });
});
