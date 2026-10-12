import { describe, expect, it } from "vitest";

import { bookingDeadline, deadlineText, scheduledText, tripDueDates, type TripDueDates } from "./booking-dates";
import { formatDateTime } from "./format";
import { PlanBookingSchema, type PlanBooking } from "./schemas/generated/plan";

const TZ = "Europe/Lisbon";

function booking(fields: Partial<PlanBooking> & { title: string }): PlanBooking {
  return PlanBookingSchema.parse({ kind: "lodging", ...fields });
}

const withBookBy = booking({
  title: "Hotel Lisboa Plaza",
  book_by: "2027-03-31T18:00:00+01:00",
  scheduled_for: "2027-04-14T15:00:00+01:00",
});
const derived = booking({ title: "Oceanário", kind: "ticket", scheduled_for: "2027-04-15T10:00:00+01:00" });
const tooClose = booking({ title: "Aerobus", kind: "transport", scheduled_for: "2026-10-13T09:00:00+01:00" });
const undated = booking({ title: "Parcheggio", kind: "parking" });
const plan = { bookings: [withBookBy, derived, tooClose, undated] };

/** What backend/app/mapping.py stores: titles copied in order, dueAt only when there is one. */
const trip = {
  id: "trip-1",
  bookings: [
    { id: "b1", title: "Hotel Lisboa Plaza", dueAt: "2027-03-31T18:00:00+01:00", scheduledFor: "2027-04-14T15:00:00+01:00" },
    { id: "b2", title: "Oceanário", dueAt: "2027-04-14T10:00:00+01:00", scheduledFor: "2027-04-15T10:00:00+01:00" },
    { id: "b3", title: "Aerobus", scheduledFor: "2026-10-13T09:00:00+01:00", notes: "Da prenotare subito: ..." },
    { id: "b4", title: "Parcheggio" },
  ],
};
const loaded: TripDueDates = { state: "loaded", dueAt: tripDueDates(trip, plan) };

describe("tripDueDates", () => {
  it("reads each booking's dueAt from the Trip, aligned with plan.bookings", () => {
    expect(tripDueDates(trip, plan)).toEqual(["2027-03-31T18:00:00+01:00", "2027-04-14T10:00:00+01:00", null, null]);
  });

  it("refuses a Trip that is not this plan's", () => {
    expect(tripDueDates({ bookings: trip.bookings.slice(1) }, plan)).toBeNull();
    expect(tripDueDates({ bookings: [...trip.bookings].reverse() }, plan)).toBeNull();
    expect(tripDueDates({ bookings: [{ title: "Hotel Lisboa Plaza", dueAt: "domani" }] }, { bookings: [withBookBy] })).toBeNull();
    expect(tripDueDates(null, plan)).toBeNull();
  });
});

describe("bookingDeadline", () => {
  it("uses book_by as is", () => {
    expect(bookingDeadline(withBookBy, 0, { state: "loading" })).toEqual({ kind: "date", at: withBookBy.book_by });
  });

  it("shows the deadline the backend derived when book_by is null", () => {
    expect(bookingDeadline(derived, 1, loaded)).toEqual({ kind: "date", at: "2027-04-14T10:00:00+01:00" });
  });

  it("says 'Da prenotare subito' when the backend left dueAt out", () => {
    const deadline = bookingDeadline(tooClose, 2, loaded);
    expect(deadline).toEqual({ kind: "book_now" });
    expect(deadlineText(deadline, TZ)).toBe("Da prenotare subito");
  });

  it("never shows a bare dash", () => {
    const states: TripDueDates[] = [{ state: "loading" }, loaded, { state: "failed" }, { state: "loaded", dueAt: null }];
    for (const state of states) {
      plan.bookings.forEach((item, index) => {
        const text = deadlineText(bookingDeadline(item, index, state), TZ);
        expect(text).not.toMatch(/^\s*[—–-]?\s*$/);
      });
    }
    expect(deadlineText(bookingDeadline(derived, 1, { state: "loading" }), TZ)).toBe("in calcolo…");
    expect(deadlineText(bookingDeadline(derived, 1, { state: "failed" }), TZ)).toBe("non disponibile");
    expect(deadlineText(bookingDeadline(undated, 3, loaded), TZ)).toBe("nessuna scadenza");
  });

  it("keeps the two dates separate", () => {
    expect(deadlineText(bookingDeadline(derived, 1, loaded), TZ)).toBe(formatDateTime("2027-04-14T10:00:00+01:00", TZ));
    expect(scheduledText(derived, TZ)).toBe(formatDateTime("2027-04-15T10:00:00+01:00", TZ));
    expect(scheduledText(undated, TZ)).toBe("da definire");
  });
});
