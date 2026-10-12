/**
 * The reducer on events made by the backend's own normalizer (__fixtures__/backend/, written by
 * web/scripts/gen-backend-fixtures.py from backend/tests/fixtures/ma/*.jsonl): the `detail`
 * keys and labels the browser really receives.
 */

import { describe, expect, it } from "vitest";

import { PlanDetailSchema, type PlanStatus } from "../schemas/api";
import { UIEventSchema, type UIEvent } from "../schemas/generated/ui-event";
import budgetReached from "./__fixtures__/backend/budget-reached.json";
import happyPath from "./__fixtures__/backend/happy-path.json";
import mcpFailure from "./__fixtures__/backend/mcp-failure.json";
import samples from "./__fixtures__/backend/samples.json";
import { mayChangePlanStatus, readMessage } from "./detail";
import { AGENTS } from "./labels";
import { initialPlanLiveState, planEventsReducer, reducePlanEvents, type PlanLiveState } from "./reducer";

interface Scenario {
  plan_id: string;
  events: unknown[];
  statuses: { after_seq: number; status: string }[];
  end: string | null;
}

function eventsOf(scenario: Scenario): UIEvent[] {
  return scenario.events.map((event) => UIEventSchema.parse(event));
}

const happy = eventsOf(happyPath);
const paused = eventsOf(budgetReached);
const mcp = eventsOf(mcpFailure);
const sample = (name: keyof typeof samples.events, seq: number, agent?: UIEvent["agent"]): UIEvent =>
  UIEventSchema.parse({ ...samples.events[name], seq, ...(agent ? { agent } : {}) });

function feed(events: readonly UIEvent[], state: PlanLiveState = initialPlanLiveState()): PlanLiveState {
  return events.reduce((current, event) => planEventsReducer(current, { type: "events", events: [event] }), state);
}

function seqOf(events: readonly UIEvent[], title: string, from = 0): number {
  const event = events.find((candidate) => candidate.seq >= from && candidate.title === title);
  if (!event) throw new Error(`no event titled ${title}`);
  return event.seq;
}

const upTo = (events: readonly UIEvent[], seq: number) => events.filter((event) => event.seq <= seq);

/** GET /plans/{id} as the backend would answer right after `seq` (the fixture's statuses). */
function snapshot(scenario: Scenario, events: readonly UIEvent[], seq: number) {
  let status: PlanStatus = "running";
  for (const change of scenario.statuses) if (change.after_seq <= seq) status = change.status as PlanStatus;
  return PlanDetailSchema.parse({
    id: scenario.plan_id,
    status,
    title: "Lisbona, 14–18 apr",
    agent_profile: "development",
    created_at: events[0]?.ts,
    updated_at: events[seq]?.ts,
    cost_cents: 0,
    budget_cents: 60,
    submit_attempts: 0,
    request: {},
  });
}

describe("backend fixtures", () => {
  it("conform to schema/ui_event.json, with contiguous seqs", () => {
    for (const events of [happy, paused, mcp]) {
      expect(events.map((event) => event.seq)).toEqual(events.map((_, index) => index));
    }
    for (const event of Object.values(samples.events)) expect(UIEventSchema.safeParse(event).success).toBe(true);
  });
});

describe("messages", () => {
  it("reads sender and recipient from the backend's Italian labels", () => {
    expect(readMessage({ sender: "coordinatore", recipient: "attività" })).toMatchObject({
      from: "coordinator",
      to: "activities",
    });
    expect(readMessage({ sender: "utente", recipient: "Voli" })).toMatchObject({ from: null, to: "flights" });
    expect(readMessage({ sender: "subagente", recipient: "consulente" })).toMatchObject({ from: null, to: null });
    // The older AgentName form is still accepted.
    expect(readMessage({ from: "transport", to: "coordinator" })).toMatchObject({ from: "transport", to: "coordinator" });
  });

  it("builds 'mittente → destinatario' for every inter-agent message", () => {
    const state = feed(happy);
    const delegations = state.messages.filter((message) => message.from === "coordinator" && message.to !== null);
    const reports = state.messages.filter((message) => message.to === "coordinator");

    expect(delegations.map((message) => message.to)).toEqual(["flights", "lodging", "activities", "transport", "activities"]);
    expect(delegations.every((message) => message.lane === message.to)).toBe(true);
    expect(new Set(reports.map((message) => message.from))).toEqual(
      new Set(["flights", "lodging", "activities", "transport", null]),
    );
    // Only the user (the brief) and the coordinator's replies to the user have an end that is
    // not a lane.
    const userEnds = state.messages.filter((message) => message.from === null || message.to === null);
    expect(userEnds.every((message) => message.lane === "coordinator")).toBe(true);
  });
});

