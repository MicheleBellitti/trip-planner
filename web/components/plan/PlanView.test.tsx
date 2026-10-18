import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlanDetailSchema, type PlanDetail } from "@/lib/schemas/api";

import happyDetailJson from "./__fixtures__/happy-path.detail.json";
import happyTripJson from "./__fixtures__/happy-path.trip.json";
import kiwiDetailJson from "./__fixtures__/mcp-failure.detail.json";
import { PlanView, type TripLoader } from "./PlanView";

/** Real data of a ready `happy_path` demo plan (GET /plans/{id} and /trip of the local backend). */
function happyDetail(): PlanDetail {
  return PlanDetailSchema.parse(structuredClone(happyDetailJson));
}
function happyTrip(): { bookings: Record<string, unknown>[] } {
  return structuredClone(happyTripJson) as { bookings: Record<string, unknown>[] };
}

const unused: TripLoader = () => {
  throw new Error("the Trip should not be read");
};

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

/** The booking rows of the plan (not the alternatives), on screen: most urgent first. */
function rowsOnScreen(): HTMLElement[] {
  const section = screen.getByRole("heading", { level: 2, name: "Prenotazioni" }).closest("section");
  if (!section) throw new Error("no bookings section");
  return within(section).getAllByRole("listitem");
}

const positionOf = (row: HTMLElement) => Number(/-prenotazione-(\d+)$/.exec(row.id)?.[1]);

/** The same rows in the plan's own order (the agent's), which is how these tests count them. */
function bookingRows(): HTMLElement[] {
  return rowsOnScreen().sort((a, b) => positionOf(a) - positionOf(b));
}

function deadlineOf(row: HTMLElement): HTMLElement {
  const term = within(row).getByText("Prenota entro", { selector: "dt" });
  const value = term.nextElementSibling;
  if (!(value instanceof HTMLElement)) throw new Error("no deadline value");
  return value;
}

