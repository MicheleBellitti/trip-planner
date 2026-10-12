"use client";

import { useEffect } from "react";

import { SiteHeader } from "@/components/home/site-header";
import { StateFact, StatePanel } from "@/components/states/state-panel";
import { Button, LinkButton } from "@/components/ui/button";

/** Something broke while drawing the run page (a bug, not a missing run: that has its own panel).
 * Says so, reassures that the stored results are safe, and offers to try again or go back. */
export default function EvalRunError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <>
      <SiteHeader current="evals" />
      <main className="mx-auto max-w-page px-4 pt-2 lg:px-7">
        <StatePanel
          icon="warning"
          title="La pagina della valutazione si è interrotta"
          headingId="valutazione-errore"
          actions={
            <>
              <Button variant="primary" icon="arrows-clockwise" onClick={() => retry()}>
                Riprova
              </Button>
              <LinkButton href="/evals" variant="quiet" icon="arrow-left">
                Torna alle valutazioni
              </LinkButton>
            </>
          }
        >
          <StateFact label="Cosa è successo">Qualcosa è andato storto nel mostrare questa pagina.</StateFact>
          <StateFact label="Cosa è stato salvato">I risultati della valutazione sono al sicuro sul planner.</StateFact>
          <StateFact label="Cosa puoi fare">Riprova, oppure torna all&apos;elenco.</StateFact>
        </StatePanel>
      </main>
    </>
  );
}
