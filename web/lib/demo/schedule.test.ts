import { describe, expect, it } from "vitest";

import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { REPLAY_TARGET_MS, replaySchedule } from "./schedule";

const events = backend.events as unknown as UIEvent[];
const at = (ms: number) => ({ ts: new Date(Date.UTC(2026, 9, 12, 10) + ms).toISOString() });

describe("replaySchedule", () => {
  it("gives every recorded event an offset, from 0 to the replay's length, never going back", () => {
    const offsets = replaySchedule(events);
    expect(offsets).toHaveLength(events.length);
    expect(offsets[0]).toBe(0);
    expect(offsets.at(-1)).toBe(REPLAY_TARGET_MS);
    offsets.slice(1).forEach((offset, index) => expect(offset).toBeGreaterThanOrEqual(offsets[index]!));
  });

  it("weighs a long silence no more than a clamped gap, and a burst no less than the floor", () => {
    // Gaps of 5.5 s and 20 ms clamp to 2.5 s and 80 ms before scaling to the target.
    const offsets = replaySchedule([at(0), at(5_500), at(5_520)], { target: 2_580 });
    expect(offsets).toEqual([0, 2_500, 2_580]);
  });
});
