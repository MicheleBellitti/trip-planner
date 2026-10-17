"use client";

/**
 * The top of "/evals": how the evals are going, before the list of every run. The newest run
 * first: its verdict on its wash and what it means, why it stopped when it did (its first blocking
 * findings, each linked to its request), its four figures with how each moved since the run
 * before (a sign, and green or red for good or bad news). Then "Andamento" over the twenty newest
 * runs: the verdicts on their own "Esito" line, and three figures (the judge's mean, the cost per
 * plan, the accepted plans) with plain ink stations, read against the baseline when there is one.
 * The charts wait for a third run: a trend of two points says nothing.
 *
 * It fetches its own twenty runs (GET /evals/runs?limit=20), apart from the list's pages, so
 * paging the list never redraws it. Before the first run it draws nothing: the list below is the
 * invitation.
 */

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { Button, LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { api, API_ERROR_MESSAGES, ApiError, UnauthorizedError } from "@/lib/api";
import { formatCreated, formatDateTime, formatUsd } from "@/lib/format";
import type { EvalRunSummary } from "@/lib/schemas/api";

import {
  formatJudgeMean,
  formatRunCost,
  profileLabel,
  requestAnchor,
  ruleLabel,
  runDelta,
  runVerdict,
  runVerdictExplanation,
  shortSha,
  TREND_RUNS,
  trendDomain,
  trendReference,
  trendSeries,
  verdictSeries,
  type RunDelta,
  type RunMetric,
} from "./eval-model";
import { DeltaNote } from "./delta";
import { Sha } from "./external-link";
import { RunVerdictPill } from "./marks";
import { TrendChart } from "./trend-chart";
import { evalRunPath } from "@/lib/page-paths";

type DashboardState =
  | { kind: "loading" }
  | { kind: "ready"; runs: EvalRunSummary[]; openedAt: number }
  | { kind: "error"; message: string };

/** A trend needs this many runs before it is drawn. */
const MIN_TREND_RUNS = 3;

export function EvalDashboard({ className }: { className?: string }) {
  const [state, setState] = useState<DashboardState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .listEvalRuns({ limit: TREND_RUNS, signal: controller.signal })
      .then(({ runs }) => setState({ kind: "ready", runs, openedAt: Date.now() }))
      .catch((error: unknown) => {
        // 401: the browser is on its way to TripTracker's login; keep the placeholder.
        if (controller.signal.aborted || error instanceof UnauthorizedError) return;
        setState({ kind: "error", message: error instanceof ApiError ? error.message : API_ERROR_MESSAGES.unknown });
      });
    return () => controller.abort();
  }, [attempt]);

  if (state.kind === "loading") return <DashboardSkeleton className={className} />;

  if (state.kind === "error") {
    return (
      <Notice
        tone="error"
        title="Il riepilogo non si è caricato"
        className={className}
        action={
          <Button
            size="sm"
            variant="quiet"
            icon="arrows-clockwise"
            onClick={() => {
              setState({ kind: "loading" });
              setAttempt((value) => value + 1);
            }}
          >
            Riprova
          </Button>
        }
      >
        {state.message}
      </Notice>
    );
  }

  const [latest, previous] = state.runs;
  if (!latest) return null;

  return (
    <div className={cx("grid gap-4", className)}>
      <LatestRun run={latest} previous={previous ?? null} openedAt={state.openedAt} />
      <Trends runs={state.runs} openedAt={state.openedAt} />
    </div>
  );
}

