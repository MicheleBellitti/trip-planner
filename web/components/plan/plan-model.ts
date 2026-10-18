/**
 * Pure helpers of the finished plan (PlanView): what each booking's link may become, which line
 * found a booking, the estimated total, the alternatives grouped per kind, and the Italian
 * formatting of days, trip dates and durations. No React, no I/O, no Intl (the strings are the
 * same on the server and in every browser).
 *
 * Dates of a booking ("Prenota entro", "Quando") are not formatted here: DatePair does it, and
 * `bookingDeadline` (lib/booking-dates.ts) decides the "Prenota entro" side.
 */

import type { BookingDeadline } from "@/lib/booking-dates";
import type { LinkCheck } from "@/lib/schemas/api";
import type { Plan, PlanBooking, PlanStop, Price } from "@/lib/schemas/generated/plan";
import type { AgentName } from "@/lib/schemas/generated/ui-event";

export {
  daysCount,
  formatPlanDay,
  formatTripDates,
  parsePlanDate,
  titleStatesDates,
  travelersCount,
  tripDayNumber,
  tripLength,
} from "./trip-dates";

// --- links ------------------------------------------------------------------------------------

/** `value` as a URL a page may link to: absolute http(s), with a host and no user info. Anything
 * else (javascript:, data:, a relative path, "https://user@host") is null and stays text. */
export function safeHttpUrl(value: string | null | undefined): URL | null {
  if (!value) return null;
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  if (!url.hostname || url.username || url.password) return null;
  return url;
}

/** The host a reader recognises: "www.oceanario.pt" -> "oceanario.pt". */
export function hostLabel(url: URL): string {
  return url.hostname.replace(/^www\./, "");
}

/** The link checks aligned with a list of `length` items (PlanDetail.booking_links or
 * .alternative_links). A list of another length cannot be trusted to line up, so every item
 * then counts as unchecked: its link stays text (fail closed). */
export function alignedChecks(checks: readonly (LinkCheck | null)[], length: number): (LinkCheck | null)[] {
  if (checks.length !== length) return Array.from({ length }, () => null);
  return [...checks];
}

/** What a booking's link becomes on screen. */
export type BookingAction =
  /** "Prenota su <site>": the backend's allowlist accepted the link (CLAUDE.md, contract rule 4).
   * `href` is the link exactly as the plan has it, never rewritten. */
  | { kind: "button"; href: string; site: string }
  /** A link outside the allowlist (or unchecked, or not https): shown as plain text. */
  | { kind: "text"; text: string }
  /** No link at all. */
  | { kind: "none" };

/**
 * The link gate: a booking link is a button only when the backend's verdict for it says
 * `allowed` and the link is an absolute https URL; in every other case it is plain text, never
 * an anchor. The site's name is the verdict's label ("Expedia"), else its host.
 */
export function bookingAction(link: string | null | undefined, check: LinkCheck | null | undefined): BookingAction {
  const text = link?.trim();
  if (!text) return { kind: "none" };
  const url = safeHttpUrl(link);
  if (check?.allowed === true && url?.protocol === "https:") {
    const site = check.label?.trim() || check.host?.trim() || hostLabel(url);
    return { kind: "button", href: link as string, site };
  }
  return { kind: "text", text };
}

// --- which line found a booking ---------------------------------------------------------------

const FLIGHT_WORDS = /\b(?:vol[oi]|flights?)\b/i;
const FLIGHT_PROVIDERS = new Set(["kiwi", "google_flights"]);

/** A `transport` booking that is a flight: its title says so ("Volo TAP ..."), or its link is a
 * flight search (Kiwi.com, Google Voli, Expedia's Flights-Search). */
export function isFlight(booking: Pick<PlanBooking, "kind" | "title" | "link">, check?: LinkCheck | null): boolean {
  if (booking.kind !== "transport") return false;
  if (FLIGHT_WORDS.test(booking.title)) return true;
  if (check?.allowed && check.provider && FLIGHT_PROVIDERS.has(check.provider)) return true;
  const url = safeHttpUrl(booking.link);
  return url !== null && /\/flights?[-/]/i.test(url.pathname);
}

