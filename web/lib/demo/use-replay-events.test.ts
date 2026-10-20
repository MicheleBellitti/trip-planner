import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { answeredTitle, readAskedChoice } from "@/lib/choices";
import choicesRun from "@/lib/plan-events/__fixtures__/backend/choices.json";
import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { REPLAY_TARGET_MS, replaySchedule } from "./schedule";
import { AUTO_PICK_SHOW_MS, DEMO_CHOICE_WINDOW_MS, REPLAY_SETTLE_MS, useReplayEvents } from "./use-replay-events";

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

/** Advances in steps of `step` ms until `happened` (within a minute, else the test fails). */
async function advanceUntil(happened: () => boolean, step: number) {
  for (let waited = 0; !happened(); waited += step) {
    if (waited > 60_000) throw new Error("it never happened");
    await advance(step);
  }
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
  it("never runs its clock back, even if the system clock does", async () => {
    const { result } = renderHook(() => useReplayEvents(events, { speed: 1, epoch }));
    await advance(REPLAY_SETTLE_MS + 5_000);
    const before = result.current.now;
    vi.setSystemTime(Date.now() - 60_000);
    await advance(300);
    expect(result.current.now).toBeGreaterThanOrEqual(before);
  });
});

describe("useReplayEvents, the recorded questions", () => {
  /** The recording that asks twice: seq 53 what to see (answered at 56), seq 77 what to eat (80). */
  const run = choicesRun.events as unknown as UIEvent[];
  const runEpoch = run[0]!.ts;
  const runEpochMs = Date.parse(runEpoch);
  const offsets = replaySchedule(run);
  const indexOf = (seq: number) => run.findIndex((event) => event.seq === seq);
  /** Where an event sits on the compressed schedule (ms from the replay's start). */
  const at = (seq: number) => offsets[indexOf(seq)]!;
  const recorded = (seq: number) => run[indexOf(seq)]!;
  const activities = readAskedChoice(recorded(53).detail)!;
  const food = readAskedChoice(recorded(77).detail)!;
  /** The time a passive hold adds to the clock: the window and the picks shown, less the schedule's
   * own gap from the question to its answer (the clock runs through it at 1× during the hold). */
  const heldFor = (asked: number, answered: number) =>
    DEMO_CHOICE_WINDOW_MS + AUTO_PICK_SHOW_MS - (at(answered) - at(asked));

  const play = (speed = 1) =>
    renderHook(({ speed }) => useReplayEvents(run, { speed, epoch: runEpoch }), { initialProps: { speed } });
  type Played = ReturnType<typeof play>["result"];
  const lastSeq = (result: Played) => result.current.state.lastSeq;
  const landed = (result: Played, seq: number) => result.current.state.events.find((event) => event.seq === seq);

  function hide(hidden: boolean) {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => (hidden ? "hidden" : "visible"),
    });
  }
  afterEach(() => {
    hide(false);
  });

  it("holds on the first question: nothing after it lands, the clock keeps running at real time, at 2× too", async () => {
    const { result, rerender } = play();
    await advance(REPLAY_SETTLE_MS + at(53) - 1);
    expect(lastSeq(result)).toBe(52);
    expect(result.current.hold).toBeNull();

    await advance(1);
    const askedAt = result.current.now;
    expect(askedAt - runEpochMs).toBe(at(53));
    expect(result.current.hold).toEqual({
      choiceId: activities.id,
      resumeAt: askedAt + DEMO_CHOICE_WINDOW_MS,
      autoPick: null,
    });
    expect(result.current.state.openChoice?.choice.id).toBe(activities.id);

    // The coordinator's waiting idle, recorded before the answer, still lands on the schedule.
    await advance(at(55) - at(53));
    expect(lastSeq(result)).toBe(55);
    expect(Date.parse(landed(result, 55)!.ts)).toBe(runEpochMs + at(55));

    // 2× does not hurry a question: the clock runs at real time, and the answer does not land.
    rerender({ speed: 2 });
    const before = result.current.now;
    await advance(10_000);
    expect(result.current.now - before).toBe(10_000);
    expect(lastSeq(result)).toBe(55);
    expect(result.current.hold).toMatchObject({ resumeAt: askedAt + DEMO_CHOICE_WINDOW_MS, autoPick: null });
  });

  it("holds at real time when 2× was pressed before the question", async () => {
    const { result } = play(2);
    await advanceUntil(() => result.current.hold !== null, 10);
    // The question landed within the last 10 ms of real time.
    const seen = Date.now();
    const resumeAt = result.current.hold!.resumeAt!;
    await advanceUntil(() => result.current.hold?.autoPick !== null, 10);
    // The window took 15 s of real time (7.5 s at 2×), and the clock 15 s.
    expect(Date.now() - seen).toBeGreaterThan(DEMO_CHOICE_WINDOW_MS - 10);
    expect(Date.now() - seen).toBeLessThanOrEqual(DEMO_CHOICE_WINDOW_MS + 10);
    expect(result.current.now).toBe(resumeAt);
    expect(lastSeq(result)).toBe(55);
  });

  it("does not count hidden time against the hold", async () => {
    const { result } = play();
    await advance(REPLAY_SETTLE_MS + at(53));
    const resumeAt = result.current.hold!.resumeAt!;
    await advance(5_000);

    hide(true);
    const before = result.current.now;
    await advance(60_000);
    expect(result.current.now).toBe(before);
    expect(result.current.hold).toEqual({ choiceId: activities.id, resumeAt, autoPick: null });
    expect(lastSeq(result)).toBe(55);

    // Back in view: the rest of the window, in visible time (to a tick), and the picks show on time.
    hide(false);
    const left = resumeAt - result.current.now;
    expect(left).toBeGreaterThan(9_000);
    await advance(left - 250);
    expect(result.current.hold?.autoPick).toBeNull();
    await advanceUntil(() => result.current.hold?.autoPick !== null, 10);
    expect(result.current.now).toBe(resumeAt);
  });

  it("without a touch, shows the recorded picks then lands the recorded answer and goes on", async () => {
    const { result } = play();
    await advance(REPLAY_SETTLE_MS + at(53));
    const resumeAt = result.current.now + DEMO_CHOICE_WINDOW_MS;

    await advance(DEMO_CHOICE_WINDOW_MS - 1);
    expect(result.current.hold).toEqual({ choiceId: activities.id, resumeAt, autoPick: null });
    await advance(1);
    expect(result.current.now).toBe(resumeAt);
    expect(result.current.hold).toEqual({ choiceId: activities.id, resumeAt, autoPick: ["a1", "a2"] });
    expect(lastSeq(result)).toBe(55);

    await advance(AUTO_PICK_SHOW_MS - 1);
    expect(lastSeq(result)).toBe(55);
    await advance(1);
    // The recording's own answer, unchanged but for its stamp: the clock's.
    expect(result.current.hold).toBeNull();
    expect(lastSeq(result)).toBe(56);
    const answered = landed(result, 56)!;
    expect({ ...answered, ts: recorded(56).ts }).toEqual(recorded(56));
    expect(Date.parse(answered.ts)).toBe(resumeAt + AUTO_PICK_SHOW_MS);
    expect(result.current.now).toBe(resumeAt + AUTO_PICK_SHOW_MS);
    expect(result.current.state.openChoice).toBeNull();

    // It goes on: the next events keep their distance on the schedule, later by the time held.
    const shift = heldFor(53, 56);
    await advance(at(57) - at(56));
    expect(lastSeq(result)).toBe(57);
    expect(Date.parse(landed(result, 57)!.ts)).toBe(runEpochMs + at(57) + shift);

    // The second question holds the same way, and the run ends ready: the replay's length plus
    // the time both questions held.
    await advance(at(77) - at(57));
    expect(result.current.hold).toMatchObject({ choiceId: food.id, autoPick: null });
    await advance(DEMO_CHOICE_WINDOW_MS);
    expect(result.current.hold?.autoPick).toEqual(["c1", "c2"]);
    await advance(AUTO_PICK_SHOW_MS + REPLAY_TARGET_MS);
    expect(result.current.state.status).toBe("ready");
    expect(result.current.done).toBe(true);
    expect(result.current.state.events).toHaveLength(run.length);
    expect(result.current.now - runEpochMs).toBe(REPLAY_TARGET_MS + shift + heldFor(77, 80));
    const stamps = result.current.state.events.map((event) => Date.parse(event.ts));
    expect(stamps).toEqual([...stamps].sort((a, b) => a - b));
    expect(stamps.at(-1)).toBe(result.current.now);
  });

  it("answer() lands the visitor's picks under the recorded seq with answeredTitle's title, and goes on", async () => {
    const { result } = play();
    await advance(REPLAY_SETTLE_MS + at(55) + 3_000);
    const before = result.current.now;
    act(() => result.current.answer({ selected: ["a3", "a1"] }));
    // The clock comes to the answer's moment (from the last tick, under 250 ms ago).
    const now = result.current.now;
    expect(now - before).toBeGreaterThanOrEqual(0);
    expect(now - before).toBeLessThan(250);

    expect(result.current.hold).toBeNull();
    expect(lastSeq(result)).toBe(56);
    const answered = landed(result, 56)!;
    expect(answered.title).toBe("Hai scelto: Oceanário de Lisboa, Torre di Belém e Mosteiro dos Jerónimos");
    expect(answered.title).toBe(answeredTitle(activities, "traveller", ["a1", "a3"]));
    expect(answered).toEqual({
      ...recorded(56),
      ts: new Date(now).toISOString(),
      title: answered.title,
      detail: {
        ...recorded(56).detail,
        answered_by: "traveller",
        selected: ["a1", "a3"],
        answered_at: new Date(now).toISOString(),
      },
    });
    expect(result.current.state.openChoice).toBeNull();

    // It goes on from the answer at once, on the schedule.
    await advance(at(57) - at(56));
    expect(lastSeq(result)).toBe(57);
    expect(Date.parse(landed(result, 57)!.ts)).toBe(now + at(57) - at(56));

    // "Scegli tu" on the second question as soon as it is asked: what the recording has before
    // its answer (the usage and the waiting idle) lands first, then the skip, all at that moment.
    await advanceUntil(() => result.current.hold !== null, 10);
    expect(lastSeq(result)).toBe(77);
    act(() => result.current.answer({ skip: true }));
    const asked = result.current.now;
    expect(Date.parse(landed(result, 77)!.ts)).toBeLessThanOrEqual(asked);
    expect(result.current.state.events.slice(-3).map((event) => [event.seq, Date.parse(event.ts)])).toEqual([
      [78, asked],
      [79, asked],
      [80, asked],
    ]);
    const skipped = landed(result, 80)!;
    expect(skipped.title).toBe("Hai lasciato scegliere ad Atlas");
    expect(skipped.detail).toEqual({
      ...recorded(80).detail,
      answered_by: "skip",
      selected: [],
      answered_at: new Date(asked).toISOString(),
    });

    await advance(REPLAY_TARGET_MS);
    expect(result.current.state.status).toBe("ready");
  });

  it("touch() stops the hold's clock: the replay waits for the answer", async () => {
    const { result } = play();
    await advance(REPLAY_SETTLE_MS + at(53) + 2_000);
    act(() => result.current.touch());
    expect(result.current.hold).toEqual({ choiceId: activities.id, resumeAt: null, autoPick: null });

    // No timeout: long past the window, no picks show and nothing after the question lands; the
    // run's own clock goes on at real time.
    const before = result.current.now;
    await advance(60_000);
    expect(result.current.hold).toEqual({ choiceId: activities.id, resumeAt: null, autoPick: null });
    expect(lastSeq(result)).toBe(55);
    expect(result.current.now - before).toBe(60_000);

    act(() => result.current.answer({ selected: ["a2"] }));
    expect(landed(result, 56)?.title).toBe("Hai scelto: Palácio da Pena a Sintra");
    expect(result.current.hold).toBeNull();
  });

  it("skip() lands every event as recorded and ends ready", async () => {
    const { result } = play();
    await advance(REPLAY_SETTLE_MS + at(53) + 5_000);
    expect(result.current.hold).not.toBeNull();
    act(() => result.current.skip());

    expect(result.current.hold).toBeNull();
    expect(result.current.state.status).toBe("ready");
    expect(result.current.done).toBe(true);
    const events = result.current.state.events;
    const unstamped = (list: readonly UIEvent[]) => list.map((event) => ({ ...event, ts: "" }));
    expect(unstamped(events)).toEqual(unstamped(run));
    const stamps = events.map((event) => Date.parse(event.ts));
    expect(stamps).toEqual([...stamps].sort((a, b) => a - b));
    expect(stamps.at(-1)).toBe(result.current.now);

    // Nothing more happens: no hold for the second question, no clock running on.
    const now = result.current.now;
    await advance(30_000);
    expect(result.current.hold).toBeNull();
    expect(result.current.now).toBe(now);
  });
});
