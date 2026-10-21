"use client";

/**
 * The traveller's choice: the coordinator's `ask_traveller` pause as a panel of cards (spec
 * 2026-10-18-plan-creation-ux-design.md §2, DESIGN.md "Choice cards"). The live screen and the
 * demo load it lazily (hence the default export) and own what it cannot know: `answer` sends,
 * `now` ticks, and the parent hides the panel once the answer went.
 *
 * - In order: the eyebrow (whose findings, with that line's roundel), the question (the `h2` that
 *   labels the section and the cards' group, focused once per choice id), the intro that states
 *   the rule once, the cards, the countdown, the action row (the count, "Scegli tu", the primary)
 *   and, above that row, the error of the last send.
 * - The picks are the panel's own, kept per choice id: the same question as a new object (the
 *   reducer derives it again) keeps them and the focus where it is; the next question starts
 *   empty. A failed send keeps them.
 * - States: picking; sending (the pressed button turns, everything rests); failed (the error,
 *   picks kept); closed (the backend's sentence takes the place of the countdown and the buttons);
 *   expired (the countdown at zero, everything rests); auto-picking (the demo's picks show, every
 *   control rests, no countdown).
 * - Nothing animates and nothing is amber (DESIGN.md, "Choice cards" and Motion).
 */

import { useEffect, useId, useRef, useState } from "react";

import { AgentRoundel } from "@/components/ui/agent";
import { Button } from "@/components/ui/button";
import { ChoiceCard, type ChoiceCardMedia } from "@/components/ui/choice-card";
import { Countdown } from "@/components/ui/countdown";
import { cx } from "@/components/ui/cx";
import { Notice } from "@/components/ui/notice";
import {
  CHOICE_PANEL_ID,
  choiceEyebrow,
  choiceIntro,
  choiceRule,
  choiceWindowMs,
  type ChoiceAnswerInput,
  type ChoiceView,
} from "@/lib/choices";

export interface ChoiceControls {
  /** Sends the answer; resolves to an Italian error to show, null when it went, or
   *  { closed: message } when the backend says the question is closed (409). */
  answer(choiceId: string, answer: ChoiceAnswerInput): Promise<null | string | { closed: string }>;
  /** The countdown's deadline (ms). Default: the choice's deadline_at. Null: no countdown and no rule. */
  deadlineAt?: number | null;
  /** The countdown's whole window (ms), for its bar. Default: choiceWindowMs(choice). */
  windowMs?: number;
  /** The intro's second sentence. Default: choiceRule(choiceWindowMs(choice)). Null: none. */
  rule?: string | null;
  /** The demo picking for the visitor: these cards show selected, every control rests and the
   *  countdown is hidden. */
  autoPick?: readonly string[] | null;
  /** The visitor changed a pick (the demo stops its clock). */
  onTouch?: () => void;
}

interface ChoicePanelProps {
  choice: ChoiceView;
  controls: ChoiceControls;
  /** The shared clock (lib/use-now, or the demo's); null before its first tick. */
  now: number | null;
  /** The request's destination, for the eyebrow; null drops the place. */
  destination: string | null;
}

/** What the error says when `answer` throws instead of resolving (it should not: callers turn
 * their failures into a sentence). The panel never imports lib/api, which the demo must not load. */
const UNEXPECTED_FAILURE = "Non sono riuscito a inviarla per un errore inatteso. Riprova.";

type Phase =
  | { kind: "picking"; error: string | null }
  /** `via`: the button that was pressed, the one that turns. */
  | { kind: "sending"; via: "picks" | "skip" }
  /** The answer went: everything rests until the parent hides the panel. */
  | { kind: "sent" }
  | { kind: "closed"; message: string };

interface PanelState {
  choiceId: string;
  picked: readonly string[];
  phase: Phase;
}

const fresh = (choiceId: string): PanelState => ({ choiceId, picked: [], phase: { kind: "picking", error: null } });

type Outcome = Awaited<ReturnType<ChoiceControls["answer"]>>;

/** Where a send leaves the panel: resting once it went, back to picking with the error, or closed. */
function phaseAfter(outcome: Outcome): Phase {
  if (outcome === null) return { kind: "sent" };
  if (typeof outcome === "string") return { kind: "picking", error: outcome };
  return { kind: "closed", message: outcome.closed };
}

/** One photo frame for every card: none when no option has a photo (a tile is not a photo),
 * else 16:10 for food and 4:3 for the rest. */
function mediaOf(choice: ChoiceView): ChoiceCardMedia {
  if (!choice.options.some((option) => option.photo !== null)) return "none";
  return choice.kind === "food" ? "16/10" : "4/3";
}

function countLabel(n: number): string {
  if (n === 0) return "Nessuna scelta";
  return n === 1 ? "1 scelta" : `${n} scelte`;
}

/** The intro's second sentence: the caller's, else the window's ("Se non scegli entro 4 minuti,
 * scelgo io."); none without a deadline or with an empty window. */
function ruleOf(controls: ChoiceControls, windowMs: number, deadlineAt: number | null): string | null {
  if (deadlineAt === null) return null;
  if (controls.rule !== undefined) return controls.rule;
  return windowMs > 0 ? choiceRule(windowMs) : null;
}

