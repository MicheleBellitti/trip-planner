"use client";

/**
 * /plans/[id]: the live timeline while the plan runs, every state that is not `ready`, and the
 * finished plan with the run's timeline closed under it (spec, "La timeline in diretta" and
 * "Tutti gli stati sono disegnati"; DESIGN.md, direction "Linee").
 *
 * Data: GET /plans/{id} (status, cost, budget, the plan) and the SSE stream through
 * usePlanEvents, re-reading the plan whenever an event may change its status. Everything is
 * fetched in the browser, which carries the session cookie to the backend.
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { TripLoader } from "@/components/plan/PlanView";
import { daysCount, titleStatesDates, tripLength } from "@/components/plan/trip-dates";
import { isEndedStatus } from "@/components/states/ended-status";
import { SessionExpiredPanel } from "@/components/states/session-expired";
import { AppHeaderBar } from "@/components/nav/app-header-bar";
import { PlanSkeleton } from "@/components/states/plan-skeleton";
import { InlineStatus } from "@/components/ui/notice";
import { API_ERROR_MESSAGES, ApiError, UnauthorizedError, type ApiClient } from "@/lib/api";
import { BRAND_NAME } from "@/lib/brand";
import { displayTitle, formatElapsed } from "@/lib/format";
import { mayChangePlanStatus } from "@/lib/plan-events/detail";
import { AGENTS, PLAN_STATUS_LABELS } from "@/lib/plan-events/labels";
import { elapsedMs } from "@/lib/plan-events/reducer";
import { usePlanEvents } from "@/lib/plan-events/use-plan-events";
import type { PlanDetail } from "@/lib/schemas/api";
import { useNow } from "@/lib/use-now";

import { AgentLanes } from "./agent-lanes";
import { useLiveBaseline, useOnline } from "./hooks";
import { InterruptControl } from "./interrupt-control";
import { liveApi } from "./live-api";
import { LiveHeader, PLAN_STATE_ID } from "./live-header";
import { requestSummary } from "./request-summary";
import { RunSection } from "./run-section";
import { buildLaneViews, findBlocker } from "./stations";
import { StreamStatus } from "./stream-status";

/**
 * The finished plan is its own chunk: a running plan never needs it, and it is a fifth of what
 * the page ships (JS budget, README "Measure the JS"). It is fetched when the run is under way
 * (so the arrival is instant) or when the plan is already finished.
 */
const loadPlanView = () => import("@/components/plan/PlanView");
const PlanView = lazy(() => loadPlanView().then((module) => ({ default: module.PlanView })));

/** The panels of the plan states (paused, ended, not loadable): the same on-demand chunk. */
const loadPanels = () => import("@/components/states/panels");
const BudgetPausedPanel = lazy(() => loadPanels().then((module) => ({ default: module.BudgetPausedPanel })));
const PlanEndedPanel = lazy(() => loadPanels().then((module) => ({ default: module.PlanEndedPanel })));
const PlanLoadFailed = lazy(() => loadPanels().then((module) => ({ default: module.PlanLoadFailed })));

/** Several events can announce a status change at once: read the plan once after them. */
const REFRESH_DEBOUNCE_MS = 400;

