import { wallClock } from "./zone-time";

/** Italian formatting of figures shown on screen. Pure and locale-independent (no Intl data
 * differences between Node and browsers). */

function groupThousands(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const absolute = Math.abs(Math.round(cents));
  const units = Math.floor(absolute / 100);
  const rest = String(absolute % 100).padStart(2, "0");
  return `${sign}${groupThousands(String(units))},${rest}`;
}

/** US cents of Managed Agents list cost as Italian copy: 4820 -> "48,20 $" (the backend's
 * `format_usd`). Session budgets, costs and the monthly limit are always US dollars. */
export function formatUsd(cents: number): string {
  return `${formatCents(cents)} $`;
}

/** Euro cents as Italian copy: 150000 -> "1.500,00 €". */
export function formatEur(cents: number): string {
  return `${formatCents(cents)} €`;
}

/** A trip price in its currency, Italian format: EUR 81200 -> "812,00 €", USD 1250 -> "12,50 USD"
 * (a finished plan's bookings, a choice card's price for the party). Only the run's own cost is
 * written with "$" (formatUsd). */
export function formatPrice(price: { amount_cents: number; currency: string }): string {
  const cents = Math.max(0, Math.round(price.amount_cents));
  return `${formatCents(cents)} ${price.currency === "EUR" ? "€" : price.currency}`;
}

/** An expected duration in minutes (a stop's, a choice card's): 45 -> "45 min", 60 -> "1 h",
 * 160 -> "2 h 40 min", 2880 -> "2 giorni". */
export function formatDuration(minutes: number): string {
  const total = Math.max(0, Math.round(minutes));
  if (total >= 1440 && total % 1440 === 0) {
    const days = total / 1440;
    return days === 1 ? "1 giorno" : `${days} giorni`;
  }
  if (total < 60) return `${total} min`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

/** Elapsed time for the live header: 65_000 -> "1:05", 3_725_000 -> "1:02:05". Negative values
 * (clock skew between the browser and the backend) count as zero. */
export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`;
  }
  return `${minutes}:${seconds}`;
}

/** How long a plan has been running, for a list row: "meno di 1 min", "3 min", "1 h 5 min". Whole
 * minutes, rounded down: a row that is not watched does not need a second hand. */
export function formatRunningFor(ms: number): string {
  const minutes = Math.max(0, Math.floor(ms / 60_000));
  if (minutes < 1) return "meno di 1 min";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

/** A plan's title as the page shows it: the agent writes some titles with a hyphen between the
 * days of a range ("14-18 aprile"), the request's own title with an en dash. One form on screen:
 * the en dash between digits. */
export function displayTitle(title: string): string {
  return title.replace(/(\d)-(\d)/g, "$1–$2");
}

/** A date range inside a title: "14–18 aprile", "14–18 apr", "28 apr–2 mag". */
const DATE_RANGE = /\d{1,2}(?:\s\p{L}+)?–\d{1,2}\s\p{L}+/u;

/** A title cut around its first date range, so a screen can keep the range on one line
 * (`nowrap`): a break inside "14–/18 aprile" reads as two dates. The parts joined are the title. */
export function splitDateRange(title: string): { text: string; nowrap: boolean }[] {
  const match = DATE_RANGE.exec(title);
  if (!match) return [{ text: title, nowrap: false }];
  const parts = [
    { text: title.slice(0, match.index), nowrap: false },
    { text: match[0], nowrap: true },
    { text: title.slice(match.index + match[0].length), nowrap: false },
  ];
  return parts.filter((part) => part.text !== "");
}

/** Michele's clock: the zone his deadlines are read in (mirrors backend/app/clock.py
 * HOME_TIMEZONE). A booking's "Prenota entro" is when he must act, so it shows in this zone. */
export const HOME_TIMEZONE = "Europe/Rome";

const DATE_TIME_FORMATS = new Map<string, Intl.DateTimeFormat>();

/** An instant as Italian date and time in `timeZone` (default Europe/Rome), e.g.
 * "12 ott 2026, 15:00". For dates shown in the browser only: Intl data can differ between the
 * server's and the browser's ICU, so don't render it during server rendering. */
export function formatDateTime(iso: string, timeZone = HOME_TIMEZONE): string {
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return iso;
  let format = DATE_TIME_FORMATS.get(timeZone);
  if (!format) {
    format = new Intl.DateTimeFormat("it-IT", {
      timeZone,
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    DATE_TIME_FORMATS.set(timeZone, format);
  }
  return format.format(time);
}

const MONTHS_SHORT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];

const epochDay = (date: string) => Math.floor(Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10))) / 86_400_000);

/**
 * When a plan was created, the way a list reads it: "Oggi, 17:36", "Ieri, 21:40", "8 ott, 09:15"
 * and, only when the year is not the current one, "8 ott 2025, 09:15". Days are Michele's (Rome). For the
 * browser only (Intl), like formatDateTime.
 */
export function formatCreated(iso: string, nowMs: number, timeZone = HOME_TIMEZONE): string {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return iso;
  const then = wallClock(at, timeZone);
  const today = wallClock(nowMs, timeZone);
  const ago = epochDay(today.date) - epochDay(then.date);
  if (ago === 0) return `Oggi, ${then.time}`;
  if (ago === 1) return `Ieri, ${then.time}`;
  const day = `${Number(then.date.slice(8, 10))} ${MONTHS_SHORT[Number(then.date.slice(5, 7)) - 1]}`;
  // The time stays on older days too: two plans of one title and one day differ only by it.
  const date = then.date.slice(0, 4) === today.date.slice(0, 4) ? day : `${day} ${then.date.slice(0, 4)}`;
  return `${date}, ${then.time}`;
}