describe("PlanView", () => {
  it("offers its own hand-off when it is given one, instead of TripTracker's", () => {
    render(
      <PlanView
        detail={happyDetail()}
        trip={happyTrip()}
        loadTrip={unused}
        handoff={{ title: "Il tuo viaggio", text: "Descrivi il tuo viaggio.", label: "Pianifica il tuo viaggio", href: "/new" }}
      />,
    );
    const links = screen.getAllByRole("link", { name: "Pianifica il tuo viaggio" });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link.getAttribute("href")).toBe("/new");
    expect(screen.queryByRole("link", { name: /Apri in TripTracker/ })).toBeNull();
  });

  it("draws the hand-off's second link beside the first when it is given one", () => {
    render(
      <PlanView
        detail={happyDetail()}
        trip={happyTrip()}
        loadTrip={unused}
        handoff={{
          title: "Il tuo viaggio",
          text: "Su invito.",
          label: "Mettiti in lista",
          href: "/#lista",
          secondary: { label: "Accedi", href: "/login" },
        }}
      />,
    );
    const first = screen.getAllByRole("link", { name: "Mettiti in lista" });
    const second = screen.getAllByRole("link", { name: "Accedi" });
    expect(second).toHaveLength(first.length);
    for (const link of second) expect(link.getAttribute("href")).toBe("/login");
  });

  it("puts a notice above the plan when it is given one", () => {
    const { container } = render(
      <PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} notice={<p>Una corsa registrata.</p>} />,
    );
    const first = container.firstElementChild?.firstElementChild;
    expect(first?.textContent).toBe("Una corsa registrata.");
  });

  it("shows the summary, the estimated total and the warnings", () => {
    const detail = happyDetail();
    render(<PlanView detail={detail} trip={happyTrip()} loadTrip={unused} />);
    expect(screen.getByText(/^Cinque giorni a Lisbona/)).toBeTruthy();
    // The total has its own fact: the agent's line that restates it is left out.
    expect(screen.queryByText(/^Costo stimato: circa 1\.690 €/)).toBeNull();
    expect(screen.getByText("1.690,00 €")).toBeTruthy();
    expect(screen.getByText("3 prezzi stimati")).toBeTruthy();
    // The title ("Lisbona in famiglia, 14–18 aprile 2027") already states the dates.
    expect(screen.queryByText("Dal 14 al 18 aprile 2027")).toBeNull();
    const notice = screen.getByText("Da sapere prima di prenotare").closest("[data-tone]");
    expect(notice?.getAttribute("data-tone")).toBe("warning");
    expect(within(notice as HTMLElement).getAllByRole("listitem")).toHaveLength(2);
  });

  it("lists a source that did not answer among the warnings", () => {
    render(<PlanView detail={PlanDetailSchema.parse(kiwiDetailJson)} trip={happyTrip()} loadTrip={unused} />);
    expect(screen.getByText(/Kiwi\.com non ha risposto/)).toBeTruthy();
  });

  it("draws the days as stops with time, kind, duration and place", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const day = screen.getByRole("list", { name: "Tappe del giorno 2, gio 15 apr" });
    const stop = within(day).getAllByRole("listitem")[0] as HTMLElement;
    expect(stop.textContent).toContain("10:00");
    expect(stop.textContent).toContain("Oceanário de Lisboa");
    expect(stop.textContent).toContain("Attività, 2 h 30 min");
    expect(stop.textContent).toContain("Esplanada Dom Carlos I, 1990-005 Lisboa");
    const site = within(stop).getByRole("link", { name: /oceanario\.pt/ });
    expect(site.getAttribute("href")).toBe("https://www.oceanario.pt/");
    expect(site.getAttribute("target")).toBe("_blank");
    expect(site.getAttribute("rel")).toBe("noopener noreferrer");
    const booking = within(stop).getByRole("link", { name: "Biglietti Oceanário de Lisboa" });
    expect(booking.getAttribute("href")).toMatch(/^#.+-prenotazione-3$/);
  });

  it("says what the clock at home reads for the move that leaves home, and only for that one", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const first = within(screen.getByRole("list", { name: "Tappe del giorno 1, mer 14 apr" })).getAllByRole("listitem");
    expect(first[0]?.textContent).toContain("Spostamento, 2 h 40 min (parte alle 09:40 in Italia)");
    // The Aerobus in Lisbon and the flight home are read on the trip's clock.
    expect(first[1]?.textContent).not.toContain("in Italia");
    const last = within(screen.getByRole("list", { name: "Tappe del giorno 5, dom 18 apr" })).getAllByRole("listitem");
    expect(last.at(-1)?.textContent).not.toContain("in Italia");
  });

  it("lists the bookings in the strip's order, most urgent first, and the stops in the agent's", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const strip = screen
      .getByRole("heading", { level: 2, name: "Da prenotare" })
      .closest("section")
      ?.querySelectorAll("a") as NodeListOf<HTMLAnchorElement>;
    const stripOrder = [...strip].map((link) => link.getAttribute("href"));
    const listOrder = rowsOnScreen().map((row) => `#${row.id}`);
    expect(listOrder).toEqual(stripOrder);
  });

  it("gives every booking both dates, separate and labelled", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const rows = bookingRows();
    expect(rows).toHaveLength(5);
    for (const row of rows) {
      expect(within(row).getAllByRole("term").map((term) => term.textContent)).toEqual(["Prenota entro", "Quando"]);
    }
    // The agent's book_by, and the dueAt the backend derived for a booking without one.
    expect(deadlineOf(rows[0] as HTMLElement).querySelector("time")?.getAttribute("datetime")).toBe("2027-02-26T20:00:00Z");
    expect(deadlineOf(rows[2] as HTMLElement).querySelector("time")?.getAttribute("datetime")).toBe("2027-04-12T10:00:00+01:00");
    expect(document.querySelectorAll("[data-due-soon]")).toHaveLength(0);
  });

  it("turns amber only a deadline within 72 hours or past, never a booking to book now", () => {
    const detail = happyDetail();
    const trip = happyTrip();
    const plan = detail.plan!;
    plan.bookings[0]!.book_by = new Date(NOW + 30 * HOUR).toISOString();
    plan.bookings[1]!.book_by = new Date(NOW - 2 * HOUR).toISOString();
    plan.bookings[3]!.book_by = new Date(NOW + 73 * HOUR).toISOString();
    delete trip.bookings[2]!.dueAt; // the backend left it out: "Da prenotare subito"
    render(<PlanView detail={detail} trip={trip} loadTrip={unused} />);
    const rows = bookingRows();
    const due = rows.map((row) => row.querySelectorAll("[data-due-soon]").length);
    expect(due).toEqual([1, 1, 0, 0, 0]);
    expect(rows[0]?.textContent).toContain("In scadenza · tra un giorno");
    expect(rows[1]?.textContent).toContain("Scadenza passata");
    expect(deadlineOf(rows[2] as HTMLElement).textContent).toBe("Da prenotare subito");
  });

  it("opens 'Prenota su <sito>' in a new tab only for links the backend allowed", () => {
    const detail = happyDetail();
    const plan = detail.plan!;
    plan.bookings[3]!.link = "https://www.parquesdesintra.pt/bilhetes";
    detail.booking_links[3] = { allowed: false, provider: null, label: null, host: "www.parquesdesintra.pt" };
    render(<PlanView detail={detail} trip={happyTrip()} loadTrip={unused} />);
    const rows = bookingRows();
    const buttons = screen.getAllByRole("link", { name: /^Prenota su / });
    expect(buttons.map((link) => link.textContent)).toEqual([
      "Prenota su Expedia (si apre in una nuova scheda)",
      "Prenota su Expedia (si apre in una nuova scheda)",
    ]);
    buttons.forEach((link, index) => {
      expect(link.getAttribute("href")).toBe(plan.bookings[index]!.link);
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    });
    const refused = rows[3] as HTMLElement;
    expect(refused.querySelector('a[href="https://www.parquesdesintra.pt/bilhetes"]')).toBeNull();
    expect(within(refused).getByText("https://www.parquesdesintra.pt/bilhetes")).toBeTruthy();
    expect(within(refused).getByText("Link non verificato")).toBeTruthy();
  });

  it("shows no booking button when the verdicts do not line up with the bookings", () => {
    const detail = happyDetail();
    detail.booking_links = detail.booking_links.slice(0, 2);
    render(<PlanView detail={detail} trip={happyTrip()} loadTrip={unused} />);
    expect(screen.queryAllByRole("link", { name: /^Prenota su / })).toHaveLength(0);
    expect(screen.getAllByText("Link non verificato")).toHaveLength(2);
  });

  it("puts the alternatives in a closed section per kind, gated the same way", () => {
    const detail = happyDetail();
    detail.alternative_links[1] = { allowed: false, provider: null, label: null, host: "www.booking.com" };
    render(<PlanView detail={detail} trip={happyTrip()} loadTrip={unused} />);
    const sections = Array.from(document.querySelectorAll("details"));
    expect(sections.map((section) => section.querySelector("summary")?.textContent)).toEqual([
      "Voli1 alternativa",
      "Alloggi1 alternativa",
    ]);
    expect(sections.every((section) => !section.open)).toBe(true);
    expect(within(sections[0] as HTMLElement).getByRole("link", { name: /^Vedi su Expedia/ }).getAttribute("rel")).toBe(
      "noopener noreferrer",
    );
    expect(within(sections[1] as HTMLElement).queryByRole("link", { name: /^Vedi su/ })).toBeNull();
    for (const section of sections) {
      expect(within(section).getAllByRole("term").map((term) => term.textContent)).toEqual(["Prenota entro", "Quando"]);
    }
  });

  it("puts 'Apri in TripTracker' right after the bookings, above the alternatives and the timeline", () => {
    const detail = happyDetail();
    render(<PlanView detail={detail} trip={happyTrip()} loadTrip={unused} timeline={<p>la timeline</p>} />);
    const link = screen.getByRole("link", { name: /^Apri in TripTracker/ });
    expect(link.getAttribute("href")).toBe(detail.import_url);
    expect(link.getAttribute("href")).toMatch(/\/import\?plan=646f6139-324b-4817-96b5-d8dd4d392174$/);
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    const after = (earlier: Node, later: Node) => Boolean(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING);
    const bookings = screen.getByRole("heading", { level: 2, name: "Prenotazioni" });
    expect(after(bookings, link)).toBe(true);
    expect(after(link, screen.getByRole("heading", { level: 2, name: "Alternative scartate" }))).toBe(true);
    expect(after(link, screen.getByText("la timeline"))).toBe(true);
    // Full width on the phone.
    expect(link.className).toContain("w-full");
    cleanup();
    render(<PlanView detail={{ ...detail, import_url: null }} trip={happyTrip()} loadTrip={unused} />);
    expect(screen.queryByRole("link", { name: /^Apri in TripTracker/ })).toBeNull();
  });
});

