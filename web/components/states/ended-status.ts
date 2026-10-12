import type { PlanStatus } from "@/lib/schemas/api";

/** The statuses after which a plan will not move again on its own and has words of its own
 * (PlanEndedPanel). Kept apart from the panel so the live page can ask without loading it. */
export type EndedStatus = Extract<PlanStatus, "interrupted" | "failed" | "blocked">;

export function isEndedStatus(status: PlanStatus | null): status is EndedStatus {
  return status === "interrupted" || status === "failed" || status === "blocked";
}