function LatestRun({ run, previous, openedAt }: { run: EvalRunSummary; previous: EvalRunSummary | null; openedAt: number }) {
  const verdict = runVerdict(run);
  const mean = formatJudgeMean(run.judge_mean);
  return (
    // One grid: the answer reads first; the way in comes last in the markup, so on the phone it
    // follows the figures, and from 640 px it moves up beside the title.
    <section
      aria-labelledby="ultimo-collaudo"
      className="grid grid-cols-1 rounded-md border border-rule bg-surface px-4 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-4 lg:px-5"
    >
      <div className="min-w-0 sm:col-start-1 sm:row-start-1">
        <h2 id="ultimo-collaudo" className="font-cond text-heading font-semibold">
          Ultimo collaudo
        </h2>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-meta text-ink-2">
          <time dateTime={run.started_at} title={formatDateTime(run.started_at)}>
            {formatCreated(run.started_at, openedAt)}
          </time>
          <Sha sha={run.git_sha} short={shortSha(run.git_sha)} />
          <span>{profileLabel(run.profile)}</span>
        </p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 sm:col-span-2">
        <RunVerdictPill verdict={verdict} />
        <p className="min-w-0 flex-1 basis-64 text-small text-ink-2">{runVerdictExplanation(verdict, null)}</p>
      </div>
      <Reasons run={run} />

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-rule pt-4 sm:col-span-2 lg:grid-cols-4">
        <Figure label="Piani accettati" delta={runDelta("accepted", run, previous)}>
          {run.requests_accepted}/{run.requests_total}
        </Figure>
        <Figure label="Richieste senza blocchi" delta={runDelta("checks", run, previous)}>
          {run.checks_passed}/{run.requests_total}
        </Figure>
        <Figure label="Voto medio" delta={runDelta("judge", run, previous)}>
          {mean ?? <span className="text-ink-2">nessuno</span>}
        </Figure>
        <Figure label="Costo" delta={runDelta("cost", run, previous)}>
          {formatRunCost(run.total_cost_cents)}
        </Figure>
      </dl>
      {previous ? (
        <p className="mt-3 text-micro text-ink-2 sm:col-span-2">
          Variazioni rispetto al collaudo precedente (
          {formatCreated(previous.started_at, openedAt).toLocaleLowerCase("it")}).
        </p>
      ) : null}

      <LinkButton
        href={evalRunPath(run.id)}
        size="sm"
        className="mt-4 justify-self-start sm:col-start-2 sm:row-start-1 sm:mt-0 sm:self-start"
      >
        Apri il collaudo
      </LinkButton>
    </section>
  );
}

/** How many of a run's blocking findings the panel names; the rest are behind the run's page. */
const SHOWN_REASONS = 2;

/** Why a run stopped, in the panel: its first blocking findings (the rule in Italian, the request
 * it is about, linked to its open row, and compare.py's own sentence), so "can I merge?" is
 * answered without opening the run. */
function Reasons({ run }: { run: EvalRunSummary }) {
  const findings = run.blocking_findings;
  if (findings.length === 0) return null;
  const rest = findings.length - SHOWN_REASONS;
  return (
    <div className="mt-3 sm:col-span-2">
      <ul aria-label="Perché si è fermato" className="grid gap-2.5">
        {findings.slice(0, SHOWN_REASONS).map((finding, index) => (
          <li key={index} className="grid grid-cols-[1rem_minmax(0,1fr)] gap-x-2">
            <Icon name="x-circle" size={15} className="mt-[3px] text-error" />
            <div className="min-w-0">
              <p className="flex flex-wrap items-baseline gap-x-2 text-small">
                <span className="font-semibold text-error">{ruleLabel(finding.rule)}</span>
                {finding.request_id ? (
                  <Link
                    href={`${evalRunPath(run.id)}#${requestAnchor(finding.request_id)}`}
                    className="font-medium text-ink underline-offset-[0.2em] hover:underline"
                  >
                    {finding.request_title ?? finding.request_id}
                  </Link>
                ) : null}
              </p>
              <p lang="en" className="mt-0.5 max-w-prose text-meta break-words text-ink-2">
                {finding.message}
              </p>
            </div>
          </li>
        ))}
      </ul>
      {rest > 0 ? (
        <p className="mt-1.5 text-meta">
          <Link
            href={`${evalRunPath(run.id)}#confronto`}
            className="text-ink-2 underline underline-offset-[0.2em] hover:text-ink"
          >
            {rest === 1 ? "Un altro motivo nel collaudo" : `Altri ${rest} motivi nel collaudo`}
          </Link>
        </p>
      ) : null}
    </div>
  );
}

