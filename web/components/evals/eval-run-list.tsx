"use client";

/**
 * "/evals": the eval history (GET /evals/runs), drawn like the home page's plans: a 3 px ink rail
 * down the left of the card, each run a station on it with its verdict as the node. Newest first,
 * ten runs a page (`?pagina=N`, RunPager); a new page keeps the old rows, dimmed, until it arrives.
 * A row says when the run started, which commit it measured, which roster, the verdict in a word,
 * how many plans were accepted, what it cost, the judge's mean and the CI run it came from; the
 * whole row opens the run (a stretched link), the GitHub link sits above it.
 *
 * Fetched in the browser, which carries the TripTracker cookie. The clock is read only in the
 * fetch callback, never in render: with Cache Components the route is prerendered.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button, LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { api, API_ERROR_MESSAGES, ApiError, UnauthorizedError } from "@/lib/api";
import { formatCreated, formatDateTime } from "@/lib/format";
import type { EvalRunSummary } from "@/lib/schemas/api";

import {
  acceptedLabel,
  formatJudgeMean,
  formatRunCost,
  PAGE_SIZE,
  pageCount,
  pageHref,
  profileLabel,
  RUN_VERDICT_LABELS,
  runVerdict,
  shortSha,
} from "./eval-model";
import { EvalEmptyInvitation } from "./eval-empty";
import { Sha, WorkflowLink } from "./external-link";
import { RunVerdictGlyph, verdictTone } from "./marks";
import { RunPager } from "./run-pager";
import { evalRunPath } from "@/lib/page-paths";

type ListState =
  | { kind: "loading" }
  /** `page` is the page these rows belong to: while another one loads they stay, dimmed. */
  | { kind: "ready"; page: number; runs: EvalRunSummary[]; total: number | null; openedAt: number }
  | { kind: "error"; message: string };

/** The rail's column: 36 px, so its centre (18 px) is where the rail and every node sit. */
const RAIL_COL = "2.25rem";
/** Phone: rail, content (date over two meta lines), caret. Desktop: rail, date, commit, profile,
 * verdict, accepted plans, cost, judge mean, CI run, caret. */
const ROW_GRID =
  "grid-cols-[2.25rem_minmax(0,1fr)_1rem] " +
  "lg:grid-cols-[2.25rem_minmax(8rem,1.1fr)_4.5rem_5.5rem_7.5rem_minmax(9.5rem,1fr)_4.5rem_3.25rem_8.5rem_1rem]";

