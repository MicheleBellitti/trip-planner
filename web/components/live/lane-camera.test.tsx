import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import { reducePlanEvents } from "@/lib/plan-events/reducer";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { laneCardId } from "./agent-lane";
import { AgentLanes, type LaneFollow } from "./agent-lanes";
import { buildLaneViews } from "./stations";

const events = backend.events as unknown as UIEvent[];
const at = (count: number) => reducePlanEvents(events.slice(0, count));
const scrolled = vi.fn();

function lanes(count: number, follow: LaneFollow) {
  const state = at(count);
  return (
    <AgentLanes
      state={state}
      views={buildLaneViews(state)}
      now={Date.parse(events[count - 1]!.ts)}
      freshAfterSeq={0}
      stale={false}
      follow={follow}
    />
  );
}

function screenWidth(desktop: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: desktop,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

beforeEach(() => {
  scrolled.mockReset();
  Element.prototype.scrollIntoView = function (this: Element, options?: boolean | ScrollIntoViewOptions) {
    // The card a scrolled element belongs to (the card, or its body's end marker).
    scrolled((this.closest("[id^='lane-']")?.id ?? this.tagName).replace(/-body$/, ""), options);
  };
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the demo's camera", () => {
  it("on the phone, keeps the open card's newest station in view while the visitor only watches", () => {
    screenWidth(false);
    const { rerender } = render(lanes(10, "show"));
    scrolled.mockReset();
    rerender(lanes(14, "show"));
    // The work moved from the coordinator to a subagent at work (voli and alloggio start together).
    const ids = scrolled.mock.calls.map(([id]) => id as string);
    expect([laneCardId("flights"), laneCardId("lodging")]).toContain(ids.at(-1));
    for (const [, options] of scrolled.mock.calls) expect(options).toMatchObject({ block: "nearest" });
  });

  it("live, never moves the page for the viewer", () => {
    screenWidth(false);
    const { rerender } = render(lanes(10, "reader"));
    rerender(lanes(14, "reader"));
    expect(scrolled).not.toHaveBeenCalled();
  });

  it("on a wide screen, keeps the coordinator's newest station in view, only when it is out of it", () => {
    screenWidth(true);
    const { rerender } = render(lanes(10, "show"));
    scrolled.mockReset();
    rerender(lanes(30, "show"));
    expect(scrolled).toHaveBeenCalled();
    for (const [, options] of scrolled.mock.calls) expect(options).toMatchObject({ block: "nearest" });
  });
  it("hands the page back when the visitor scrolls it away from the work in any way (scrollbar, assistive tech)", () => {
    screenWidth(false);
    vi.useFakeTimers();
    try {
      const { rerender } = render(lanes(10, "show"));
      // Long after the camera's own move, the page is scrolled and the work is out of view.
      vi.advanceTimersByTime(2_000);
      for (const end of document.querySelectorAll("[data-lane-end], [id^='lane-']")) {
        end.getBoundingClientRect = () => ({ top: 5_000, bottom: 5_100 }) as DOMRect;
      }
      window.dispatchEvent(new Event("scroll"));
      scrolled.mockReset();
      rerender(lanes(14, "show"));
      expect(scrolled).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
