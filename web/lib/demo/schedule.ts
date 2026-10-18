/**
 * The demo's timetable (spec, "Demo": the replay): the recorded run took about 78 s, with silences
 * of up to 5.5 s while a model thought and bursts of events 20 ms apart. The replay keeps the
 * run's rhythm but not its waits: each gap is clamped between 80 ms and 2.5 s, then the whole is
 * scaled to last 45 s at 1×.
 */

export const REPLAY_TARGET_MS = 45_000;

/** One offset in ms from the replay's start per event, the first at 0 and the last at `target`. */
export function replaySchedule(
  events: readonly { ts: string }[],
  { target = REPLAY_TARGET_MS, min = 80, max = 2_500 }: { target?: number; min?: number; max?: number } = {},
): number[] {
  if (events.length === 0) return [];
  const times = events.map((event) => Date.parse(event.ts));
  const gaps = times.slice(1).map((time, index) => Math.min(max, Math.max(min, time - times[index]!)));
  const total = gaps.reduce((sum, gap) => sum + gap, 0);
  const scale = total > 0 ? target / total : 0;
  const offsets = [0];
  let elapsed = 0;
  for (const gap of gaps) {
    elapsed += gap * scale;
    offsets.push(Math.round(elapsed));
  }
  if (offsets.length > 1) offsets[offsets.length - 1] = target;
  return offsets;
}
