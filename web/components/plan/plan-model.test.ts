import { describe, expect, it } from "vitest";

import { formatDuration as formatDurationOfLib, formatPrice as formatPriceOfLib } from "@/lib/format";
import type { LinkCheck, LinkHealthMap } from "@/lib/schemas/api";
import type { PlanBooking } from "@/lib/schemas/generated/plan";

import {
  alignedChecks,
  alternativeDeadline,
  budgetComparison,
  sortByDeadline,
  tripZoneName,
  alternativeGroups,
  alternativesCount,
  bookingAction,
  bookingLine,
  bookingsByStop,
  formatDuration,
  formatPlanDay,
  formatPrice,
  formatTripDates,
  isFlight,
  needsTripDueDate,
  parsePlanDate,
  planNeedsTrip,
  planUrl,
  planTotal,
  safeHttpUrl,
  stopPlace,
  summaryLines,
  titleStatesDates,
  totalNote,
  tripDayNumber,
  tripLength,
} from "./plan-model";

const EXPEDIA: LinkCheck = { allowed: true, provider: "expedia", label: "Expedia", host: "www.expedia.it" };
const REFUSED: LinkCheck = { allowed: false, provider: null, label: null, host: "www.parquesdesintra.pt" };

function booking(overrides: Partial<PlanBooking> = {}): PlanBooking {
  return {
    title: "Hotel Lisboa Plaza",
    kind: "lodging",
    vendor: null,
    book_by: null,
    book_by_reason: null,
    scheduled_for: null,
    link: null,
    notes: null,
    phone: null,
    price: null,
    stop_ref: null,
    ...overrides,
  };
}

describe("link gate", () => {
  const link = "https://www.expedia.it/Hotel-Search?chkin=2027-04-14&rm1=a2:c9:c6";

  it("makes a button only when the backend allowed the link, with the link exactly as received", () => {
    expect(bookingAction(link, EXPEDIA)).toEqual({ kind: "button", href: link, site: "Expedia" });
  });

  it("keeps a refused or unchecked link as text", () => {
    expect(bookingAction(link, REFUSED)).toEqual({ kind: "text", text: link });
    expect(bookingAction(link, null)).toEqual({ kind: "text", text: link });
    expect(bookingAction(link, undefined)).toEqual({ kind: "text", text: link });
  });

  it("never makes a button of a link that is not https, whatever the verdict says", () => {
    expect(bookingAction("http://www.expedia.it/x", EXPEDIA).kind).toBe("text");
    expect(bookingAction("javascript:alert(1)", EXPEDIA).kind).toBe("text");
    expect(bookingAction("/relative", EXPEDIA).kind).toBe("text");
  });

  it("has nothing to show without a link", () => {
    expect(bookingAction(null, EXPEDIA)).toEqual({ kind: "none" });
    expect(bookingAction("   ", EXPEDIA)).toEqual({ kind: "none" });
  });

  it("names the site by the verdict's label, else its host", () => {
    expect(bookingAction(link, { ...EXPEDIA, label: null })).toMatchObject({ site: "www.expedia.it" });
    expect(bookingAction(link, { ...EXPEDIA, label: null, host: null })).toMatchObject({ site: "expedia.it" });
  });

  it("trusts link verdicts only when they line up with the list", () => {
    expect(alignedChecks([EXPEDIA, null], 2)).toEqual([EXPEDIA, null]);
    expect(alignedChecks([EXPEDIA], 2)).toEqual([null, null]);
    expect(alignedChecks([], 3)).toEqual([null, null, null]);
  });

  it("links only to absolute http(s) URLs without user info", () => {
    expect(safeHttpUrl("https://www.oceanario.pt/")?.hostname).toBe("www.oceanario.pt");
    expect(safeHttpUrl("http://localhost:3999/import?plan=1")?.host).toBe("localhost:3999");
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "oceanario.pt", "https://user:pw@x.pt/", "", null]) {
      expect(safeHttpUrl(bad)).toBeNull();
    }
  });
});