describe("tools", () => {
  it("shows the MCP server of the tool in progress, then clears it on the result", () => {
    const call = seqOf(happy, "Expedia · voli MXP→LIS · 14–18 apr");
    const during = feed(upTo(happy, call));

    expect(during.lanes.flights.currentTool).toMatchObject({ server: "expedia", tool: "search_flights" });
    expect(during.lanes.flights.currentTool?.params).toMatchObject({ origin: "MXP" });
    expect(feed(upTo(happy, call + 1)).lanes.flights.currentTool).toBeNull();
  });

  it("treats the backend's answer to submit_plan as a result, not a tool in progress", () => {
    const answered = feed(upTo(happy, seqOf(happy, "Esito inviato all'agente")));

    expect(answered.lanes.coordinator.currentTool).toBeNull();
    expect(answered).toMatchObject({ submissions: 1, rejections: 0, planAccepted: true });

    const rejected = feed([sample("submit_result_rejected", 0)]);
    expect(rejected.lanes.coordinator.currentTool).toBeNull();
  });
});

describe("lane states", () => {
  it("follows lane_state: waiting on requires_action, working again, done on end_turn", () => {
    const idle = seqOf(happy, "In attesa di una risposta");

    expect(feed(upTo(happy, idle)).lanes.coordinator.state).toBe("waiting");
    expect(feed(upTo(happy, idle + 3)).lanes.coordinator.state).toBe("working");
    const all = feed(happy);
    for (const agent of AGENTS) expect(all.lanes[agent].state).toBe("done");
  });

  it("leaves the lanes waiting at 'Piano avviato'", () => {
    const state = feed(upTo(happy, 0));
    for (const agent of AGENTS) expect(state.lanes[agent].state).toBe("waiting");
  });

  it("shows a terminated (archived) thread or session as done, not as an error", () => {
    const working = feed(upTo(happy, seqOf(happy, "Al lavoro", 17)));
    expect(working.lanes.flights.state).toBe("working");

    const thread = feed([sample("thread_terminated", working.events.length)], working);
    expect(thread.lanes.flights.state).toBe("done");
    expect(thread.lanes.flights.lastError).toBeNull();

    const session = feed([sample("session_terminated", thread.events.length)], thread);
    expect(session.lanes.coordinator.state).toBe("done");
  });

  it("shows an unreachable MCP server as a warning naming it, never as an error", () => {
    const state = feed(mcp);
    const warnings = AGENTS.flatMap((agent) => state.lanes[agent].warnings);

    expect(warnings).toHaveLength(2);
    expect(warnings.every((warning) => warning.source === "kiwi")).toBe(true);
    for (const agent of AGENTS) expect(state.lanes[agent].lastError).toBeNull();
    expect(feed(upTo(mcp, seqOf(mcp, "Kiwi.com · voli Milan→Lisbon · 14–18 apr"))).lanes.flights.currentTool?.server).toBe("kiwi");
  });
});

describe("budget reached, then 'Continua'", () => {
  const idle = budgetReached.statuses.find((change) => change.status === "budget_paused")?.after_seq ?? -1;

  it("asks for a fresh snapshot on the idle event that pauses the plan", () => {
    const pausing = paused[idle];

    expect(pausing?.detail).toMatchObject({ event_type: "session.status_idle", stop_reason: "budget_reached" });
    expect(pausing?.detail).not.toHaveProperty("plan_status");
    expect(mayChangePlanStatus(pausing?.detail ?? null)).toBe(true);
    expect(mayChangePlanStatus(paused[idle - 1]?.detail ?? null)).toBe(false);
  });

  it("keeps running until the snapshot says budget_paused, then stops the working lanes", () => {
    const events = upTo(paused, idle);
    const before = reducePlanEvents(events, { detail: snapshot(budgetReached, paused, idle - 1) });
    expect(before.status).toBe("running");
    expect(before.lanes.lodging.state).toBe("working");

    const after = reducePlanEvents(events, { detail: snapshot(budgetReached, paused, idle) });
    expect(after.status).toBe("budget_paused");
    expect(after.lanes.coordinator.state).toBe("stopped");
    expect(after.lanes.lodging.state).toBe("stopped");
    expect(after.lanes.flights.state).toBe("done");
    expect(after.stoppedAt).toBe(paused[idle]?.ts);
    expect(after.costCents).toBe(61);
  });

  it("resumes with the raised budget after 'Continua'", () => {
    const resumed = seqOf(paused, "Al lavoro", idle);
    const state = reducePlanEvents(upTo(paused, resumed), { detail: snapshot(budgetReached, paused, idle) });

    expect(state.status).toBe("running");
    expect(state.budgetCents).toBe(261);
    expect(state.stoppedAt).toBeNull();
    expect(state.lanes.coordinator.state).toBe("working");
  });
});
