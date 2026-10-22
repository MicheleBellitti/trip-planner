/**
 * What the request form remembers between plans, in this browser only: where Michele leaves
 * from, how many adults travel and how many children, and how he travels (what he retypes every
 * time; Michele, 2026-10-22: a habit, not a property of one trip). Never the budget, the
 * preferences, the destination or the dates: those are the new trip. Never the children's ages
 * either, though they are stored: a year later they are not the same, and the party sets the
 * price of flights and rooms in a paid run, so each age is a conscious tap.
 *
 * localStorage can be missing or throw (a private window, blocked site data, a quota): every
 * read and write is guarded, and the form works the same without it.
 */

import { DEFAULT_JOURNEY_MODE, type JourneyMode } from "./journey-mode";
import { fieldConstraints, JOURNEY_MODES, type RequestFormValues } from "./request-form";

const KEY = "atlas:last-request";
const MAX_TRAVELERS = fieldConstraints("travelers").maxItems ?? 9;
const MAX_ORIGIN = fieldConstraints("origin").maxLength ?? 200;

export interface RememberedRequest {
  origin: string;
  adults: number;
  childAges: string[];
  /** Missing in an entry written before the travel mode, or when the stored one is not a mode. */
  journeyMode?: JourneyMode;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** What a stored string says, or null when it is not what `rememberRequest` wrote. */
export function parseRemembered(raw: string | null): RememberedRequest | null {
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object") return null;
  const { origin, adults, childAges, journeyMode } = data as Record<string, unknown>;
  if (typeof origin !== "string" || origin.length > MAX_ORIGIN) return null;
  if (typeof adults !== "number" || !Number.isInteger(adults) || adults < 1 || adults > MAX_TRAVELERS) return null;
  if (!Array.isArray(childAges) || adults + childAges.length > MAX_TRAVELERS) return null;
  if (!childAges.every((age) => typeof age === "string" && /^\d{1,2}$/.test(age))) return null;
  const entry: RememberedRequest = { origin: origin.trim(), adults, childAges: childAges as string[] };
  // An odd mode is dropped on its own: the rest of the entry still saves a retype.
  if (JOURNEY_MODES.includes(journeyMode as JourneyMode)) entry.journeyMode = journeyMode as JourneyMode;
  return entry;
}

export function readRemembered(): RememberedRequest | null {
  try {
    return parseRemembered(storage()?.getItem(KEY) ?? null);
  } catch {
    return null;
  }
}

/** Keeps the four fields of a request that was sent. Ages not chosen yet are left out. */
export function rememberRequest(values: Pick<RequestFormValues, "origin" | "adults" | "childAges" | "journeyMode">): void {
  const childAges = values.childAges.filter((age) => /^\d{1,2}$/.test(age));
  const entry: RememberedRequest = {
    origin: values.origin.trim(),
    adults: values.adults,
    childAges,
    journeyMode: values.journeyMode,
  };
  try {
    storage()?.setItem(KEY, JSON.stringify(entry));
  } catch {
    // Nothing to do: the form just starts empty next time.
  }
}

/** The form's values with the remembered ones laid in, only where the form is still untouched.
 * The children come back as many empty ages ("Scegli"), never as the ages they had; the mode comes
 * back as it was sent (the plane for an entry from before the mode). */
export function applyRemembered(values: RequestFormValues, remembered: RememberedRequest | null): RequestFormValues {
  if (!remembered) return values;
  const untouched =
    values.origin === "" &&
    values.adults === 1 &&
    values.childAges.length === 0 &&
    values.journeyMode === DEFAULT_JOURNEY_MODE;
  if (!untouched) return values;
  return {
    ...values,
    origin: remembered.origin,
    adults: remembered.adults,
    childAges: remembered.childAges.map(() => ""),
    journeyMode: remembered.journeyMode ?? DEFAULT_JOURNEY_MODE,
  };
}
