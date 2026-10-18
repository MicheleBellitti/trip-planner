import type { BookingDeadline } from "@/lib/booking-dates";
import { clockTime } from "@/lib/zone-time";

import { cx } from "./cx";
import { dueDistance, isDueSoon } from "./due-soon";
import { Icon } from "./icon";
import { VisuallyHidden } from "./visually-hidden";

const FORMATS = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string, withTime: boolean): Intl.DateTimeFormat {
  const key = `${timeZone}|${withTime}`;
  let format = FORMATS.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat("it-IT", {
      timeZone,
      weekday: "short",
      day: "numeric",
      month: "short",
      ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
    });
    FORMATS.set(key, format);
  }
  return format;
}

/** A booking instant as the plan shows it, in the trip's time zone: "mer 14 ott, 23:59" (or
 * "mer 14 ott" without the time). Intl data can differ between server and browser, so render it
 * in the browser (the plan page is a Client Component) or in a Server Component, never both. */
export function formatBookingInstant(iso: string, timeZone: string, withTime = true): string {
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return iso;
  return formatter(timeZone, withTime).format(time);
}

/** The amber field's second line: the state in words, then the distance. */
function dueSoonHint(distance: string | null): string {
  if (distance === "scadenza passata") return "Scadenza passata";
  return distance ? `In scadenza · ${distance}` : "In scadenza";
}

interface DatePairProps {
  /** The "Prenota entro" side, from lib/booking-dates `bookingDeadline()`. */
  deadline: BookingDeadline;
  /** The "Quando" side: `scheduled_for`, ISO 8601 with offset; null when not fixed yet. */
  scheduledFor: string | null;
  /** The trip's time zone (plan.timezone): the clock of "Quando". */
  timeZone: string;
  /** The clock of "Prenota entro": Michele's, because that is when he has to act. Defaults to
   * `timeZone`. */
  deadlineTimeZone?: string;
  /** The booking starts from home (a flight leaving Milan): "Quando" leads with the clock at
   * home, the one he lives by ("mer 14 apr, 09:40"), and the trip's clock is the second line
   * ("08:40 a Lisbona"). Where the two clocks agree at that instant, or for a booking at the
   * destination (the default), "Quando" is the trip's clock alone: no second clock, no zone
   * words. */
  startsAtHome?: boolean;
  /** The words after the trip's clock when it is the second line ("a Lisbona", "ora locale"). */
  tripLabel?: string | null;
  /** Now in ms (lib/use-now `useNow()`); null during server rendering, when nothing is amber and
   * no distance is shown. */
  now: number | null;
  /** A second line under "Quando", e.g. "fino a mer 18 nov" or "ritorno mer 18 nov". */
  scheduledHint?: string;
  /** `fields`: two labelled boxes side by side (the plan, the booking preview). `compact`: one
   * wrapping line with both labels, for strips and lists. Both dates, both labels, always.
   * Compact says the days alone, each on the clock the fields lead with, and so drops the trip's
   * clock note: with no time beside it, "(08:40 a Lisbona)" would read as the booking's time. */
  variant?: "fields" | "compact";
  className?: string;
}

/**
 * A booking's two dates, always separate and labelled: "Prenota entro" (dueAt, by when to book)
 * and "Quando" (scheduledFor, when it happens). CLAUDE.md contract rule 1 and UI rules.
 *
 * Amber is computed here and only here: the "Prenota entro" side turns amber when its dueAt is
 * within 72 hours (./due-soon.ts) and says so in words too ("In scadenza"), never by colour alone.
 * The caller cannot force it on or off.
 */
