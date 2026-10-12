import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PlanPreview } from "./preview";

export const metadata: Metadata = {
  title: "Anteprima del piano",
  robots: { index: false, follow: false },
};

/**
 * "/dev/plan": the finished plan (components/plan/PlanView) on real demo data, in development
 * only. The fixtures are a ready `happy_path` and `mcp_failure` demo plan of the local backend
 * (GET /plans/{id} and /trip, saved under components/plan/__fixtures__/). `?scenario=` picks:
 * happy, kiwi (a source that did not answer), edge (deadlines due soon, past, "Da prenotare
 * subito", links outside the allowlist, missing dates), fetch (the Trip read after a delay),
 * failed (the Trip could not be read). `?plan=<id>` shows a plan of the running backend instead,
 * read with lib/api, and PlanView reads its Trip itself. The preview reads the query in the
 * browser, so the page holds no request data and prerenders.
 */
export default function PlanPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <PlanPreview />;
}
