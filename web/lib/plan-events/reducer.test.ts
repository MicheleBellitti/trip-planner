import { describe, expect, it } from "vitest";

import { PlanDetailSchema } from "../schemas/api";
import { UIEventSchema, type UIEvent } from "../schemas/generated/ui-event";
import budgetPaused from "./__fixtures__/budget-paused.json";
import happyPath from "./__fixtures__/happy-path.json";
import { AGENTS, LANE_STATE_LABELS } from "./labels";
import {
  activeLane,
  costProgress,
  elapsedMs,
  initialPlanLiveState,
  planEventsReducer,
  reducePlanEvents,
  type PlanLiveState,
} from "./reducer";
import { shouldVirtualize, VIRTUALIZATION_THRESHOLD, virtualWindow } from "./virtualization";

const happyEvents: UIEvent[] = happyPath.events.map((event) => UIEventSchema.parse(event));
const happyDetail = PlanDetailSchema.parse(happyPath.detail);
const pausedEvents: UIEvent[] = budgetPaused.events.map((event) => UIEventSchema.parse(event));

function feed(events: readonly UIEvent[], state: PlanLiveState = initialPlanLiveState()): PlanLiveState {
  return events.reduce((current, event) => planEventsReducer(current, { type: "events", events: [event] }), state);
}

function upTo(seq: number): UIEvent[] {
  return happyEvents.filter((event) => event.seq <= seq);
}

function seqOf(title: string, events: readonly UIEvent[] = happyEvents): number {
  const event = events.find((candidate) => candidate.title === title);
  if (!event) throw new Error(`no event titled ${title}`);
  return event.seq;
}

describe("fixtures", () => {
  it("conform to schema/ui_event.json (generated Zod schema)", () => {
    for (const event of [...happyPath.events, ...budgetPaused.events]) {
      expect(UIEventSchema.safeParse(event).success).toBe(true);
    }
    expect(happyEvents.map((event) => event.seq)).toEqual(happyEvents.map((_, index) => index));
  });
});

describe("initial state", () => {
  it("has the five lanes waiting, in display order", () => {
    const state = initialPlanLiveState();

    expect(Object.keys(state.lanes)).toEqual([...AGENTS]);
    for (const agent of AGENTS) expect(state.lanes[agent].state).toBe("waiting");
    expect(state.status).toBeNull();
    expect(state.lastSeq).toBeNull();
    expect(state.announcement).toBeNull();
  });
});

