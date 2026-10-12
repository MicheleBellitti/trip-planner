/**
 * The home page's invitation (spec: "un invito con un esempio di richiesta già scritto"): the
 * example request of lib/request-form.ts in words, so the sentence on the home page and the
 * form it prefills (/new?esempio=1) can never say two different things.
 */

import { exampleRequestForm, type RequestFormValues } from "@/lib/request-form";

import { budgetSummary, countNoun, datesSummary, monthName, travelersSummary } from "../request/summary";

/** The /new link that opens the form already filled in with the example. */
export const EXAMPLE_HREF = "/new?esempio=1";

export interface ExampleRequest {
  /** "Lisbona a metà aprile, 2 adulti e 2 bambini, 2.400 €". */
  sentence: string;
  origin: string;
  destination: string;
  /** "14–18 aprile 2027, 4 notti". */
  dates: string;
  /** "2 adulti, 2 bambini di 8 e 11 anni". */
  travelers: string;
  /** "2.400 €". */
  budget: string;
  preferences: string;
}

export function describeExample(values: RequestFormValues): ExampleRequest {
  const budget = budgetSummary(values) ?? "";
  const people = [countNoun(values.adults, "adulto", "adulti")];
  if (values.childAges.length > 0) people.push(countNoun(values.childAges.length, "bambino", "bambini"));
  return {
    sentence: `${values.destination} a metà ${monthName(values.exactStart)}, ${people.join(" e ")}, ${budget}`,
    origin: values.origin,
    destination: values.destination,
    dates: datesSummary(values) ?? "",
    travelers: travelersSummary(values),
    budget,
    preferences: values.preferences,
  };
}

/** The example for `today` (YYYY-MM-DD, Europe/Rome). */
export function exampleRequest(today: string): ExampleRequest {
  return describeExample(exampleRequestForm(today));
}
