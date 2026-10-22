"use client";

/**
 * The plan screen as a view (spec, "Demo": the seam): the live header, the lanes, the plan
 * states, the traveller's choice and the finished plan, from a reducer state and a detail it is
 * given. Two data sources render it: PlanScreen (the live plan, GET /plans/{id} and the SSE
 * stream) and DemoPlanScreen (a recorded run replayed in the browser). This module never imports
 * an API client, so the demo never evaluates one: what needs the backend arrives as props (the
 * choice's `answer` among them).
 *
 * The choice (the coordinator's `ask_traveller` pause, components/choice/choice-panel.tsx) shows
 * while the plan runs and the data source gives its controls: first under the live header on the
 * phone, under the lanes from 1080 px; the coordinator's plate shows only with it. On the live
 * screen it counts down to the backend's deadline corrected for the browser clock's skew
 * (`useClockSkew`). The page's one live region says once that a minute is left, and once how a
 * question it showed closed. While it shows, the demo's camera holds still (AgentLanes
 * `cameraHeld`).
 */

import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { ChoiceControls } from "@/components/choice/choice-panel";
import type { CoverLoader } from "@/components/plan/cover/cover-store";
import type { PlanHandoff, TripLoader } from "@/components/plan/PlanView";
import { daysCount, titleStatesDates, tripLength } from "@/components/plan/trip-dates";
import { isEndedStatus } from "@/components/states/ended-status";
import { InlineStatus } from "@/components/ui/notice";
import { choiceWindowMs, readChoiceAnswer, type ChoiceView } from "@/lib/choices";
import { displayTitle, formatElapsed } from "@/lib/format";
import { AGENTS, PLAN_STATUS_LABELS, type ConnectionStatus } from "@/lib/plan-events/labels";
import { elapsedMs, type OpenChoice, type PlanLiveState } from "@/lib/plan-events/reducer";
import type { PlanDetail } from "@/lib/schemas/api";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { AgentLanes, type LaneFollow } from "./agent-lanes";
import { useClockSkew, useLaneLayout, useLiveBaseline } from "./hooks";
import { LiveHeader, PLAN_STATE_ID } from "./live-header";
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

/** The traveller's choice: its own chunk too, warmed with the others (most runs never ask). */
export const loadChoicePanel = () => import("@/components/choice/choice-panel");
const ChoicePanel = lazy(loadChoicePanel);

/** The question on screen: the open one while the plan runs, unless the viewer is interrupting
 * or already answered it from this page (it stays hidden until its answered event arrives). */
export function shownChoice(
  state: PlanLiveState,
  closedChoices: ReadonlySet<string> | undefined,
  interrupting: boolean,
): OpenChoice | null {
  const open = state.openChoice;
  if (!open || state.status !== "running" || interrupting || closedChoices?.has(open.choice.id)) return null;
  return open;
}

const MINUTE_MS = 60_000;

/** The last minute of a question whose window is longer than one (never the demo's 15 s). The
 * deadline and the window are the panel's own: the controls' when they set them. */
function inLastMinute(choice: ChoiceView, controls: ChoiceControls, clock: number): boolean {
  const deadlineAt = controls.deadlineAt === undefined ? Date.parse(choice.deadlineAt) : controls.deadlineAt;
  if (deadlineAt === null) return false;
  const left = deadlineAt - clock;
  return (controls.windowMs ?? choiceWindowMs(choice)) > MINUTE_MS && left > 0 && left <= MINUTE_MS;
}

/** The title of the event that answered each question ("Tempo scaduto: sceglie Atlas"), by its id:
 * the latest one when a question has several. */