describe("a realistic plan, event by event", () => {
  it("shows the five lanes waiting, with the clock running, when the plan starts", () => {
    const state = feed(upTo(0));

    expect(state.status).toBe("running");
    expect(state.startedAt).toBe(happyEvents[0]?.ts);
    for (const agent of AGENTS) expect(state.lanes[agent].state).toBe("waiting");
  });

  it("starts running with the coordinator at work", () => {
    const state = feed(upTo(1));

    expect(state.status).toBe("running");
    expect(state.startedAt).toBe(happyEvents[0]?.ts);
    expect(state.stoppedAt).toBeNull();
    expect(state.lanes.coordinator.state).toBe("working");
    expect(state.lanes.flights.state).toBe("waiting");
  });

  it("shows the current tool with its main parameters, and clears it on the result", () => {
    const during = feed(upTo(seqOf("Kiwi · voli MXP→LIS · 14–17 nov")));
    const tool = during.lanes.flights.currentTool;

    expect(during.lanes.flights.state).toBe("working");
    expect(tool?.title).toBe("Kiwi · voli MXP→LIS · 14–17 nov");
    expect(tool?.server).toBe("kiwi");
    expect(tool?.tool).toBe("search-flight");
    expect(tool?.params).toMatchObject({ from: "MXP", to: "LIS", adults: 2 });

    const after = feed(upTo(seqOf("Kiwi · 12 voli trovati")));
    expect(after.lanes.flights.currentTool).toBeNull();
    expect(after.lanes.flights.state).toBe("working");
  });

  it("records inter-agent messages with sender, recipient and text", () => {
    const state = feed(happyEvents);
    const tasks = state.messages.filter((message) => message.from === "coordinator");
    const reports = state.messages.filter((message) => message.to === "coordinator");

    expect(tasks.map((message) => message.to)).toEqual(["flights", "lodging", "activities", "transport"]);
    expect(tasks[0]?.title).toBe("coordinatore → voli: incarico");
    expect(tasks[0]?.text).toContain("MXP→LIS");
    expect(reports.map((message) => message.from)).toEqual(["flights", "activities", "lodging"]);
    expect(state.messages.map((message) => message.seq)).toEqual(
      [...state.messages.map((message) => message.seq)].sort((a, b) => a - b),
    );
  });

  it("shows a failed MCP source as a lane warning, not an error", () => {
    const state = feed(upTo(seqOf("Expedia non risponde: si prosegue con il web")));
    const lodging = state.lanes.lodging;

    expect(lodging.state).toBe("working");
    expect(lodging.lastError).toBeNull();
    expect(lodging.warnings).toHaveLength(1);
    expect(lodging.warnings[0]).toMatchObject({ source: "expedia", title: "Expedia non risponde: si prosegue con il web" });
  });

  it("marks a failed agent in error while the others go on", () => {
    const state = feed(upTo(seqOf("Spostamenti: il modello non ha risposto")));

    expect(state.lanes.transport.state).toBe("error");
    expect(state.lanes.transport.lastError?.title).toBe("Spostamenti: il modello non ha risposto");
    expect(state.lanes.transport.currentTool).toBeNull();
    expect(state.lanes.flights.state).toBe("working");
    expect(state.status).toBe("running");
  });

  it("finishes a lane when its thread ends its turn", () => {
    const state = feed(upTo(seqOf("Voli: finito")));

    expect(state.lanes.flights.state).toBe("done");
    expect(state.lanes.lodging.state).toBe("working");
  });

  it("counts submit_plan outcomes", () => {
    const rejected = feed(upTo(seqOf("Piano rifiutato: 2 problemi da correggere")));
    expect(rejected).toMatchObject({ submissions: 1, rejections: 1, planAccepted: false, planReady: false });

    const accepted = feed(upTo(seqOf("Piano accettato")));
    expect(accepted).toMatchObject({ submissions: 2, rejections: 1, planAccepted: true, planReady: false });
  });

  it("tracks the cumulative cost against the session budget", () => {
    const state = feed(happyEvents, planEventsReducer(initialPlanLiveState(), { type: "detail", detail: happyDetail }));

    expect(state.costCents).toBe(41);
    expect(state.budgetCents).toBe(60);
    expect(costProgress(state)).toBeCloseTo(41 / 60);
  });

  it("ends ready: every lane done except the one in error, the clock stopped", () => {
    const state = planEventsReducer(feed(happyEvents), { type: "end", status: "ready" });

    expect(state.status).toBe("ready");
    expect(state.ended).toBe(true);
    expect(state.planReady).toBe(true);
    expect(state.lanes.coordinator.state).toBe("done");
    expect(state.lanes.flights.state).toBe("done");
    expect(state.lanes.lodging.state).toBe("done");
    expect(state.lanes.activities.state).toBe("done");
    expect(state.lanes.transport.state).toBe("error");
    const last = happyEvents[happyEvents.length - 1];
    expect(state.stoppedAt).toBe(last?.ts);
    expect(elapsedMs(state, Date.parse("2030-01-01T00:00:00Z"))).toBe(
      Date.parse(last?.ts ?? "") - Date.parse(happyEvents[0]?.ts ?? ""),
    );
  });

  it("keeps each lane's events in seq order", () => {
    const state = feed(happyEvents);
    const total = AGENTS.reduce((sum, agent) => sum + state.lanes[agent].events.length, 0);

    expect(total).toBe(happyEvents.length);
    for (const agent of AGENTS) {
      const seqs = state.lanes[agent].events.map((event) => event.seq);
      expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
      expect(state.lanes[agent].events.every((event) => event.agent === agent)).toBe(true);
    }
  });
});

describe("dedupe and ordering", () => {
  it("ignores an event whose seq was already received (a reconnection replay)", () => {
    const once = feed(happyEvents);
    const twice = planEventsReducer(once, { type: "events", events: happyEvents.slice(10, 20) });

    expect(twice).toBe(once);
    expect(twice.events).toHaveLength(happyEvents.length);
  });

  it("folds out-of-order arrivals as if they came in order", () => {
    const shuffled = [...happyEvents].reverse();
    const outOfOrder = feed(shuffled);
    const inOrder = feed(happyEvents);

    expect(outOfOrder.events.map((event) => event.seq)).toEqual(inOrder.events.map((event) => event.seq));
    expect(outOfOrder.lanes).toEqual(inOrder.lanes);
    expect(outOfOrder.messages).toEqual(inOrder.messages);
    expect(outOfOrder.status).toBe(inOrder.status);
    expect(outOfOrder.lastSeq).toBe(happyEvents.length - 1);
  });

  it("takes a batch with duplicates and gaps", () => {
    const batch = [happyEvents[3], happyEvents[1], happyEvents[3], happyEvents[0], happyEvents[2]].filter(
      (event): event is UIEvent => event !== undefined,
    );
    const state = planEventsReducer(initialPlanLiveState(), { type: "events", events: batch });

    expect(state.events.map((event) => event.seq)).toEqual([0, 1, 2, 3]);
    expect(state.lastSeq).toBe(3);
  });
});