export function ChoicePanel({ choice, controls, now, destination }: ChoicePanelProps) {
  const name = useId();
  const headingId = `${CHOICE_PANEL_ID}-domanda`;
  const sectionRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const closedRef = useRef<HTMLDivElement>(null);
  // The question whose first pick was already reported to `onTouch`.
  const touched = useRef<string | null>(null);
  const [stored, setStored] = useState<PanelState>(() => fresh(choice.id));
  const state = stored.choiceId === choice.id ? stored : fresh(choice.id);
  const { phase } = state;

  const windowMs = controls.windowMs ?? choiceWindowMs(choice);
  const deadlineAt = controls.deadlineAt === undefined ? Date.parse(choice.deadlineAt) : controls.deadlineAt;
  const rule = ruleOf(controls, windowMs, deadlineAt);
  const expired = deadlineAt !== null && now !== null && now >= deadlineAt;
  const autoPick = controls.autoPick ?? null;
  const resting = autoPick !== null || expired || phase.kind !== "picking";
  const shown = autoPick ?? state.picked;
  const media = mediaOf(choice);

  // Keyed on the id, never the object: a new object for the same question must not take the focus
  // back from wherever the traveller moved it. The focus alone would centre the heading, leaving
  // the countdown and the buttons under the fold: the panel's top goes under the sticky bars
  // instead (`scroll-padding-top`), so the whole question is in view.
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
    sectionRef.current?.scrollIntoView?.({ block: "start" });
  }, [choice.id]);

  // The buttons the traveller pressed are gone: the backend's sentence takes the focus, and says it.
  useEffect(() => {
    if (phase.kind === "closed") closedRef.current?.focus();
  }, [phase.kind]);

  /** Changes the current question's state, starting it afresh if it is new. */
  const change = (next: (current: PanelState) => PanelState) =>
    setStored((current) => next(current.choiceId === choice.id ? current : fresh(choice.id)));

  function pick(id: string, checked: boolean) {
    if (resting) return;
    if (touched.current !== choice.id) {
      touched.current = choice.id;
      controls.onTouch?.();
    }
    change((current) => {
      const others = current.picked.filter((value) => value !== id);
      const picked = checked ? (choice.multiple ? [...others, id] : [id]) : others;
      return { ...current, picked };
    });
  }

  async function send(input: ChoiceAnswerInput, via: "picks" | "skip") {
    if (resting) return;
    const choiceId = choice.id;
    change((current) => ({ ...current, phase: { kind: "sending", via } }));
    let outcome: Outcome;
    try {
      outcome = await controls.answer(choiceId, input);
    } catch {
      outcome = UNEXPECTED_FAILURE;
    }
    // A late answer for a question that has since changed leaves the new one alone.
    setStored((current) => (current.choiceId === choiceId ? { ...current, phase: phaseAfter(outcome) } : current));
  }

  // The picks in the order the cards were offered, whatever order they were made in.
  const selected = choice.options.filter((option) => state.picked.includes(option.id)).map((option) => option.id);
  const sendingVia = phase.kind === "sending" ? phase.via : null;

  return (
    <section ref={sectionRef} id={CHOICE_PANEL_ID} aria-labelledby={headingId} className="min-w-0">
      <div className="grid max-w-prose gap-1">
        <p className="flex items-center gap-2 text-meta font-medium text-ink-2">
          <AgentRoundel agent={choice.kind === "activities" ? "activities" : "coordinator"} size="sm" />
          {choiceEyebrow(choice, destination)}
        </p>
        <h2
          ref={headingRef}
          id={headingId}
          tabIndex={-1}
          className="mt-1 font-cond text-heading font-semibold [overflow-wrap:anywhere] focus:outline-none"
        >
          {choice.question}
        </h2>
        <p className="text-body text-ink-2">{rule ? `${choiceIntro(choice)} ${rule}` : choiceIntro(choice)}</p>
      </div>

      <div
        role={choice.multiple ? "group" : "radiogroup"}
        aria-labelledby={headingId}
        className={cx(
          // At most the plans list's measure: wider, the 4:3 photos alone would fill a laptop's
          // window and push the countdown and the buttons out of it.
          "mt-4 grid max-w-[64rem] grid-cols-2 gap-2.5 lg:gap-3.5",
          choice.kind === "food" ? "lg:grid-cols-4" : "lg:grid-cols-3",
        )}
      >
        {choice.options.map((option) => (
          <ChoiceCard
            key={option.id}
            option={option}
            control={choice.multiple ? "checkbox" : "radio"}
            name={name}
            checked={shown.includes(option.id)}
            disabled={resting}
            onChange={(checked) => pick(option.id, checked)}
            media={media}
          />
        ))}
      </div>

      {phase.kind === "closed" ? (
        <div ref={closedRef} tabIndex={-1} className="mt-4 max-w-prose rounded-sm focus:outline-none">
          <Notice>{phase.message}</Notice>
        </div>
      ) : (
        <>
          {deadlineAt !== null && autoPick === null ? (
            <Countdown deadlineAt={deadlineAt} windowMs={windowMs} now={now} className="mt-4 max-w-md" />
          ) : null}
          {phase.kind === "picking" && phase.error ? (
            <Notice tone="error" role="alert" title="Scelta non inviata" className="mt-3 max-w-prose">
              {phase.error}
            </Notice>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            {choice.multiple ? (
              // As wide as its longest wording ("Nessuna scelta"), so the buttons never move as it counts.
              <p className="text-meta font-medium text-ink-2 max-sm:w-full sm:min-w-[14ch]">{countLabel(shown.length)}</p>
            ) : null}
            <div className="flex gap-2 max-sm:w-full">
              <Button
                busy={sendingVia === "skip"}
                disabled={resting}
                onClick={() => void send({ skip: true }, "skip")}
                className="pointer-coarse:min-h-11"
              >
                Scegli tu
              </Button>
              <Button
                variant="primary"
                busy={sendingVia === "picks"}
                disabled={resting || shown.length === 0}
                onClick={() => void send({ selected }, "picks")}
                className="pointer-coarse:min-h-11 max-sm:flex-1"
              >
                {!choice.multiple || shown.length === 1 ? "Continua con questa" : "Continua con queste"}
              </Button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

export default ChoicePanel;