/** A figure of the newest run, its caption above and, under it, how it moved since the run before. */
function Figure({ label, delta, children }: { label: string; delta: RunDelta | null; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-micro text-ink-2">{label}</dt>
      <dd className="mt-0.5 font-cond text-title font-semibold text-ink">{children}</dd>
      <DeltaNote delta={delta} />
    </div>
  );
}

const CHARTS: { metric: RunMetric; title: string; empty: string; tick: (value: number) => string }[] = [
  { metric: "judge", title: "Voto medio", empty: "nessun voto", tick: (value) => `${value}` },
  { metric: "cost_per_plan", title: "Costo a piano", empty: "non registrato", tick: (value) => formatUsd(value) },
  { metric: "accepted", title: "Piani accettati", empty: "nessuno", tick: (value) => `${value}` },
];

/** "Andamento": the verdicts on their own line across the card, then the three figures side by
 * side from 1080 px (stacked on the phone), one card with hairlines between them (not four cards).
 * Each figure is read against the baseline when there is one. */
function Trends({ runs, openedAt }: { runs: EvalRunSummary[]; openedAt: number }) {
  const recent = runs.slice(0, TREND_RUNS);
  const count = recent.length;
  return (
    <section aria-labelledby="andamento">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h2 id="andamento" className="font-cond text-heading font-semibold">
          Andamento
        </h2>
        {count >= MIN_TREND_RUNS ? <p className="text-meta text-ink-2">ultimi {count} collaudi</p> : null}
      </div>
      {count >= MIN_TREND_RUNS ? (
        <div className="mt-2 rounded-md border border-rule bg-surface">
          <TrendChart kind="verdict" title="Esito" points={verdictSeries(recent)} openedAt={openedAt} />
          <div className="grid divide-y divide-rule border-t border-rule lg:grid-cols-3 lg:divide-x lg:divide-y-0">
            {CHARTS.map((chart) => {
              const reference = trendReference(recent, chart.metric);
              return (
                <TrendChart
                  key={chart.metric}
                  title={chart.title}
                  points={trendSeries(recent, chart.metric)}
                  domain={trendDomain(recent, chart.metric, reference?.value ?? null)}
                  tick={chart.tick}
                  empty={chart.empty}
                  reference={reference}
                  openedAt={openedAt}
                />
              );
            })}
          </div>
        </div>
      ) : (
        <p className="mt-1.5 max-w-prose text-small text-ink-2">L&apos;andamento compare dal terzo collaudo.</p>
      )}
    </section>
  );
}

function DashboardSkeleton({ className }: { className?: string }) {
  return (
    <div aria-busy="true" className={cx("grid gap-4", className)}>
      <VisuallyHidden>Carico il riepilogo…</VisuallyHidden>
      <div className="rounded-md border border-rule bg-surface px-4 py-4 lg:px-5">
        <Skeleton className="w-44 text-heading" />
        <Skeleton className="mt-2 w-56" />
        <Skeleton className="mt-4 w-32 text-title" />
        <div className="mt-4 grid grid-cols-2 gap-4 border-t border-rule pt-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((cell) => (
            <div key={cell}>
              <Skeleton className="w-24" />
              <Skeleton className="mt-1.5 w-16 text-title" />
            </div>
          ))}
        </div>
      </div>
      {/* "Andamento" in its final shape: the Esito line, then three charts of their real height. */}
      <div>
        <Skeleton className="w-36 text-heading" />
        <div className="mt-2 rounded-md border border-rule bg-surface">
          <div className="h-[6.75rem] px-4 py-4 lg:px-5">
            <Skeleton className="w-14" />
          </div>
          <div className="grid divide-y divide-rule border-t border-rule lg:grid-cols-3 lg:divide-x lg:divide-y-0">
            {[0, 1, 2].map((chart) => (
              <div key={chart} className="h-[10.75rem] px-4 py-4 lg:h-[11.75rem] lg:px-5">
                <Skeleton className="w-24" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
