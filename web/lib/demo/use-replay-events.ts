"use client";

/**
 * useReplayEvents (spec, "Demo": the replay): a recorded run fed to the live screen's own reducer
 * on a compressed clock, in the browser, with no network. The events are re-stamped on the
 * replay's clock, and `now` is that clock, so the elapsed time, the lanes' times and "in corso da"
 * all read replay time. The replay pauses while the page is hidden and never leaps more than a
 * second at a time, so a visitor who looks away comes back to where it was.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { SETTLE_MS } from "@/components/live/hooks";
import { initialPlanLiveState, planEventsReducer, type PlanLiveState } from "@/lib/plan-events/reducer";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { replaySchedule } from "./schedule";

/** The first event waits for the live screen's baseline (components/live/hooks.ts, SETTLE_MS),
 * so the replayed events draw in and are announced as live ones. Strictly later, not equal: two
 * timers due in the same millisecond can both run before React renders, and the baseline would
 * then count the first events as history (no draw-in, no announcement). */
export const REPLAY_SETTLE_MS = SETTLE_MS + 150;

/** The clock updates a few times a second (the elapsed time shows seconds). */
const TICK_MS = 250;

/** The most the replay advances in one tick, after a hidden or frozen page. */
const MAX_STEP_MS = 1_000;

export interface ReplayOptions {
  /** 1 or 2: how fast the replay runs from now on. */
  speed: number;
  /** The run's start, an ISO instant (the first recorded event's): the replay's clock starts here. */
  epoch: string;
}

export interface ReplayResult {
  state: PlanLiveState;
  /** The replay's clock, in ms since the Unix epoch, for the elapsed time and the lanes. */
  now: number;
  done: boolean;
  /** Lands every event left and the end at once ("Salta al piano"). */
  skip: () => void;
}

export function useReplayEvents(events: readonly UIEvent[], { speed, epoch }: ReplayOptions): ReplayResult {
  const epochMs = Date.parse(epoch);
  const offsets = useMemo(() => replaySchedule(events), [events]);
  const total = offsets.at(-1) ?? 0;
  const restamped = useMemo(
    () => events.map((event, index) => ({ ...event, ts: new Date(epochMs + offsets[index]!).toISOString() })),
    [events, offsets, epochMs],
  );

  const [state, dispatch] = useReducer(planEventsReducer, undefined, () =>
    // The run is under way from the first frame: a running snapshot, as GET /plans/{id} would give.
    planEventsReducer(initialPlanLiveState(), {
      type: "detail",
      detail: {
        status: "running",
        created_at: epoch,
        updated_at: epoch,
        cost_cents: 0,
        budget_cents: 60,
        failure_reason: null,
        submit_attempts: 0,
      },
    }),
  );
  const [replayMs, setReplayMs] = useState(0);
  const [done, setDone] = useState(false);

  const speedRef = useRef(speed);
  const cursor = useRef(0);
  const position = useRef(0);
  const finished = useRef(false);

  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

  const finish = useCallback(() => {
    if (finished.current) return;
    finished.current = true;
    const rest = restamped.slice(cursor.current);
    cursor.current = restamped.length;
    if (rest.length > 0) dispatch({ type: "events", events: rest });
    dispatch({ type: "end", status: "ready" });
    position.current = total;
    setReplayMs(total);
    setDone(true);
  }, [restamped, total]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let last = 0;

    const tick = () => {
      if (finished.current) return;
      const realNow = Date.now();
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      // Never negative: a system clock set back must not run the replay backwards.
      const step = hidden ? 0 : Math.max(0, Math.min(realNow - last, MAX_STEP_MS));
      last = realNow;
      position.current = Math.min(total, position.current + step * speedRef.current);

      let next = cursor.current;
      while (next < restamped.length && offsets[next]! <= position.current) next += 1;
      if (next > cursor.current) {
        dispatch({ type: "events", events: restamped.slice(cursor.current, next) });
        cursor.current = next;
      }
      setReplayMs(position.current);
      if (cursor.current >= restamped.length) {
        finish();
        return;
      }
      const wait = (offsets[cursor.current]! - position.current) / speedRef.current;
      timer = setTimeout(tick, Math.max(16, Math.min(TICK_MS, wait)));
    };

    const start = setTimeout(() => {
      last = Date.now();
      tick();
    }, REPLAY_SETTLE_MS);
    return () => {
      clearTimeout(start);
      if (timer) clearTimeout(timer);
    };
  }, [restamped, offsets, total, finish]);

  return { state, now: epochMs + replayMs, done, skip: finish };
}
