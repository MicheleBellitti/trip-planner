import { LANE_BADGE_LABELS, PLAN_STATUS_LABELS, type LaneBadgeState } from "@/lib/plan-events/labels";
import type { PlanStatus } from "@/lib/schemas/api";
import type { AgentName } from "@/lib/schemas/generated/ui-event";

import { cx } from "./cx";
import { Icon, type IconName } from "./icon";

/** "in attesa" -> "In attesa": a badge starts a phrase, so it gets sentence case. */
function sentenceCase(text: string): string {
  return text.charAt(0).toLocaleUpperCase("it") + text.slice(1);
}

/** The "at work" glyph: a hollow ring in the lane's colour, the same station ring the line draws.
 * Reduced motion has nothing to drop: it never moves. */
function WorkingRing({ inLineColour }: { inLineColour: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "inline-block size-[11px] shrink-0 rounded-full border-[2.5px]",
        inLineColour ? "border-line" : "border-ink",
      )}
    />
  );
}

/** The "never started" glyph: a dashed ring, the line's own form for a stretch that was not
 * travelled (the dashed stub, the empty waiting line). Eight dashes on a 15 px box. */
function DashedRing() {
  return (
    <svg aria-hidden="true" viewBox="0 0 15 15" width={15} height={15} className="shrink-0">
      <circle cx="7.5" cy="7.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeDasharray="2.7 1.62" />
    </svg>
  );
}

const LANE_GLYPHS: Record<Exclude<LaneBadgeState, "working" | "not_started">, IconName> = {
  waiting: "hourglass-medium",
  done: "check-circle",
  error: "x-circle",
  stopped: "stop-circle",
};

/**
 * A lane's state as a word and a glyph, never colour alone: in attesa (hourglass), al lavoro
 * (ring in the lane's colour), finito (check), errore (cross, error red), fermato (stop), and
 * non partita (dashed ring): a lane of an ended plan that never got an event.
 * `agent` gives the working ring its line colour; without it the ring is ink.
 */
export function StatusBadge({
  state,
  agent,
  className,
}: {
  state: LaneBadgeState;
  agent?: AgentName;
  className?: string;
}) {
  return (
    <span
      data-agent={agent}
      data-state={state}
      className={cx(
        "inline-flex items-center gap-1.5 text-meta font-medium",
        state === "working" ? "text-ink" : state === "error" ? "text-error" : "text-ink-2",
        className,
      )}
    >
      {state === "working" ? (
        <WorkingRing inLineColour={agent !== undefined} />
      ) : state === "not_started" ? (
        <DashedRing />
      ) : (
        <Icon name={LANE_GLYPHS[state]} size={15} />
      )}
      {sentenceCase(LANE_BADGE_LABELS[state])}
    </span>
  );
}

const PLAN_GLYPHS: Record<Exclude<PlanStatus, "running">, IconName> = {
  ready: "check-circle",
  failed: "x-circle",
  budget_paused: "pause-circle",
  blocked: "prohibit",
  interrupted: "stop-circle",
};

const PLAN_GLYPH_SIZES = {
  md: { ring: "size-[11px] border-[2.5px]", icon: 15 },
  lg: { ring: "size-3 border-[3px]", icon: 18 },
  /** A station on the home list's rail: the running plan's ring is the large "you are here" one. */
  node: { ring: "size-[18px] border-4", icon: 20 },
} as const;

/** A plan status's glyph alone: an ink ring while running, else the status's line form (check,
 * cross, pause, prohibit, stop). The word goes beside it (PlanStatusBadge) or elsewhere on the
 * row (the home list's rail draws the glyph as the plan's station). */
export function PlanStatusGlyph({ status, size = "md" }: { status: PlanStatus; size?: keyof typeof PLAN_GLYPH_SIZES }) {
  const { ring, icon } = PLAN_GLYPH_SIZES[size];
  return status === "running" ? (
    <span aria-hidden="true" className={cx("inline-block shrink-0 rounded-full border-ink", ring)} />
  ) : (
    <Icon name={PLAN_GLYPHS[status]} size={icon} />
  );
}

/**
 * A plan's status as a word and a glyph: In corso (an ink ring, the live station), Pronto,
 * Budget raggiunto, Interrotto, and the two failures in error red (Non riuscito, Bloccato).
 * `size="lg"` is the live header's condensed title size.
 */
export function PlanStatusBadge({
  status,
  size = "md",
  className,
}: {
  status: PlanStatus;
  size?: "md" | "lg";
  className?: string;
}) {
  const failure = status === "failed" || status === "blocked";
  return (
    <span
      data-status={status}
      className={cx(
        "inline-flex items-center",
        size === "lg" ? "gap-2 font-cond text-title font-semibold" : "gap-1.5 text-meta font-medium",
        failure ? "text-error" : status === "running" || size === "lg" ? "text-ink" : "text-ink-2",
        className,
      )}
    >
      <PlanStatusGlyph status={status} size={size} />
      {PLAN_STATUS_LABELS[status]}
    </span>
  );
}
