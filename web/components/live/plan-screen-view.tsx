"use client";

/**
 * The plan screen as a view (spec, "Demo": the seam): the live header, the lanes, the plan
 * states and the finished plan, from a reducer state and a detail it is given. Two data sources
 * render it: PlanScreen (the live plan, GET /plans/{id} and the SSE stream) and DemoPlanScreen
 * (a recorded run replayed in the browser). This module never imports an API client, so the demo
 * never evaluates one: what needs the backend arrives as props.
 */

import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";

import type { CoverLoader } from "@/components/plan/cover/cover-store";
import type { PlanHandoff, TripLoader } from "@/components/plan/PlanView";
import { daysCount, titleStatesDates, tripLength } from "@/components/plan/trip-dates";
import { isEndedStatus } from "@/components/states/ended-status";
import { InlineStatus } from "@/components/ui/notice";
import { displayTitle, formatElapsed } from "@/lib/format";
import { AGENTS, PLAN_STATUS_LABELS, type ConnectionStatus } from "@/lib/plan-events/labels";
import { elapsedMs, type PlanLiveState } from "@/lib/plan-events/reducer";
import type { PlanDetail } from "@/lib/schemas/api";

import { AgentLanes, type LaneFollow } from "./agent-lanes";
import { useLiveBaseline } from "./hooks";
import { LiveHeader } from "./live-header";
import { requestSummary } from "./request-summary";
import { RunSection } from "./run-section";
import { buildLaneViews, findBlocker } from "./stations";

/**
 * The finished plan is its own chunk: a running plan never needs it, and it is a fifth of what
 * the page ships (JS budget, README "Measure the JS"). It is fetched when the run is under way
 * (so the arrival is instant) or when the plan is already finished.
 */
export const loadPlanView = () => import("@/components/plan/PlanView");
const PlanView = lazy(() => loadPlanView().then((module) => ({ default: module.PlanView })));

/** The panels of the plan states (paused, ended, not loadable): the same on-demand chunk. */
export const loadPanels = () => import("@/components/states/panels");
const BudgetPausedPanel = lazy(() => loadPanels().then((module) => ({ default: module.BudgetPausedPanel })));
const PlanEndedPanel = lazy(() => loadPanels().then((module) => ({ default: module.PlanEndedPanel })));

/** What the finished plan takes from the data source besides the detail (the demo's cover,
 * handoff and notice). */
export interface PlanViewExtras {
  loadCover?: CoverLoader;
  handoff?: PlanHandoff;
  notice?: ReactNode;
  /** A fixed "now" for the plan's relative dates (the demo's recording date). */
  now?: number;
}

export interface PlanScreenViewProps {
  state: PlanLiveState;
  detail: PlanDetail | null;
  /** The clock the elapsed time and the lanes read: the wall clock (stopped at the last known
   * state while stale) live, the replay's clock in the demo. Null before the first tick. */
  clock: number | null;
  /** The page is not up to date (offline, signed out): the lanes say so. */
  stale: boolean;
  connection: ConnectionStatus;
  /** The bar above the plan: the app header live, the public header in the demo. */
  header: ReactNode;
  /** The control beside the state ("Interrompi" live). */
  action?: ReactNode;
  /** A row of its own in the state group (the demo's bar). */
  bar?: ReactNode;
  /** How a finished plan's cost is named (the demo's recorded run). */
  costLabel?: string;
  /** How a finished plan's duration is named, and the duration to show (the demo's recorded run,
   * not its replay). */
  durationLabel?: string;
  finishedElapsed?: string;
  /** How the phone's open lane follows the work (`show` in the demo). */
  followLanes?: LaneFollow;
  /** The stream's own line under the header (live). */
  streamLine?: ReactNode;
  /** The viewer asked to interrupt and the plan has not stopped yet. */
  interrupting?: boolean;
  /** "Continua" on a plan paused at its cost cap. */
  onContinue?: () => Promise<void>;
  loadTrip?: TripLoader;
  /** The TripTracker trip, when the data source already has it (the demo's fixture). */
  trip?: unknown;
  planView?: PlanViewExtras;
}

