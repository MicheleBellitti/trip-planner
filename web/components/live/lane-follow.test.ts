import { describe, expect, it } from "vitest";

import { mayFollowLane } from "./agent-lanes";

const base = { caughtUp: true, layout: "stack" as const, chosen: null, touched: false, followedOnScreen: true };

describe("mayFollowLane", () => {
  it("live, never swaps the open card under a reader: not while it is on screen", () => {
    expect(mayFollowLane({ ...base, follow: "reader" })).toBe(false);
    expect(mayFollowLane({ ...base, follow: "reader", followedOnScreen: false })).toBe(true);
  });

  it("in the demo, follows the work even on screen, until the viewer takes over", () => {
    expect(mayFollowLane({ ...base, follow: "show" })).toBe(true);
    expect(mayFollowLane({ ...base, follow: "show", touched: true })).toBe(false);
    expect(mayFollowLane({ ...base, follow: "show", chosen: new Set(["voli"]) as never })).toBe(false);
  });

  it("follows freely while the history replays, in either mode", () => {
    expect(mayFollowLane({ ...base, caughtUp: false, touched: true, follow: "reader" })).toBe(true);
  });
});
