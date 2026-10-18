import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { REPLAY_TARGET_MS } from "./schedule";
import { REPLAY_SETTLE_MS, useReplayEvents } from "./use-replay-events";

const events = backend.events as unknown as UIEvent[];
const epoch = events[0]!.ts;
const epochMs = Date.parse(epoch);

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useReplayEvents", () => {
  it("shows a running plan at once, and the first event once the page has settled", async () => {
    const { result } = renderHook(() => useReplayEvents(events, { speed: 1, epoch }));
    expect(result.current.state.status).toBe("running");
    expect(result.current.state.events).toHaveLength(0);
    await advance(REPLAY_SETTLE_MS + 50);
    expect(result.current.state.events.length).toBeGreaterThan(0);
  });

  it("lands every event and ends ready, its clock at the replay's length", async () => {
    const { result } = renderHook(() => useReplayEvents(events, { speed: 1, epoch }));
    await advance(REPLAY_SETTLE_MS + REPLAY_TARGET_MS + 1_000);
    expect(result.current.state.events).toHaveLength(events.length);
    expect(result.current.state.status).toBe("ready");
    expect(result.current.done).toBe(true);
    expect(result.current.now - epochMs).toBe(REPLAY_TARGET_MS);
  });

  it("re-stamps the events on the replay's clock, so the elapsed time and the lanes agree", async () => {
    const { result } = renderHook(() => useReplayEvents(events, { speed: 1, epoch }));
    await advance(REPLAY_SETTLE_MS + 10_000);
    const last = result.current.state.events.at(-1)!;
    expect(Date.parse(last.ts)).toBeLessThanOrEqual(result.current.now);
    expect(result.current.now - epochMs).toBeGreaterThan(9_000);
    expect(result.current.now - epochMs).toBeLessThan(11_000);
  });

  it("jumps to the finished plan on skip", async () => {
    const { result } = renderHook(() => useReplayEvents(events, { speed: 1, epoch }));
    await advance(REPLAY_SETTLE_MS + 2_000);
    act(() => result.current.skip());
    expect(result.current.state.events).toHaveLength(events.length);
    expect(result.current.state.status).toBe("ready");
    expect(result.current.done).toBe(true);
  });

  it("runs the rest twice as fast at 2×, and its clock never goes back", async () => {
    const { result, rerender } = renderHook(({ speed }) => useReplayEvents(events, { speed, epoch }), {
      initialProps: { speed: 1 },
    });
    await advance(REPLAY_SETTLE_MS + 10_000);
    const before = result.current.now;
    rerender({ speed: 2 });
    expect(result.current.now).toBeGreaterThanOrEqual(before);
    await advance(10_000);
    const replayed = result.current.now - epochMs;
    expect(replayed).toBeGreaterThan(28_000);
    expect(replayed).toBeLessThan(32_000);
  });

  it("picks up where it was after the page sat in the background, and still ends ready", async () => {
    const { result } = renderHook(() => useReplayEvents(events, { speed: 1, epoch }));
    await advance(REPLAY_SETTLE_MS + 5_000);
    const before = result.current.now;
    // No timer ran for a minute (a hidden tab): the clock must not leap a minute ahead.
    vi.setSystemTime(Date.now() + 60_000);
    await advance(300);
    expect(result.current.now - before).toBeLessThan(2_000);
    await advance(REPLAY_TARGET_MS);
    expect(result.current.state.status).toBe("ready");
  });
});
