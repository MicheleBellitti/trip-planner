/**
 * The request in one line under the plan's title: "Da Milano, 2 adulti e 2 bambini (8 e 11
 * anni), budget 2.400 €". The title already says where and when ("Lisbona, 14–18 apr"); this says
 * from where, who and how much. Read defensively: GET /plans/{id} returns the stored request as
 * an open object, and an old or odd row must never break the page.
 */

import { journeyModePhrase } from "@/lib/journey-mode";

function count(value: number, one: string, many: string): string {
  return `${value} ${value === 1 ? one : many}`;
}

function wholeEuro(amount: number): string {
  const grouped = String(Math.round(amount)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${grouped} €`;
}

function childAges(ages: number[]): string {
  if (ages.length === 1) {
    const [age] = ages;
    if (age === 0) return "meno di 1 anno";
    return count(age ?? 0, "anno", "anni");
  }
  const listed = ages.length === 2 ? ages.join(" e ") : `${ages.slice(0, -1).join(", ")} e ${ages[ages.length - 1]}`;
  return `${listed} anni`;
}

/** "2 adulti e 2 bambini (8 e 11 anni)", "1 adulto", "1 adulto e 1 bambino (meno di 1 anno)". */
export function travelersText(travelers: unknown): string | null {
  if (!Array.isArray(travelers)) return null;
  let adults = 0;
  const ages: number[] = [];
  let unknownAges = 0;
  for (const traveler of travelers as unknown[]) {
    if (!traveler || typeof traveler !== "object") continue;
    const { kind, age } = traveler as { kind?: unknown; age?: unknown };
    if (kind === "adult") adults += 1;
    else if (kind === "child") {
      if (typeof age === "number" && Number.isInteger(age) && age >= 0) ages.push(age);
      else unknownAges += 1;
    }
  }
  const children = ages.length + unknownAges;
  const parts: string[] = [];
  if (adults > 0) parts.push(count(adults, "adulto", "adulti"));
  if (children > 0) {
    const label = count(children, "bambino", "bambini");
    parts.push(ages.length === children ? `${label} (${childAges(ages)})` : label);
  }
  return parts.length > 0 ? parts.join(" e ") : null;
}

/** The one-line summary of a stored PlanRequest, or null when nothing in it can be read. A
 * finished plan sets its total against the budget itself and states how it travels, so its
 * header leaves the budget and the mode out (`withBudget: false`, `withMode: false`) and may add
 * the trip's length (`extra`). */
export function requestSummary(
  request: Record<string, unknown> | null | undefined,
  {
    withBudget = true,
    withMode = true,
    extra = null,
  }: { withBudget?: boolean; withMode?: boolean; extra?: string | null } = {},
): string | null {
  if (!request) return null;
  const parts: string[] = [];
  const origin = typeof request.origin === "string" ? request.origin.trim() : "";
  // How they get there, unless by plane (the default): "Da Milano in treno". A finished plan
  // leaves it out (`withMode: false`): a journey pause may have changed it, and the stored
  // request keeps the mode asked for.
  const journey = withMode ? journeyModePhrase(request.journey_mode) : null;
  if (origin) parts.push(journey ? `Da ${origin} ${journey}` : `Da ${origin}`);
  else if (journey) parts.push(journey.charAt(0).toLocaleUpperCase("it") + journey.slice(1));
  const travelers = travelersText(request.travelers);
  if (travelers) parts.push(travelers);
  const dates = request.dates;
  if (dates && typeof dates === "object") {
    const { nights, exact_start: start } = dates as { nights?: unknown; exact_start?: unknown };
    // Fixed dates are in the title; a month and a number of nights only names the month there.
    if (!start && typeof nights === "number" && Number.isInteger(nights) && nights > 0) {
      parts.push(count(nights, "notte", "notti"));
    }
  }
  const budget = request.budget_eur;
  if (withBudget && typeof budget === "number" && Number.isFinite(budget) && budget > 0) parts.push(`budget ${wholeEuro(budget)}`);
  if (extra) parts.push(extra);
  if (parts.length === 0) return null;
  return parts.join(", ");
}
