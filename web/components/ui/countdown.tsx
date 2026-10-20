import { formatElapsed } from "@/lib/format";

import { cx } from "./cx";
import { Icon } from "./icon";
import { VisuallyHidden } from "./visually-hidden";

interface CountdownProps {
  /** The deadline, in ms on the clock `now` reads (the question's `deadline_at`, or the demo's). */
  deadlineAt: number;
  /** The question's whole window, in ms: the bar's full length, and the most the clock shows. */
  windowMs: number;
  /** The shared clock; null before its first tick, which shows the whole window. */
  now: number | null;
  /** Layout only. */
  className?: string;
}

/**
 * The time left to choose (DESIGN.md, "Choice cards"): "4:12" beside a thin ink bar that empties
 * towards the deadline, then "Tempo scaduto: scelgo io." with the bar empty. What is left is
 * clamped to the window and to zero, so a browser clock minutes off never shows more than the
 * question's own window, or less than nothing. A second that has begun counts, so the clock
 * reads "4:00" when the question opens and "0:01" in its last second.
 *
 * Ink only: never amber (it belongs to booking deadlines) and never red (running out is the rule
 * at work, not a failure). It reports the time and does not move by itself: no transition, and
 * no live region (the page says the last minute once, through its own).
 */
export function Countdown({ deadlineAt, windowMs, now, className }: CountdownProps) {
  const whole = Math.max(0, windowMs);
  const left = now === null ? whole : Math.min(whole, Math.max(0, deadlineAt - now));
  const share = whole > 0 ? left / whole : 0;

  return (
    <div className={cx("flex items-center gap-3", className)}>
      <p className="m-0 flex shrink-0 items-center gap-1.5 text-small font-semibold text-ink">
        <Icon name="clock" size={15} className="text-ink-2" />
        {left === 0 ? (
          "Tempo scaduto: scelgo io."
        ) : (
          <span>
            <VisuallyHidden>Tempo per scegliere: </VisuallyHidden>
            {formatElapsed(Math.ceil(left / 1000) * 1000)}
          </span>
        )}
      </p>
      <span aria-hidden="true" className="relative h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-rule">
        {/* The time left, scaled from the left edge. */}
        <span
          data-countdown-bar=""
          className="absolute inset-0 origin-left bg-ink"
          style={{ transform: `scaleX(${share})` }}
        />
      </span>
    </div>
  );
}