export function DatePair({
  deadline,
  scheduledFor,
  timeZone,
  deadlineTimeZone = timeZone,
  startsAtHome = false,
  tripLabel = null,
  now,
  scheduledHint,
  variant = "fields",
  className,
}: DatePairProps) {
  const dueSoon = deadline.kind === "date" && now !== null && isDueSoon(deadline.at, now);
  const distance = deadline.kind === "date" && now !== null ? dueDistance(deadline.at, now) : null;
  const compact = variant === "compact";
  // A booking that starts from home reads on the clock at home, with the trip's as the second
  // line, but only where the two differ at that instant; every other booking reads on the trip's.
  const homeClock = startsAtHome && scheduledFor && timeZone !== deadlineTimeZone ? clockTime(scheduledFor, deadlineTimeZone) : null;
  const tripClock = homeClock && scheduledFor ? clockTime(scheduledFor, timeZone) : null;
  const leadsAtHome = homeClock !== null && tripClock !== null && homeClock !== tripClock;
  const whenZone = leadsAtHome ? deadlineTimeZone : timeZone;
  const zoneNote = leadsAtHome ? `${tripClock} ${tripLabel ?? "ora locale"}` : null;

  const deadlineValue =
    deadline.kind === "date" ? (
      <time dateTime={deadline.at}>{formatBookingInstant(deadline.at, deadlineTimeZone, !compact)}</time>
    ) : deadline.kind === "book_now" ? (
      "Da prenotare subito"
    ) : deadline.kind === "none" ? (
      "nessuna scadenza"
    ) : deadline.kind === "pending" ? (
      "in calcolo…"
    ) : (
      "non disponibile"
    );
  const deadlineQuiet = deadline.kind === "none" || deadline.kind === "pending" || deadline.kind === "unknown";

  const scheduledValue = scheduledFor ? (
    <time dateTime={scheduledFor}>{formatBookingInstant(scheduledFor, whenZone, !compact)}</time>
  ) : (
    "da definire"
  );

  if (compact) {
    return (
      <dl className={cx("flex flex-wrap items-baseline gap-x-4 gap-y-1 text-meta", className)}>
        <div className="flex items-baseline gap-1">
          <dt className="text-ink-2">Prenota entro</dt>
          <dd
            data-due-soon={dueSoon || undefined}
            aria-busy={deadline.kind === "pending" || undefined}
            className={cx(
              dueSoon
                ? "inline-flex items-center gap-1 self-center rounded-xs bg-amber-wash px-1.5 font-semibold text-amber-ink inset-ring-1 inset-ring-amber"
                : deadlineQuiet
                  ? "text-ink-2"
                  : "font-semibold text-ink",
            )}
          >
            {dueSoon ? <Icon name="clock" size={13} /> : null}
            {deadlineValue}
            {dueSoon ? <VisuallyHidden>, in scadenza</VisuallyHidden> : null}
          </dd>
        </div>
        <div className="flex items-baseline gap-1">
          <dt className="text-ink-2">Quando</dt>
          <dd className={scheduledFor ? "font-semibold text-ink" : "text-ink-2"}>
            {scheduledValue}
          </dd>
        </div>
      </dl>
    );
  }

  return (
    <dl className={cx("grid grid-cols-2 gap-2.5", className)}>
      <div
        data-due-soon={dueSoon || undefined}
        className={cx(
          "min-w-0 rounded-sm px-2.5 py-2",
          dueSoon ? "bg-amber-wash inset-ring-[1.5px] inset-ring-amber" : "bg-surface inset-ring-1 inset-ring-rule",
        )}
      >
        <dt className="text-meta text-ink-2">Prenota entro</dt>
        <dd
          aria-busy={deadline.kind === "pending" || undefined}
          className={cx(
            "text-body",
            dueSoon ? "font-semibold text-amber-ink" : deadlineQuiet ? "text-ink-2" : "font-semibold text-ink",
          )}
        >
          {deadlineValue}
          {dueSoon ? (
            <span className="block text-micro font-normal text-amber-ink">{dueSoonHint(distance)}</span>
          ) : distance ? (
            <span className="block text-micro font-normal text-ink-2">{distance}</span>
          ) : null}
        </dd>
      </div>
      <div className="min-w-0 rounded-sm bg-surface px-2.5 py-2 inset-ring-1 inset-ring-rule">
        <dt className="text-meta text-ink-2">Quando</dt>
        <dd className={cx("text-body", scheduledFor ? "font-semibold text-ink" : "text-ink-2")}>
          {scheduledValue}
          {zoneNote ? <span className="block text-micro font-normal text-ink-2">{zoneNote}</span> : null}
          {scheduledHint ? <span className="block text-micro font-normal text-ink-2">{scheduledHint}</span> : null}
        </dd>
      </div>
    </dl>
  );
}
