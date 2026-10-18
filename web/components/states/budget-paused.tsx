"use client";

import { useState } from "react";

import { Button, LinkButton } from "@/components/ui/button";
import { Notice, type NoticeTone } from "@/components/ui/notice";
import { API_ERROR_MESSAGES, ApiError, MonthlyLimitError, QuotaReachedError } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { useMe } from "@/lib/me";
import { ROUTES } from "@/lib/routes";

import { describeQuotaLimit, describeQuotaRefusal, quotaBlocks } from "../request/failure";

import { StateFact, StatePanel } from "./state-panel";

interface BudgetPausedPanelProps {
  costCents: number | null;
  budgetCents: number | null;
  /** How many times "Continua" raised this plan's budget, and how many times it may
   * (plan detail `continues`, `continues_limit`; a limit of 0 means the backend has no cap). */
  continues?: number;
  continuesLimit?: number;
  /** POST /plans/{id}/continue. Throws the client's errors (a 429 is a MonthlyLimitError or a
   * QuotaReachedError, a 409 continue_limit_reached an ApiError of kind "continue_limit"). */
  onContinue: () => Promise<void>;
}

interface Failure {
  title: string;
  message: string;
  /** A refusal by rule is a warning (nothing failed); anything else is an error (DESIGN.md, Notice). */
  tone: NoticeTone;
  /** A limit: asking again cannot help until next month, or ever for this plan. */
  final: boolean;
}

/** The sentence "Continua" would be a lie without: the plan stays paused and can be interrupted. */
const STAYS_PAUSED = "Il piano resta in pausa e puoi interromperlo.";

function failureOf(error: unknown): Failure {
  if (error instanceof QuotaReachedError) {
    const { title, body } = describeQuotaRefusal(error, "continue");
    return { title, message: `${body} ${STAYS_PAUSED}`, tone: "warning", final: true };
  }
  if (error instanceof ApiError && error.kind === "continue_limit") {
    // The backend's sentence already says what to do (interrupt, or a new plan).
    return { title: "Il budget non si può aumentare ancora", message: error.message, tone: "warning", final: true };
  }
  if (error instanceof MonthlyLimitError) {
    const figures =
      error.spentCents !== null && error.limitCents !== null
        ? `Questo mese il planner ha già impegnato ${formatUsd(error.spentCents)} su ${formatUsd(error.limitCents)}: `
        : "Questo mese il limite di spesa è raggiunto: ";
    return {
      title: "Limite mensile raggiunto",
      message: `${figures}il budget non si può aumentare fino al mese prossimo. ${STAYS_PAUSED}`,
      tone: "warning",
      final: true,
    };
  }
  const message = error instanceof ApiError ? error.message : API_ERROR_MESSAGES.unknown;
  return { title: "Il piano non è ripartito", message, tone: "error", final: false };
}

/**
 * `budget_paused`: the session reached its budget and the agents stopped where they were. Says how
 * much was spent (less than the budget: the next step did not fit in it) and offers "Continua con
 * 2 $ in più", the one primary action of the view. At the cap of "Continua" the plan can only be
 * interrupted (the header's control) or replaced: the panel offers a new plan instead. When GET
 * /me's month says the 2 $ would not fit (the backend's rule, `quotaBlocks(quota, "continue")`) the
 * panel says so before the press and the button stays off; a 429 after the press says the same.
 */
export function BudgetPausedPanel({ costCents, budgetCents, continues = 0, continuesLimit = 0, onContinue }: BudgetPausedPanelProps) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  /** The plan had every "Continua" it may have: no button, the sentence says so. */
  const capped = continuesLimit > 0 && continues >= continuesLimit;
  const me = useMe();
  /** The month would refuse the 2 $ (null for the users exempt from the quota, or while unknown). */
  const standing =
    !capped && me?.quota && quotaBlocks(me.quota, "continue") !== null
      ? describeQuotaLimit("cents", me.quota, "continue")
      : null;
  const notice: Failure | null =
    failure ?? (standing ? { title: standing.title, message: `${standing.body} ${STAYS_PAUSED}`, tone: "warning", final: true } : null);

  async function resume() {
    setBusy(true);
    setFailure(null);
    try {
      await onContinue();
    } catch (error) {
      setFailure(failureOf(error));
    } finally {
      setBusy(false);
    }
  }

  const spent = costCents === null ? "quanto previsto" : formatUsd(costCents);
  const budget = budgetCents === null ? null : formatUsd(budgetCents);
  // The platform pauses before a step that would not fit (the meter then stops short of 100 %), or
  // once the step in progress spent the rest: the sentence says which.
  const reason =
    budget === null
      ? ""
      : costCents !== null && budgetCents !== null && costCents < budgetCents
        ? `: il passo successivo non stava nel budget di ${budget}`
        : `: il budget di ${budget} è finito`;
  const increases = continuesLimit === 1 ? "i suoi 2 $ in più" : `${continuesLimit} volte i suoi 2 $ in più`;

  return (
    <StatePanel
      icon="pause-circle"
      title="Budget della sessione raggiunto"
      headingId="state-budget"
      footer={
        notice ? (
          <Notice tone={notice.tone} role={failure ? "alert" : undefined} title={notice.title}>
            {notice.message}
          </Notice>
        ) : null
      }
      actions={
        capped ? (
          <LinkButton href={ROUTES.newPlan} icon="plus" className="min-h-11 sm:min-h-10">
            Crea un nuovo piano
          </LinkButton>
        ) : (
          <Button
            variant="primary"
            icon="play"
            busy={busy}
            disabled={notice?.final}
            onClick={() => void resume()}
            // 44 px on the phone, 40 px from 640 px (DESIGN.md, Buttons).
            className="min-h-11 sm:min-h-10"
          >
            Continua con 2 $ in più
          </Button>
        )
      }
    >
      <StateFact label="Cosa è successo">
        La sessione ha speso {spent}
        {reason}, e gli agenti si sono fermati dove erano.
      </StateFact>
      <StateFact label="Cosa è stato salvato">
        {capped
          ? "Il lavoro fatto finora resta qui sotto, corsia per corsia."
          : "Il lavoro fatto finora resta qui sotto, corsia per corsia, e con 2 $ in più gli agenti riprendono da lì."}
      </StateFact>
      <StateFact label="Cosa puoi fare">
        {capped
          ? `Questo piano ha già avuto ${increases}: il budget non si può aumentare ancora. Puoi interromperlo con «Interrompi» qui sopra, o creare un nuovo piano.`
          : "Aggiungi 2 $ al budget della sessione per farli continuare, oppure interrompi il piano con «Interrompi» qui sopra."}
      </StateFact>
    </StatePanel>
  );
}
