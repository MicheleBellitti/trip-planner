import type { ReactNode } from "react";

import { cx } from "@/components/ui/cx";
import { formatDateTime, formatUsd } from "@/lib/format";
import type { EvalRunDetail } from "@/lib/schemas/api";

import {
  formatJudgeMean,
  formatRunCost,
  formatSeconds,
  profileLabel,
  runVerdictExplanation,
  runSeconds,
  runVerdict,
  shortSha,
} from "./eval-model";
import { Sha, WorkflowLink } from "./external-link";
import { RunVerdictBadge } from "./marks";

/** A figure with its caption above, in the page's facts grid. */
export function Fact({ label, children, note }: { label: string; children: ReactNode; note?: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-micro text-ink-2">{label}</dt>
      <dd className="mt-0.5 font-cond text-title font-semibold text-ink">{children}</dd>
      {note ? <dd className="mt-0.5 text-micro text-ink-2">{note}</dd> : null}
    </div>
  );
}

/**
 * The top of a run's page: the title (when it started), the line of facts that identify it (commit,
 * roster, how long it took, the CI run), then the verdict in a word and a glyph with what it
 * means, and the figures of the whole run.
 */
export function RunHeader({ run, className }: { run: EvalRunDetail; className?: string }) {
  const verdict = runVerdict(run);
  const sha = shortSha(run.git_sha);
  const took = formatSeconds(runSeconds(run.started_at, run.finished_at));
  const estimate = run.results.estimate;
  const judge = run.results.judge;
  const mean = formatJudgeMean(run.judge_mean);
  return (
    <header className={className}>
      <h1 className="font-cond text-display font-semibold lg:text-display-lg">
        <time dateTime={run.started_at}>Valutazione del {formatDateTime(run.started_at)}</time>
      </h1>
      <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-small text-ink-2">
        <Sha sha={run.git_sha} short={sha} className="text-ink" />
        <span>{profileLabel(run.profile)}</span>
        {took ? <span>{took}</span> : null}
        <WorkflowLink href={run.workflow_run_url} />
      </p>

      <div className="mt-5 rounded-md border border-rule bg-surface px-4 py-4 lg:px-5">
        <RunVerdictBadge verdict={verdict} size="lg" />
        <p className="mt-1 max-w-prose text-small text-ink-2">{runVerdictExplanation(verdict, run.comparison)}</p>
        <dl
          className={cx(
            "mt-4 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-rule pt-4",
            "sm:grid-cols-3 lg:grid-cols-6",
          )}
        >
          <Fact label="Piani accettati">
            {run.requests_accepted}/{run.requests_total}
          </Fact>
          <Fact label="Richieste senza blocchi">
            {run.checks_passed}/{run.requests_total}
          </Fact>
          <Fact
            label="Costo"
            note={
              estimate?.cost_cents != null && run.requests_total > 0
                ? `stima ${formatUsd(estimate.cost_cents)} a piano`
                : undefined
            }
          >
            {formatRunCost(run.total_cost_cents)}
          </Fact>
          <Fact label="Ricerche web">{run.web_search_requests}</Fact>
          <Fact label="Voto medio" note={mean ? "su 5" : undefined}>
            {mean ?? <span className="text-ink-2">nessuno</span>}
          </Fact>
          <Fact
            label="Giudice"
            note={
              judge?.enabled === false
                ? "spento in questa run"
                : judge?.spent_cents != null
                  ? `${formatUsd(judge.spent_cents)} spesi${judge.cap_cents != null ? ` su ${formatUsd(judge.cap_cents)}` : ""}`
                  : undefined
            }
          >
            <span lang="en" className="text-small break-words">
              {judge?.model ?? "non indicato"}
            </span>
          </Fact>
        </dl>
      </div>
    </header>
  );
}
