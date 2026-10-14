import type { Metadata } from "next";
import { Suspense } from "react";

import { AppHeader } from "@/components/nav/app-header";
import { EvalDashboard } from "@/components/evals/eval-dashboard";
import { parsePage } from "@/components/evals/eval-model";
import { EvalRunList, EvalRunListPlaceholder } from "@/components/evals/eval-run-list";

export const metadata: Metadata = { title: "Valutazioni" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** "/evals": the eval history. The dashboard (the newest run, the trends), then every run, ten a
 * page (`?pagina=N`). Both are fetched in the browser, which carries the TripTracker cookie, like
 * the plans; only the page number is read on the server. */
export default function EvalsPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <>
      <AppHeader current="evals" />
      <main className="mx-auto max-w-page px-4 pt-6 pb-16 lg:px-7 lg:pt-8">
        <h1 className="font-cond text-display font-semibold lg:text-display-lg">Valutazioni</h1>
        <p className="mt-1.5 max-w-prose text-small text-ink-2">
          Le richieste di riferimento girano a ogni modifica di agenti, prompt o skill: qui l&apos;esito di ogni giro.
        </p>
        <div className="mt-5 grid max-w-[72rem] gap-9 lg:mt-6">
          <EvalDashboard />
          <Suspense fallback={<EvalRunListPlaceholder />}>
            <PagedList searchParams={searchParams} />
          </Suspense>
        </div>
      </main>
    </>
  );
}

/** Reads `?pagina=` at request time; anything that is not a page number is the first page. */
async function PagedList({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  return <EvalRunList page={parsePage(params.pagina)} />;
}
