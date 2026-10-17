import type { Metadata } from "next";
import { Suspense } from "react";

import { PlanScreen } from "@/components/live/plan-screen";
import { PlanSkeleton } from "@/components/states/plan-skeleton";

export const metadata: Metadata = { title: "Piano" };

/**
 * "/plans/[id]": the live timeline while the plan runs, every state that is not `ready`, and the
 * finished plan with the timeline closed under it. Everything is fetched in the browser, which
 * carries the session cookie to the backend; the server only sends the skeleton.
 */
export default function PlanPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<PlanSkeleton />}>
      {params.then(({ id }) => (
        <PlanScreen key={id} planId={id} />
      ))}
    </Suspense>
  );
}
