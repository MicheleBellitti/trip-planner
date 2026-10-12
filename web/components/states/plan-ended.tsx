import { LinkButton } from "@/components/ui/button";
import type { IconName } from "@/components/ui/icon";
import { formatUsd } from "@/lib/format";
import { AGENT_LABELS } from "@/lib/plan-events/labels";
import type { AgentName } from "@/lib/schemas/generated/ui-event";

import type { EndedStatus } from "./ended-status";
import { StateFact, StatePanel } from "./state-panel";

export { isEndedStatus, type EndedStatus } from "./ended-status";

interface Copy {
  icon: IconName;
  tone: "neutral" | "error";
  title: string;
  /** When the backend gives no reason. */
  happened: string;
}

const COPY: Record<EndedStatus, Copy> = {
  interrupted: {
    icon: "stop-circle",
    tone: "neutral",
    title: "Piano interrotto",
    happened: "Il piano è stato interrotto prima di essere consegnato.",
  },
  failed: {
    icon: "x-circle",
    tone: "error",
    title: "Piano non riuscito",
    happened: "Il piano si è fermato prima di essere consegnato.",
  },
  blocked: {
    icon: "prohibit",
    tone: "error",
    title: "Piano bloccato",
    happened: "Un agente aspettava una conferma che nessuno può dare, e il piano si è fermato.",
  },
};

/** What a blocked plan was waiting on: the agent and the source of the tool that asked for a
 * permission only a person could give (`findBlocker`, components/live/stations.ts). */
export interface PlanBlocker {
  agent: AgentName;
  source: string | null;
}

/** "L'agente Voli aspettava il permesso per usare lastminute.com, che questa app non può dare.
 * Il piano non può continuare." */
export function blockedReason({ agent, source }: PlanBlocker): string {
  const what = source ? `il permesso per usare ${source}` : "un permesso";
  return `L'agente ${AGENT_LABELS[agent]} aspettava ${what}, che questa app non può dare. Il piano non può continuare.`;
}

interface PlanEndedPanelProps {
  status: EndedStatus;
  /** For `blocked`: who was waiting, and for what. Named instead of the backend's general line. */
  blocker?: PlanBlocker | null;
  /** The backend's Italian reason (`failure_reason`), e.g. "Interrotto da te.". */
  failureReason: string | null;
  costCents: number | null;
}

/**
 * `interrupted`, `failed` and `blocked`: what happened (the backend's reason), what was saved
 * (the agents' work stays on the page, lane by lane, and what it cost) and what can be done (a
 * new plan starts from zero with a new session budget). Nothing here can resume the plan: the
 * session is closed.
 */
export function PlanEndedPanel({ status, blocker = null, failureReason, costCents }: PlanEndedPanelProps) {
  const copy = COPY[status];
  const cost = costCents === null ? null : formatUsd(costCents);
  return (
    <StatePanel
      icon={copy.icon}
      tone={copy.tone}
      title={copy.title}
      headingId="state-ended"
      actions={
        <>
          <LinkButton href="/new" variant="primary" icon="plus">
            Crea un nuovo piano
          </LinkButton>
          <LinkButton href="/" variant="quiet" icon="arrow-left">
            Torna ai piani
          </LinkButton>
        </>
      }
    >
      <StateFact label="Cosa è successo">
        {status === "blocked" && blocker ? blockedReason(blocker) : (failureReason ?? copy.happened)}
        {status === "interrupted" ? " Gli agenti hanno chiuso il passo che avevano in corso." : null}
      </StateFact>
      <StateFact label="Cosa è stato salvato">
        Il lavoro degli agenti resta qui sotto, corsia per corsia: si vede fin dove sono arrivati.
        {cost ? ` Costo della sessione: ${cost}.` : null}
      </StateFact>
      <StateFact label="Cosa puoi fare">
        Crea un nuovo piano: riparte da zero, con un nuovo budget di sessione. Questo non si può riprendere.
      </StateFact>
    </StatePanel>
  );
}