describe("PlanView, what to do first", () => {
  it("lists the bookings by deadline right under the facts, each a link to its row", () => {
    const detail = happyDetail();
    render(<PlanView detail={detail} trip={happyTrip()} loadTrip={unused} />);
    const strip = screen.getByRole("heading", { level: 2, name: "Da prenotare" }).closest("section") as HTMLElement;
    const rows = within(strip).getAllByRole("link");
    // book_by 26 feb, 14 mar, 9 apr; dueAt derived for the other two: 12 apr (Oceanário), and
    // "Aerobus" has none ("da prenotare subito" or a date, whichever the Trip says).
    const titles = [
      "Volo TAP Milano Malpensa ⇄ Lisbona",
      "Hotel Lisboa Plaza, camera familiare (4 notti)",
      "Ingressi Palácio da Pena a orario fisso",
      "Biglietti Oceanário de Lisboa",
      "Aerobus aeroporto → centro",
    ];
    expect(rows.map((row) => titles.find((title) => row.textContent?.startsWith(title)))).toEqual(titles);
    // Each one previews both dates, labelled, as everywhere a booking appears.
    for (const row of rows) {
      expect(within(row).getAllByRole("term").map((term) => term.textContent)).toEqual(["Prenota entro", "Quando"]);
    }
    expect(deadlineOf(rows[0] as HTMLElement).textContent).toBe("ven 26 feb");
    expect(rows[0]?.getAttribute("href")).toMatch(/^#.+-prenotazione-1$/);
    // Nothing is due soon on 12 Oct 2026: no amber, no count.
    expect(strip.textContent).not.toContain("in scadenza");
    expect(strip.querySelector("[data-due-soon]")).toBeNull();
    // It sits between the facts and the warnings, above the itinerary.
    const days = screen.getByRole("heading", { level: 2, name: "Giorno per giorno" });
    expect(strip.compareDocumentPosition(days) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says in words and in ink how many are due within 72 hours", () => {
    const detail = happyDetail();
    const plan = detail.plan!;
    plan.bookings[0]!.book_by = new Date(NOW + 30 * HOUR).toISOString();
    plan.bookings[1]!.book_by = new Date(NOW - 2 * HOUR).toISOString();
    render(<PlanView detail={detail} trip={happyTrip()} loadTrip={unused} />);
    const strip = screen.getByRole("heading", { level: 2, name: "Da prenotare" }).closest("section") as HTMLElement;
    expect(within(strip).getByText("2 in scadenza")).toBeTruthy();
    expect(strip.textContent).toContain("Scadenza passata");
    expect(strip.textContent).toContain("In scadenza · tra un giorno");
    // Amber on those two deadlines only, drawn by their DatePair.
    expect(strip.querySelectorAll("[data-due-soon]")).toHaveLength(2);
    // The most urgent first: the one already past.
    expect(within(strip).getAllByRole("link")[0]?.textContent).toContain("Hotel Lisboa Plaza");
  });

  it("sets the total against the budget, in neutral words", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    expect(screen.getByText("710 € sotto il budget di 2.400 €")).toBeTruthy();
    cleanup();
    const over = happyDetail();
    over.request = { ...over.request, budget_eur: 1500 };
    render(<PlanView detail={over} trip={happyTrip()} loadTrip={unused} />);
    expect(screen.getByText("190 € sopra il budget di 1.500 €")).toBeTruthy();
  });

  it("reads 'Prenota entro' on Michele's clock, and a flight from home on the clock at home", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const flight = bookingRows()[0] as HTMLElement;
    // 20:00 UTC on 26 Feb is 21:00 in Rome; the flight leaves Milan at 09:40 there (08:40 in Lisbon).
    expect(deadlineOf(flight).textContent).toContain("ven 26 feb, 21:00");
    const when = within(flight).getByText("Quando", { selector: "dt" }).nextElementSibling as HTMLElement;
    // The bold clock is the one at home; the trip's is the second line and names its zone.
    expect(when.querySelector("time")?.textContent).toBe("mer 14 apr, 09:40");
    expect(when.textContent).toContain("08:40 a Lisbona");
    expect(when.textContent).not.toContain("in Italia");
    expect(screen.getByText("Gli orari sono quelli di Lisbona.")).toBeTruthy();
  });

  it("reads a booking at the destination on the trip's clock alone, with no second clock", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const whenOf = (row: HTMLElement) =>
      within(row).getByText("Quando", { selector: "dt" }).nextElementSibling as HTMLElement;
    const rows = bookingRows();
    // The hotel's check-in and the Aerobus (11:50 in Lisbon, after the flight landed): trip clock only.
    const hotel = whenOf(rows[1] as HTMLElement);
    expect(hotel.textContent).toBe("mer 14 apr, 15:00");
    const aerobus = whenOf(rows.at(-1) as HTMLElement);
    expect(aerobus.textContent).toBe("mer 14 apr, 11:50");
    for (const row of rows.slice(1)) expect(whenOf(row).textContent).not.toMatch(/a Lisbona|in Italia/);
  });

  it("points a booking without a link at the supplier's site, as text", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const oceanario = bookingRows()[2] as HTMLElement;
    expect(oceanario.textContent).toContain("Nessun link di prenotazione. Prenota sul sito di Oceanário de Lisboa: oceanario.pt");
    expect(within(oceanario).queryByRole("link", { name: /^Prenota su/ })).toBeNull();
  });

  it("brings the plan's top into view and focuses its summary when it arrives under a watcher", () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    const { rerender } = render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    expect(document.activeElement).toBe(document.body);
    cleanup();
    render(<PlanView arrival detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: "Sintesi del piano" }));
    expect(rerender).toBeDefined();
    vi.unstubAllGlobals();
  });
});

