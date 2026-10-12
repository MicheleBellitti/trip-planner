"use client";

import { useEffect } from "react";

import { TopBar } from "@/components/live/top-bar";
import { StateFact, StatePanel } from "@/components/states/state-panel";
import { Button, LinkButton } from "@/components/ui/button";

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
      <TopBar />
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
              <LinkButton href="/" variant="quiet" icon="arrow-left">
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
