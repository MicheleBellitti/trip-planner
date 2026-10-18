import type { Metadata } from "next";
import { Suspense } from "react";

import { EvalRunScreen } from "@/components/evals/eval-run-screen";
import { EvalRunSkeleton } from "@/components/evals/eval-run-skeleton";

export const metadata: Metadata = { title: "Collaudo" };

/** "/evals/[id]": one eval run with its comparison, its requests and the agents it used.
 * Everything is fetched in the browser, which carries the session cookie; the server only
 * sends the skeleton. */
export default function EvalRunPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<EvalRunSkeleton />}>
      {params.then(({ id }) => (
        <EvalRunScreen key={id} runId={id} />
      ))}
    </Suspense>
  );
}
