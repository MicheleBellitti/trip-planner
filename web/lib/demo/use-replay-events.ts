"use client";

/**
 * useReplayEvents (spec, "Demo": the replay): a recorded run fed to the live screen's own reducer
 * on a compressed clock, in the browser, with no network. The events are re-stamped on the
 * replay's clock, and `now` is that clock, so the elapsed time, the lanes' times and "in corso da"
 * all read replay time. The replay pauses while the page is hidden and never leaps more than a
 * second at a time, so a visitor who looks away comes back to where it was.
 *
 * The recorded questions (the coordinator's `ask_traveller` pauses, plan decision 3): when a
 * question's asked event lands, the replay holds (`hold`). What the recording has before that
 * question's answer (the coordinator's waiting idle) still lands on the schedule; the answer does
 * not. While the replay holds, its clock runs at real time (1×, even at 2×, and not while the page
 * is hidden), and every later event is stamped later by the time held, so the stamps keep pace
 * with the clock. Then:
 * - untouched for DEMO_CHOICE_WINDOW_MS, the recording's picks show (`autoPick`) for
 *   AUTO_PICK_SHOW_MS, and the recorded answer lands;
 * - a visitor who picks takes over (`touch`): no timeout, the replay waits for `answer`, which
 *   lands their answer under the recorded answer's seq (the finished plan stays the recording's);
 * - "Salta al piano" (`skip`) lands everything as recorded.
 * Either way the replay goes on from the answer's place on the schedule.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { SETTLE_MS } from "@/components/live/hooks";
import {
  answeredTitle,
  readAskedChoice,
  readChoiceAnswer,
  type AnsweredBy,
  type ChoiceAnswerInput,
  type ChoiceView,
} from "@/lib/choices";
import { initialPlanLiveState, planEventsReducer, type PlanLiveState } from "@/lib/plan-events/reducer";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { replaySchedule } from "./schedule";

/** The first event waits for the live screen's baseline (components/live/hooks.ts, SETTLE_MS),
 * so the replayed events draw in and are announced as live ones. Strictly later, not equal: two
 * timers due in the same millisecond can both run before React renders, and the baseline would
 * then count the first events as history (no draw-in, no announcement). */
export const REPLAY_SETTLE_MS = SETTLE_MS + 150;

/** How long a question waits for the visitor, in visible time, before the recording answers. */
export const DEMO_CHOICE_WINDOW_MS = 15_000;

/** How long the recording's picks show on the cards before its answer lands. */
export const AUTO_PICK_SHOW_MS = 900;

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

/** A recorded question the replay is holding on. */
export interface ReplayHold {
  choiceId: string;
  /** demo clock ms; null once the visitor took over */
  resumeAt: number | null;
  /** The recording's picks, shown for AUTO_PICK_SHOW_MS before its answer lands; null until then. */
  autoPick: readonly string[] | null;
}

export interface ReplayResult {
  state: PlanLiveState;
  /** The replay's clock, in ms since the Unix epoch, for the elapsed time and the lanes. */
  now: number;
  done: boolean;
  /** The question the replay is holding on, or null. */
  hold: ReplayHold | null;
  /** Lands every event left and the end at once ("Salta al piano"), the recorded answers among them. */
  skip: () => void;
  /** Lands a synthesized answered event in place of the recorded one, and resumes. */
  answer: (input: ChoiceAnswerInput) => void;
  /** The visitor took over: no timeout (`resumeAt` null), the replay waits for `answer`. */
  touch: () => void;
}

/** A recorded question: the asked event's choice and the index of its recorded answer. */
interface Question {
  choice: ChoiceView;
  answer: number;
  /** What the recording picked. */
  picks: readonly string[];
}

/** The questions of a recording, by the index of their asked event: each one with a recorded
 * answer after it (a question left unanswered is replayed as recorded). */
function questionsOf(events: readonly UIEvent[]): ReadonlyMap<number, Question> {
  const questions = new Map<number, Question>();
  events.forEach((event, index) => {
    const choice = readAskedChoice(event.detail);
    if (!choice) return;
    const answer = events.findIndex(
      (later, at) => at > index && readChoiceAnswer(later.detail)?.choiceId === choice.id,
    );
    if (answer < 0) return;
    questions.set(index, { choice, answer, picks: readChoiceAnswer(events[answer]!.detail)?.selected ?? [] });
  });
  return questions;
}

