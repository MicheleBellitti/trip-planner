import type { Metadata } from "next";

import { PlanList } from "@/components/home/plan-list";
import { AppHeader } from "@/components/nav/app-header";
import { BRAND_NAME } from "@/lib/brand";

/** Absolute: the root layout's "%s · Atlas" template skips the page of its own segment. */
export const metadata: Metadata = { title: { absolute: `I tuoi piani · ${BRAND_NAME}` } };

/** "/plans": the latest plans with status, cost and date; "Nuovo piano" is in the
 * header. The list is fetched in the browser, which carries the session cookie. */
export default function PlansPage() {
  return (
    <>
      <AppHeader current="plans" />
      <main className="mx-auto max-w-page px-4 pt-6 pb-16 lg:px-7 lg:pt-8">
        <h1 className="font-cond text-display font-semibold lg:text-display-lg">I tuoi piani</h1>
        {/* The list keeps its 64 rem; from 1280 px the featured plan fills the column beside it. */}
        <PlanList className="mt-5 lg:mt-6" />
      </main>
    </>
  );
}
