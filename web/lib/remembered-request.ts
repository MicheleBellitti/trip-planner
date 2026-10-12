/**
 * What the request form remembers between plans, in this browser only: where Michele leaves
 * from, how many adults travel and how many children (what he retypes every time). Never the
 * budget, the preferences, the destination or the dates: those are the new trip. Never the
 * children's ages either, though they are stored: a year later they are not the same, and the
 * party sets the price of flights and rooms in a paid run, so each age is a conscious tap.
 *
 * localStorage can be missing or throw (a private window, blocked site data, a quota): every
 * read and write is guarded, and the form works the same without it.
 */

import { fieldConstraints, type RequestFormValues } from "./request-form";

const KEY = "atlas:last-request";
const MAX_TRAVELERS = fieldConstraints("travelers").maxItems ?? 9;
const MAX_ORIGIN = fieldConstraints("origin").maxLength ?? 200;

export interface RememberedRequest {
  origin: string;
  adults: number;
  childAges: string[];
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
  const { origin, adults, childAges } = data as Record<string, unknown>;
  if (typeof origin !== "string" || origin.length > MAX_ORIGIN) return null;
  if (typeof adults !== "number" || !Number.isInteger(adults) || adults < 1 || adults > MAX_TRAVELERS) return null;
  if (!Array.isArray(childAges) || adults + childAges.length > MAX_TRAVELERS) return null;
  if (!childAges.every((age) => typeof age === "string" && /^\d{1,2}$/.test(age))) return null;
  return { origin: origin.trim(), adults, childAges: childAges as string[] };
}

export function readRemembered(): RememberedRequest | null {
  try {
    return parseRemembered(storage()?.getItem(KEY) ?? null);
  } catch {
    return null;
  }
}

/** Keeps the three fields of a request that was sent. Ages not chosen yet are left out. */
export function rememberRequest(values: Pick<RequestFormValues, "origin" | "adults" | "childAges">): void {
  const childAges = values.childAges.filter((age) => /^\d{1,2}$/.test(age));
  const entry: RememberedRequest = { origin: values.origin.trim(), adults: values.adults, childAges };
  try {
    storage()?.setItem(KEY, JSON.stringify(entry));
  } catch {
    // Nothing to do: the form just starts empty next time.
  }
}

/** The form's values with the remembered ones laid in, only where the form is still untouched.
 * The children come back as many empty ages ("Scegli"), never as the ages they had. */
export function applyRemembered(values: RequestFormValues, remembered: RememberedRequest | null): RequestFormValues {
  if (!remembered) return values;
  const untouched = values.origin === "" && values.adults === 1 && values.childAges.length === 0;
  if (!untouched) return values;
  return { ...values, origin: remembered.origin, adults: remembered.adults, childAges: remembered.childAges.map(() => "") };
}