describe("the line that found a booking", () => {
  it("tells flights from other transport", () => {
    const flight = booking({ kind: "transport", title: "Volo TAP Milano Malpensa ⇄ Lisbona" });
    const bus = booking({ kind: "transport", title: "Aerobus aeroporto → centro" });
    expect(bookingLine(flight)).toBe("flights");
    expect(bookingLine(bus)).toBe("transport");
    expect(isFlight(booking({ kind: "transport", title: "Andata e ritorno", link: "https://www.expedia.it/Flights-Search?trip=roundtrip" }))).toBe(true);
    expect(isFlight(booking({ kind: "transport", title: "Andata" }), { ...EXPEDIA, provider: "kiwi" })).toBe(true);
  });

  it("maps the other kinds to their lines", () => {
    expect(bookingLine(booking({ kind: "lodging" }))).toBe("lodging");
    expect(bookingLine(booking({ kind: "ticket" }))).toBe("activities");
    expect(bookingLine(booking({ kind: "restaurant" }))).toBe("activities");
    expect(bookingLine(booking({ kind: "parking" }))).toBe("transport");
    expect(bookingLine(booking({ kind: "other" }))).toBe("coordinator");
  });

  it("groups alternatives per kind, in order, with their own verdicts", () => {
    const alternatives = [
      booking({ kind: "transport", title: "Volo easyJet" }),
      booking({ kind: "lodging", title: "Martinhal" }),
      booking({ kind: "transport", title: "Volo Ryanair" }),
    ];
    const groups = alternativeGroups(alternatives, [EXPEDIA, REFUSED, null]);
    expect(groups.map((group) => [group.label, group.items.map((item) => item.index)])).toEqual([
      ["Voli", [0, 2]],
      ["Alloggi", [1]],
    ]);
    expect(groups[1]?.items[0]?.check).toEqual(REFUSED);
    expect(alternativeGroups(alternatives, [EXPEDIA]).flatMap((group) => group.items.map((item) => item.check))).toEqual([
      null,
      null,
      null,
    ]);
    expect(alternativesCount(1)).toBe("1 alternativa");
    expect(alternativesCount(2)).toBe("2 alternative");
  });
});

describe("booking dates the page decides", () => {
  it("reads the Trip only for a booking without book_by but with scheduled_for", () => {
    expect(needsTripDueDate({ book_by: null, scheduled_for: "2027-04-15T10:00:00+01:00" })).toBe(true);
    expect(needsTripDueDate({ book_by: "2027-04-09T20:00:00+01:00", scheduled_for: "2027-04-16T10:30:00+01:00" })).toBe(false);
    expect(needsTripDueDate({ book_by: null, scheduled_for: null })).toBe(false);
    expect(planNeedsTrip({ bookings: [booking({ book_by: "2027-02-26T20:00:00+00:00" })] })).toBe(false);
    expect(planNeedsTrip({ bookings: [booking({ scheduled_for: "2027-04-14T15:00:00+01:00" })] })).toBe(true);
  });

  it("gives an alternative its own book_by, never a date it does not have", () => {
    expect(alternativeDeadline({ book_by: "2027-03-01T10:00:00+00:00", scheduled_for: null })).toEqual({
      kind: "date",
      at: "2027-03-01T10:00:00+00:00",
    });
    expect(alternativeDeadline({ book_by: null, scheduled_for: "2027-04-14T09:25:00+01:00" })).toEqual({ kind: "none" });
    expect(alternativeDeadline({ book_by: null, scheduled_for: null })).toEqual({ kind: "none" });
  });
});

describe("trip days", () => {
  it("formats a plan date without moving it across time zones", () => {
    expect(formatPlanDay("2027-04-14")).toBe("mer 14 apr");
    expect(formatPlanDay("2027-01-03")).toBe("dom 3 gen");
    expect(formatPlanDay("2027-02-30")).toBe("2027-02-30");
    expect(parsePlanDate("2027-13-01")).toBeNull();
  });

  it("numbers days from the start, counting omitted ones", () => {
    expect(tripDayNumber("2027-04-14", "2027-04-14")).toBe(1);
    expect(tripDayNumber("2027-04-18", "2027-04-14")).toBe(5);
    expect(tripDayNumber("2027-03-01", "2027-02-27")).toBe(3);
    expect(tripLength("2027-04-14", "2027-04-18")).toBe(5);
    expect(tripLength("2027-04-18", "2027-04-14")).toBeNull();
  });

  it("writes the trip's dates in words, with Italian elision", () => {
    expect(formatTripDates("2027-04-14", "2027-04-18")).toBe("Dal 14 al 18 aprile 2027");
    expect(formatTripDates("2027-04-28", "2027-05-02")).toBe("Dal 28 aprile al 2 maggio 2027");
    expect(formatTripDates("2026-12-30", "2027-01-03")).toBe("Dal 30 dicembre 2026 al 3 gennaio 2027");
    expect(formatTripDates("2027-08-01", "2027-08-11")).toBe("Dall'1 all'11 agosto 2027");
    expect(formatTripDates("2027-04-14", "2027-04-14")).toBe("Il 14 aprile 2027");
    expect(formatTripDates("2027-04-08", "2027-04-08")).toBe("L'8 aprile 2027");
  });

  it("re-exports the duration and price formats of lib/format, for its callers", () => {
    expect(formatDuration).toBe(formatDurationOfLib);
    expect(formatPrice).toBe(formatPriceOfLib);
  });
});

