/**
 * The request in words, for the form's summary (desktop) and the home page's example. Pure and
 * locale-independent (no Intl): the same text on the server and in every browser.
 */

import { journeyModePhrase } from "@/lib/journey-mode";
import { monthLabel, parseBudget, type RequestFormValues } from "@/lib/request-form";

const DAY_MS = 86_400_000;

function parseDay(value: string): { year: number; month: number; day: number; time: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const time = Date.UTC(year, month - 1, day);
  const date = new Date(time);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return { year, month, day, time };
}

/** "aprile" for "2027-04" or "2027-04-14" ("" when it is not a date). */
export function monthName(value: string): string {
  const label = monthLabel(value.slice(0, 7));
  return label === value.slice(0, 7) ? "" : (label.split(" ")[0] ?? "");
}

/** "Aprile 2027" for "2027-04": a month on its own starts a phrase. */
export function monthTitle(month: string): string {
  const label = monthLabel(month);
  return label.charAt(0).toLocaleUpperCase("it") + label.slice(1);
}

/** "14 aprile 2027". */
export function formatDay(value: string): string | null {
  const day = parseDay(value);
  return day ? `${day.day} ${monthName(value)} ${day.year}` : null;
}

/** A trip's fixed dates in words: "14–18 aprile 2027", "28 aprile – 2 maggio 2027",
 * "30 dicembre 2026 – 3 gennaio 2027", "14 aprile 2027" for a day trip. Null unless both
 * dates are valid and in order. */
export function formatDayRange(start: string, end: string): string | null {
  const from = parseDay(start);
  const to = parseDay(end);
  if (!from || !to || to.time < from.time) return null;
  if (from.time === to.time) return formatDay(start);
  if (from.year === to.year && from.month === to.month) return `${from.day}–${to.day} ${monthName(end)} ${to.year}`;
  if (from.year === to.year) return `${from.day} ${monthName(start)} – ${to.day} ${monthName(end)} ${to.year}`;
  return `${formatDay(start)} – ${formatDay(end)}`;
}

/** Nights between two valid dates (0 for a day trip), else null. */
export function nightsBetween(start: string, end: string): number | null {
  const from = parseDay(start);
  const to = parseDay(end);
  if (!from || !to || to.time < from.time) return null;
  return Math.round((to.time - from.time) / DAY_MS);
}

export function countNoun(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "Italian list": "8", "8 e 11", "3, 8 e 11". */
function joinAnd(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} e ${items.at(-1)}`;
}

/** Whole euros with the Italian thousands dot: 2400 -> "2.400 €". */
export function formatWholeEuros(amount: number): string {
  return `${String(Math.trunc(amount)).replace(/\B(?=(\d{3})+(?!\d))/g, ".")} €`;
}

/** When, in words: "14–18 aprile 2027, 4 notti", "Aprile 2027, 7 notti", "Aprile 2027", or null
 * while nothing usable is filled in. */
export function datesSummary(values: RequestFormValues): string | null {
  if (values.dateMode === "exact") {
    const range = formatDayRange(values.exactStart, values.exactEnd);
    if (range) {
      const nights = nightsBetween(values.exactStart, values.exactEnd) ?? 0;
      return nights === 0 ? `${range}, in giornata` : `${range}, ${countNoun(nights, "notte", "notti")}`;
    }
    const start = formatDay(values.exactStart);
    return start ? `Dal ${start}` : null;
  }
  const month = /^\d{4}-(0[1-9]|1[0-2])$/.test(values.month) ? monthTitle(values.month) : null;
  const nights = /^\d+$/.test(values.nights.trim()) && Number(values.nights) > 0 ? Number(values.nights) : null;
  if (month && nights) return `${month}, ${countNoun(nights, "notte", "notti")}`;
  if (month) return month;
  return nights ? countNoun(nights, "notte", "notti") : null;
}

/** Who, in words: "2 adulti, 2 bambini di 8 e 11 anni", "1 adulto", "2 adulti, 1 bambino". The
 * ages show once every child has one. */
export function travelersSummary(values: RequestFormValues): string {
  const adults = countNoun(values.adults, "adulto", "adulti");
  const children = values.childAges.length;
  if (children === 0) return adults;
  const ages = values.childAges.map((age) => age.trim());
  const known = ages.every((age) => /^\d+$/.test(age));
  const kids = countNoun(children, "bambino", "bambini");
  if (!known) return `${adults}, ${kids}`;
  if (ages.every((age) => age === "0")) return `${adults}, ${kids} di meno di un anno`;
  const years = joinAnd(ages.map((age) => (age === "0" ? "meno di 1" : String(Number(age)))));
  const unit = ages.length === 1 && Number(ages[0]) === 1 ? "anno" : "anni";
  return `${adults}, ${kids} di ${years} ${unit}`;
}

/** How they get there, in words ("In treno"), or null for the plane: the default needs no line. */
export function journeySummary(values: RequestFormValues): string | null {
  const phrase = journeyModePhrase(values.journeyMode);
  return phrase ? phrase.charAt(0).toLocaleUpperCase("it") + phrase.slice(1) : null;
}

/** The budget in words ("2.400 €"), or null while it is not a whole positive amount. */
export function budgetSummary(values: RequestFormValues): string | null {
  const amount = parseBudget(values.budgetEur);
  return typeof amount === "number" && amount > 0 ? formatWholeEuros(amount) : null;
}
