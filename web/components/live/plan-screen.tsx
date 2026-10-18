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

import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";

import type { CoverLoader } from "@/components/plan/cover/cover-store";
import type { TripLoader } from "@/components/plan/PlanView";
import { SessionExpiredPanel } from "@/components/states/session-expired";
import { AppHeaderBar } from "@/components/nav/app-header-bar";
import { PlanSkeleton } from "@/components/states/plan-skeleton";
import { API_ERROR_MESSAGES, ApiError, UnauthorizedError, type ApiClient } from "@/lib/api";
import { BRAND_NAME } from "@/lib/brand";
import { displayTitle } from "@/lib/format";
import { mayChangePlanStatus } from "@/lib/plan-events/detail";
import { usePlanEvents } from "@/lib/plan-events/use-plan-events";
import type { PlanDetail } from "@/lib/schemas/api";
import { useNow } from "@/lib/use-now";

import { useOnline } from "./hooks";
import { InterruptControl } from "./interrupt-control";
import { liveApi } from "./live-api";
import { PLAN_STATE_ID } from "./live-header";
import { loadPanels, loadPlanView, PlanScreenView } from "./plan-screen-view";
import { StreamStatus } from "./stream-status";

/** The panel of a plan that cannot be loaded: the panels' on-demand chunk (plan-screen-view). */
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
  const loadTrip = useCallback<TripLoader>((id, signal) => client.getTrip(id, { signal }), [client]);
  const loadCover = useCallback<CoverLoader>((id) => client.getCover(id), [client]);

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
  const canInterrupt = status === "running" || status === "budget_paused";

  return (
    <PlanScreenView
      state={state}
      detail={detail}
      // While the page is not up to date its clocks stop at the last known state.
      clock={stale ? lastUpdate : now}
      stale={stale}
      connection={connection}
      header={<AppHeaderBar current="plans" compact />}
      interrupting={interrupting}
      action={
        canInterrupt ? (
          <InterruptControl
            interrupting={interrupting && status === "running"}
            paused={status === "budget_paused"}
            onConfirm={interrupt}
          />
        ) : null
      }
      streamLine={
        <StreamStatus
          connection={connection}
          online={online}
          loginUrl={loginUrl}
          lastUpdate={lastUpdate === null ? null : clockTime(lastUpdate)}
        />
      }
      onContinue={resume}
      loadTrip={loadTrip}
      planView={{ loadCover }}
    />
  );
}
