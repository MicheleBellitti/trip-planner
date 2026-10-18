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
/** The elements the camera scrolled into view, in order. */
let targets: Element[] = [];

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
  targets = [];
  Element.prototype.scrollIntoView = function (this: Element, options?: boolean | ScrollIntoViewOptions) {
    targets.push(this);
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

  it("on the phone, aims at the card while its body is still 0 px tall, at its newest station once it shows", () => {
    screenWidth(false);
    const { rerender } = render(lanes(10, "show"));
    // jsdom lays nothing out: every body is 0 px tall, as one that is closed or just opening.
    targets = [];
    rerender(lanes(14, "show"));
    const opening = targets.at(-1)!;
    expect(opening.tagName).toBe("SECTION");
    expect(opening.id).toMatch(/^lane-(flights|lodging)$/);
    // Grown open: the body has a height, so the camera follows its end marker.
    const body = document.getElementById(`${opening.id}-body`)!;
    body.getBoundingClientRect = () => ({ top: 0, bottom: 400, height: 400 }) as DOMRect;
    targets = [];
    rerender(lanes(15, "show"));
    rerender(lanes(16, "show"));
    const grown = targets.at(-1);
    expect(grown?.hasAttribute("data-lane-end")).toBe(true);
    expect(grown?.closest("section")?.id).toBe(opening.id);
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