function answeredTitles(events: readonly UIEvent[]): ReadonlyMap<string, string> {
  const titles = new Map<string, string>();
  for (const event of events) {
    const answer = event.kind === "choice" ? readChoiceAnswer(event.detail) : null;
    if (answer) titles.set(answer.choiceId, event.title);
  }
  return titles;
}

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
  /** How the traveller answers the coordinator's question; without it no question shows. */
  choice?: ChoiceControls;
  /** Questions this page already answered: hidden until their answered event arrives. */
  closedChoices?: ReadonlySet<string>;
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
  choice,
  closedChoices,
  onContinue,
  loadTrip,
  trip,
  planView,
}: PlanScreenViewProps) {
  // The viewer watched the run (the plan was running when the page was up): when it turns ready
  // the plan is an arrival, not a page load (PlanView brings its top into view).
  const [watchedRun, setWatchedRun] = useState(false);
  // The coordinator's plate stands for the question's panel, and goes with it.
  const views = useMemo(
    () =>
      buildLaneViews(state, {
        askingChoiceId: choice ? (shownChoice(state, closedChoices, interrupting)?.choice.id ?? null) : null,
      }),
    [state, choice, closedChoices, interrupting],
  );
  const baseline = useLiveBaseline(connection, state.lastSeq, state.announcement?.id ?? null);

  // A plan-level change a watcher would miss (budget reached, failed, blocked, interrupted) is
  // said once in the live region, next to the lanes' own words. Ready is announced by the focus
  // that moves to the plan, the viewer's own interrupt by the focus that moves to the state.
  const settledForSpeech = baseline.announceAfterId !== null;
  const [seenStatus, setSeenStatus] = useState(state.status);
  const [planNote, setPlanNote] = useState<{ id: number; text: string } | null>(null);
  // This render's note: the choice's notes below go with the region's words as they will be.
  let note = planNote;
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
      note = { id: (planNote?.id ?? 0) + 1, text: `Piano: ${PLAN_STATUS_LABELS[next].toLowerCase()}` };
      setPlanNote(note);
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

  // The question on screen.
  const asked = choice ? shownChoice(state, closedChoices, interrupting) : null;
  const askedId = asked?.choice.id ?? null;

  // The question's clock on the live screen (the demo sets its own deadline): the backend's
  // deadline_at moved onto the browser's clock by its skew, set by each GET /plans/{id} answer's
  // own clock (`now`) and lowered by a newer server timestamp the page holds (the newest event's
  // ts; the snapshot's updated_at, which matters only from a backend without `now`). So a device
  // clock minutes fast or slow neither opens a question at "Tempo scaduto" nor holds it past the
  // backend's deadline, even after a reload in a quiet pause, when every event is minutes old.
  // While the page is stale its clock is a server time (the last known state), so the deadline
  // stays the backend's and nothing is sampled.
  const skew = useClockSkew(stale ? null : clock, detail?.now, [
    state.events[state.events.length - 1]?.ts,
    detail?.updated_at,
  ]);
  const controls: ChoiceControls | undefined =
    choice && asked && choice.deadlineAt === undefined
      ? {
          ...choice,
          deadlineAt: Date.parse(asked.choice.deadlineAt) + (stale ? 0 : skew),
          windowMs: choiceWindowMs(asked.choice),
        }
      : choice;

  // The traveller's choice, and the one time the page says a minute is left: the question's id,
  // and what the live region said before it, so the note goes with the region's next words (it is
  // atomic: a note that stayed would be read again with every lane change).
  const layout = useLaneLayout();
  const spokenNow = `${announcement?.id ?? ""}|${note?.id ?? ""}`;
  const [minuteSaid, setMinuteSaid] = useState<{ choiceId: string; spoken: string } | null>(null);
  if (asked && controls && clock !== null && minuteSaid?.choiceId !== asked.choice.id && inLastMinute(asked.choice, controls, clock)) {
    setMinuteSaid({ choiceId: asked.choice.id, spoken: spokenNow });
  }
  const minuteNote = asked !== null && minuteSaid?.choiceId === asked.choice.id && minuteSaid.spoken === spokenNow;

  // A question that was on screen and closes (its answered event arrives: the deadline, the
  // traveller's own answer, an interrupt) is said once, by that event's title ("Tempo scaduto:
  // sceglie Atlas"), with the region's words of that moment: the panel and its words are gone, and
  // a screen reader still picking would otherwise hear nothing. So is one the next question
  // replaces at once (both events in one batch), whose panel then takes the focus. Never the
  // replayed history. The titles are read once per change of the events, never per clock tick.
  const titles = useMemo(() => answeredTitles(state.events), [state.events]);
  const [watching, setWatching] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<{ choiceId: string; text: string; spoken: string } | null>(null);
  if (watching !== null && askedId !== watching) {
    const answered = titles.get(watching);
    if (answered !== undefined || askedId !== null) setWatching(askedId);
    if (answered !== undefined && settledForSpeech) setReceipt({ choiceId: watching, text: answered, spoken: spokenNow });
  } else if (watching === null && askedId !== null) {
    setWatching(askedId);
  }
  const receiptNote = receipt !== null && receipt.spoken === spokenNow ? receipt : null;

  // A question that leaves with the focus (its deadline, the demo's recording answering) hands it
  // to the plan's state, as the traveller's own answer does; a focus anywhere else stays put.
  const previousAsked = useRef<string | null>(null);
  useEffect(() => {
    const left = previousAsked.current !== null && askedId === null;
    previousAsked.current = askedId;
    if (left && (document.activeElement === null || document.activeElement === document.body)) {
      document.getElementById(PLAN_STATE_ID)?.focus({ preventScroll: true });
    }
  }, [askedId]);
  const place = detail?.request.destination;
  const choicePanel =
    asked && controls ? (
      <Suspense fallback={null}>
        <div className={layout === "stack" ? "mb-6" : "mt-8"}>
          <ChoicePanel
            choice={asked.choice}
            controls={controls}
            now={clock}
            destination={typeof place === "string" && place.trim() !== "" ? place : null}
          />
        </div>
      </Suspense>
    ) : null;

  const lanes = (
    <AgentLanes
      state={state}
      views={views}
      now={clock}
      freshAfterSeq={baseline.freshAfterSeq}
      stale={stale}
      follow={followLanes}
      cameraHeld={choicePanel !== null}
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
        {/* On the phone the question comes first, under the live header. */}
        {layout === "stack" ? choicePanel : null}
        {status === "budget_paused" && onContinue ? (
          <Suspense fallback={null}>
            <BudgetPausedPanel
              costCents={state.costCents}
              budgetCents={state.budgetCents}
              continues={detail?.continues ?? 0}
              continuesLimit={detail?.continues_limit ?? 0}
              onContinue={onContinue}
            />
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
        {/* From 1080 px it sits under the lanes. */}
        {layout === "stack" ? null : choicePanel}
      </main>
      {/* The page's one live region: lane state changes, the plan's own state, the choice's last
          minute and how it closed, never tool calls. */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement ? <span key={announcement.id}>{announcement.text}</span> : null}
        {note ? <span key={`plan-${note.id}`}>{note.text}</span> : null}
        {asked && minuteNote ? <span key={`minute-${asked.choice.id}`}>Manca un minuto per scegliere.</span> : null}
        {receiptNote ? <span key={`answer-${receiptNote.choiceId}`}>{receiptNote.text}</span> : null}
      </div>
    </div>
  );
}
