"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { API_ERROR_MESSAGES, ApiError, MonthlyLimitError } from "@/lib/api";
import { formatUsd } from "@/lib/format";

import { StateFact, StatePanel } from "./state-panel";

interface BudgetPausedPanelProps {
  costCents: number | null;
  budgetCents: number | null;
  /** POST /plans/{id}/continue. Throws the client's errors (a 429 is a MonthlyLimitError). */
  onContinue: () => Promise<void>;
}

interface Failure {
  title: string;
  message: string;
  /** The monthly limit: asking again cannot help until next month. */
  final: boolean;
}

function failureOf(error: unknown): Failure {
  if (error instanceof MonthlyLimitError) {
    const figures =
      error.spentCents !== null && error.limitCents !== null
        ? `Questo mese sono già stati spesi ${formatUsd(error.spentCents)} su ${formatUsd(error.limitCents)}: `
        : "Questo mese il limite di spesa è raggiunto: ";
    return {
      title: "Limite mensile raggiunto",
      message: `${figures}il budget non si può aumentare fino al mese prossimo. Il piano resta in pausa e puoi interromperlo.`,
      final: true,
    };
  }
  const message = error instanceof ApiError ? error.message : API_ERROR_MESSAGES.unknown;
  return { title: "Il piano non è ripartito", message, final: false };
}

/**
 * `budget_paused`: the session spent its budget and the agents stopped where they were. Says how
 * much was spent and offers "Continua con 2 $ in più" (the one primary action of the view). A
 * 429 means the month's limit is reached: the button stays off and the plan can only be
 * interrupted.
 */
export function BudgetPausedPanel({ costCents, budgetCents, onContinue }: BudgetPausedPanelProps) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);

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

  return (
    <StatePanel
      icon="pause-circle"
      title="Budget della sessione esaurito"
      headingId="state-budget"
      footer={
        failure ? (
          <Notice tone="error" role="alert" title={failure.title}>
            {failure.message}
          </Notice>
        ) : null
      }
      actions={
        <Button variant="primary" icon="play" busy={busy} disabled={failure?.final} onClick={() => void resume()}>
          Continua con 2 $ in più
        </Button>
      }
    >
      <StateFact label="Cosa è successo">
        La sessione ha speso {spent}
        {budget ? ` su un budget di ${budget}` : null}: gli agenti si sono fermati dove erano.
      </StateFact>
      <StateFact label="Cosa è stato salvato">
        Il lavoro fatto finora resta qui sotto, corsia per corsia, e gli agenti riprendono da lì.
      </StateFact>
      <StateFact label="Cosa puoi fare">
        Aggiungi 2 $ al budget della sessione per farli continuare, oppure interrompi il piano.
      </StateFact>
    </StatePanel>
  );
}
