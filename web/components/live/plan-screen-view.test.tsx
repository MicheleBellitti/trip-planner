import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import detailJson from "@/components/plan/__fixtures__/happy-path.detail.json";
import tripJson from "@/components/plan/__fixtures__/happy-path.trip.json";
import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import { reducePlanEvents } from "@/lib/plan-events/reducer";
import { PlanDetailSchema } from "@/lib/schemas/api";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { PlanScreenView } from "./plan-screen-view";

// The view is shared with the demo, which must never reach the backend: neither API client may
// even be evaluated in its module graph.
vi.mock("@/lib/api", () => {
  throw new Error("@/lib/api evaluated");
});
vi.mock("@/components/live/live-api", () => {
  throw new Error("live-api evaluated");
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
