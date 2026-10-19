import type { ReactNode } from "react";

import { cx } from "@/components/ui/cx";
import { Notice } from "@/components/ui/notice";
import { formatEur } from "@/lib/format";
import type { Plan } from "@/lib/schemas/generated/plan";

import {
  budgetComparison,
  daysCount,
  formatTripDates,
  planTotal,
  summaryLines,
  titleStatesDates,
  totalNote,
  tripLength,
} from "./plan-model";

function Fact({
  label,
  children,
  note,
  lead,
  className,
}: {
  label: string;
  children: ReactNode;
  note?: string | null;
  lead?: string | null;
  className?: string;
}) {
  return (
    <div className={className ? `min-w-0 ${className}` : "min-w-0"}>
      <dt className="text-meta text-ink-2">{label}</dt>
      <dd className="min-w-0">
        <span className="block text-body font-semibold [overflow-wrap:anywhere]">{children}</span>
        {lead ? <span className="block text-meta text-ink [overflow-wrap:anywhere]">{lead}</span> : null}
        {note ? <span className="block text-micro text-ink-2 [overflow-wrap:anywhere]">{note}</span> : null}
      </dd>
    </div>
  );
}

interface PlanSummaryProps {
  plan: Plan;
  /** The page's title: when it already states the dates, the facts do not repeat them. */
  title: string;
  /** The request's total budget, in euro, to set the estimated total against. */
  budgetEur: number | null;
  /** "Da prenotare": the bookings by deadline, right under the facts. From 1080 px it moves to
   * the right column, level with the summary, together with `aside`, and stays beside the days
   * under it until the bookings begin. */
  children?: ReactNode;
  /** From 1080 px only: what the right column adds under the strip (the TripTracker hand-off). */
  aside?: ReactNode;
  headingId: string;
  /** The titles of the bookings whose link is dead with no button to send the reader to: the
   * notice names them, and their rows hold the address as text. */
  deadLinkTitles?: readonly string[];
}

/**
 * The top of the finished plan: the agent's three-line summary, a strip of facts (estimated
 * total in euro set against the budget, dates, base), "Da prenotare" (the bookings by deadline,
 * passed as children), then the plan's warnings (estimated prices,
 * sources that did not answer) in one calm notice: notice wash, dashed edge, ink glyph. Never
 * amber, never red: a warning is a note, not an error.
 *
 * From 1080 px the section is `display: contents`: its parts are cells of the page's two-column
 * grid (PlanView), the text on the left and "Da prenotare" with the TripTracker hand-off in one
 * sticky cell on the right that spans the summary and "Giorno per giorno", so it stays beside the
 * stops instead of scrolling away after the first 400 px. Without that grid (the phone, a test)
 * the parts simply stack.
 */
export function PlanSummary({ plan, title, budgetEur, children, aside, headingId, deadLinkTitles = [] }: PlanSummaryProps) {
  const total = planTotal(plan.bookings);
  // The total has its own fact right below: the agent's line that restates it is left out.
  const lines = summaryLines(plan.summary, total.cents !== null);
  const length = tripLength(plan.start_date, plan.end_date);
  const datesInTitle = titleStatesDates(title, plan.start_date, plan.end_date);
  const warnings = (plan.warnings ?? []).map((warning) => warning.trim()).filter(Boolean);
  const dead = deadLinkTitles.map((title) => title.trim()).filter(Boolean);
  if (dead.length === 1) {
    warnings.push(`Il link di prenotazione di ${dead[0]} non funziona più: nella sua riga trovi l'indirizzo come testo.`);
  } else if (dead.length > 1) {
    warnings.push(
      `${dead.length} link di prenotazione non funzionano più (${dead.join(", ")}): nelle loro righe trovi gli indirizzi come testo.`,
    );
  }

  return (
    <section
      aria-labelledby={headingId}
      className="flex min-w-0 flex-col lg:contents"
    >
      {/* The page's first stop when the plan arrives: focus moves here, so a screen reader starts
          at the summary (PlanView `arrival`). */}
      <h2 id={headingId} tabIndex={-1} className="sr-only">
        Sintesi del piano
      </h2>
      <div
        className={cx(
          "max-w-prose space-y-1 text-body lg:col-start-1",
          // On the phone "Da prenotare" comes first (below), so the prose starts under its rule.
          children ? "max-lg:mt-6 max-lg:border-t max-lg:border-rule max-lg:pt-4" : null,
        )}
      >
        {lines.map((line, index) => (
          <p key={index}>{line}</p>
        ))}
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3.5 border-t border-rule pt-4 lg:grid-cols-[repeat(3,minmax(0,auto))] lg:col-start-1 lg:justify-start lg:gap-x-12">
        <Fact className="col-span-2 lg:col-span-1" label="Costo stimato totale" lead={budgetComparison(total, budgetEur)} note={totalNote(total)}>
          {total.cents === null ? "non disponibile" : formatEur(total.cents)}
        </Fact>
        {datesInTitle ? null : (
          <Fact label="Date" note={length !== null ? daysCount(length) : null}>
            {formatTripDates(plan.start_date, plan.end_date)}
          </Fact>
        )}
        {plan.lodging_name ? (
          <Fact label="Base" note={plan.lodging_address}>
            {plan.lodging_name}
          </Fact>
        ) : null}
      </dl>

      {children || aside ? (
        // The phone leads with it: "Da prenotare" is the first thing under the photo, drawn before
        // the prose by `order` (the markup keeps the summary first). From 1080 px it is the right column
        // of the page's grid, from the summary's first line through the last day (the span is
        // longer than the rows there are: the extra rows are empty), sticky while the left reads on.
        <div className="min-w-0 max-lg:order-first lg:sticky lg:top-6 lg:col-start-2 lg:row-span-6 lg:row-start-1 lg:-mx-2 lg:max-h-[calc(100dvh-3rem)] lg:self-start lg:overflow-y-auto lg:px-2">
          {children}
          {aside}
        </div>
      ) : null}

      {warnings.length > 0 ? (
        <Notice tone="warning" title="Da sapere prima di prenotare" className="mt-5 max-w-prose lg:col-start-1">
          {warnings.length === 1 ? (
            <p>{warnings[0]}</p>
          ) : (
            <ul className="list-disc space-y-0.5 pl-4">
              {warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          )}
        </Notice>
      ) : null}
    </section>
  );
}
