import type { ReactNode } from "react";

import { cx } from "@/components/ui/cx";
import { formatDateTime, formatUsd } from "@/lib/format";
import type { EvalRunDetail } from "@/lib/schemas/api";

import {
  formatJudgeMean,
  formatRunCost,
  formatSeconds,
  profileLabel,
  runDelta,
  runVerdictExplanation,
  runSeconds,
  runVerdict,
  shortSha,
  type RunDelta,
} from "./eval-model";
import { DeltaNote } from "./delta";
import { Sha, WorkflowLink } from "./external-link";
import { RunVerdictPill } from "./marks";

/** A figure with its caption above, in the page's facts grid, and how it moved since the run
 * before when there is one. */
export function Fact({
  label,
  children,
  note,
  delta = null,
}: {
  label: string;
  children: ReactNode;
  note?: ReactNode;
  delta?: RunDelta | null;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-micro text-ink-2">{label}</dt>
      <dd className="mt-0.5 font-cond text-title font-semibold text-ink">{children}</dd>
      <DeltaNote delta={delta} />
      {note ? <dd className="mt-0.5 text-micro text-ink-2">{note}</dd> : null}
    </div>
  );
}

/** Under the total: what a plan cost on average, beside the estimate (both per plan, so they
 * compare): "0,58 $ a piano, stima 0,55 $". */
function costNote(run: EvalRunDetail): string | undefined {
  const perPlan = run.requests_total > 0 ? formatRunCost(Math.round(run.total_cost_cents / run.requests_total)) : null;
  const estimate = run.results.estimate?.cost_cents;
  const estimated = estimate != null ? `stima ${formatUsd(estimate)}` : null;
  if (perPlan && estimated) return `${perPlan} a piano, ${estimated}`;
  return perPlan ? `${perPlan} a piano` : (estimated ?? undefined);
}

/**
 * The top of a run's page: the title (when it started), the line of facts that identify it (commit,
 * roster, how long it took, the CI run), then the verdict in a word and a glyph with what it
 * means, and the figures of the whole run, each with how it moved since the run before it.
 */
export function RunHeader({ run, className }: { run: EvalRunDetail; className?: string }) {
  const verdict = runVerdict(run);
  const sha = shortSha(run.git_sha);
  const took = formatSeconds(runSeconds(run.started_at, run.finished_at));
  const judge = run.results.judge;
  const mean = formatJudgeMean(run.judge_mean);
  const previous = run.previous_run;
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
        <RunVerdictPill verdict={verdict} />
        <p className="mt-2 max-w-prose text-small text-ink-2">{runVerdictExplanation(verdict, run.comparison)}</p>
        <dl
          className={cx(
            "mt-4 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-rule pt-4",
            "sm:grid-cols-3 lg:grid-cols-6",
          )}
        >
          <Fact label="Piani accettati" delta={runDelta("accepted", run, previous)}>
            {run.requests_accepted}/{run.requests_total}
          </Fact>
          <Fact label="Richieste senza blocchi" delta={runDelta("checks", run, previous)}>
            {run.checks_passed}/{run.requests_total}
          </Fact>
          <Fact label="Costo" delta={runDelta("cost", run, previous)} note={costNote(run)}>
            {formatRunCost(run.total_cost_cents)}
          </Fact>
          <Fact label="Ricerche web">{run.web_search_requests}</Fact>
          <Fact label="Voto medio" delta={runDelta("judge", run, previous)} note={mean ? "su 5" : undefined}>
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
        {previous ? (
          <p className="mt-3 text-micro text-ink-2">
            Variazioni rispetto alla valutazione precedente ({formatDateTime(previous.started_at)}).
          </p>
        ) : null}
      </div>
    </header>
  );
}
