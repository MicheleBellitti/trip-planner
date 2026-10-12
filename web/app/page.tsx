import type { Metadata } from "next";

import { PlanList } from "@/components/home/plan-list";
import { SiteHeader } from "@/components/home/site-header";
import { LinkButton } from "@/components/ui/button";
import { BRAND_NAME } from "@/lib/brand";

/** Absolute: the root layout's "%s · Atlas" template skips the page of its own segment. */
export const metadata: Metadata = { title: { absolute: `I tuoi piani · ${BRAND_NAME}` } };

/** "/": the latest plans with status, cost and date, and "Nuovo piano" as the one primary
 * action. The list is fetched in the browser, which carries the TripTracker cookie. */
export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-page px-4 pt-6 pb-16 lg:px-7 lg:pt-8">
        <div className="flex max-w-[64rem] flex-wrap items-center justify-between gap-x-4 gap-y-3">
          <h1 className="font-cond text-display font-semibold lg:text-display-lg">I tuoi piani</h1>
          <LinkButton href="/new" variant="primary" icon="plus">
            Nuovo piano
          </LinkButton>
        </div>
        {/* The list keeps its 64 rem; from 1280 px the featured plan fills the column beside it. */}
        <PlanList className="mt-5 lg:mt-6" />
      </main>
    </>
  );
}