describe("PlanView reading the Trip", () => {
  it("reads it once when a booking needs a derived deadline, showing it as pending meanwhile", async () => {
    const detail = happyDetail();
    let resolve: (value: unknown) => void = () => {};
    const loadTrip = vi.fn<TripLoader>(() => new Promise((done) => (resolve = done)));
    render(<PlanView detail={detail} loadTrip={loadTrip} />);
    expect(loadTrip).toHaveBeenCalledTimes(1);
    expect(loadTrip.mock.calls[0]?.[0]).toBe(detail.id);
    const rows = bookingRows();
    expect(deadlineOf(rows[2] as HTMLElement).textContent).toBe("in calcolo…");
    // A booking with its own book_by does not wait for the Trip.
    expect(deadlineOf(rows[0] as HTMLElement).querySelector("time")).toBeTruthy();
    await act(async () => resolve(happyTrip()));
    expect(deadlineOf(bookingRows()[2] as HTMLElement).querySelector("time")?.getAttribute("datetime")).toBe(
      "2027-04-12T10:00:00+01:00",
    );
    expect(loadTrip).toHaveBeenCalledTimes(1);
  });

  it("says the deadline is not available when the Trip cannot be read", async () => {
    const loadTrip = vi.fn<TripLoader>(() => Promise.reject(new Error("offline")));
    render(<PlanView detail={happyDetail()} loadTrip={loadTrip} />);
    await act(async () => {});
    expect(deadlineOf(bookingRows()[2] as HTMLElement).textContent).toBe("non disponibile");
  });

  it("does not read it when the page gave it, or when no booking needs it", () => {
    const loadTrip = vi.fn<TripLoader>(() => Promise.resolve(happyTrip()));
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={loadTrip} />);
    cleanup();
    const detail = happyDetail();
    for (const booking of detail.plan!.bookings) booking.book_by ??= "2027-04-01T10:00:00+01:00";
    render(<PlanView detail={detail} loadTrip={loadTrip} />);
    expect(loadTrip).not.toHaveBeenCalled();
  });

  it("does not use a Trip that belongs to another plan", () => {
    const trip = happyTrip();
    trip.bookings[0]!.title = "Un altro volo";
    render(<PlanView detail={happyDetail()} trip={trip} loadTrip={unused} />);
    expect(deadlineOf(bookingRows()[2] as HTMLElement).textContent).toBe("non disponibile");
  });

  it("numbers each stop by its place in the day, the number the map draws on its station", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const day = within(screen.getByRole("list", { name: "Tappe del giorno 3, ven 16 apr" })).getAllByRole("listitem");
    expect(day.map((stop) => stop.querySelector("[aria-hidden='true'].text-ink-2.min-w-4")?.textContent)).toEqual(["1", "2", "3", "4"]);
  });

  it("leads with 'Da prenotare' on the phone: it is drawn before the prose", () => {
    render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
    const strip = screen.getByRole("heading", { level: 2, name: "Da prenotare" }).closest("section")?.parentElement;
    expect(strip?.className).toContain("max-lg:order-first");
  });

  describe("the map", () => {
    const days = () => screen.getByRole("heading", { level: 2, name: "Giorno per giorno" }).closest("section") as HTMLElement;

    it("opens 'Giorno per giorno' on the phone, above the list", () => {
      render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
      const region = screen.getByRole("region", { name: "Mappa delle tappe" });
      expect(days().contains(region)).toBe(true);
      const firstDay = within(days()).getAllByRole("list")[0] as HTMLElement;
      expect(region.compareDocumentPosition(firstDay) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("sits under 'Apri in TripTracker' in the sticky right cell from 1080 px, in view while the days are read", () => {
      vi.stubGlobal("matchMedia", (query: string) => ({
        matches: true,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }));
      try {
        render(<PlanView detail={happyDetail()} trip={happyTrip()} loadTrip={unused} />);
        const region = screen.getByRole("region", { name: "Mappa delle tappe" });
        expect(days().contains(region)).toBe(false);
        const cell = region.closest(".lg\\:sticky") as HTMLElement;
        expect(cell).toBeTruthy();
        const handoff = within(cell).getByRole("link", { name: /Apri in TripTracker/ });
        expect(handoff.compareDocumentPosition(region) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(within(cell).getByRole("heading", { level: 2, name: "Da prenotare" })).toBeTruthy();
      } finally {
        vi.unstubAllGlobals();
      }
    });
  });
});
