"use client";

import type { ComponentProps } from "react";

import { DatePair } from "@/components/ui/date-pair";
import { usePlanNow } from "./plan-now";

/**
 * DatePair with the shared one-second clock: only these small pieces re-render every second,
 * not the whole plan. Before the first tick (and during server rendering) `now` is null, so
 * nothing is amber yet; DatePair alone decides amber from `dueAt` and `now` (72 hours, past
 * deadlines included).
 */
export function LiveDatePair(props: Omit<ComponentProps<typeof DatePair>, "now">) {
  const now = usePlanNow();
  return <DatePair {...props} now={now} />;
}
