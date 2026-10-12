import { describe, expect, it } from "vitest";

import { AgentNameSchema } from "../schemas/generated/ui-event";
import { PlanStatusSchema } from "../schemas/api";
import { AGENT_LABELS, AGENTS, laneAnnouncement, messageLine, PLAN_STATUS_LABELS } from "./labels";

describe("labels", () => {
  it("cover every agent and plan status of the contract", () => {
    expect([...AGENTS]).toEqual(AgentNameSchema.options);
    expect(Object.keys(AGENT_LABELS)).toEqual(AgentNameSchema.options);
    expect(Object.keys(PLAN_STATUS_LABELS)).toEqual(PlanStatusSchema.options);
  });

  it("write an inter-agent message as one line", () => {
    expect(messageLine("coordinator", "flights", "incarico")).toBe("coordinatore → voli: incarico");
    expect(messageLine("transport", "coordinator")).toBe("spostamenti → coordinatore");
    expect(messageLine(null, "lodging", "incarico")).toBe("→ alloggio: incarico");
  });

  it("announce a lane state in Italian", () => {
    expect(laneAnnouncement("activities", "working")).toBe("Attività: al lavoro");
    expect(laneAnnouncement("coordinator", "stopped")).toBe("Coordinatore: fermato");
  });
});