describe("snapshot and stream end", () => {
  it("does not let a replayed older status override a newer snapshot", () => {
    const detail = { ...happyDetail, status: "budget_paused" as const, updated_at: "2026-10-12T14:00:00Z" };
    const state = reducePlanEvents(upTo(10), { detail });

    expect(state.status).toBe("budget_paused");
    expect(state.startedAt).toBe("2026-10-12T13:00:00Z");
  });

  it("lets a status event newer than the snapshot win", () => {
    const state = reducePlanEvents(happyEvents, { detail: happyDetail });

    expect(state.status).toBe("ready");
  });

  it("treats `event: end` as the final word", () => {
    const state = reducePlanEvents(upTo(5), { detail: happyDetail, end: "interrupted" });

    expect(state.status).toBe("interrupted");
    expect(state.ended).toBe(true);
    expect(state.lanes.coordinator.state).toBe("stopped");
    expect(state.stoppedAt).not.toBeNull();
  });

  it("marks the coordinator in error when the plan failed", () => {
    const state = reducePlanEvents(upTo(12), { end: "failed" });

    expect(state.lanes.coordinator.state).toBe("error");
    expect(state.lanes.flights.state).toBe("stopped");
  });
});

describe("budget reached, then 'Continua'", () => {
  const pauseAfter = budgetPaused.pause_after_seq;

  it("pauses: working lanes stop, the clock stops, the cost is past the budget", () => {
    const state = feed(pausedEvents.filter((event) => event.seq <= pauseAfter));

    expect(state.status).toBe("budget_paused");
    expect(state.lanes.coordinator.state).toBe("stopped");
    expect(state.lanes.flights.state).toBe("stopped");
    expect(state.stoppedAt).toBe(pausedEvents[pauseAfter]?.ts);
    expect(state.costCents).toBe(61);
    expect(costProgress(state)).toBeNull();
  });

  it("resumes with the raised budget", () => {
    const state = feed(pausedEvents);

    expect(state.status).toBe("running");
    expect(state.budgetCents).toBe(261);
    expect(state.stoppedAt).toBeNull();
    expect(state.lanes.coordinator.state).toBe("working");
    expect(state.lanes.flights.state).toBe("working");
    expect(state.lanes.lodging.state).toBe("waiting");
  });
});

describe("announcements (aria-live)", () => {
  it("announces lane state changes only, in Italian", () => {
    const announced: string[] = [];
    let state = initialPlanLiveState();
    for (const event of happyEvents) {
      const next = planEventsReducer(state, { type: "events", events: [event] });
      if (next.announcement && next.announcement.id !== state.announcement?.id) announced.push(next.announcement.text);
      state = next;
    }

    expect(announced[0]).toBe("Coordinatore: al lavoro");
    expect(announced).toContain("Voli: al lavoro");
    expect(announced).toContain("Voli: finito");
    expect(announced).toContain("Spostamenti: errore");
    // Tool calls never announce: far fewer announcements than events.
    expect(announced.length).toBeLessThan(happyEvents.length / 2);
    expect(announced.every((text) => Object.values(LANE_STATE_LABELS).some((label) => text.endsWith(label)))).toBe(true);
  });
});

describe("selectors", () => {
  it("measures elapsed time from the start to now while running", () => {
    const state = feed(upTo(1));
    const start = Date.parse(happyEvents[0]?.ts ?? "");

    expect(elapsedMs(state, start + 65_000)).toBe(65_000);
    expect(elapsedMs(initialPlanLiveState(), start)).toBe(0);
  });

  it("opens the most recently active working lane on a phone", () => {
    expect(activeLane(feed(upTo(seqOf("Kiwi · voli MXP→LIS · 14–17 nov"))))).toBe("flights");
    expect(activeLane(initialPlanLiveState())).toBe("coordinator");
  });
});

describe("virtualization", () => {
  it("starts above 300 events", () => {
    expect(VIRTUALIZATION_THRESHOLD).toBe(300);
    expect(shouldVirtualize(300)).toBe(false);
    expect(shouldVirtualize(301)).toBe(true);
  });

  it("computes the window of rows to render", () => {
    expect(virtualWindow({ count: 1000, rowHeight: 40, scrollTop: 4000, viewportHeight: 400, overscan: 5 })).toEqual({
      start: 95,
      end: 116,
      offsetTop: 3800,
      totalHeight: 40_000,
    });
    expect(virtualWindow({ count: 0, rowHeight: 40, scrollTop: 0, viewportHeight: 400 })).toEqual({
      start: 0,
      end: 0,
      offsetTop: 0,
      totalHeight: 0,
    });
    expect(virtualWindow({ count: 10, rowHeight: 40, scrollTop: 99_999, viewportHeight: 400, overscan: 2 }).end).toBe(10);
  });
});