export function PlanScreenView({
  state,
  detail,
  clock,
  stale,
  connection,
  header,
  action,
  bar,
  costLabel,
  durationLabel,
  finishedElapsed,
  followLanes,
  streamLine,
  interrupting = false,
  onContinue,
  loadTrip,
  trip,
  planView,
}: PlanScreenViewProps) {
  // The viewer watched the run (the plan was running when the page was up): when it turns ready
  // the plan is an arrival, not a page load (PlanView brings its top into view).
  const [watchedRun, setWatchedRun] = useState(false);
  const views = useMemo(() => buildLaneViews(state), [state]);
  const baseline = useLiveBaseline(connection, state.lastSeq, state.announcement?.id ?? null);

  // A plan-level change a watcher would miss (budget reached, failed, blocked, interrupted) is
  // said once in the live region, next to the lanes' own words. Ready is announced by the focus
  // that moves to the plan, the viewer's own interrupt by the focus that moves to the state.
  const settledForSpeech = baseline.announceAfterId !== null;
  const [seenStatus, setSeenStatus] = useState(state.status);
  const [planNote, setPlanNote] = useState<{ id: number; text: string } | null>(null);
  if (state.status !== seenStatus) {
    const next = state.status;
    setSeenStatus(next);
    if (
      seenStatus !== null &&
      settledForSpeech &&
      next !== null &&
      next !== "ready" &&
      next !== "running" &&
      !(next === "interrupted" && interrupting)
    ) {
      setPlanNote({ id: (planNote?.id ?? 0) + 1, text: `Piano: ${PLAN_STATUS_LABELS[next].toLowerCase()}` });
    }
  }

  const title = displayTitle(detail?.title ?? "Piano");
  const status = state.status;
  const measured = clock === null ? null : formatElapsed(elapsedMs(state, clock));
  const elapsed = status === "ready" && finishedElapsed ? finishedElapsed : measured;
  const ready = state.planReady && detail?.plan ? detail : null;
  // A finished plan sets its total against the budget and states its dates in its own facts, so
  // the header says who travels and from where, and the length when the title has no dates.
  const subtitle = ready?.plan
    ? requestSummary(ready.request, {
        withBudget: false,
        extra: titleStatesDates(title, ready.plan.start_date, ready.plan.end_date)
          ? daysCount(tripLength(ready.plan.start_date, ready.plan.end_date) ?? 0)
          : null,
      })
    : requestSummary(detail?.request);
  const announcement =
    state.announcement && baseline.announceAfterId !== null && state.announcement.id > baseline.announceAfterId
      ? state.announcement
      : null;
  if (status === "running" && !watchedRun) setWatchedRun(true);
  const blocker = status === "blocked" ? findBlocker(state) : null;
  const stationCount = AGENTS.reduce((sum, agent) => sum + views[agent].stations.length, 0);

  const lanes = (
    <AgentLanes
      state={state}
      views={views}
      now={clock}
      freshAfterSeq={baseline.freshAfterSeq}
      stale={stale}
      follow={followLanes}
    />
  );

  return (
    <div className="pb-12">
      {header}
      <LiveHeader
        title={title}
        summary={subtitle}
        status={status}
        interrupting={interrupting && status === "running"}
        elapsed={elapsed}
        costCents={state.costCents}
        budgetCents={state.budgetCents}
        costPending={(status === null || status === "running") && !state.costReported}
        sticky={!ready}
        action={action}
        bar={bar}
        costLabel={costLabel}
        durationLabel={durationLabel}
      />
      {streamLine}
      <main className="mx-auto max-w-page px-4 pt-3 lg:px-7 lg:pt-5">
        {status === "budget_paused" && onContinue ? (
          <Suspense fallback={null}>
            <BudgetPausedPanel costCents={state.costCents} budgetCents={state.budgetCents} onContinue={onContinue} />
          </Suspense>
        ) : null}
        {isEndedStatus(status) ? (
          <Suspense fallback={null}>
            <PlanEndedPanel
              status={status}
              blocker={blocker}
              failureReason={detail?.failure_reason ?? null}
              costCents={state.costCents}
            />
          </Suspense>
        ) : null}
        {status === "ready" && !ready ? <InlineStatus icon="hourglass-medium">Carico il piano finito…</InlineStatus> : null}

        {ready ? (
          <Suspense fallback={<InlineStatus icon="hourglass-medium">Carico il piano finito…</InlineStatus>}>
            <PlanView
              detail={ready}
              trip={trip}
              loadTrip={loadTrip}
              loadCover={planView?.loadCover}
              handoff={planView?.handoff}
              notice={planView?.notice}
              now={planView?.now}
              arrival={watchedRun}
              timeline={
                <RunSection title="Il lavoro degli agenti" meta={`${stationCount} eventi`}>
                  {lanes}
                </RunSection>
              }
            />
          </Suspense>
        ) : (
          <div className={status === "running" || status === null ? undefined : "mt-6 lg:mt-8"}>{lanes}</div>
        )}
      </main>
      {/* The page's one live region: lane state changes and the plan's own state, never tool calls. */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement ? <span key={announcement.id}>{announcement.text}</span> : null}
        {planNote ? <span key={`plan-${planNote.id}`}>{planNote.text}</span> : null}
      </div>
    </div>
  );
}
