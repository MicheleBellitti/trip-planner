import { describe, expect, it } from "vitest";

import { JOIN_LIMIT, JOIN_WINDOW_MS, joinWindow, SlidingWindow } from "./rate-limit";

describe("SlidingWindow", () => {
  it("allows the limit, then refuses until the oldest hit leaves", () => {
    let now = 1_000_000;
    const window = new SlidingWindow(2, 60_000, () => now);
    expect(window.hit("a").allowed).toBe(true);
    now += 10_000;
    expect(window.hit("a").allowed).toBe(true);
    expect(window.hit("a")).toEqual({ allowed: false, retryAfterSeconds: 50 });
    expect(window.hit("b").allowed).toBe(true); // another key
    now += 50_000; // the first hit leaves
    expect(window.hit("a").allowed).toBe(true);
    expect(window.hit("a").allowed).toBe(false);
  });

  it("drops the keys whose hits left the window, so the map stays bounded", () => {
    let now = 1_000_000;
    const window = new SlidingWindow(2, 60_000, () => now);
    for (let i = 0; i < 500; i += 1) window.hit(`203.0.113.${i}`);
    expect(window.size).toBe(500);
    now += 60_001;
    window.hit("198.51.100.1"); // the first hit after a window sweeps the stale keys
    expect(window.size).toBe(1);
  });

  it("the join's window is ten per client in ten minutes", () => {
    expect([JOIN_LIMIT, JOIN_WINDOW_MS]).toEqual([10, 600_000]);
    joinWindow.clear();
    for (let i = 0; i < 10; i += 1) expect(joinWindow.hit("x").allowed).toBe(true);
    expect(joinWindow.hit("x").allowed).toBe(false);
    joinWindow.clear();
  });
});