describe("money and text", () => {
  it("adds up the euro prices and says how much is estimated", () => {
    const price = (amount: number, status: "verified" | "estimated", currency = "EUR") => ({
      amount_cents: amount,
      currency,
      status,
      source_url: "https://example.org/",
      retrieved_at: "2026-10-12T12:00:00+02:00",
    });
    const total = planTotal([
      booking({ price: price(81200, "verified") }),
      booking({ price: price(6000, "estimated") }),
      booking({ price: null }),
      booking({ price: price(500, "verified", "USD") }),
    ]);
    expect(total).toEqual({ cents: 87200, count: 4, priced: 2, estimated: 1, otherCurrency: 1 });
    expect(totalNote(total)).toBe("Somma di 2 prenotazioni su 4, 1 prezzo stimato");
    // Every booking priced: only what to trust, the label above already says it is a total.
    expect(totalNote(planTotal([booking({ price: price(100, "verified") }), booking({ price: price(100, "verified") })]))).toBe(
      "Prezzi verificati",
    );
    expect(totalNote(planTotal([booking({ price: price(100, "estimated") }), booking({ price: price(100, "verified") })]))).toBe(
      "1 prezzo stimato",
    );
    expect(totalNote(planTotal([booking({ price: price(100, "estimated") }), booking({ price: price(100, "estimated") })]))).toBe(
      "Tutti i prezzi stimati",
    );
    expect(planTotal([booking()]).cents).toBeNull();
    expect(totalNote(planTotal([booking()]))).toBe("Nessuna prenotazione ha un prezzo");
  });

  it("splits the summary into its lines", () => {
    expect(summaryLines("Uno.\nDue.\r\n\n  Tre.  ")).toEqual(["Uno.", "Due.", "Tre."]);
  });

  it("leaves out the line that restates the total only when asked", () => {
    const summary = "Uno.\nDue.\nCosto stimato: circa 1.690 € (voli 812 €).";
    expect(summaryLines(summary)).toHaveLength(3);
    expect(summaryLines(summary, true)).toEqual(["Uno.", "Due."]);
  });

  it("knows when the title already states the dates", () => {
    expect(titleStatesDates("Lisbona in famiglia, 14–18 aprile 2027", "2027-04-14", "2027-04-18")).toBe(true);
    expect(titleStatesDates("Lisbona, 14–18 apr", "2027-04-14", "2027-04-18")).toBe(true);
    expect(titleStatesDates("Lisbona, 28 apr–2 mag", "2027-04-28", "2027-05-02")).toBe(true);
    expect(titleStatesDates("Lisbona, weekend lungo di novembre", "2027-11-14", "2027-11-18")).toBe(false);
    // 18 inside 2018 is not the 18th.
    expect(titleStatesDates("Lisbona 2018, aprile", "2027-04-14", "2027-04-18")).toBe(false);
  });

  it("names a stop's place without repeating its title", () => {
    expect(stopPlace({ title: "Oceanário de Lisboa", location_name: "Oceanário de Lisboa", address: "Esplanada Dom Carlos I" })).toBe(
      "Esplanada Dom Carlos I",
    );
    expect(stopPlace({ title: "Volo TP827", location_name: "Aeroporto di Milano Malpensa", address: null })).toBe(
      "Aeroporto di Milano Malpensa",
    );
    expect(stopPlace({ title: "Pranzo", location_name: null, address: null })).toBeNull();
  });

  it("finds each stop's bookings", () => {
    const map = bookingsByStop([booking({ stop_ref: "d1-volo" }), booking(), booking({ stop_ref: "d1-volo" })]);
    expect([...map.entries()]).toEqual([["d1-volo", [0, 2]]]);
  });
});

describe("the plan's first screen", () => {
  const total = (cents: number, priced = 5, count = 5) => ({ cents, count, priced, estimated: 0, otherCurrency: 0 });

  it("sets the total against the budget in neutral words, whole euros", () => {
    expect(budgetComparison(total(169000), 2400)).toBe("710 € sotto il budget di 2.400 €");
    expect(budgetComparison(total(250000), 2400)).toBe("100 € sopra il budget di 2.400 €");
    expect(budgetComparison(total(240020), 2400)).toBe("In linea con il budget di 2.400 €");
    expect(budgetComparison(total(169000, 3, 5), 2400)).toBeNull();
    expect(budgetComparison(total(169000), null)).toBeNull();
    expect(budgetComparison({ ...total(0), cents: null, priced: 0 }, 2400)).toBeNull();
  });

  it("orders 'Da prenotare' by deadline: too close first, then dates, then the ones with none", () => {
    const booking = {} as never;
    const items = [
      { index: 0, booking, deadline: { kind: "none" } as const },
      { index: 1, booking, deadline: { kind: "date", at: "2027-04-09T20:00:00+01:00" } as const },
      { index: 2, booking, deadline: { kind: "book_now" } as const },
      { index: 3, booking, deadline: { kind: "date", at: "2027-02-26T20:00:00Z" } as const },
      { index: 4, booking, deadline: { kind: "unknown" } as const },
    ];
    expect(sortByDeadline(items).map((item) => item.index)).toEqual([2, 3, 1, 0, 4]);
  });

  it("names the trip's clock only when the trip is away from home", () => {
    expect(tripZoneName({ timezone: "Europe/Lisbon", destination: "Lisbona, Portogallo" }, "Europe/Rome")).toBe("ora di Lisbona");
    expect(tripZoneName({ timezone: "Europe/Rome", destination: "Roma" }, "Europe/Rome")).toBeNull();
  });
});

