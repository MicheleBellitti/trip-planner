import { cx } from "@/components/ui/cx";
import { HOME_TIMEZONE } from "@/lib/format";
import { homeClockFor } from "@/lib/zone-time";
import type { PlanBooking, PlanDay, PlanStop } from "@/lib/schemas/generated/plan";
import type { CSSProperties } from "react";

import { QuietExternalLink } from "./bookings";
import { cycleFor, hueFor, hueVariable } from "./map/model";
import {
  bookingsByStop,
  formatDuration,
  formatPlanDay,
  HOME_CLOCK_LABEL,
  hostLabel,
  leavesHome,
  safeHttpUrl,
  STOP_KIND_LABELS,
  stopPlace,
  tripDayNumber,
} from "./plan-model";

/** The station row of DESIGN.md (Layout): 2.6 rem time gutter, 1.5 rem track, the content. */
const ROW = "grid grid-cols-[2.6rem_1.5rem_minmax(0,1fr)] gap-x-[0.45rem]";
/** Level with the first line of text, as on the lanes. */
const GLYPH_TOP = "top-[0.78rem]";
/** A day's line: 5 px, the lanes' width, in the day's hue, the same hue the map draws that day in
 * (DESIGN.md, Map: Giorno 1 blue, 2 green, ...), dashed from the sixth day as on the map. The
 * hue comes from the day's `<li>` (`--day`, `--day-fill`, see `dayStyle`). */
const LINE = "absolute left-1/2 -ml-[2.5px] w-[5px] [background:var(--day-fill)]";

/** The day's hue for its line, its stations and its number disc: the map's, so a day reads as the
 * same line in the list and on the map. */
function dayStyle(dayIndex: number): CSSProperties {
  const hue = `var(${hueVariable(hueFor(dayIndex))})`;
  const fill = cycleFor(dayIndex) > 0 ? `repeating-linear-gradient(to bottom, ${hue} 0 9px, transparent 9px 14px)` : hue;
  return { "--day": hue, "--day-fill": fill } as CSSProperties;
}

/** The day's badge: a disc in its hue with its number, like a line badge on a transit map. The
 * number is also in the caption beside it, so the disc is decorative. */
function DayDisc({ number, className }: { number: number | null; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "grid size-7 place-items-center rounded-full xl:size-8 bg-(--day) font-cond text-title leading-none font-semibold text-on-line",
        "shadow-[0_0_0_3px_var(--ground)]",
        className,
      )}
    >
      {number ?? ""}
    </span>
  );
}

interface ItineraryProps {
  days: readonly PlanDay[];
  startDate: string;
  /** The trip's time zone (plan.timezone): the clock of the gutter. */
  timeZone: string;
  bookings: readonly PlanBooking[];
  /** The anchor id of the booking at a position in plan.bookings. */
  bookingAnchor: (index: number) => string;
}

/**
 * The days as one vertical line of stops, as in TripTracker, never a grid of cards. On the
 * phone the trip is one continuous line: each day is a large ink ring (a named station, like the
 * waves on the coordinator's line) and its stops are small rings with their start time in the
 * gutter. From 1280 px each day becomes a row of a timetable: the day on the left, its own line
 * of stops on the right.
 */
