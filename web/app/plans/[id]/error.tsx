"use client";

import { useEffect } from "react";

import { StateFact, StatePanel } from "@/components/states/state-panel";
import { Button, LinkButton } from "@/components/ui/button";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/**
 * Something broke while drawing the plan page (a bug, not a plan state: those have their own
 * panels). Says so, reassures that the plan itself is safe on the planner, and offers to try
 * again or go back to the list.
 */
export default function PlanError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <>
      {/* The lockup only, as on not-found: this boundary rides in the plan page's first load, so it
          does not carry the whole header bar (JS budget, README). */}
      <div className="mx-auto flex min-h-14 max-w-page items-center px-4 lg:px-7">
        <Wordmark href={ROUTES.plans} />
      </div>
      <main className="mx-auto max-w-page px-4 pt-2 lg:px-7">
        <StatePanel
          icon="warning"
          title="La pagina del piano si è interrotta"
          headingId="state-page-error"
          actions={
            <>
              <Button variant="primary" icon="arrows-clockwise" onClick={() => retry()}>
                Riprova
              </Button>
              <LinkButton href={ROUTES.plans} variant="quiet" icon="arrow-left">
                Torna ai piani
              </LinkButton>
            </>
          }
        >
          <StateFact label="Cosa è successo">Qualcosa è andato storto nel mostrare questa pagina.</StateFact>
          <StateFact label="Cosa è stato salvato">
            Il piano è al sicuro sul planner: gli agenti lavorano anche senza questa pagina.
          </StateFact>
          <StateFact label="Cosa puoi fare">Riprova: la pagina riparte dall&apos;ultimo stato del piano.</StateFact>
        </StatePanel>
      </main>
    </>
  );
}
