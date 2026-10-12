import type { Metadata } from "next";

import { SiteHeader } from "@/components/home/site-header";
import { EvalRunList } from "@/components/evals/eval-run-list";

export const metadata: Metadata = { title: "Valutazioni" };

/** "/evals": the eval history, newest run first. The list is fetched in the browser, which
 * carries the TripTracker cookie, like the plans. */
export default function EvalsPage() {
  return (
    <>
      <SiteHeader current="evals" />
      <main className="mx-auto max-w-page px-4 pt-6 pb-16 lg:px-7 lg:pt-8">
        <h1 className="font-cond text-display font-semibold lg:text-display-lg">Valutazioni</h1>
        <p className="mt-1.5 max-w-prose text-small text-ink-2">
          Ogni modifica agli agenti, ai prompt o alle skill fa girare cinque richieste di riferimento. Qui trovi come è
          andata ogni volta: controlli, voti del giudice, costo e confronto con il livello accettato.
        </p>
        <EvalRunList className="mt-5 max-w-[72rem] lg:mt-6" />
      </main>
    </>
  );
}
