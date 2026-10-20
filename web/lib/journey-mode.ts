/**
 * The main journey's travel mode (PlanRequest.journey_mode) in words: the form's labels and the
 * summaries' phrases. Type-only imports, so the plan page's header can name a stored request's
 * mode without loading the request schema. The enum itself is read from schema/request.json in
 * lib/request-form.ts (`JOURNEY_MODES`); a test keeps the two in step.
 */

import type { PlanRequest } from "./schemas/generated/request";

export type JourneyMode = NonNullable<PlanRequest["journey_mode"]>;

/** Aereo is chosen when the form opens (spec 2026-10-18, "The form"). */
export const DEFAULT_JOURNEY_MODE: JourneyMode = "flight";

/** The form's labels, in the schema's order. */
export const JOURNEY_MODE_LABELS: Readonly<Record<JourneyMode, string>> = {
  flight: "Aereo",
  train: "Treno",
  ferry: "Traghetto",
  car: "Auto",
  coach: "Pullman",
};

/** The plane is the default, so the summaries say nothing for it. */
const PHRASES: Readonly<Partial<Record<JourneyMode, string>>> = {
  train: "in treno",
  ferry: "in traghetto",
  car: "in auto",
  coach: "in pullman",
};

/** "in treno" for a request's mode; null for the plane, null, or anything that is not a mode (a
 * stored request is read as an open object, so the value may be anything). */
export function journeyModePhrase(mode: unknown): string | null {
  if (typeof mode !== "string" || !Object.hasOwn(PHRASES, mode)) return null;
  return PHRASES[mode as JourneyMode] ?? null;
}