describe("planUrl and dead links", () => {
  const DEAD = "https://www.a.example/old-page";
  const HEALTH: LinkHealthMap = {
    [DEAD]: { status: "dead", fallback: "https://www.a.example/", fallback_allowed: false },
    "https://b.example/gone": { status: "dead", fallback: null, fallback_allowed: false },
    "https://c.example/x": { status: "unknown", fallback: null, fallback_allowed: false },
    "https://d.example/x": { status: "ok", fallback: null, fallback_allowed: false },
  };

  it("planUrl: a dead page with a fallback is the homepage", () =>
    expect(planUrl(DEAD, HEALTH)).toEqual({ kind: "homepage", href: "https://www.a.example/", host: "a.example" }));
  it("planUrl: a dead page without a fallback is missing", () =>
    expect(planUrl("https://b.example/gone", HEALTH)).toEqual({ kind: "missing", host: "b.example" }));
  it("planUrl: no verdict, or ok or unknown, is the link as today", () => {
    for (const url of ["https://c.example/x", "https://d.example/x", "https://e.example/x"]) {
      expect(planUrl(url, HEALTH)).toMatchObject({ kind: "link", href: url });
    }
    expect(planUrl("https://www.e.example/x", {})).toEqual({ kind: "link", href: "https://www.e.example/x", host: "e.example" });
  });
  it("planUrl: an empty or non-http URL is none", () => {
    expect(planUrl(null, HEALTH)).toEqual({ kind: "none" });
    expect(planUrl("", HEALTH)).toEqual({ kind: "none" });
    expect(planUrl("javascript:alert(1)", HEALTH)).toEqual({ kind: "none" });
  });
  it("planUrl: an unsafe fallback is never linked", () => {
    const health: LinkHealthMap = { [DEAD]: { status: "dead", fallback: "javascript:alert(1)", fallback_allowed: false } };
    expect(planUrl(DEAD, health)).toEqual({ kind: "missing", host: "a.example" });
  });

  const FLIGHTS = "https://www.google.com/travel/flights?q=x";
  it("bookingAction: a dead Google Flights link is missing, never a button", () => {
    const check: LinkCheck = { allowed: true, provider: "google_flights", label: "Google Voli", host: "www.google.com" };
    const health: LinkHealthMap = { [FLIGHTS]: { status: "dead", fallback: "https://www.google.com/", fallback_allowed: false } };
    expect(bookingAction(FLIGHTS, check, health)).toEqual({ kind: "missing", text: FLIGHTS });
  });
  it("bookingAction: a dead Booking.com link with an allowed fallback is a button to it", () => {
    const link = "https://www.booking.com/hotel/pt/gone.html";
    const check: LinkCheck = { allowed: true, provider: "booking", label: "Booking.com", host: "www.booking.com" };
    const health: LinkHealthMap = { [link]: { status: "dead", fallback: "https://www.booking.com/", fallback_allowed: true } };
    expect(bookingAction(link, check, health)).toEqual({ kind: "button", href: "https://www.booking.com/", site: "Booking.com", fallback: true });
  });
  it("bookingAction: an allowed fallback is not trusted without an allowed check", () => {
    const link = "https://www.booking.com/hotel/pt/gone.html";
    const health: LinkHealthMap = { [link]: { status: "dead", fallback: "https://www.booking.com/", fallback_allowed: true } };
    expect(bookingAction(link, REFUSED, health)).toEqual({ kind: "missing", text: link });
  });
  it("bookingAction: a dead link that does not parse is missing, with its text", () => {
    const link = "expedia senza indirizzo";
    const health: LinkHealthMap = { [link]: { status: "dead", fallback: null, fallback_allowed: false } };
    expect(bookingAction(link, null, health)).toEqual({ kind: "missing", text: link });
  });
  it("bookingAction: without health, or with a live verdict, is unchanged", () => {
    expect(bookingAction("https://www.expedia.it/x", EXPEDIA)).toEqual({ kind: "button", href: "https://www.expedia.it/x", site: "Expedia" });
    const health: LinkHealthMap = { "https://www.expedia.it/x": { status: "ok", fallback: null, fallback_allowed: false } };
    expect(bookingAction("https://www.expedia.it/x", EXPEDIA, health)).toMatchObject({ kind: "button" });
  });
});
