import { cx } from "@/components/ui/cx";
import type { RequestFormValues } from "@/lib/request-form";

import { JOURNEY_MODE_ICONS } from "./form-model";
import { budgetSummary, datesSummary, journeySummary, travelersSummary } from "./summary";
import { RouteLine, TripFact } from "./trip-outline";

/**
 * The request in words beside the form on desktop, next to the button: what the agents will be
 * asked, read back before it costs anything. A mirror of the fields, not a live region.
 */
export function RequestSummary({ values, className }: { values: RequestFormValues; className?: string }) {
  const origin = values.origin.trim();
  const destination = values.destination.trim();
  const idea = values.destinationIdea.trim();
  const journey = journeySummary(values);
  const dates = datesSummary(values);
  const budget = budgetSummary(values);

  return (
    <section aria-labelledby="request-summary-title" className={cx("gap-4", className)}>
      <h2 id="request-summary-title" className="font-cond text-title font-semibold">
        Il tuo viaggio
      </h2>
      <RouteLine
        origin={origin ? { text: origin } : { text: "Partenza da scegliere", missing: true }}
        destination={
          values.suggestDestination
            ? { text: "Meta suggerita dal planner", note: idea || undefined, bare: true }
            : destination
              ? { text: destination }
              : { text: "Meta da scegliere", missing: true }
        }
      />
      <ul className="grid gap-2 border-t border-rule pt-4 text-small">
        <TripFact icon={JOURNEY_MODE_ICONS[values.journeyMode]}>{journey}</TripFact>
        <TripFact icon="calendar-blank" missing={!dates}>
          {dates ?? "Date da scegliere"}
        </TripFact>
        <TripFact icon="users">{travelersSummary(values)}</TripFact>
        <TripFact icon="wallet" missing={!budget}>
          {budget ? `${budget} in tutto` : "Budget da indicare"}
        </TripFact>
      </ul>
    </section>
  );
}
