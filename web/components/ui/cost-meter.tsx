import type { CSSProperties } from "react";

import { formatUsd } from "@/lib/format";

import { cx } from "./cx";

/** The meter's spoken value: "1,62 dollari spesi su un limite di 4,00 dollari. Il costo si aggiorna
 * alla fine di ogni turno." The cost is the session's (the API), the limit its cap: the word
 * "budget" stays with the trip's money. */
export function costValueText(costCents: number, budgetCents: number): string {
  const amount = (cents: number) => formatUsd(cents).replace(/ \$$/, "");
  return `${amount(costCents)} dollari spesi su un limite di ${amount(budgetCents)} dollari. Il costo si aggiorna alla fine di ogni turno.`;
}

interface CostMeterProps {
  /** Cumulative Managed Agents cost, US cents; null until the first snapshot. */
  costCents: number | null;
  /** The session budget, US cents (400 production, 60 development; more after "Continua").
   * Without it the cost shows as text, with no meter. */
  budgetCents: number | null;
  /** The backend has not reported a cost yet (it does so at the end of a session turn): the meter
   * says so instead of showing a zero that reads as "nothing spent". */
  pending?: boolean;
  /** A line of ink-2 under the meter, desktop only ("Aggiornato a fine turno"). */
  hint?: string;
  /** The meter's accessible name. */
  label?: string;
  className?: string;
}

/**
 * The session cost on a line that ends at the budget (DESIGN.md, Components): "1,62 $ spesi" and
 * "budget 4,00 $" above an ink line with a ring at the current value and a stop tick at the
 * budget. role="meter" with aria-valuetext in words. Dollars with two decimals, Italian format.
 * Ink only: reaching the budget is a plan state (shown by the header), not an alarm colour.
 * The line eases to a new value in 400 ms; with reduced motion it jumps.
 */
export function CostMeter({ costCents, budgetCents, pending = false, hint, label = "Costo della sessione", className }: CostMeterProps) {
  const cost = costCents === null ? null : formatUsd(costCents);
  const hasMeter = !pending && costCents !== null && budgetCents !== null && budgetCents > 0;
  const ratio = hasMeter ? Math.min(1, Math.max(0, costCents / budgetCents)) : 0;

  const figures = (
    <div className="mb-1.5 flex items-baseline justify-between gap-3 text-meta text-ink-2">
      {pending ? (
        <span>Costo non ancora aggiornato</span>
      ) : (
        <span>
          <b className="text-body font-semibold text-ink">{cost ?? "…"}</b> spesi
        </span>
      )}
      {budgetCents !== null ? <span>limite {formatUsd(budgetCents)}</span> : null}
    </div>
  );

  if (!hasMeter) {
    return (
      <div className={className} aria-busy={costCents === null || undefined}>
        {figures}
        {pending ? <p className="sr-only">Il costo si aggiorna alla fine di ogni turno.</p> : null}
      </div>
    );
  }

  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={budgetCents}
      aria-valuenow={Math.min(costCents, budgetCents)}
      aria-valuetext={costValueText(costCents, budgetCents)}
      className={className}
      style={{ "--meter-value": ratio } as CSSProperties}
    >
      {figures}
      <div aria-hidden="true" className="relative h-3.5 [container-type:inline-size]">
        {/* The track: a hairline to the budget. */}
        <span className="absolute inset-x-0 top-1.5 h-0.5 rounded-full bg-rule-strong opacity-55" />
        {/* The spent part: scaled from the left, so it animates on the compositor. */}
        <span
          className={cx(
            "absolute top-1 left-0 h-1.5 w-full origin-left rounded-full bg-ink",
            "scale-x-(--meter-value) transition-[scale] duration-(--duration-meter) ease-expo motion-reduce:transition-none",
          )}
        />
        {/* The budget's stop tick. */}
        <span className="absolute top-0 right-0 h-3.5 w-1 rounded-[2px] bg-ink" />
        {/* The ring at the current value. */}
        <span
          className={cx(
            "absolute top-px left-0 -ml-1.5 size-3 rounded-full border-[3px] border-ink bg-surface",
            "translate-x-[calc(var(--meter-value)*100cqw)] transition-[translate] duration-(--duration-meter) ease-expo motion-reduce:transition-none",
          )}
        />
      </div>
      {hint ? <p aria-hidden="true" className="mt-1 hidden text-micro text-ink-2 lg:block">{hint}</p> : null}
    </div>
  );
}
