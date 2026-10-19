import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BookingDeadline } from "@/lib/booking-dates";
import { PlanDetailSchema } from "@/lib/schemas/api";

import happyDetailJson from "./__fixtures__/happy-path.detail.json";
import { BookingStrip } from "./booking-strip";
import type { BookingStripItem } from "./plan-model";

/** "Today" for these tests: 12 ott 2026, 10:36 in Rome. */
const NOW = Date.parse("2026-10-12T10:36:12+02:00");
const HOUR = 3_600_000;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/** The bookings of a ready `happy_path` demo plan, in Lisbon. */
function happyBookings() {
  return PlanDetailSchema.parse(structuredClone(happyDetailJson)).plan!.bookings;
}

function strip(items: BookingStripItem[]) {
  return render(
    <BookingStrip
      items={items}
      anchor={(index) => `prenotazione-${index + 1}`}
      headingId="da-prenotare"
      timeZone="Europe/Lisbon"
    />,
  );
}

/** The strip's row for a booking, found by its title. */
function rowOf(title: string): HTMLElement {
  const row = screen.getAllByRole("link").find((link) => link.textContent?.includes(title));
  if (!row) throw new Error(`no row for ${title}`);
  return row;
}

function valueOf(row: HTMLElement, term: "Prenota entro" | "Quando"): HTMLElement {
  const value = within(row).getByText(term, { selector: "dt" }).nextElementSibling;
  if (!(value instanceof HTMLElement)) throw new Error(`no ${term} value`);
  return value;
}

describe("BookingStrip", () => {
  it("previews every booking with both dates, labelled 'Prenota entro' and 'Quando'", () => {
    const bookings = happyBookings();
    bookings[2]!.scheduled_for = null; // Oceanário: not fixed yet
    const deadlines: BookingDeadline[] = [
      { kind: "date", at: bookings[0]!.book_by! },
      { kind: "date", at: bookings[1]!.book_by! },
      { kind: "none" },
      { kind: "date", at: bookings[3]!.book_by! },
      { kind: "book_now" },
    ];
    strip(bookings.map((booking, index) => ({ index, booking, deadline: deadlines[index]! })));

    const rows = screen.getAllByRole("link");
    expect(rows).toHaveLength(5);
    for (const row of rows) {
      expect(within(row).getAllByRole("term").map((term) => term.textContent)).toEqual(["Prenota entro", "Quando"]);
    }
    // The flight: book by 26 Feb (on Michele's clock), it happens on 14 Apr. Never one for the other.
    const flight = rowOf("Volo TAP");
    expect(valueOf(flight, "Prenota entro").querySelector("time")?.getAttribute("datetime")).toBe("2027-02-26T20:00:00Z");
    expect(valueOf(flight, "Prenota entro").textContent).toBe("ven 26 feb");
    expect(valueOf(flight, "Quando").querySelector("time")?.getAttribute("datetime")).toBe("2027-04-14T08:40:00+01:00");
    expect(valueOf(flight, "Quando").textContent).toContain("mer 14 apr");
    expect(valueOf(rowOf("Aerobus"), "Prenota entro").textContent).toBe("Da prenotare subito");
    expect(valueOf(rowOf("Aerobus"), "Quando").textContent).toBe("mer 14 apr");
    expect(valueOf(rowOf("Oceanário"), "Prenota entro").textContent).toBe("nessuna scadenza");
    expect(valueOf(rowOf("Oceanário"), "Quando").textContent).toBe("da definire");
  });

  it("previews a flight from home on the day at home, with no lone clock time", () => {
    const bookings = happyBookings();
    strip([{ index: 0, booking: bookings[0]!, deadline: { kind: "date", at: bookings[0]!.book_by! }, startsAtHome: true }]);
    const flight = rowOf("Volo TAP");
    // It leaves Milan at 09:40 (08:40 in Lisbon): the strip says the day, the row below both clocks.
    expect(valueOf(flight, "Quando").textContent).toBe("mer 14 apr");
    expect(flight.textContent).not.toMatch(/\d{1,2}:\d{2}|a Lisbona|ora locale/);
  });

  it("draws amber only on a 'Prenota entro' within 72 hours", () => {
    const bookings = happyBookings();
    const deadlines: BookingDeadline[] = [
      { kind: "date", at: new Date(NOW + 30 * HOUR).toISOString() },
      { kind: "date", at: new Date(NOW - 2 * HOUR).toISOString() },
      { kind: "date", at: new Date(NOW + 10 * 24 * HOUR).toISOString() },
      { kind: "date", at: new Date(NOW + 73 * HOUR).toISOString() },
      { kind: "book_now" },
    ];
    const { container } = strip(bookings.map((booking, index) => ({ index, booking, deadline: deadlines[index]! })));

    const amber = [...container.querySelectorAll("[data-due-soon]")];
    expect(amber).toEqual([valueOf(rowOf("Hotel Lisboa Plaza"), "Prenota entro"), valueOf(rowOf("Volo TAP"), "Prenota entro")]);
    // Said in words too, not by colour alone.
    expect(screen.getByText("2 in scadenza")).toBeTruthy();
    expect(rowOf("Hotel Lisboa Plaza").textContent).toContain("Scadenza passata");
    expect(rowOf("Volo TAP").textContent).toContain("In scadenza · tra un giorno");
    // A booking without a dueAt is not amber, however urgent its words.
    expect(rowOf("Aerobus").querySelector("[data-due-soon]")).toBeNull();
  });

  it("marks 'senza link' on the booking with a dead link only, never in amber", () => {
    const bookings = happyBookings();
    const deadline: BookingDeadline = { kind: "date", at: new Date(NOW + 30 * HOUR).toISOString() };
    const { container } = strip(
      bookings.slice(0, 3).map((booking, index) => ({ index, booking, deadline, noLink: index === 1 })),
    );
    expect(within(rowOf(bookings[1]!.title)).getByText("senza link")).toBeTruthy();
    expect(within(rowOf(bookings[0]!.title)).queryByText("senza link")).toBeNull();
    expect(within(rowOf(bookings[2]!.title)).queryByText("senza link")).toBeNull();
    const label = screen.getByText("senza link");
    expect(label.className).not.toMatch(/amber|due-soon|bg-/);
    expect(label.closest("[data-due-soon]")).toBeNull();
    expect(container.querySelectorAll("[data-due-soon]").length).toBeGreaterThanOrEqual(0);
  });
});