function clockTime(ms: number): string {
  return new Date(ms).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function latest(...instants: (string | null | undefined)[]): number | null {
  let best: number | null = null;
  for (const instant of instants) {
    const at = instant ? Date.parse(instant) : Number.NaN;
    if (!Number.isNaN(at) && (best === null || at > best)) best = at;
  }
  return best;
}

type PlanLoad = { ok: true; detail: PlanDetail } | { ok: false; error: unknown };

async function fetchPlan(client: ApiClient, planId: string): Promise<PlanLoad> {
  try {
    return { ok: true, detail: await client.getPlan(planId) };
  } catch (error) {
    return { ok: false, error };
  }
}

export function PlanScreen({ planId, client = liveApi }: { planId: string; client?: ApiClient }) {
  const [detail, setDetail] = useState<PlanDetail | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [loginUrl, setLoginUrl] = useState<string | null>(null);
  const [interrupting, setInterrupting] = useState(false);
  // The viewer watched the run (the plan was running when the page was up): when it turns ready
  // the plan is an arrival, not a page load (PlanView brings its top into view).
  const [watchedRun, setWatchedRun] = useState(false);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Applies a GET /plans/{id} outcome; false when the stream should not reconnect (signed
   * out, plan gone, account not allowed). */
  const apply = useCallback((outcome: PlanLoad): boolean => {
    if (outcome.ok) {
      setDetail(outcome.detail);
      setLoadError(null);
      return true;
    }
    const { error } = outcome;
    if (error instanceof UnauthorizedError) {
      setLoginUrl(error.loginUrl);
      return false;
    }
    if (error instanceof ApiError) {
      setLoadError(error);
      return error.kind !== "not_found" && error.kind !== "forbidden";
    }
    return true;
  }, []);

  const load = useCallback(async () => apply(await fetchPlan(client, planId)), [apply, client, planId]);

  const scheduleRefresh = useCallback(
    (delay = REFRESH_DEBOUNCE_MS) => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      refreshTimer.current = setTimeout(() => void load(), delay);
    },
    [load],
  );

  useEffect(() => {
    let active = true;
    void fetchPlan(client, planId).then((outcome) => {
      if (active) apply(outcome);
    });
    return () => {
      active = false;
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [apply, client, planId]);

  const gone = loadError?.kind === "not_found" || loadError?.kind === "forbidden";
  const { state, connection, reconnect } = usePlanEvents(planId, {
    detail,
    enabled: loginUrl === null && !gone,
    eventsUrl: client.eventsUrl,
    beforeReconnect: load,
    // The consumer changes the status on the session's idle and error events (budget_paused is
    // not terminal: no `event: end` follows it), so re-read the plan after any of them.
    onEvent: (event) => {
      if (mayChangePlanStatus(event.detail)) scheduleRefresh();
    },
    onEnd: () => scheduleRefresh(0),
  });

  // Warm the finished plan's chunk once the page is up, off the critical path.
  useEffect(() => {
    const warm = () => {
      void loadPlanView();
      void loadPanels();
    };
    if (typeof window.requestIdleCallback === "function") {
      const id = window.requestIdleCallback(warm, { timeout: 4000 });
      return () => window.cancelIdleCallback(id);
    }
    const id = window.setTimeout(warm, 1500);
    return () => window.clearTimeout(id);
  }, []);

  const now = useNow();
  const online = useOnline();
  const views = useMemo(() => buildLaneViews(state), [state]);
  const baseline = useLiveBaseline(connection, state.lastSeq, state.announcement?.id ?? null);
  const loadTrip = useCallback<TripLoader>((id, signal) => client.getTrip(id, { signal }), [client]);

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
  useEffect(() => {
    document.title = `${title} · ${BRAND_NAME}`;
  }, [title]);

  async function interrupt(): Promise<string | null> {
    try {
      const result = await client.interruptPlan(planId);
      if (result.status === "running") setInterrupting(true);
      scheduleRefresh(0);
      requestAnimationFrame(() => document.getElementById(PLAN_STATE_ID)?.focus());
      return null;
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        setLoginUrl(error.loginUrl);
        return null;
      }
      if (error instanceof ApiError && error.kind === "conflict") {
        // Already over: the page catches up with the plan's real status.
        scheduleRefresh(0);
        return null;
      }
      return error instanceof ApiError ? error.message : API_ERROR_MESSAGES.unknown;
    }
  }

  async function resume(): Promise<void> {
    try {
      await client.continuePlan(planId);
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        setLoginUrl(error.loginUrl);
        return;
      }
      if (error instanceof ApiError && error.kind === "conflict") {
        scheduleRefresh(0);
        return;
      }
      throw error;
    }
    await load();
    if (connection === "closed") reconnect();
  }

  // --- nothing to show yet -------------------------------------------------------------------
  const hasData = detail !== null || state.events.length > 0;
  if (!hasData && loginUrl) {
    return (
      <>
        <AppHeaderBar current="plans" compact />
        <main className="mx-auto max-w-page px-4 pt-2 lg:px-7">
          <SessionExpiredPanel loginUrl={loginUrl} />
        </main>
      </>
    );
  }
  if (loadError && (gone || !hasData)) {
    return (
      <>
        <AppHeaderBar current="plans" compact />
        <main className="mx-auto max-w-page px-4 pt-2 lg:px-7">
          <Suspense fallback={null}>
            <PlanLoadFailed
              error={loadError}
              onRetry={() => {
                setLoadError(null);
                void load();
                reconnect();
              }}
            />
          </Suspense>
        </main>
      </>
    );
  }
  if (!hasData) return <PlanSkeleton />;

  // --- the plan ------------------------------------------------------------------------------
  const status = state.status;
  const stale = !online || loginUrl !== null;
  const lastUpdate = latest(state.events[state.events.length - 1]?.ts, detail?.updated_at);
  // While the page is not up to date its clocks stop at the last known state.
  const clock = stale ? lastUpdate : now;
  const elapsed = clock === null ? null : formatElapsed(elapsedMs(state, clock));
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
  const canInterrupt = status === "running" || status === "budget_paused";
  const announcement =
    state.announcement && baseline.announceAfterId !== null && state.announcement.id > baseline.announceAfterId
      ? state.announcement
      : null;
  if (status === "running" && !watchedRun) setWatchedRun(true);
  const blocker = status === "blocked" ? findBlocker(state) : null;
  const stationCount = AGENTS.reduce((sum, agent) => sum + views[agent].stations.length, 0);

  const lanes = (
    <AgentLanes state={state} views={views} now={clock} freshAfterSeq={baseline.freshAfterSeq} stale={stale} />
  );

  return (
    <div className="pb-12">
      <AppHeaderBar current="plans" compact />
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
        action={
          canInterrupt ? (
            <InterruptControl
              interrupting={interrupting && status === "running"}
              paused={status === "budget_paused"}
              onConfirm={interrupt}
            />
          ) : null
        }
      />
      <StreamStatus
        connection={connection}
        online={online}
        loginUrl={loginUrl}
        lastUpdate={lastUpdate === null ? null : clockTime(lastUpdate)}
      />
      <main className="mx-auto max-w-page px-4 pt-3 lg:px-7 lg:pt-5">
        {status === "budget_paused" ? (
          <Suspense fallback={null}>
            <BudgetPausedPanel costCents={state.costCents} budgetCents={state.budgetCents} onContinue={resume} />
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
              loadTrip={loadTrip}
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
