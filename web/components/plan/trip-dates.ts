/**
 * Calendar helpers of the finished plan, in Italian: a plan date (YYYY-MM-DD) read in UTC, the
 * trip's dates in words, day and traveller counts. A module of its own so the live page, which
 * only needs a subtitle for a finished plan, does not ship the rest of plan-model (JS budget,
 * README "Measure the JS"). plan-model re-exports everything here.
 */

const WEEKDAYS = ["dom", "lun", "mar", "mer", "gio", "ven", "sab"];
const MONTHS_SHORT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const MONTHS = [
  "gennaio",
  "febbraio",
  "marzo",
  "aprile",
  "maggio",
  "giugno",
  "luglio",
  "agosto",
  "settembre",
  "ottobre",
  "novembre",
  "dicembre",
];

interface CalendarDate {
  year: number;
  month: number;
  day: number;
  /** Days since 1970-01-01, for differences. */
  epochDay: number;
}

/** A plan date (YYYY-MM-DD) as calendar parts; null when it is not one. Read in UTC: a plan
 * date is a day of the trip, not an instant, so no time zone may move it. */
export function parsePlanDate(date: string): CalendarDate | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const time = Date.UTC(year, month - 1, day);
  const check = new Date(time);
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return null;
  return { year, month, day, epochDay: Math.round(time / 86_400_000) };
}

/** "mer 14 apr", like the booking dates; the raw string when it is not a date. */
export function formatPlanDay(date: string): string {
  const parts = parsePlanDate(date);
  if (!parts) return date;
  const weekday = WEEKDAYS[new Date(Date.UTC(parts.year, parts.month - 1, parts.day)).getUTCDay()];
  return `${weekday} ${parts.day} ${MONTHS_SHORT[parts.month - 1]}`;
}

/** 1-based day of the trip ("Giorno 3"); null when a date is not one. */
export function tripDayNumber(date: string, startDate: string): number | null {
  const day = parsePlanDate(date);
  const start = parsePlanDate(startDate);
  if (!day || !start) return null;
  return day.epochDay - start.epochDay + 1;
}

/** Days in the trip, both ends included. */
export function tripLength(startDate: string, endDate: string): number | null {
  const start = parsePlanDate(startDate);
  const end = parsePlanDate(endDate);
  if (!start || !end || end.epochDay < start.epochDay) return null;
  return end.epochDay - start.epochDay + 1;
}

/** Italian elides "dal"/"al" before a number read with a vowel: dall'1, all'8, dall'11. */
function elides(day: number): boolean {
  return day === 1 || day === 8 || day === 11;
}
const from = (day: number) => (elides(day) ? `Dall'${day}` : `Dal ${day}`);
const to = (day: number) => (elides(day) ? `all'${day}` : `al ${day}`);

/** The trip's dates in words: "Dal 14 al 18 aprile 2027", "Dal 28 aprile al 2 maggio 2027",
 * "Dal 30 dicembre 2026 al 3 gennaio 2027", "Il 14 aprile 2027". */
export function formatTripDates(startDate: string, endDate: string): string {
  const start = parsePlanDate(startDate);
  const end = parsePlanDate(endDate);
  if (!start || !end) return `${startDate}, ${endDate}`;
  const month = (parts: CalendarDate) => MONTHS[parts.month - 1];
  if (start.epochDay === end.epochDay) {
    return `${elides(start.day) ? "L'" : "Il "}${start.day} ${month(start)} ${start.year}`;
  }
  if (start.year !== end.year) {
    return `${from(start.day)} ${month(start)} ${start.year} ${to(end.day)} ${month(end)} ${end.year}`;
  }
  if (start.month !== end.month) {
    return `${from(start.day)} ${month(start)} ${to(end.day)} ${month(end)} ${end.year}`;
  }
  return `${from(start.day)} ${to(end.day)} ${month(end)} ${end.year}`;
}

/** "1 giorno", "5 giorni". */
export function daysCount(count: number): string {
  return count === 1 ? "1 giorno" : `${count} giorni`;
}

/** "1 viaggiatore", "4 viaggiatori". */
export function travelersCount(count: number): string {
  return count === 1 ? "1 viaggiatore" : `${count} viaggiatori`;
}

/** True when the title already says the trip's days ("Lisbona, 14–18 aprile 2027"): both day
 * numbers and the end month's name, in full or abbreviated, are in it. Then the page does not
 * state the dates a second time. */
export function titleStatesDates(title: string, startDate: string, endDate: string): boolean {
  const start = parsePlanDate(startDate);
  const end = parsePlanDate(endDate);
  if (!start || !end) return false;
  const text = title.toLocaleLowerCase("it");
  const hasNumber = (day: number) => new RegExp(`(^|\\D)${day}(\\D|$)`).test(text);
  const month = MONTHS[end.month - 1] ?? "";
  return hasNumber(start.day) && hasNumber(end.day) && month !== "" && text.includes(month.slice(0, 3));
}
