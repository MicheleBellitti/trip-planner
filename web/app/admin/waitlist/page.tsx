import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { WaitlistAdmin } from "@/components/admin/waitlist-admin";
import { AppHeader } from "@/components/nav/app-header";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { ROUTES } from "@/lib/routes";
import { currentCaller, type Caller } from "@/lib/server/admin";
import { readAuthConfig } from "@/lib/server/auth-config";
import { getPool } from "@/lib/server/db";
import { listWaitlist } from "@/lib/server/waitlist";

export const metadata: Metadata = { title: "Inviti", robots: { index: false } };

/**
 * "/admin/waitlist": the requests and the invitations, for the users who manage the planner. The
 * backend says who that is (`GET /me`, lib/server/admin.ts): signed out goes to the login and
 * comes back here, anyone else gets the not-found page (the header never showed them the way in;
 * it streams inside the shell, so the status stays 200). The rows are read at request time,
 * inside the Suspense boundary.
 */
export default function InvitesPage() {
  return (
    <>
      <AppHeader current="invites" />
      <main className="mx-auto max-w-page px-4 pt-6 pb-16 lg:px-7 lg:pt-8">
        <h1 className="font-cond text-display font-semibold lg:text-display-lg">Inviti</h1>
        <p className="mt-1.5 max-w-prose text-small text-ink-2">
          Chi ha chiesto di entrare e chi può già farlo. Un invito manda un&apos;email con la pagina di accesso.
        </p>
        <div className="mt-5 lg:mt-6">
          <Suspense fallback={<Placeholder />}>
            <Gate />
          </Suspense>
        </div>
      </main>
    </>
  );
}

async function Gate() {
  let caller: Caller;
  try {
    caller = await currentCaller();
  } catch (error) {
    console.error("[waitlist] admin check failed", error instanceof Error ? error.message : error);
    return (
      <Notice tone="error" title="Non riesco a verificare chi sei.">
        Il planner non ha risposto. Ricarica la pagina tra poco.
      </Notice>
    );
  }
  if (!caller) redirect(`${ROUTES.login}?returnTo=${encodeURIComponent(ROUTES.invites)}`);
  if (!caller.isAdmin) notFound();
  const config = readAuthConfig();
  if (!config) {
    return (
      <Notice tone="warning" title="Gli account non sono configurati su questo server.">
        Senza il loro database non c&apos;è una lista da gestire.
      </Notice>
    );
  }
  const rows = await listWaitlist(getPool(config.databaseUrl));
  return <WaitlistAdmin rows={rows} />;
}

/** The add form and a few rows, in their final rhythm, while the request-time part arrives. */
function Placeholder() {
  return (
    <div aria-busy="true" className="grid max-w-[64rem] gap-8">
      <VisuallyHidden>Carico la lista…</VisuallyHidden>
      <div className="grid gap-4">
        <Skeleton className="w-40 text-heading" />
        <Skeleton shape="block" className="h-11 w-full max-w-[26rem]" />
        <Skeleton shape="round" className="h-11 w-full sm:h-10 sm:w-32" />
      </div>
      <div className="grid gap-3">
        <Skeleton className="w-32 text-heading" />
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} shape="block" className="h-14 w-full" />
        ))}
      </div>
    </div>
  );
}