/** The line (agent) whose roundel a booking carries (DESIGN.md: "each booking carries the
 * roundel of the line that found it"). The Plan does not record who found it, so it follows
 * from the kind: flights to voli, other transport and parking to spostamenti, lodging to
 * alloggio, tickets, activities, meals and wellness to attività, anything else to the
 * coordinator. */
export function bookingLine(booking: Pick<PlanBooking, "kind" | "title" | "link">, check?: LinkCheck | null): AgentName {
  switch (booking.kind) {
    case "lodging":
      return "lodging";
    case "transport":
      return isFlight(booking, check) ? "flights" : "transport";
    case "parking":
      return "transport";
    case "ticket":
    case "activity":
    case "restaurant":
    case "wellness":
      return "activities";
    case "other":
      return "coordinator";
  }
}

/** A booking's kind as one word, with flights told apart from other transport. */
export type BookingCategory = PlanBooking["kind"] | "flight";

export function bookingCategory(booking: Pick<PlanBooking, "kind" | "title" | "link">, check?: LinkCheck | null): BookingCategory {
  return isFlight(booking, check) ? "flight" : booking.kind;
}

/** The kind above a booking's title (singular). */
export const CATEGORY_LABELS: Record<BookingCategory, string> = {
  flight: "Volo",
  transport: "Trasporto",
  lodging: "Alloggio",
  ticket: "Biglietti",
  activity: "Attività",
  restaurant: "Ristorante",
  wellness: "Benessere",
  parking: "Parcheggio",
  other: "Altro",
};

/** The title of a closed section of alternatives (plural). */
export const CATEGORY_GROUP_LABELS: Record<BookingCategory, string> = {
  flight: "Voli",
  transport: "Trasporti",
  lodging: "Alloggi",
  ticket: "Biglietti",
  activity: "Attività",
  restaurant: "Ristoranti",
  wellness: "Benessere",
  parking: "Parcheggi",
  other: "Altro",
};

export interface AlternativeItem {
  booking: PlanBooking;
  /** Position in plan.alternatives (and in PlanDetail.alternative_links). */
  index: number;
  check: LinkCheck | null;
}

export interface AlternativeGroup {
  category: BookingCategory;
  label: string;
  items: AlternativeItem[];
}

/** The discarded alternatives, one group per kind, in the order the kinds first appear. */
export function alternativeGroups(
  alternatives: readonly PlanBooking[],
  checks: readonly (LinkCheck | null)[],
): AlternativeGroup[] {
  const aligned = alignedChecks(checks, alternatives.length);
  const groups = new Map<BookingCategory, AlternativeGroup>();
  alternatives.forEach((booking, index) => {
    const check = aligned[index] ?? null;
    const category = bookingCategory(booking, check);
    let group = groups.get(category);
    if (!group) {
      group = { category, label: CATEGORY_GROUP_LABELS[category], items: [] };
      groups.set(category, group);
    }
    group.items.push({ booking, index, check });
  });
  return [...groups.values()];
}

/** "1 alternativa", "3 alternative". */
export function alternativesCount(count: number): string {
  return count === 1 ? "1 alternativa" : `${count} alternative`;
}

// --- dates the plan page decides --------------------------------------------------------------

/** True when a booking's "Prenota entro" lives only in the Trip: no `book_by`, but a
 * `scheduled_for` the backend derived a `dueAt` from (CLAUDE.md, contract rule 1). Only then is
 * GET /plans/{id}/trip worth reading. */
export function needsTripDueDate(booking: Pick<PlanBooking, "book_by" | "scheduled_for">): boolean {
  return !booking.book_by && Boolean(booking.scheduled_for);
}

export function planNeedsTrip(plan: Pick<Plan, "bookings">): boolean {
  return plan.bookings.some(needsTripDueDate);
}

/** "Prenota entro" of a discarded alternative. Alternatives do not go to TripTracker, so the
 * backend derives no deadline for them: the agent's `book_by` if any, else "nessuna scadenza"
 * (quiet, not an error value). */
export function alternativeDeadline(booking: Pick<PlanBooking, "book_by" | "scheduled_for">): BookingDeadline {
  if (booking.book_by) return { kind: "date", at: booking.book_by };
  return { kind: "none" };
}

