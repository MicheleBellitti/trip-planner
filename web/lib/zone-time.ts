/**
 * Clock times across two time zones: the trip's (Lisbon) and Michele's (Rome). The plan writes
 * times in the destination's clock; a flight that leaves Milan at 09:40 at home is "08:40" in
 * the plan, and he reads the plan from home. Browser-only (Intl): the plan page renders on the
 * client, like DatePair.
 */

const CLOCKS = new Map<string, Intl.DateTimeFormat>();

function clock(timeZone: string): Intl.DateTimeFormat {
  let format = CLOCKS.get(timeZone);
  if (!format) {
    format = new Intl.DateTimeFormat("en-GB", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
    CLOCKS.set(timeZone, format);
  }
  return format;
}

export interface Wall {
  date: string;
  time: string;
}

/** The wall clock of an instant in a zone: date "2027-04-14", time "09:40". */
export function wallClock(ms: number, timeZone: string): Wall {
  const parts: Record<string, string> = {};
  for (const part of clock(timeZone).formatToParts(ms)) parts[part.type] = part.value;
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` };
}

/** "09:40" in `timeZone`, for an ISO instant; null when it is not one. */
export function clockTime(iso: string, timeZone: string): string | null {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : wallClock(ms, timeZone).time;
}

/** The instant (ms) of a wall-clock date and time ("2027-04-14", "08:40") read in `timeZone`;
 * null when they are not a date and a time. Two passes settle the offset around a DST change. */
export function instantOfWallClock(date: string, time: string, timeZone: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const clockMatch = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(time);
  if (!match || !clockMatch) return null;
  const asUtc = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(clockMatch[1]), Number(clockMatch[2]));
  let guess = asUtc;
  for (let pass = 0; pass < 2; pass += 1) {
    const wall = wallClock(guess, timeZone);
    const shown = Date.UTC(
      Number(wall.date.slice(0, 4)),
      Number(wall.date.slice(5, 7)) - 1,
      Number(wall.date.slice(8, 10)),
      Number(wall.time.slice(0, 2)),
      Number(wall.time.slice(3, 5)),
    );
    guess += asUtc - shown;
  }
  return guess;
}

/**
 * What the home clock says when the trip's clock says `date` `time`, as "09:40", or null when
 * the two clocks agree at that instant (or the input is not a date and a time). Only the
 * clock is returned: a plan's stops are daytime, so the day never changes between the zones.
 */
export function homeClockFor(date: string, time: string, tripTimeZone: string, homeTimeZone: string): string | null {
  if (tripTimeZone === homeTimeZone) return null;
  const at = instantOfWallClock(date, time, tripTimeZone);
  if (at === null) return null;
  const home = wallClock(at, homeTimeZone).time;
  return home === time ? null : home;
}