export function Itinerary({ days, startDate, timeZone, bookings, bookingAnchor }: ItineraryProps) {
  const byStop = bookingsByStop(bookings);
  return (
    <ol className="m-0 list-none p-0">
      {days.map((day, dayIndex) => {
        const lastDay = dayIndex === days.length - 1;
        const number = tripDayNumber(day.date, startDate);
        const date = formatPlanDay(day.date);
        const label = number !== null ? `Giorno ${number}, ${date}` : date;
        const caption = day.title ? label : number !== null ? `Giorno ${number}` : null;
        return (
          <li
            key={`${day.date}-${dayIndex}`}
            style={dayStyle(dayIndex)}
            className={cx(
              "xl:grid xl:grid-cols-[minmax(0,13rem)_minmax(0,44rem)] xl:gap-x-8",
              dayIndex > 0 && "xl:mt-2 xl:border-t xl:border-rule xl:pt-5",
            )}
          >
            <div className={cx(ROW, "xl:flex xl:items-start xl:gap-3")}>
              <span aria-hidden="true" className="xl:hidden" />
              <span aria-hidden="true" className="relative xl:hidden">
                {day.stops.length > 0 || !lastDay ? <span className={cx(LINE, "top-3.5 bottom-0")} /> : null}
                <DayDisc number={number} className="absolute top-0 left-1/2 -translate-x-1/2" />
              </span>
              <DayDisc number={number} className="hidden shrink-0 xl:grid" />
              <h3 className="min-w-0 pt-[0.2rem] pb-4 pl-1 xl:pt-0 xl:pb-0 xl:pl-0">
                {caption ? <span className="block text-meta text-ink-2">{caption}</span> : null}
                <span className="block font-cond text-heading font-semibold [overflow-wrap:anywhere]">
                  {day.title ?? capitalize(date)}
                </span>
              </h3>
            </div>
            {day.stops.length > 0 ? (
              <ol aria-label={`Tappe del ${label.toLocaleLowerCase("it")}`} className="m-0 list-none p-0">
                {day.stops.map((stop, stopIndex) => (
                  <StopRow
                    key={`${stop.ref}-${stopIndex}`}
                    stop={stop}
                    number={stopIndex + 1}
                    first={stopIndex === 0}
                    last={stopIndex === day.stops.length - 1}
                    lastDay={lastDay}
                    homeClock={
                      // The trip's first move starts from home: say what the clock there reads.
                      leavesHome(dayIndex, stopIndex, stop) && stop.start_time
                        ? homeClockFor(day.date, stop.start_time, timeZone, HOME_TIMEZONE)
                        : null
                    }
                    bookings={(byStop.get(stop.ref) ?? []).map((index) => ({
                      title: bookings[index]?.title ?? "",
                      href: `#${bookingAnchor(index)}`,
                    }))}
                  />
                ))}
              </ol>
            ) : (
              <div className={cx(ROW, "xl:block")}>
                <span aria-hidden="true" className="xl:hidden" />
                <span aria-hidden="true" className="relative xl:hidden">
                  {lastDay ? null : <span className={cx(LINE, "inset-y-0")} />}
                </span>
                <p className={cx("text-meta text-ink-2", lastDay ? "pb-[0.9rem]" : "pb-7 xl:pb-[0.9rem]")}>
                  Giornata libera, senza tappe.
                </p>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function capitalize(text: string): string {
  return text.charAt(0).toLocaleUpperCase("it") + text.slice(1);
}

interface StopRowProps {
  stop: PlanStop;
  /** The stop's place in its day (1-based): the number the map draws on its station. */
  number: number;
  first: boolean;
  last: boolean;
  lastDay: boolean;
  /** What the clock at home reads at this stop's start ("09:40"), for the move that leaves home. */
  homeClock: string | null;
  /** The plan's bookings that belong to this stop, as links to their rows. */
  bookings: { title: string; href: string }[];
}

function StopRow({ stop, number, first, last, lastDay, homeClock, bookings }: StopRowProps) {
  const url = safeHttpUrl(stop.url);
  const place = stopPlace(stop);
  const meta = [STOP_KIND_LABELS[stop.kind], stop.duration_min ? formatDuration(stop.duration_min) : null]
    .filter(Boolean)
    .join(", ");
  const home = homeClock ? ` (parte alle ${homeClock} ${HOME_CLOCK_LABEL})` : "";
  // Phone: one line through the whole trip, so a stop's segment reaches the next day's ring
  // and only the very last stop ends at its glyph. Desktop: one line per day.
  const segment = cx(
    LINE,
    "top-0",
    first && "xl:top-[0.78rem]",
    last && lastDay ? "bottom-[calc(100%-0.78rem)]" : "bottom-0",
    last ? "xl:bottom-[calc(100%-0.78rem)]" : "xl:bottom-0",
    first && last && "xl:hidden",
  );
  return (
    <li className={ROW}>
      <span className="pt-[0.2rem] text-right text-micro text-ink-2">
        {stop.start_time ? <time dateTime={stop.start_time}>{stop.start_time}</time> : null}
      </span>
      <span aria-hidden="true" className="relative">
        <span className={segment} />
        <span
          className={cx(
            "absolute left-1/2 size-[13px] -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-(--day) bg-ground",
            GLYPH_TOP,
          )}
        />
      </span>
      <div className={cx("flex min-w-0 gap-1.5 pt-[0.12rem]", last && !lastDay ? "pb-7 xl:pb-[0.9rem]" : "pb-[0.9rem]")}>
        {/* The number the map draws on this stop. The list is already in order, so it is not read. */}
        <span aria-hidden="true" className="min-w-4 shrink-0 text-right text-small leading-[1.35] text-ink-2">
          {number}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-small leading-[1.35] font-medium [overflow-wrap:anywhere]">{stop.title}</p>
          <p className="mt-px text-meta text-ink-2">
            {meta}
            {home}
          </p>
          {place ? <p className="text-meta text-ink-2 [overflow-wrap:anywhere]">{place}</p> : null}
          {stop.notes ? (
            <p className="mt-1 text-meta whitespace-pre-line text-ink-2 [overflow-wrap:anywhere]">{stop.notes}</p>
          ) : null}
          {url || bookings.length > 0 ? (
            <div className="mt-1 flex flex-col gap-0.5 text-meta">
              {bookings.map((booking) => (
                <p key={booking.href} className="text-ink-2">
                  Da prenotare:{" "}
                  <a
                    href={booking.href}
                    className="rounded-xs text-ink underline decoration-rule-strong underline-offset-[0.2em] hover:decoration-ink"
                  >
                    {booking.title}
                  </a>
                </p>
              ))}
              {url && stop.url ? (
                <p>
                  <QuietExternalLink href={stop.url} className="py-1">
                    {hostLabel(url)}
                  </QuietExternalLink>
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}