/** The words after Michele's clock where the trip's differs, in the itinerary: "(parte alle 09:40
 * in Italia)". */
export const HOME_CLOCK_LABEL = "in Italia";

/** The words after the trip's clock when it is the second line of a booking's "Quando": "08:40 a
 * Lisbona" (the destination's first part), "ora locale" without one. */
export function tripPlaceLabel(plan: Pick<Plan, "destination">): string {
  const city = plan.destination.split(",")[0]?.trim();
  return city ? `a ${city}` : "ora locale";
}

/** The trip's first move starts from home: the first stop of the first day, a transfer with a
 * start time. The itinerary says "parte alle 09:40 in Italia" on it, and the booking that belongs
 * to it (the flight) reads on the clock at home. One predicate for both. */
export function leavesHome(dayIndex: number, stopIndex: number, stop: Pick<PlanStop, "kind" | "start_time">): boolean {
  return dayIndex === 0 && stopIndex === 0 && stop.kind === "transfer" && Boolean(stop.start_time);
}

/** The booking belongs to the stop that leaves home. */
export function bookingStartsAtHome(plan: Pick<Plan, "days">, booking: Pick<PlanBooking, "stop_ref">): boolean {
  const first = plan.days[0]?.stops[0];
  return Boolean(first && booking.stop_ref && booking.stop_ref === first.ref && leavesHome(0, 0, first));
}

/** The clock the trip's own times are read in, named for the reader: "ora di Lisbona" (the
 * destination's first part). Null when the trip is in the home zone. Whether the two clocks
 * really differ at a given instant is DatePair's call. */
export function tripZoneName(plan: Pick<Plan, "timezone" | "destination">, homeTimeZone: string): string | null {
  if (plan.timezone === homeTimeZone) return null;
  const city = plan.destination.split(",")[0]?.trim();
  return city ? `ora di ${city}` : "ora locale";
}

/** How a booking reads in "Da prenotare": most urgent first. A deadline already too close to have
 * one ("Da prenotare subito") first, then dates ascending, then the bookings with no date to
 * book by, in the plan's own order. */
export interface BookingStripItem {
  /** Position in plan.bookings (the row's anchor). */
  index: number;
  booking: PlanBooking;
  deadline: BookingDeadline;
  /** The backend's verdict on the booking's link (which line found it). */
  check?: LinkCheck | null;
  /** The booking starts from home: its "Quando" leads with the clock at home (DatePair). */
  startsAtHome?: boolean;
}

function stripRank(deadline: BookingDeadline): number {
  switch (deadline.kind) {
    case "book_now":
      return 0;
    case "date":
      return 1;
    default:
      return 2;
  }
}

export function sortByDeadline(items: readonly BookingStripItem[]): BookingStripItem[] {
  return [...items].sort((a, b) => {
    const rank = stripRank(a.deadline) - stripRank(b.deadline);
    if (rank !== 0) return rank;
    if (a.deadline.kind === "date" && b.deadline.kind === "date") {
      const delta = Date.parse(a.deadline.at) - Date.parse(b.deadline.at);
      if (delta !== 0 && !Number.isNaN(delta)) return delta;
    }
    return a.index - b.index;
  });
}

// --- money ------------------------------------------------------------------------------------

