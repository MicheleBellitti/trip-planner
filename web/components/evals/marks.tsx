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
 * ring of a run nobody compared. The word goes beside it (RunVerdictBadge) or elsewhere on the row. */
export function RunVerdictGlyph({ verdict, size = 15 }: { verdict: RunVerdict; size?: number }) {
  return verdict === "unknown" ? <DashedRing size={size} /> : <Icon name={VERDICT_GLYPHS[verdict]} size={size} />;
}

/** The ink for a verdict: only a blocked run is red, and it always has its word and its glyph. */
export function verdictTone(verdict: RunVerdict): string {
  return verdict === "blocked" ? "text-error" : verdict === "passed" ? "text-ink" : "text-ink-2";
}

/** A run's verdict as a word and a glyph (never colour alone): Superato, Bloccato, Solo report,
 * Interrotto, Senza confronto. `lg` is the page header's condensed title size. */
export function RunVerdictBadge({
  verdict,
  size = "md",
  className,
}: {
  verdict: RunVerdict;
  size?: "md" | "lg";
  className?: string;
}) {
  return (
    <span
      data-verdict={verdict}
      className={cx(
        "inline-flex items-center",
        size === "lg" ? "gap-2 font-cond text-title font-semibold" : "gap-1.5 text-meta font-medium",
        verdictTone(verdict),
        className,
      )}
    >
      <RunVerdictGlyph verdict={verdict} size={size === "lg" ? 18 : 15} />
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

/** The ink of a check's status: failures in error red (always with a cross and a word), warnings
 * in ink, passes and skips quiet. */
export function checkTone(status: string): string {
  const kind = checkKind(status);
  return kind === "fail" || kind === "error" ? "text-error" : kind === "warn" ? "text-ink" : "text-ink-2";
}

/** A check's status glyph: check (Superato), warning (Avviso), cross (Non superato, Errore), dashed
 * ring (Saltato). The word is written next to it by the row. */
export function CheckGlyph({ status, size = 15 }: { status: string; size?: number }) {
  const kind = checkKind(status);
  return kind === "skip" ? <DashedRing size={size} /> : <Icon name={CHECK_GLYPHS[kind]} size={size} />;
}

/** A judge score as a roundel with the number in it: the number is the information, the ring is
 * only its station. Low scores (1 and 2) take the error red, with the number and the word beside. */
export function ScoreRoundel({ score, className }: { score: number; className?: string }) {
  const low = score <= 2;
  return (
    <span
      data-score={score}
      className={cx(
        "grid size-7 shrink-0 place-items-center rounded-full border-[2.5px] font-cond text-small font-semibold",
        low ? "border-error text-error" : "border-ink text-ink",
        className,
      )}
    >
      <span aria-hidden="true">{score}</span>
      <span className="sr-only">{score} su 5</span>
    </span>
  );
}
