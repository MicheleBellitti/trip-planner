import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AuthHeader } from "@/components/auth/auth-header";
import { LoginForm } from "@/components/auth/login-form";
import { Skeleton } from "@/components/ui/skeleton";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { auth, authConfig } from "@/lib/auth";
import { safeReturnTo } from "@/lib/return-to";

export const metadata: Metadata = { title: "Accedi", robots: { index: false } };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** "/login": the app's own sign-in (lib/auth.ts). A signed-in visitor is sent straight back to
 * `returnTo` (lib/api.ts put the interrupted page there), everyone else gets the form. */
export default function LoginPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <>
      <AuthHeader />
      <main className="mx-auto max-w-page px-4 pt-8 pb-16 lg:px-7 lg:pt-14">
        <div className="mx-auto max-w-[26rem]">
          <h1 className="font-cond text-display font-semibold lg:text-display-lg">Accedi</h1>
          <p className="mt-1.5 max-w-prose text-small text-ink-2">
            I tuoi piani ti aspettano: voli, alloggio, attività e spostamenti, con le date entro cui prenotare.
          </p>
          <div className="mt-7">
            <Suspense fallback={<FormPlaceholder />}>
              <Gate searchParams={searchParams} />
            </Suspense>
          </div>
        </div>
      </main>
    </>
  );
}

function first(value: string | string[] | undefined): string | null {
  const chosen = Array.isArray(value) ? value[0] : value;
  return chosen?.trim() ? chosen : null;
}

/** Reads the query and the cookie at request time (hence inside the Suspense boundary). */
async function Gate({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const returnTo = first(params.returnTo);
  const errorCode = first(params.error);
  let signedIn = false;
  if (auth) {
    try {
      signedIn = (await auth.api.getSession({ headers: await headers() })) !== null;
    } catch (error) {
      // The database is unreachable: the form still renders, and the submit says what failed.
      console.error("[auth] get-session failed on /login", error instanceof Error ? error.message : error);
    }
  }
  if (signedIn && authConfig) redirect(safeReturnTo(returnTo, authConfig.baseUrl));
  return (
    <LoginForm
      returnTo={returnTo}
      errorCode={errorCode}
      configured={auth !== null}
      googleEnabled={authConfig?.google != null}
    />
  );
}

function FormPlaceholder() {
  return (
    <div aria-busy="true" className="grid gap-4">
      <VisuallyHidden>Carico il modulo…</VisuallyHidden>
      <div className="grid gap-2">
        <Skeleton className="w-16" />
        <Skeleton className="h-11 w-full" />
      </div>
      <Skeleton className="h-10 w-40 rounded-full" />
    </div>
  );
}
