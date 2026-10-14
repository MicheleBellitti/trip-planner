import type { Metadata } from "next";

import { buttonClasses } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

export const metadata: Metadata = { title: "Pagina non trovata" };

/**
 * An address that leads nowhere (a mistyped link, an old bookmark): says so in the product's
 * language and offers the way back, instead of Next's English default. It is also what the
 * development-only /dev pages answer in production.
 *
 * Server markup only, on purpose: this boundary is referenced by the root layout, so a client
 * component in it (the theme toggle, `next/link`) would ride in the first load of every route
 * (JS budget, README). A plain link is right here: leaving a dead end deserves a full load.
 */
export default function NotFound() {
  return (
    <>
      <header className="border-b border-rule">
        <div className="mx-auto flex min-h-16 max-w-page items-center px-4 py-3 lg:px-7">
          <Wordmark />
        </div>
      </header>
      <main className="mx-auto max-w-page px-4 pt-6 pb-16 lg:px-7 lg:pt-8">
        <h1 className="font-cond text-display font-semibold lg:text-display-lg">Questa pagina non c&apos;è</h1>
        <p className="mt-2 max-w-prose text-small text-ink-2">
          L&apos;indirizzo non porta a nessuna schermata. Controlla il link, oppure riparti dai tuoi piani.
        </p>
        <div className="mt-5">
          {/* A plain <a>, not next/link: see the comment above, no client JS here. */}
          <a href={ROUTES.plans} className={buttonClasses("primary")}>
            <Icon name="arrow-left" size={16} />
            Torna ai piani
          </a>
        </div>
      </main>
    </>
  );
}
