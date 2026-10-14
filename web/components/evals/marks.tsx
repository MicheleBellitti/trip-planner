import { cx } from "@/components/ui/cx";
import { Icon, type IconName } from "@/components/ui/icon";

import { checkKind, RUN_VERDICT_LABELS, type CheckKind, type RunVerdict } from "./eval-model";

/** The line's own form for a stretch that was not travelled (status-badge.tsx draws the same
 * dashed ring for a lane that never started): here a check that was skipped, a run nobody
 * compared. Eight dashes on a 15 px box. */
export function DashedRing({ size = 15 }: { size?: number }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 15 15" width={size} height={size} className="shrink-0">
      <circle cx="7.5" cy="7.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeDasharray="2.7 1.62" />
    </svg>
  );
}

const VERDICT_GLYPHS: Record<Exclude<RunVerdict, "unknown">, IconName> = {
  passed: "check-circle",
  blocked: "prohibit",
  report_only: "info",
  aborted: "stop-circle",
};

/** A run verdict's glyph alone: a check, a prohibition sign, an info mark, a stop, or the dashed
 * ring of a run nobody compared. The word goes beside it (RunVerdictPill) or elsewhere on the row. */
export function RunVerdictGlyph({ verdict, size = 15 }: { verdict: RunVerdict; size?: number }) {
  return verdict === "unknown" ? <DashedRing size={size} /> : <Icon name={VERDICT_GLYPHS[verdict]} size={size} />;
}

/** The ink for a verdict: a passed run is green, a blocked one red (The Green Means Passed Rule),
 * the rest quiet; each always has its word and its glyph. */
export function verdictTone(verdict: RunVerdict): string {
  return verdict === "blocked" ? "text-error" : verdict === "passed" ? "text-success" : "text-ink-2";
}

/** The wash under a verdict's pill: green, red, or the quiet notice wash. */
function verdictWash(verdict: RunVerdict): string {
  return verdict === "blocked" ? "bg-error-wash" : verdict === "passed" ? "bg-success-wash" : "bg-notice-wash";
}

/** A run's verdict as a pill: the word and the glyph on its wash, at title size in the dashboard
 * and the run's header, where the verdict is the first thing read. */
export function RunVerdictPill({ verdict, className }: { verdict: RunVerdict; className?: string }) {
  return (
    <span
      data-verdict={verdict}
      className={cx(
        "inline-flex items-center gap-2 rounded-full py-1 pr-3.5 pl-2.5 font-cond text-title font-semibold",
        verdictWash(verdict),
        verdictTone(verdict),
        className,
      )}
    >
      <RunVerdictGlyph verdict={verdict} size={18} />
      {RUN_VERDICT_LABELS[verdict]}
    </span>
  );
}

const CHECK_GLYPHS: Record<Exclude<CheckKind, "skip">, IconName> = {
  pass: "check-circle",
  warn: "warning",
  fail: "x-circle",
  error: "x-circle",
};

/** The ink of a check's status: failures in error red (always with a cross and a word), passes
 * green (with a check), warnings in ink (with a warning sign), skips quiet (a dashed ring). */
export function checkTone(status: string): string {
  const kind = checkKind(status);
  return kind === "fail" || kind === "error"
    ? "text-error"
    : kind === "pass"
      ? "text-success"
      : kind === "warn"
        ? "text-ink"
        : "text-ink-2";
}

/** A check's status glyph: check (Superato), warning (Avviso), cross (Non superato, Errore), dashed
 * ring (Saltato). The word is written next to it by the row. */
export function CheckGlyph({ status, size = 15 }: { status: string; size?: number }) {
  const kind = checkKind(status);
  return kind === "skip" ? <DashedRing size={size} /> : <Icon name={CHECK_GLYPHS[kind]} size={size} />;
}

/** The ink of a judge score: 4 and 5 green (Buono, Ottimo), 1 and 2 red (Inutilizzabile,
 * Scarso), 3 plain ink. */
export function scoreTone(score: number): string {
  return score >= 4 ? "border-success text-success" : score <= 2 ? "border-error text-error" : "border-ink text-ink";
}

/** A judge score as a roundel with the number in it: the number is the information, the ring is
 * only its station, in the score's ink; the word is written beside it. */
export function ScoreRoundel({ score, className }: { score: number; className?: string }) {
  return (
    <span
      data-score={score}
      className={cx(
        "grid size-7 shrink-0 place-items-center rounded-full border-[2.5px] font-cond text-small font-semibold",
        scoreTone(score),
        className,
      )}
    >
      <span aria-hidden="true">{score}</span>
      <span className="sr-only">{score} su 5</span>
    </span>
  );
}