export function EvalRunList({ page, className }: { page: number; className?: string }) {
  const [state, setState] = useState<ListState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .listEvalRuns({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, signal: controller.signal })
      .then(({ runs, total }) => setState({ kind: "ready", page, runs, total, openedAt: Date.now() }))
      .catch((error: unknown) => {
        // 401: the browser is on its way to TripTracker's login; keep the placeholder rows.
        if (controller.signal.aborted || error instanceof UnauthorizedError) return;
        setState({ kind: "error", message: error instanceof ApiError ? error.message : API_ERROR_MESSAGES.unknown });
      });
    return () => controller.abort();
  }, [page, attempt]);

  if (state.kind === "loading") return <EvalRunListPlaceholder className={className} />;

  if (state.kind === "error") {
    return (
      <Notice
        tone="error"
        title="I collaudi non si sono caricati"
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

  if (state.runs.length === 0 && state.page === 1) return <EvalEmptyInvitation className={className} />;

  // A backend older than the pages sends no total and ignores the offset: a later page would show
  // the newest runs again under another number, so it says so instead.
  if (state.total === null && state.page > 1) {
    return (
      <Notice
        tone="info"
        title="Le pagine non sono ancora disponibili"
        className={className}
        action={
          <LinkButton href={pageHref(1)} size="sm" variant="quiet" icon="arrow-left">
            Vai alle più recenti
          </LinkButton>
        }
      >
        Il planner non divide ancora i collaudi in pagine: si aggiorna con il prossimo rilascio.
      </Notice>
    );
  }

  if (state.runs.length === 0) {
    const last = pageCount(state.total ?? 0, PAGE_SIZE);
    return (
      <Notice
        tone="info"
        title={`I collaudi finiscono a pagina ${last}`}
        className={className}
        action={
          <LinkButton href={pageHref(last)} size="sm" variant="quiet" icon="arrow-left">
            Vai a pagina {last}
          </LinkButton>
        }
      >
        Questa pagina è oltre l&apos;ultimo collaudo caricato.
      </Notice>
    );
  }

  const stale = state.page !== page;
  const first = (state.page - 1) * PAGE_SIZE + 1;
  const pages = state.total === null ? null : pageCount(state.total, PAGE_SIZE);
  return (
    <section aria-labelledby={LIST_HEADING_ID} className={className}>
      <ListHeading total={state.total} />
      <div
        aria-busy={stale || undefined}
        className={cx(
          "relative overflow-hidden rounded-md border border-rule bg-surface transition-opacity duration-(--duration-hover)",
          stale && "opacity-60",
        )}
      >
        <Rail />
        <div
          aria-hidden="true"
          className={cx("hidden gap-x-4 border-b border-rule py-2 pr-4 text-micro text-ink-2 lg:grid", ROW_GRID)}
        >
          <span />
          <span>Avviata</span>
          <span>Commit</span>
          <span>Profilo</span>
          <span>Esito</span>
          <span>Piani</span>
          <span className="text-right">Costo</span>
          <span className="text-right">Voto</span>
          <span>Esecuzione</span>
        </div>
        <ul className="divide-y divide-rule">
          {state.runs.map((run) => (
            <li key={run.id}>
              <RunRow run={run} openedAt={state.openedAt} />
            </li>
          ))}
        </ul>
      </div>
      {state.total !== null ? (
        <RunPager page={state.page} total={state.total} pageSize={PAGE_SIZE} className="mt-3" />
      ) : null}
      <p className="mt-3 max-w-prose text-meta text-ink-2">
        {pages !== null && pages > 1
          ? `Collaudi da ${first} a ${first + state.runs.length - 1} di ${state.total}. `
          : ""}
        I collaudi arrivano dalla CI dopo ogni run; il voto è la media dei punteggi del giudice, da 1 a 5.
      </p>
    </section>
  );
}

const LIST_HEADING_ID = "tutti-i-collaudi";

/** The list's heading, with how many runs the history holds when the backend says. */
function ListHeading({ total }: { total: number | null }) {
  return (
    <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
      <h2 id={LIST_HEADING_ID} className="font-cond text-heading font-semibold">
        Tutti i collaudi
      </h2>
      {total ? <p className="text-meta text-ink-2">{total === 1 ? "una in tutto" : `${total} in tutto`}</p> : null}
    </div>
  );
}

/** The line itself: 3 px of ink down the card, passing under the nodes. */
function Rail() {
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute inset-y-0 z-[1] w-[3px] bg-ink"
      style={{ left: `calc(${RAIL_COL} / 2 - 1.5px)` }}
    />
  );
}