interface HoldRun {
  question: Question;
  resumeAt: number | null;
  /** When the recording's picks began to show (demo clock ms), or null. */
  autoPickAt: number | null;
}

const holdView = (run: HoldRun | null): ReplayHold | null =>
  run && {
    choiceId: run.question.choice.id,
    resumeAt: run.resumeAt,
    autoPick: run.autoPickAt === null ? null : run.question.picks,
  };

export function useReplayEvents(events: readonly UIEvent[], { speed, epoch }: ReplayOptions): ReplayResult {
  const epochMs = Date.parse(epoch);
  const offsets = useMemo(() => replaySchedule(events), [events]);
  const questions = useMemo(() => questionsOf(events), [events]);
  const total = offsets.at(-1) ?? 0;

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
  const [clockMs, setClockMs] = useState(0);
  const [done, setDone] = useState(false);
  const [hold, setHold] = useState<ReplayHold | null>(null);

  const speedRef = useRef(speed);
  /** The next event to land. */
  const cursor = useRef(0);
  /** Where the replay is on the compressed schedule (ms from its start). */
  const position = useRef(0);
  /** How far the schedule has moved on the clock: the time held. The clock is position + shift. */
  const shift = useRef(0);
  const holding = useRef<HoldRun | null>(null);
  const finished = useRef(false);
  /** Runs a tick now (the clock to this moment, the next tick rescheduled); null before the start. */
  const tickNow = useRef<(() => void) | null>(null);

  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

  const stamp = useCallback(
    (event: UIEvent, at: number): UIEvent => ({ ...event, ts: new Date(epochMs + at).toISOString() }),
    [epochMs],
  );

  const setHolding = useCallback((run: HoldRun | null) => {
    holding.current = run;
    setHold(holdView(run));
  }, []);

  const finish = useCallback(() => {
    if (finished.current) return;
    finished.current = true;
    const from = cursor.current;
    const rest = events.slice(from).map((event, index) => stamp(event, offsets[from + index]! + shift.current));
    cursor.current = events.length;
    setHolding(null);
    if (rest.length > 0) dispatch({ type: "events", events: rest });
    dispatch({ type: "end", status: "ready" });
    position.current = total;
    setClockMs(total + shift.current);
    setDone(true);
  }, [events, offsets, total, stamp, setHolding]);

  /** Ends the hold with `answered` in place of the recorded answer, at the clock's moment; what
   * the recording has before the answer and has not landed yet comes first. The schedule goes on
   * from the answer's place, the clock from where it is. */
  const release = useCallback(
    (answered: UIEvent) => {
      const run = holding.current;
      if (!run || finished.current) return;
      const index = run.question.answer;
      const clock = position.current + shift.current;
      const batch = events.slice(cursor.current, index).map((event) => stamp(event, clock));
      batch.push(stamp(answered, clock));
      position.current = offsets[index]!;
      shift.current = clock - position.current;
      cursor.current = index + 1;
      setHolding(null);
      dispatch({ type: "events", events: batch });
    },
    [events, offsets, stamp, setHolding],
  );

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let last = 0;

    /** Lands the events the schedule has reached (never a held question's answer), and holds on a
     * question as soon as it lands. */
    const landDue = () => {
      const batch: UIEvent[] = [];
      const limit = () => holding.current?.question.answer ?? events.length;
      while (cursor.current < limit() && offsets[cursor.current]! <= position.current) {
        const index = cursor.current;
        batch.push(stamp(events[index]!, offsets[index]! + shift.current));
        cursor.current += 1;
        const question = questions.get(index);
        if (question && !holding.current) {
          // A long step (after a frozen page) may have run past the answer's place: the rest is held.
          const answerAt = offsets[question.answer]!;
          if (position.current > answerAt) {
            shift.current += position.current - answerAt;
            position.current = answerAt;
          }
          const clock = epochMs + position.current + shift.current;
          setHolding({ question, resumeAt: clock + DEMO_CHOICE_WINDOW_MS, autoPickAt: null });
        }
      }
      if (batch.length > 0) dispatch({ type: "events", events: batch });
    };

    /** Moves the replay on by `step` ms of visible time. */
    const advance = (step: number) => {
      const held = holding.current;
      if (held) {
        // Real time: the schedule runs on to the answer's place, then stands while the clock goes on.
        const moved = Math.min(step, Math.max(0, offsets[held.question.answer]! - position.current));
        position.current += moved;
        shift.current += step - moved;
      } else {
        position.current = Math.min(total, position.current + step * speedRef.current);
      }
      landDue();
      const run = holding.current;
      if (run) {
        const clock = epochMs + position.current + shift.current;
        if (run.resumeAt !== null && run.autoPickAt === null && clock >= run.resumeAt) {
          setHolding({ ...run, autoPickAt: clock });
        } else if (run.autoPickAt !== null && clock >= run.autoPickAt + AUTO_PICK_SHOW_MS) {
          release(events[run.question.answer]!);
        }
      }
      setClockMs(position.current + shift.current);
      if (cursor.current >= events.length) finish();
    };

    /** Until the next tick: the next event, or the next moment of a hold, at most TICK_MS. */
    const nextWait = (hidden: boolean) => {
      if (hidden) return TICK_MS;
      const run = holding.current;
      if (!run) {
        const wait = (offsets[cursor.current]! - position.current) / speedRef.current;
        return Math.max(16, Math.min(TICK_MS, wait));
      }
      // At 1×, to the millisecond: the picks show, and the answer lands, on time.
      const clock = epochMs + position.current + shift.current;
      const moments = [TICK_MS];
      if (cursor.current < run.question.answer) moments.push(offsets[cursor.current]! - position.current);
      if (run.resumeAt !== null && run.autoPickAt === null) moments.push(run.resumeAt - clock);
      if (run.autoPickAt !== null) moments.push(run.autoPickAt + AUTO_PICK_SHOW_MS - clock);
      return Math.max(1, Math.min(...moments));
    };

    const tick = () => {
      if (finished.current) return;
      const realNow = Date.now();
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      // Never negative: a system clock set back must not run the replay backwards.
      const step = hidden ? 0 : Math.max(0, Math.min(realNow - last, MAX_STEP_MS));
      last = realNow;
      advance(step);
      if (finished.current) return;
      timer = setTimeout(tick, nextWait(hidden));
    };

    const start = setTimeout(() => {
      last = Date.now();
      tickNow.current = () => {
        if (timer) clearTimeout(timer);
        tick();
      };
      tick();
    }, REPLAY_SETTLE_MS);
    return () => {
      tickNow.current = null;
      clearTimeout(start);
      if (timer) clearTimeout(timer);
    };
  }, [events, offsets, questions, total, epochMs, stamp, setHolding, release, finish]);

  const answer = useCallback(
    (input: ChoiceAnswerInput) => {
      // The answer lands at this moment, not at the last tick's, and the replay goes on from it.
      tickNow.current?.();
      const run = holding.current;
      if (!run) return;
      const { choice, answer: index } = run.question;
      const recorded = events[index]!;
      const by: AnsweredBy = "skip" in input ? "skip" : "traveller";
      // In the order offered, as the backend keeps them.
      const selected =
        "skip" in input ? [] : choice.options.filter((option) => input.selected.includes(option.id)).map((option) => option.id);
      const at = new Date(epochMs + position.current + shift.current).toISOString();
      release({
        ...recorded,
        title: answeredTitle(choice, by, selected),
        detail: { ...recorded.detail, answered_by: by, selected, answered_at: at },
      });
      tickNow.current?.();
    },
    [events, epochMs, release],
  );

  const touch = useCallback(() => {
    const run = holding.current;
    if (!run || run.resumeAt === null || run.autoPickAt !== null) return;
    setHolding({ ...run, resumeAt: null });
  }, [setHolding]);

  return { state, now: epochMs + clockMs, done, hold, skip: finish, answer, touch };
}
