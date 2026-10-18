"use client";

import { AgentRoundel } from "@/components/ui/agent";
import { DatePair } from "@/components/ui/date-pair";
import { dueDistance, isDueSoon } from "@/components/ui/due-soon";
import { HOME_TIMEZONE } from "@/lib/format";
import { usePlanNow } from "./plan-now";

import { bookingLine, sortByDeadline, type BookingStripItem } from "./plan-model";

interface BookingStripProps {
  items: readonly BookingStripItem[];
  /** The anchor id of the booking at a position in plan.bookings. */
  anchor: (index: number) => string;
  headingId: string;
  /** The trip's time zone (plan.timezone): the clock of "Quando". */
  timeZone: string;
}

/** "2 in scadenza", "1 in scadenza": how many are due within 72 hours, in words. */
export function dueSoonCount(count: number): string {
  return `${count} in scadenza`;
}

/**
 * "Da prenotare": the plan's bookings by deadline, one row each, under the summary's facts, so
 * the first thing to do is the first thing on the page. Each row jumps to the booking below
 * (`#prenotazione-N`) and is at least 44 px tall on the phone. Under the title it previews both
 * dates, "Prenota entro" and "Quando" (DatePair, compact): the days alone, on the same clocks as
 * the row below, which has the times. DatePair alone draws amber, on a deadline within 72 hours;
 * the words say it too ("In scadenza · tra 2 giorni", "Scadenza passata"). Relative dates read
 * the plan's clock (`usePlanNow`: the demo's fixed one, else the live one).
 */
export function BookingStrip({ items, anchor, headingId, timeZone }: BookingStripProps) {
  const now = usePlanNow();
  const sorted = sortByDeadline(items);
  const soon = (item: BookingStripItem) =>
    now !== null && item.deadline.kind === "date" && isDueSoon(item.deadline.at, now);
  const dueCount = sorted.filter(soon).length;

  return (
    <section aria-labelledby={headingId} className="max-w-prose lg:max-w-none">
      <div className="flex flex-wrap items-baseline gap-x-2.5">
        <h2 id={headingId} className="font-cond text-title font-semibold">
          Da prenotare
        </h2>
        <span className="text-meta text-ink-2">
          {sorted.length}
          {dueCount > 0 ? (
            <>
              {", "}
              <b className="font-semibold text-ink">{dueSoonCount(dueCount)}</b>
            </>
          ) : null}
        </span>
      </div>
      <ol className="m-0 mt-1 list-none p-0">
        {sorted.map((item) => {
          const distance =
            soon(item) && item.deadline.kind === "date" && now !== null ? dueDistance(item.deadline.at, now) : null;
          return (
            <li key={item.index} className="border-t border-rule first:border-t-0">
              <a
                href={`#${anchor(item.index)}`}
                className="group/row -mx-2 flex min-h-11 items-start gap-2.5 rounded-sm px-2 py-2 no-underline transition-colors duration-(--duration-hover) hover:bg-notice-wash"
              >
                <AgentRoundel agent={bookingLine(item.booking, item.check ?? null)} size="sm" className="mt-0.5" />
                <div className="min-w-0 flex-1">
                  {/* Underlined, like every link that jumps within the page: on touch there is no hover
                      to say that a row goes somewhere. */}
                  <span className="block text-small font-medium underline decoration-rule-strong underline-offset-[0.2em] [overflow-wrap:anywhere] group-hover/row:decoration-ink">
                    {item.booking.title}
                  </span>
                  <DatePair
                    variant="compact"
                    deadline={item.deadline}
                    scheduledFor={item.booking.scheduled_for}
                    timeZone={timeZone}
                    deadlineTimeZone={HOME_TIMEZONE}
                    startsAtHome={item.startsAtHome}
                    now={now}
                    className="mt-1"
                  />
                  {distance ? (
                    <span className="mt-0.5 block text-micro text-ink-2">
                      {distance === "scadenza passata" ? "Scadenza passata" : `In scadenza · ${distance}`}
                    </span>
                  ) : null}
                </div>
              </a>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