function RunRow({ run, openedAt }: { run: EvalRunSummary; openedAt: number }) {
  const verdict = runVerdict(run);
  const sha = shortSha(run.git_sha);
  const cost = formatRunCost(run.total_cost_cents);
  const mean = formatJudgeMean(run.judge_mean);
  return (
    <div
      className={cx(
        "group relative grid items-center gap-x-2.5 gap-y-1 py-3.5 pr-4 lg:gap-x-4",
        "transition-[background-color] duration-(--duration-hover) ease-out hover:bg-notice-wash",
        ROW_GRID,
      )}
    >
      {/* The station: the verdict's glyph on a disc that hides the rail behind it. */}
      <span
        aria-hidden="true"
        className={cx(
          "absolute z-[2] grid -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-surface",
          "top-1/2 transition-[background-color] duration-(--duration-hover) ease-out group-hover:bg-notice-wash",
          verdictTone(verdict),
        )}
        style={{ left: `calc(${RAIL_COL} / 2)` }}
      >
        <RunVerdictGlyph verdict={verdict} size={20} />
      </span>

      {/* The run's link: its text is the date, its box is the whole row. */}
      <Link
        href={evalRunPath(run.id)}
        className={cx(
          "col-start-2 row-start-1 min-w-0 font-cond text-title font-semibold text-ink no-underline group-hover:underline",
          "after:absolute after:inset-0 after:content-['']",
          "focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-focus",
        )}
      >
        <time dateTime={run.started_at} title={formatDateTime(run.started_at)}>
          <VisuallyHidden>Collaudo del </VisuallyHidden>
          {formatCreated(run.started_at, openedAt)}
        </time>
      </Link>

      <span className="col-start-2 row-start-2 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-meta lg:contents">
        <span
          className={cx(
            "lg:col-start-5 lg:row-start-1 lg:text-small",
            (verdict === "blocked" || verdict === "passed") && "font-medium",
            verdictTone(verdict),
          )}
        >
          <VisuallyHidden>Esito </VisuallyHidden>
          {RUN_VERDICT_LABELS[verdict]}
        </span>
        <span className="text-ink-2 lg:col-start-6 lg:row-start-1 lg:text-small lg:text-ink">
          {acceptedLabel(run.requests_accepted, run.requests_total)}
        </span>
        <span className="text-ink-2 lg:col-start-7 lg:row-start-1 lg:text-right lg:text-small lg:text-ink">
          <VisuallyHidden>Costo </VisuallyHidden>
          {cost}
        </span>
      </span>

      <span className="col-start-2 row-start-3 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-meta text-ink-2 lg:contents">
        <Sha sha={run.git_sha} short={sha} className="lg:col-start-3 lg:row-start-1 lg:text-small lg:text-ink" />
        <span className="lg:col-start-4 lg:row-start-1 lg:text-small">{profileLabel(run.profile)}</span>
        <span className="lg:col-start-8 lg:row-start-1 lg:text-right lg:text-small lg:text-ink">
          <VisuallyHidden>Voto medio </VisuallyHidden>
          <span className="lg:hidden">{mean ? `voto ${mean}` : "senza voto"}</span>
          <span className="hidden lg:inline">{mean ?? <span className="text-ink-2">nessuno</span>}</span>
        </span>
        {/* Above the stretched link, so it takes its own clicks. */}
        <WorkflowLink
          href={run.workflow_run_url}
          short
          className="relative z-[3] lg:col-start-9 lg:row-start-1 lg:text-small"
        />
      </span>

      <Icon
        name="caret-right"
        size={16}
        className="col-start-3 row-span-3 row-start-1 text-ink-2 lg:col-start-10 lg:row-span-1"
      />
    </div>
  );
}

/** The list's rows in their final shape while the page arrives (also the page's Suspense
 * fallback while it reads `?pagina=`). */
export function EvalRunListPlaceholder({ className }: { className?: string }) {
  return (
    <div aria-busy="true" className={className}>
      <VisuallyHidden>Carico i collaudi…</VisuallyHidden>
      <ListHeading total={null} />
      <div className="relative overflow-hidden rounded-md border border-rule bg-surface">
        <Rail />
        <ul className="divide-y divide-rule">
          {[0, 1, 2, 3].map((row) => (
            <li key={row} className={cx("relative grid items-center gap-x-2.5 gap-y-2 py-3.5 pr-4 lg:gap-x-4", ROW_GRID)}>
              <span
                aria-hidden="true"
                className="absolute top-1/2 z-[2] size-[18px] -translate-x-1/2 -translate-y-1/2 rounded-full border-4 border-rule bg-surface"
                style={{ left: `calc(${RAIL_COL} / 2)` }}
              />
              <Skeleton className={cx("col-start-2 text-title", row === 1 ? "w-2/5" : "w-1/2", "lg:w-3/4")} />
              <Skeleton className="col-start-2 row-start-2 w-48 lg:col-start-5 lg:row-start-1 lg:w-20" />
              <Skeleton className="hidden w-32 lg:col-start-6 lg:row-start-1 lg:block" />
              <Skeleton className="col-start-2 row-start-3 w-36 lg:col-start-3 lg:row-start-1 lg:w-14" />
              <Skeleton className="hidden w-12 justify-self-end lg:col-start-7 lg:row-start-1 lg:block" />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
