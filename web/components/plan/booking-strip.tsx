"use client";

import { AgentRoundel } from "@/components/ui/agent";
import { cx } from "@/components/ui/cx";
import { dueDistance, isDueSoon } from "@/components/ui/due-soon";
import { formatBookingInstant } from "@/components/ui/date-pair";
import { Icon } from "@/components/ui/icon";
import type { BookingDeadline } from "@/lib/booking-dates";
import { HOME_TIMEZONE } from "@/lib/format";
import { usePlanNow } from "./plan-now";

import { bookingLine, sortByDeadline, type BookingStripItem } from "./plan-model";

interface BookingStripProps {
  items: readonly BookingStripItem[];
  /** The anchor id of the booking at a position in plan.bookings. */
  anchor: (index: number) => string;
  headingId: string;
}

/** "2 in scadenza", "1 in scadenza": how many are due within 72 hours, in words. */
export function dueSoonCount(count: number): string {
  return `${count} in scadenza`;
}

function deadlineWords(deadline: BookingDeadline): { text: string; quiet: boolean } {
  switch (deadline.kind) {
    case "date":
      return { text: `entro ${formatBookingInstant(deadline.at, HOME_TIMEZONE, false)}`, quiet: false };
    case "book_now":
      return { text: "da prenotare subito", quiet: false };
    case "none":
      return { text: "nessuna scadenza", quiet: true };
    case "pending":
      return { text: "in calcolo…", quiet: true };
    case "unknown":
      return { text: "scadenza non disponibile", quiet: true };
  }
}

/**
 * "Da prenotare": the plan's bookings by deadline, one row each, under the summary's facts, so
 * the first thing to do is the first thing on the page. Each row jumps to the booking below
 * (`#prenotazione-N`) and is 44 px tall on the phone. Which ones are due within 72 hours is said
 * in words and in ink ("In scadenza · tra 2 giorni"): amber belongs to the date field of the
 * booking itself (DatePair) and never leaves it.
 */
export function BookingStrip({ items, anchor, headingId }: BookingStripProps) {
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
          const words = deadlineWords(item.deadline);
          const distance =
            soon(item) && item.deadline.kind === "date" && now !== null ? dueDistance(item.deadline.at, now) : null;
          return (
            <li key={item.index} className="border-t border-rule first:border-t-0">
              <a
                href={`#${anchor(item.index)}`}
                className="group/row -mx-2 flex min-h-11 items-center lg:min-h-9 gap-2.5 rounded-sm px-2 py-1.5 no-underline transition-colors duration-(--duration-hover) hover:bg-notice-wash"
              >
                <AgentRoundel agent={bookingLine(item.booking, item.check ?? null)} size="sm" />
                {/* Underlined, like every link that jumps within the page: on touch there is no hover
                    to say that a row goes somewhere. */}
                <span className="min-w-0 flex-1 text-small font-medium underline decoration-rule-strong underline-offset-[0.2em] [overflow-wrap:anywhere] group-hover/row:decoration-ink">
                  {item.booking.title}
                </span>
                <span className="shrink-0 text-right text-meta">
                  <span className={cx("block", words.quiet ? "text-ink-2" : "font-semibold text-ink")}>{words.text}</span>
                  {distance ? (
                    <span className="flex items-center justify-end gap-1 text-micro text-ink-2">
                      <Icon name="clock" size={12} />
                      {distance === "scadenza passata" ? "Scadenza passata" : `In scadenza · ${distance}`}
                    </span>
                  ) : null}
                </span>
              </a>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
