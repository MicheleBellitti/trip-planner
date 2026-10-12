/**
 * A booking's two dates on the finished plan, "Prenota entro" and "Quando" (CLAUDE.md, UI
 * rules: always separate and labelled, previews too).
 *
 * "Prenota entro" is TripTracker's `dueAt`. When the agent leaves `book_by` null, the backend
 * derives it from `scheduled_for` minus TripTracker's default lead for the kind, never before
 * the day after acceptance, and leaves it out ("Da prenotare subito") when that is not before
 * `scheduled_for` (CLAUDE.md, contract rule 1; backend/app/mapping.py `fallback_due_at`). That
 * date exists only in the stored Trip (GET /plans/{id}/trip), which `plan_to_trip` builds from
 * `plan.bookings` in order, copying each title: so the Trip is read here, never recomputed.
 */

import * as z from "zod/mini";

import { formatDateTime } from "./format";
import type { Plan, PlanBooking } from "./schemas/generated/plan";

/** The part of the Trip this page reads. Anything else in it is TripTracker's business. */
const TripDueDatesSchema = z.object({
  bookings: z.array(
    z.object({
      title: z.string(),
      dueAt: z.optional(z.iso.datetime({ offset: true })),
    }),
  ),
});

/** Each booking's `dueAt` in the Trip, aligned with `plan.bookings` (null where it has none);
 * null when `trip` is not this plan's Trip (another shape, count or title order). */
export function tripDueDates(trip: unknown, plan: Pick<Plan, "bookings">): (string | null)[] | null {
  const parsed = TripDueDatesSchema.safeParse(trip);
  if (!parsed.success) return null;
  const bookings = parsed.data.bookings;
  if (bookings.length !== plan.bookings.length) return null;
  if (bookings.some((booking, index) => booking.title !== plan.bookings[index]?.title)) return null;
  return bookings.map((booking) => booking.dueAt ?? null);
}

/** Where the Trip stands: being fetched, its due dates (or null: unusable), or the fetch failed. */
export type TripDueDates = { state: "loading" } | { state: "loaded"; dueAt: (string | null)[] | null } | { state: "failed" };

export type BookingDeadline =
  /** A deadline: the agent's `book_by`, or the one the backend derived. */
  | { kind: "date"; at: string }
  /** Too close for a deadline: the backend left `dueAt` out. */
  | { kind: "book_now" }
  /** Neither date is known, so there is nothing to derive from. */
  | { kind: "none" }
  /** The Trip is still on its way. */
  | { kind: "pending" }
  /** The Trip could not be read. */
  | { kind: "unknown" };

export function bookingDeadline(booking: PlanBooking, index: number, trip: TripDueDates): BookingDeadline {
  // The backend copies book_by into dueAt unchanged.
  if (booking.book_by) return { kind: "date", at: booking.book_by };
  if (!booking.scheduled_for) return { kind: "none" };
  if (trip.state === "loading") return { kind: "pending" };
  if (trip.state === "failed" || trip.dueAt === null) return { kind: "unknown" };
  const dueAt = trip.dueAt[index];
  if (dueAt === undefined) return { kind: "unknown" };
  return dueAt === null ? { kind: "book_now" } : { kind: "date", at: dueAt };
}

/** The value after "Prenota entro:", in Italian; dates in the trip's time zone. */
export function deadlineText(deadline: BookingDeadline, timeZone: string): string {
  switch (deadline.kind) {
    case "date":
      return formatDateTime(deadline.at, timeZone);
    case "book_now":
      return "Da prenotare subito";
    case "none":
      return "nessuna scadenza";
    case "pending":
      return "in calcolo…";
    case "unknown":
      return "non disponibile";
  }
}

/** The value after "Quando:", in Italian. */
export function scheduledText(booking: PlanBooking, timeZone: string): string {
  return booking.scheduled_for ? formatDateTime(booking.scheduled_for, timeZone) : "da definire";
}
