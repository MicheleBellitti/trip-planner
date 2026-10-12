/**
 * "Due soon", TripTracker's rule (docs/triptracker/snapshot/lib/bookings.ts `isExpiring`,
 * `EXPIRING_WINDOW_HOURS = 72`), decided for the planner by Michele on 2026-10-12: a booking is
 * due soon when its `dueAt` ("Prenota entro") is at most 72 hours from now, or already past. A
 * booking without a `dueAt` is never due soon. Amber means this and nothing else.
 */

export const DUE_SOON_HOURS = 72;

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/** True when `dueAt` (ISO 8601 with offset) is within 72 hours of `now` (ms), or past. */
export function isDueSoon(dueAt: string, now: number): boolean {
  const due = Date.parse(dueAt);
  if (Number.isNaN(due)) return false;
  return due <= now + DUE_SOON_HOURS * HOUR_MS;
}

/** How far the deadline is, in Italian: "tra 2 giorni", "tra un giorno", "tra 5 ore", "tra
 * meno di un'ora", "scadenza passata". Whole units, rounded down. */
export function dueDistance(dueAt: string, now: number): string | null {
  const due = Date.parse(dueAt);
  if (Number.isNaN(due)) return null;
  const left = due - now;
  if (left < 0) return "scadenza passata";
  if (left < HOUR_MS) return "tra meno di un'ora";
  if (left < DAY_MS) {
    const hours = Math.floor(left / HOUR_MS);
    return hours === 1 ? "tra un'ora" : `tra ${hours} ore`;
  }
  const days = Math.floor(left / DAY_MS);
  return days === 1 ? "tra un giorno" : `tra ${days} giorni`;
}
