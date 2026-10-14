import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";

import { AppHeader } from "@/components/nav/app-header";
import { parseDemoScenarios } from "@/components/request/form-model";
import { RequestForm } from "@/components/request/request-form";
import { Icon } from "@/components/ui/icon";
import { Skeleton } from "@/components/ui/skeleton";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { emptyRequestForm, exampleRequestForm, todayInRome } from "@/lib/request-form";
import { ROUTES } from "@/lib/routes";

export const metadata: Metadata = { title: "Nuovo piano" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** "/new": the trip request form (spec, "Il form"). */
export default function NewPlanPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <>
      <AppHeader current="new" />
      <main className="mx-auto max-w-page px-4 pt-5 pb-16 lg:px-7 lg:pt-7">
        <Link
          href={ROUTES.plans}
          className="inline-flex min-h-11 items-center gap-1.5 -my-1.5 rounded-xs text-meta text-ink-2 no-underline hover:text-ink hover:underline"
        >
          <Icon name="arrow-left" size={15} />I tuoi piani
        </Link>
        <h1 className="mt-2 font-cond text-display font-semibold lg:text-display-lg">Nuovo piano</h1>
        <p className="mt-1.5 max-w-prose text-small text-ink-2">
          Descrivi il viaggio. Cinque agenti cercano voli, alloggio, attività e spostamenti mentre li guardi lavorare, e
          alla fine trovi ogni prenotazione con la data entro cui farla.
        </p>
        <div className="mt-7">
          <Suspense fallback={<FormPlaceholder />}>
            <Form searchParams={searchParams} />
          </Suspense>
        </div>
      </main>
    </>
  );
}

/** Reads `?esempio=1` (the home page's invitation) and today's date in Rome, at request time:
 * `connection()` keeps the clock out of any prerender (the first departure is tomorrow). */
async function Form({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  await connection();
  const today = todayInRome();
  return (
    <RequestForm
      today={today}
      initialValues={params.esempio === "1" ? exampleRequestForm(today) : emptyRequestForm()}
      restoreLast={params.esempio !== "1"}
      demoScenarios={parseDemoScenarios(process.env.NEXT_PUBLIC_DEMO_SCENARIOS, process.env.NODE_ENV)}
    />
  );
}

/** The first fields in their final shape while the form arrives. */
function FormPlaceholder() {
  return (
    <div aria-busy="true" className="grid max-w-[38rem] gap-5">
      <VisuallyHidden>Carico il modulo…</VisuallyHidden>
      <Skeleton className="w-28 text-heading" />
      {[0, 1].map((row) => (
        <div key={row} className="grid gap-2">
          <Skeleton className="w-32" />
          <Skeleton shape="block" className="h-11 w-full" />
        </div>
      ))}
    </div>
  );
}
