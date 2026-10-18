"use client";

import { createContext, useContext } from "react";

import { useNow } from "@/lib/use-now";

/** A fixed "now" for a plan's relative dates ("In scadenza", "tra 2 giorni"): the demo reads them
 * on the recording's date, so its showcase never goes stale. Null, the live clock. */
export const PlanNowContext = createContext<number | null>(null);

/** The clock a plan's relative dates read: the fixed one if the page gives one, else the live one. */
export function usePlanNow(): number | null {
  const fixed = useContext(PlanNowContext);
  const live = useNow();
  return fixed ?? live;
}
