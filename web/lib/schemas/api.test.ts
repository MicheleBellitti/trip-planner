import { describe, expect, it } from "vitest";

import { PlanDetailSchema } from "./api";

const BASE_DETAIL = {
  id: "6f1c2a7e-3b4d-4e5f-8a9b-0c1d2e3f4a5b",
  status: "running",
  title: "Lisbona, weekend lungo",
  agent_profile: "development",
  created_at: "2026-10-18T10:00:00+00:00",
  updated_at: "2026-10-18T10:05:00+00:00",
  cost_cents: 12,
  submit_attempts: 0,
  request: {},
};

describe("PlanDetailSchema link_health", () => {
  it("parses a detail without link_health as an empty map", () => {
    const detail = PlanDetailSchema.parse(BASE_DETAIL);
    expect(detail.link_health).toEqual({});
  });

  it("fills the optional fields of an entry", () => {
    const detail = PlanDetailSchema.parse({
      ...BASE_DETAIL,
      link_health: { "https://a.example/gone": { status: "dead" } },
    });
    expect(detail.link_health["https://a.example/gone"]).toEqual({
      status: "dead",
      fallback: null,
      fallback_allowed: false,
    });
  });

  it("keeps an unknown status string instead of rejecting the detail", () => {
    const detail = PlanDetailSchema.parse({
      ...BASE_DETAIL,
      link_health: {
        "https://a.example/x": {
          status: "quarantined",
          fallback: "https://a.example/",
          fallback_allowed: true,
        },
      },
    });
    expect(detail.link_health["https://a.example/x"]).toEqual({
      status: "quarantined",
      fallback: "https://a.example/",
      fallback_allowed: true,
    });
  });
});
