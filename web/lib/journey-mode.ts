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

/** Each mode in words: the form's read-back names every one, the plane included. */
export const JOURNEY_MODE_PHRASES: Readonly<Record<JourneyMode, string>> = {
  flight: "in aereo",
  train: "in treno",
  ferry: "in traghetto",
  car: "in auto",
  coach: "in pullman",
};

/** A line under the form's chips for the two modes that are easy to confuse: the ferry carries the
 * party on foot, the car comes along on any ferry the route needs (spec 2026-10-18, §1). */
export const JOURNEY_MODE_NOTES: Readonly<Partial<Record<JourneyMode, string>>> = {
  ferry: "A bordo a piedi: se porti l'auto, scegli Auto.",
  car: "Con la tua auto, anche sui traghetti se servono.",
};

/** "in treno" for a stored request's mode, as the plan page's header says it; null for the plane
 * (the default, not worth a word there), null, or anything that is not a mode (a stored request
 * is read as an open object, so the value may be anything). */
export function journeyModePhrase(mode: unknown): string | null {
  if (typeof mode !== "string" || mode === DEFAULT_JOURNEY_MODE || !Object.hasOwn(JOURNEY_MODE_PHRASES, mode)) return null;
  return JOURNEY_MODE_PHRASES[mode as JourneyMode];
}