function groupThousands(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/** A price in its currency, Italian format: EUR 81200 -> "812,00 €", USD 1250 -> "12,50 USD". */
export function formatPrice(price: Pick<Price, "amount_cents" | "currency">): string {
  const cents = Math.max(0, Math.round(price.amount_cents));
  const units = groupThousands(String(Math.floor(cents / 100)));
  const rest = String(cents % 100).padStart(2, "0");
  return `${units},${rest} ${price.currency === "EUR" ? "€" : price.currency}`;
}

export interface PlanTotal {
  /** Sum of the euro prices, in euro cents; null when no booking has one. */
  cents: number | null;
  /** Bookings in the plan. */
  count: number;
  /** Bookings whose euro price is in the sum. */
  priced: number;
  /** Of those, prices marked `estimated`. */
  estimated: number;
  /** Prices in another currency, left out of the sum (the backend converts to euro, so 0). */
  otherCurrency: number;
}

/** The plan's estimated total: the sum of its bookings' euro prices. */
export function planTotal(bookings: readonly Pick<PlanBooking, "price">[]): PlanTotal {
  let cents = 0;
  let priced = 0;
  let estimated = 0;
  let otherCurrency = 0;
  for (const { price } of bookings) {
    if (!price) continue;
    if (price.currency !== "EUR") {
      otherCurrency += 1;
      continue;
    }
    cents += price.amount_cents;
    priced += 1;
    if (price.status === "estimated") estimated += 1;
  }
  return { cents: priced > 0 ? cents : null, count: bookings.length, priced, estimated, otherCurrency };
}

/** The line under the total: how much of it is estimated. Quiet by design: the label above says
 * it is a total, the line says only what to trust ("3 prezzi stimati"). A total that leaves out
 * bookings without a price says so ("Somma di 3 prenotazioni su 5"). */
export function totalNote(total: PlanTotal): string {
  if (total.cents === null) return "Nessuna prenotazione ha un prezzo";
  const trust =
    total.estimated === total.priced
      ? total.priced === 1
        ? "prezzo stimato"
        : "tutti i prezzi stimati"
      : total.estimated > 0
        ? total.estimated === 1
          ? "1 prezzo stimato"
          : `${total.estimated} prezzi stimati`
        : total.priced === 1
          ? "prezzo verificato"
          : "prezzi verificati";
  if (total.priced === total.count) return trust.charAt(0).toLocaleUpperCase("it") + trust.slice(1);
  return `Somma di ${total.priced} prenotazioni su ${total.count}, ${trust}`;
}

/** The total against the request's budget, in neutral words: "710 € sotto il budget di 2.400 €",
 * "130 € sopra il budget di 2.400 €", "In linea con il budget di 2.400 €". Null when the budget is
 * unknown or the total leaves out bookings without a price (it would compare a part). */
export function budgetComparison(total: PlanTotal, budgetEur: number | null | undefined): string | null {
  if (total.cents === null || total.priced !== total.count || !budgetEur || budgetEur <= 0) return null;
  const budget = `${groupThousands(String(Math.round(budgetEur)))} €`;
  const delta = budgetEur * 100 - total.cents;
  if (Math.abs(delta) < 50) return `In linea con il budget di ${budget}`;
  const euros = groupThousands(String(Math.round(Math.abs(delta) / 100)));
  return `${euros} € ${delta > 0 ? "sotto" : "sopra"} il budget di ${budget}`;
}

// --- text -------------------------------------------------------------------------------------

/** The summary's lines (the agent writes three, separated by newlines). With `dropTotal` the
 * line that restates the total ("Costo stimato: circa 1.690 € ...") is left out: the total has
 * its own fact right under the summary. */
export function summaryLines(summary: string, dropTotal = false): string[] {
  return summary
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "" && !(dropTotal && /^costo stimato\b/i.test(line)));
}

export const STOP_KIND_LABELS: Record<PlanStop["kind"], string> = {
  activity: "Attività",
  meal: "Pasto",
  transfer: "Spostamento",
  rest: "Tempo libero",
};

/** A stop's expected duration: 45 -> "45 min", 60 -> "1 h", 160 -> "2 h 40 min", 2880 ->
 * "2 giorni". */
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

/** The bookings of each stop (`PlanBooking.stop_ref` -> positions in plan.bookings). */
export function bookingsByStop(bookings: readonly Pick<PlanBooking, "stop_ref">[]): Map<string, number[]> {
  const byStop = new Map<string, number[]>();
  bookings.forEach((booking, index) => {
    if (!booking.stop_ref) return;
    const list = byStop.get(booking.stop_ref) ?? [];
    list.push(index);
    byStop.set(booking.stop_ref, list);
  });
  return byStop;
}

/** The place line of a stop: its name (unless the title already says it) and its address. */
export function stopPlace(stop: Pick<PlanStop, "title" | "location_name" | "address">): string | null {
  const name = stop.location_name?.trim() || null;
  const address = stop.address?.trim() || null;
  const sameAsTitle = name !== null && stop.title.toLocaleLowerCase("it").includes(name.toLocaleLowerCase("it"));
  const parts = [sameAsTitle ? null : name, address].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(", ") : null;
}
