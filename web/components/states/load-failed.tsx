import { Button, LinkButton } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";
import { ROUTES } from "@/lib/routes";

import { StateFact, StatePanel } from "./state-panel";

/**
 * The plan could not be shown at all: it does not exist (or is someone else's), this account is
 * not allowed, or the planner did not answer. Says so in the backend's words and offers the
 * way on: back to the plans, or try again when trying again can help.
 */
export function PlanLoadFailed({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  if (error.kind === "not_found") {
    return (
      <StatePanel
        icon="compass"
        title="Questo piano non c'è"
        headingId="state-load"
        actions={
          <LinkButton href={ROUTES.plans} variant="primary" icon="arrow-left">
            Torna ai piani
          </LinkButton>
        }
      >
        <StateFact label="Cosa è successo">
          Il link porta a un piano che non esiste o che appartiene a un altro account.
        </StateFact>
        <StateFact label="Cosa puoi fare">Apri un piano dalla lista, oppure creane uno nuovo.</StateFact>
      </StatePanel>
    );
  }
  const retryable = error.kind !== "forbidden";
  return (
    <StatePanel
      icon={error.kind === "network" ? "wifi-slash" : "warning"}
      title="Non riesco a mostrare il piano"
      headingId="state-load"
      actions={
        <>
          {retryable ? (
            <Button variant="primary" icon="arrows-clockwise" onClick={onRetry}>
              Riprova
            </Button>
          ) : null}
          <LinkButton href={ROUTES.plans} variant={retryable ? "quiet" : "primary"} icon="arrow-left">
            Torna ai piani
          </LinkButton>
        </>
      }
    >
      <StateFact label="Cosa è successo">{error.message}</StateFact>
      {retryable ? (
        <StateFact label="Cosa è stato salvato">
          Il piano, se esiste, è al sicuro sul planner: gli agenti lavorano anche senza questa pagina.
        </StateFact>
      ) : null}
    </StatePanel>
  );
}
