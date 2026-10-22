"use client";

/**
 * /plans/[id]: the live timeline while the plan runs, every state that is not `ready`, and the
 * finished plan with the run's timeline closed under it (spec, "La timeline in diretta" and
 * "Tutti gli stati sono disegnati"; DESIGN.md, direction "Linee").
 *
 * Data: GET /plans/{id} (status, cost, budget, the plan, the question waiting) and the SSE stream
 * through usePlanEvents, re-reading the plan whenever an event may change its status. Everything
 * is fetched in the browser, which carries the session cookie to the backend.
 *
 * The traveller's choice: the answer goes through POST /plans/{id}/choices/{choice_id}. Once it
 * went, the question is hidden at once (until its answered event arrives) and the focus moves to
 * the plan's state; a 409 `choice_closed` or a 404 `choice_not_found` leaves the backend's sentence
 * on the panel and re-reads the plan; a 401 keeps the picks with a sentence to sign in again. While a
 * question waits, the tab title starts with "Tocca a te ·".
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ChoiceControls } from "@/components/choice/choice-panel";
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
import { loadChoicePanel, loadPanels, loadPlanView, PlanScreenView, shownChoice } from "./plan-screen-view";
import { StreamStatus } from "./stream-status";

/** The panel of a plan that cannot be loaded: the panels' on-demand chunk (plan-screen-view). */
const PlanLoadFailed = lazy(() => loadPanels().then((module) => ({ default: module.PlanLoadFailed })));

/** Several events can announce a status change at once: read the plan once after them. */
const REFRESH_DEBOUNCE_MS = 400;

/** The choice's error when the session expired while the traveller picked (a 401 on the answer).
 * The sign-in reloads the page, so it never promises the picks will still be there. */
const ANSWER_SIGNED_OUT = "La sessione è scaduta: accedi di nuovo e rifai la scelta.";

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
  /** Questions answered from this page: hidden at once, without waiting for their answered event. */
  const [closedChoices, setClosedChoices] = useState<ReadonlySet<string>>(() => new Set());
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

  // Warm the finished plan's, the panels' and the choice's chunks once the page is up, off the
  // critical path.
  useEffect(() => {
    const warm = () => {
      void loadPlanView();
      void loadPanels();
      void loadChoicePanel();
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

  const answer = useCallback<ChoiceControls["answer"]>(
    async (choiceId, input) => {
      try {
        await client.answerChoice(planId, choiceId, input);
        // The stream's answered event confirms it; until then the question stays hidden. The focus
        // goes to the plan's state, in the sticky header and on screen: without preventScroll,
        // Chrome would scroll the page to the header's place in the flow, its top.
        setClosedChoices((current) => new Set(current).add(choiceId));
        requestAnimationFrame(() => document.getElementById(PLAN_STATE_ID)?.focus({ preventScroll: true }));
        return null;
      } catch (error) {
        if (error instanceof UnauthorizedError) {
          // Nothing went: the panel keeps the picks and says why, the stream line offers the sign-in.
          setLoginUrl(error.loginUrl);
          return ANSWER_SIGNED_OUT;
        }
        if (
          error instanceof ApiError &&
          (error.kind === "conflict" || (error.kind === "not_found" && error.code === "choice_not_found"))
        ) {
          // Closed already (the deadline, an interrupt), or no longer there: the backend's
          // sentence, and the real status.
          scheduleRefresh(0);
          return { closed: error.message };
        }
        return error instanceof ApiError ? error.message : API_ERROR_MESSAGES.unknown;
      }
    },
    [client, planId, scheduleRefresh],
  );
  const choiceControls = useMemo<ChoiceControls>(() => ({ answer }), [answer]);

  const title = displayTitle(detail?.title ?? "Piano");
  const asking = shownChoice(state, closedChoices, interrupting) !== null;
  useEffect(() => {
    document.title = asking ? `Tocca a te · ${title} · ${BRAND_NAME}` : `${title} · ${BRAND_NAME}`;
  }, [asking, title]);

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
  // The last known state: the newest server time the page holds (the latest answer's `now`, minutes
  // after the newest event in a quiet pause).
  const lastUpdate = latest(state.events[state.events.length - 1]?.ts, detail?.updated_at, detail?.now);
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
      choice={choiceControls}
      closedChoices={closedChoices}
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
