/**
 * What the request form (/new) needs besides lib/request-form.ts: control ids per request path,
 * the order in which errors are visited, the choices of its selects, and the development-only
 * demo scenarios. Pure: tested without rendering.
 */

import {
  childAgePath,
  fieldConstraints,
  requestErrorMessage,
  type FieldErrors,
  type RequestFormValues,
} from "@/lib/request-form";

import { monthTitle } from "./summary";

/** The 422 path of `?demo_scenario=` (backend routes.check_demo_scenario: loc query, demo_scenario). */
export const DEMO_SCENARIO_PATH = "query.demo_scenario";

/** The id of the control that shows a request path's error: "dates.exact_start" ->
 * "field-dates-exact_start". Group paths ("dates", "travelers") have no control of their own. */
export function fieldId(path: string): string {
  return `field-${path.replaceAll(".", "-") || "request"}`;
}

/** Ids of the two traveller counts (their errors live on the group path "travelers"). */
export const ADULTS_ID = "field-adults";
export const CHILDREN_ID = "field-children";
/** Id of a group's error line ("dates", "travelers"), wired into the first control's description. */
export function groupErrorId(path: string): string {
  return `${fieldId(path)}-error`;
}

export interface ErrorTarget {
  /** The request path the error is reported on. */
  path: string;
  /** The control to focus. */
  controlId: string;
  /** How the error summary names the field. */
  label: string;
}

/** Every place on the form where an error can show, in the order the form shows them. An error
 * on a path missing from this list (a hidden field, a model-level issue) belongs to the summary
 * above the button. */
export function errorTargets(values: RequestFormValues, options: { demo: boolean }): ErrorTarget[] {
  const targets: ErrorTarget[] = [{ path: "origin", controlId: fieldId("origin"), label: "Da dove parti" }];
  if (values.suggestDestination) {
    targets.push({ path: "destination_idea", controlId: fieldId("destination_idea"), label: "Che viaggio vorresti" });
  } else {
    targets.push({ path: "destination", controlId: fieldId("destination"), label: "Dove vuoi andare" });
  }
  if (values.dateMode === "exact") {
    targets.push(
      { path: "dates", controlId: fieldId("dates.exact_start"), label: "Date" },
      { path: "dates.exact_start", controlId: fieldId("dates.exact_start"), label: "Partenza" },
      { path: "dates.exact_end", controlId: fieldId("dates.exact_end"), label: "Ritorno" },
    );
  } else {
    targets.push(
      { path: "dates", controlId: fieldId("dates.month"), label: "Date" },
      { path: "dates.month", controlId: fieldId("dates.month"), label: "Mese di partenza" },
      { path: "dates.nights", controlId: fieldId("dates.nights"), label: "Notti" },
    );
  }
  targets.push({ path: "travelers", controlId: ADULTS_ID, label: "Chi viaggia" });
  values.childAges.forEach((_, index) => {
    const path = childAgePath(index, values.adults);
    targets.push({ path, controlId: fieldId(path), label: `Età del bambino ${index + 1}` });
  });
  targets.push(
    { path: "budget_eur", controlId: fieldId("budget_eur"), label: "Budget totale" },
    { path: "preferences", controlId: fieldId("preferences"), label: "Preferenze" },
  );
  if (options.demo) targets.push({ path: DEMO_SCENARIO_PATH, controlId: fieldId(DEMO_SCENARIO_PATH), label: "Scenario demo" });
  return targets;
}

export interface PlacedErrors {
  /** Errors that show next to a control, in form order. */
  placed: (ErrorTarget & { message: string })[];
  /** Errors with no control on screen: shown (and listed) in the summary only. */
  unplaced: { path: string; message: string }[];
}

/** Splits the errors into those the form shows by a control and the rest. */
export function placeErrors(errors: FieldErrors, targets: readonly ErrorTarget[]): PlacedErrors {
  const placed = targets.flatMap((target) => {
    const message = errors[target.path];
    return message ? [{ ...target, message }] : [];
  });
  const known = new Set(targets.map((target) => target.path));
  const unplaced = Object.entries(errors).flatMap(([path, message]) =>
    message && !known.has(path) ? [{ path, message }] : [],
  );
  return { placed, unplaced };
}

/** The request's generic "Campo obbligatorio.", said for the field it is about. */
const REQUIRED = requestErrorMessage("missing");
const REQUIRED_MESSAGES: Readonly<Record<string, string>> = {
  origin: "Indica da dove parti: una città o un aeroporto.",
  budget_eur: "Indica il budget totale, in euro.",
};

export function withFieldWording(errors: FieldErrors): FieldErrors {
  const next = { ...errors };
  for (const [path, message] of Object.entries(REQUIRED_MESSAGES)) {
    if (next[path] === REQUIRED) next[path] = message;
  }
  return next;
}

/** The day after `today` (YYYY-MM-DD): the earliest departure the backend accepts. */
export function nextDay(today: string): string {
  const [year, month, day] = today.split("-").map(Number);
  const next = new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, (day ?? 1) + 1));
  return next.toISOString().slice(0, 10);
}

export interface MonthOption {
  value: string;
  label: string;
}

/** The months to leave in: this month (the backend accepts it) and the next `count - 1`, as
 * "Ottobre 2026". A month already chosen outside that window stays in the list. */
export function monthOptions(today: string, count = 18, chosen = ""): MonthOption[] {
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  const options = Array.from({ length: count }, (_, offset) => {
    const index = month - 1 + offset;
    const value = `${year + Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
    return { value, label: monthTitle(value) };
  });
  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(chosen) && !options.some((option) => option.value === chosen)) {
    options.push({ value: chosen, label: monthTitle(chosen) });
    options.sort((a, b) => a.value.localeCompare(b.value));
  }
  return options;
}

/** "Meno di 1 anno", "1 anno", "2 anni" ... "17 anni": the schema's age range. */
export function childAgeOptions(): MonthOption[] {
  const age = fieldConstraints("travelers.age");
  const min = age.minimum ?? 0;
  const max = age.maximum ?? 17;
  return Array.from({ length: max - min + 1 }, (_, offset) => {
    const years = min + offset;
    const label = years === 0 ? "Meno di 1 anno" : years === 1 ? "1 anno" : `${years} anni`;
    return { value: String(years), label };
  });
}

/** At most this many travellers (the schema's maxItems). */
export const MAX_TRAVELERS = fieldConstraints("travelers").maxItems ?? 9;

/** NEXT_PUBLIC_DEMO_SCENARIOS ("happy_path,budget_reached"): the scenarios the form offers in
 * development, as backend fixture names. Production never shows them, whatever the variable
 * says; blanks, duplicates and names the backend could not have are dropped. */
export function parseDemoScenarios(raw: string | undefined, nodeEnv: string | undefined): string[] {
  if (nodeEnv === "production" || !raw) return [];
  const names = raw
    .split(",")
    .map((name) => name.trim())
    .filter((name) => /^[a-z0-9_]{1,64}$/.test(name));
  return [...new Set(names)];
}
