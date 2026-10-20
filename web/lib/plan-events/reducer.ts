/**
 * The live state of a plan, built from its UI events: a pure reducer (spec: "Lo stato dei dati
 * vive in un reducer alimentato da usePlanEvents()").
 *
 * Inputs:
 * - `events`: UIEvents from the SSE stream, in any order and with duplicates (a reconnection
 *   replays from Postgres). They are kept ordered by `seq`, each `seq` once; the state derived
 *   from them is folded in `seq` order, so an out-of-order arrival triggers a refold.
 * - `detail`: a GET /plans/{id} snapshot (status, cost, budget, timestamps). Fetched before the
 *   stream replays history, so a status from an event older than the snapshot never overrides
 *   it (compared on time: event `ts` vs the snapshot's `updated_at`).
 * - `end`: the stream's `event: end`, the plan's terminal status (authoritative).
 *
 * Output (`PlanLiveState`): plan status, the elapsed-time base, cumulative cost vs the session
 * budget, one lane per agent (state, current tool, events, warnings), inter-agent messages, the
 * submit_plan outcome and an aria-live announcement of lane state changes only.
 *
 * Lane state rules (detail keys: ./detail.ts):
 * - status events: the backend's own events (`backend.*`, `plan_status`, or no detail at all,
 *   like "Piano avviato") change the plan, not the lanes; an idle `budget_reached` leaves the
 *   lane as it was (the plan's `budget_paused` stops it, below); otherwise the backend's
 *   `detail.lane_state` decides; without one, the Managed Agents type and stop reason do
 *   (thread created/running -> working; idle end_turn -> done; requires_action -> waiting;
 *   retries_exhausted or refusal -> error; terminated or deleted -> done, as archiving ends
 *   every thread); any other status event wakes a waiting lane;
 * - a tool call, a plan submission or a message addressed to the lane -> working; a tool
 *   result (its duration, or a result type, `user.custom_tool_result` included) clears the
 *   tool in progress;
 * - an error event -> error, unless it reports a failed source (an MCP server: "Fonte MCP
 *   caduta") or the plan survives it (`severity: warning`, or still retrying): then it is a
 *   lane warning and nothing else;
 * - the plan's status is laid over the lanes: `ready` finishes the coordinator and every working
 *   lane; `budget_paused`, `interrupted`, `failed` and `blocked` stop working lanes (`stopped`),
 *   and `failed`/`blocked` mark the coordinator in error.
 *
 * The open choice (`openChoice`, lib/choices.ts): a `choice` event "asked" opens a question, the
 * "answered" event with the same id closes it. The fold keeps the asked ones and the answered ids,
 * so an out-of-order arrival refolds like anything else. The open one is the latest asked
 * question without an answer; failing that, the snapshot's `pending_choice` (a reload during the
 * pause shows the cards before the stream replays), unless an answered event for it was folded.
 * It exists only while the plan is `running` (or its status is still unknown).
 */

import { askedTitle, readAskedChoice, readChoice, readChoiceAnswer, type ChoiceView } from "../choices";
import type { PlanDetail, PlanStatus } from "../schemas/api";
import type { AgentName, UIEvent } from "../schemas/generated/ui-event";
import {
  isWarningError,
  readAgentState,
  readBudgetCents,
  readEventType,
  readMessage,
  readPlanOutcome,
  readPlanStatus,
  readSourceFailure,
  readStopReason,
  readTool,
} from "./detail";
import { AGENTS, laneAnnouncement, type LaneState } from "./labels";

export interface CurrentTool {
  seq: number;
  ts: string;
  /** The event's one-line title, e.g. "Expedia · voli MXP→LIS · 14–18 nov". */
  title: string;
  tool: string | null;
  server: string | null;
  params: Record<string, unknown> | null;
  toolUseId: string | null;
}

export interface LaneWarning {
  seq: number;
  ts: string;
  title: string;
  /** The failed source (MCP server), when the event names it. */
  source: string | null;
}

export interface LaneError {
  seq: number;
  ts: string;
  title: string;
}

export interface Lane {
  agent: AgentName;
  /** What the lane shows, with the plan's status laid over `activity`. */
  state: LaneState;
  /** What the lane's own events say, before the plan's status is laid over it. */
  activity: Exclude<LaneState, "stopped">;
  /** The tool call in progress ("il tool in corso con i parametri principali"). */
  currentTool: CurrentTool | null;
  /** The lane's events, ascending by seq. */
  events: UIEvent[];
  /** Failed sources and retried errors: shown on the lane, not as a plan error. */
  warnings: LaneWarning[];
  lastError: LaneError | null;
  lastActivityAt: string | null;
  /** The lane delivered a result: it sent a message to the coordinator. Only a subagent that
   * reported can show as finished once the plan stopped without a plan. */
  reported: boolean;
}

export interface AgentMessage {
  seq: number;
  ts: string;
  /** The lane that shows it (the subagent's, for coordinator <-> subagent messages). */
  lane: AgentName;
  from: AgentName | null;
  to: AgentName | null;
  title: string;
  /** The full text, shown on click. */
  text: string | null;
}

export interface Announcement {
  /** Increases with every announcement, so the same text can be announced twice. */
  id: number;
  text: string;
}

/** A question the coordinator put to the traveller, as the page shows it. */
export interface OpenChoice {
  choice: ChoiceView;
  /** The asked event; null when the choice comes from the snapshot. */
  seq: number | null;
  ts: string;
  /** The event's own title, or `askedTitle(kind)` from the snapshot. */
  title: string;
}

interface StatusMark {
  status: PlanStatus;
  /** When it took effect: the event's `ts`, or the snapshot's `updated_at`. */
  at: string;
}

interface DetailSnapshot {
  status: PlanStatus;
  costCents: number;
  budgetCents: number | null;
  createdAt: string;
  updatedAt: string;
  failureReason: string | null;
  submitAttempts: number;
  pendingChoice: ChoiceView | null;
}

/** What the ordered events say; rebuilt by folding them in seq order. */
interface EventFold {
  lanes: Record<AgentName, Lane>;
  messages: AgentMessage[];
  statusFromEvents: StatusMark | null;
  costCents: number | null;
  budgetCents: number | null;
  firstTs: string | null;
  lastTs: string | null;
  submissions: number;
  rejections: number;
  planAccepted: boolean;
  /** Asked choices, ascending by seq. */
  askedChoices: readonly OpenChoice[];
  /** Ids of the choices an answered event closed. */
  answeredChoiceIds: ReadonlySet<string>;
}

export interface PlanLiveState {
  /** Every event once, ascending by seq. */
  events: UIEvent[];
  /** Highest seq received: where a reconnection resumes (`?after=`). */
  lastSeq: number | null;
  /** The plan's status: `event: end` > the newer of (last status event, snapshot). */
  status: PlanStatus | null;
  /** Elapsed-time base: when the plan started (snapshot `created_at` or the first event). */
  startedAt: string | null;
  /** When the clock stopped (the plan left `running`); null while it runs. */
  stoppedAt: string | null;
  /** Cumulative session cost, US cents (never decreases). */
  costCents: number | null;
  /** The backend has reported a cost at least once (a usage event, or a snapshot above zero).
   * It reports at the end of a session turn, so until then a zero means "not updated yet". */
  costReported: boolean;
  /** The session's budget cap, US cents: the end of the cost bar. */
  budgetCents: number | null;
  lanes: Record<AgentName, Lane>;
  /** Inter-agent messages, ascending by seq ("coordinatore → voli: incarico"). */
  messages: AgentMessage[];
  /** `event: end` was received: the stream is over and will not reconnect. */
  ended: boolean;
  /** submit_plan calls seen, and how many were rejected. */
  submissions: number;
  rejections: number;
  /** submit_plan was accepted (the plan becomes `ready` when the coordinator ends its turn). */
  planAccepted: boolean;
  /** The plan is `ready`: fetch GET /plans/{id} for the finished plan. */
  planReady: boolean;
  /** The question waiting for the traveller: only while the plan is `running` (or unknown). */
  openChoice: OpenChoice | null;
  failureReason: string | null;
  /** For the aria-live="polite" region: lane state changes only, never tool calls. */
  announcement: Announcement | null;
  /** Internal: the inputs the view is derived from. */
  readonly fold: EventFold;
  readonly snapshot: DetailSnapshot | null;
  readonly endStatus: PlanStatus | null;
}

export type PlanEventsAction =
  | { type: "reset" }
  | { type: "events"; events: readonly UIEvent[] }
  | { type: "end"; status: PlanStatus }
  | { type: "detail"; detail: Pick<PlanDetail, "status" | "cost_cents" | "budget_cents" | "created_at" | "updated_at" | "failure_reason" | "submit_attempts"> & {
      /** A GET /plans/{id} `pending_choice`; optional, read tolerantly. */
      pending_choice?: unknown;
    };
  };

// --- helpers --------------------------------------------------------------------------------

function time(iso: string | null | undefined): number {
  if (!iso) return Number.NaN;
  return Date.parse(iso);
}

function earlier(a: string | null, b: string | null): string | null {
  if (a === null) return b;
  if (b === null) return a;
  return time(b) < time(a) ? b : a;
}

function later(a: string | null, b: string | null): string | null {
  if (a === null) return b;
  if (b === null) return a;
  return time(b) > time(a) ? b : a;
}

function maxOrNull(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return Math.max(a, b);
}

function emptyLane(agent: AgentName): Lane {
  return {
    agent,
    state: "waiting",
    activity: "waiting",
    currentTool: null,
    events: [],
    warnings: [],
    lastError: null,
    lastActivityAt: null,
    reported: false,
  };
}

function emptyFold(): EventFold {
  return {
    lanes: Object.fromEntries(AGENTS.map((agent) => [agent, emptyLane(agent)])) as Record<AgentName, Lane>,
    messages: [],
    statusFromEvents: null,
    costCents: null,
    budgetCents: null,
    firstTs: null,
    lastTs: null,
    submissions: 0,
    rejections: 0,
    planAccepted: false,
    askedChoices: [],
    answeredChoiceIds: new Set(),
  };
}

/** Index of the first event with seq >= `seq` (binary search on the ordered list). */
function lowerBound(events: readonly UIEvent[], seq: number): number {
  let low = 0;
  let high = events.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if ((events[middle]?.seq ?? Number.POSITIVE_INFINITY) < seq) low = middle + 1;
    else high = middle;
  }
  return low;
}

const RUNNING_TYPES = new Set([
  "session.thread_created",
  "session.thread_status_running",
  "session.status_running",
]);
const IDLE_TYPES = new Set(["session.thread_status_idle", "session.status_idle"]);
/** Archiving ends threads and sessions: "Lavoro chiuso", not a failure (a failed plan marks the
 * coordinator in error through the plan's status). */
const ENDED_TYPES = new Set(["session.thread_status_terminated", "session.status_terminated", "session.deleted"]);
/** Tool results, including the backend's answer to submit_plan ("Esito inviato all'agente"). */
const RESULT_TYPES = new Set([
  "agent.tool_result",
  "agent.mcp_tool_result",
  "user.custom_tool_result",
  "user.tool_result",
]);

type Activity = Lane["activity"];

function statusActivity(current: Activity, event: UIEvent): Activity {
  const type = readEventType(event.detail);
  // A backend status event ("Piano avviato", which has no detail; "Budget aumentato: si
  // riprende") changes the plan, not the lane: at the start the lanes wait until the session runs.
  if (!event.detail || type?.startsWith("backend.") || readPlanStatus(event.detail)) return current;
  const idle = type !== null && IDLE_TYPES.has(type);
  const stopReason = idle ? readStopReason(event.detail) : null;
  // The session's budget is spent: the lane neither finished nor waits for an agent. The plan
  // becomes budget_paused, which shows a working lane as stopped (`overlay`).
  if (stopReason === "budget_reached") return current;
  const explicit = readAgentState(event.detail);
  if (explicit && explicit !== "stopped") return explicit;
  if (type && RUNNING_TYPES.has(type)) return "working";
  if (type && ENDED_TYPES.has(type)) return "done";
  if (idle) {
    switch (stopReason) {
      case "requires_action":
        return "waiting";
      case "retries_exhausted":
      case "refusal":
        return "error";
      default:
        return "done";
    }
  }
  // Unknown status event (thinking, a model request, a type the web doesn't know): it shows
  // the lane is alive, nothing more.
  return current === "waiting" ? "working" : current;
}

function applyEvent(fold: EventFold, event: UIEvent): EventFold {
  const detail = event.detail;
  const previous = fold.lanes[event.agent];
  const lane: Lane = {
    ...previous,
    events: [...previous.events, event],
    lastActivityAt: event.ts,
  };
  let { messages, submissions, rejections, planAccepted, askedChoices, answeredChoiceIds } = fold;

  switch (event.kind) {
    case "status": {
      lane.activity = statusActivity(lane.activity, event);
      if (lane.activity !== "working") lane.currentTool = null;
      break;
    }
    case "tool": {
      lane.activity = "working";
      const tool = readTool(detail);
      const type = readEventType(detail);
      const isResult = tool.durationMs !== null || (type !== null && RESULT_TYPES.has(type));
      if (isResult) {
        const current = lane.currentTool;
        if (!current || !tool.toolUseId || !current.toolUseId || current.toolUseId === tool.toolUseId) {
          lane.currentTool = null;
        }
      } else {
        lane.currentTool = {
          seq: event.seq,
          ts: event.ts,
          title: event.title,
          tool: tool.tool,
          server: tool.server,
          params: tool.params,
          toolUseId: tool.toolUseId,
        };
      }
      break;
    }
    case "message": {
      const message = readMessage(detail);
      messages = [
        ...messages,
        {
          seq: event.seq,
          ts: event.ts,
          lane: event.agent,
          from: message.from,
          to: message.to,
          title: event.title,
          text: message.text,
        },
      ];
      if (message.from === event.agent && message.to === "coordinator" && event.agent !== "coordinator") {
        lane.reported = true;
      }
      const addressedHere = message.to === event.agent || (message.to === null && message.from === null);
      if (addressedHere || lane.activity === "waiting" || event.agent === "coordinator") {
        lane.activity = "working";
      }
      break;
    }
    case "error": {
      const failure = readSourceFailure(detail);
      if (failure || isWarningError(detail)) {
        lane.warnings = [
          ...lane.warnings,
          { seq: event.seq, ts: event.ts, title: event.title, source: failure?.source ?? null },
        ];
      } else {
        lane.activity = "error";
        lane.lastError = { seq: event.seq, ts: event.ts, title: event.title };
        lane.currentTool = null;
      }
      break;
    }
    case "plan": {
      const outcome = readPlanOutcome(detail);
      if (outcome.accepted !== null) submissions += 1;
      if (outcome.accepted === true) planAccepted = true;
      if (outcome.accepted === false) rejections += 1;
      if (lane.activity !== "error") lane.activity = "working";
      break;
    }
    case "choice": {
      // The coordinator waits for the traveller: its activity stays as it was.
      const asked = readAskedChoice(detail);
      if (asked) {
        askedChoices = [
          ...askedChoices.filter((open) => open.choice.id !== asked.id),
          { choice: asked, seq: event.seq, ts: event.ts, title: event.title },
        ];
      }
      const answer = readChoiceAnswer(detail);
      if (answer && !answeredChoiceIds.has(answer.choiceId)) {
        answeredChoiceIds = new Set(answeredChoiceIds).add(answer.choiceId);
      }
      break;
    }
    case "usage":
      break;
  }

  const planStatus = readPlanStatus(detail);
  return {
    lanes: { ...fold.lanes, [event.agent]: lane },
    messages,
    statusFromEvents: planStatus ? { status: planStatus, at: event.ts } : fold.statusFromEvents,
    costCents: maxOrNull(fold.costCents, event.cost_cents),
    budgetCents: maxOrNull(fold.budgetCents, readBudgetCents(detail)),
    firstTs: earlier(fold.firstTs, event.ts),
    lastTs: later(fold.lastTs, event.ts),
    submissions,
    rejections,
    planAccepted,
    askedChoices,
    answeredChoiceIds,
  };
}

function foldEvents(events: readonly UIEvent[]): EventFold {
  return events.reduce(applyEvent, emptyFold());
}

/** A lane that took part (it has events) but delivered nothing: it did not finish, the plan was
 * closed under it. A subagent that reported, or one that never started, keeps its state. */
function unfinished(lane: Lane, planAccepted: boolean): boolean {
  if (lane.events.length === 0) return false;
  if (lane.agent === "coordinator") return !planAccepted;
  return !lane.reported;
}

function overlay(lane: Lane, status: PlanStatus | null, planAccepted: boolean): LaneState {
  const { agent, activity } = lane;
  switch (status) {
    case "ready":
      return agent === "coordinator" || activity === "working" ? "done" : activity;
    case "failed":
    case "blocked":
      if (agent === "coordinator") return "error";
      if (activity === "working") return "stopped";
      // The lane that waited for a confirmation nobody gives, or ended its turn without
      // delivering: it stopped with the plan.
      return (activity === "waiting" || activity === "done") && unfinished(lane, planAccepted) ? "stopped" : activity;
    case "interrupted":
      if (activity === "working") return "stopped";
      return (activity === "waiting" || activity === "done") && unfinished(lane, planAccepted) ? "stopped" : activity;
    case "budget_paused":
      return activity === "working" ? "stopped" : activity;
    default:
      return activity;
  }
}

function effectiveStatus(
  fold: EventFold,
  snapshot: DetailSnapshot | null,
  endStatus: PlanStatus | null,
): { status: PlanStatus | null; at: string | null } {
  if (endStatus) {
    const at = fold.statusFromEvents?.status === endStatus ? fold.statusFromEvents.at : fold.lastTs;
    return { status: endStatus, at: at ?? snapshot?.updatedAt ?? null };
  }
  const fromEvents = fold.statusFromEvents;
  if (snapshot && (!fromEvents || !(time(fromEvents.at) > time(snapshot.updatedAt)))) {
    return { status: snapshot.status, at: snapshot.updatedAt };
  }
  return fromEvents ? { status: fromEvents.status, at: fromEvents.at } : { status: null, at: null };
}

function openChoiceOf(fold: EventFold, snapshot: DetailSnapshot | null, status: PlanStatus | null): OpenChoice | null {
  if (status !== null && status !== "running") return null;
  const asked = fold.askedChoices.filter((open) => !fold.answeredChoiceIds.has(open.choice.id));
  const latest = asked[asked.length - 1];
  if (latest) return latest;
  const pending = snapshot?.pendingChoice;
  if (!pending || fold.answeredChoiceIds.has(pending.id)) return null;
  return { choice: pending, seq: null, ts: pending.askedAt, title: askedTitle(pending.kind) };
}

function derive(
  previous: PlanLiveState | null,
  events: UIEvent[],
  fold: EventFold,
  snapshot: DetailSnapshot | null,
  endStatus: PlanStatus | null,
): PlanLiveState {
  const { status, at } = effectiveStatus(fold, snapshot, endStatus);
  const changed: string[] = [];
  const lanes = { ...fold.lanes };
  for (const agent of AGENTS) {
    const lane = fold.lanes[agent];
    const state = overlay(lane, status, fold.planAccepted);
    const shown = state === lane.state ? lane : { ...lane, state };
    lanes[agent] = shown;
    const before = previous?.lanes[agent].state ?? "waiting";
    if (before !== state) changed.push(laneAnnouncement(agent, state));
  }
  const lastId = previous?.announcement?.id ?? 0;
  return {
    events,
    lastSeq: events.length > 0 ? (events[events.length - 1]?.seq ?? null) : null,
    status,
    startedAt: earlier(snapshot?.createdAt ?? null, fold.firstTs),
    stoppedAt: status === null || status === "running" ? null : (at ?? fold.lastTs),
    costCents: maxOrNull(snapshot?.costCents ?? null, fold.costCents),
    costReported: fold.costCents !== null || (snapshot?.costCents ?? 0) > 0,
    budgetCents: maxOrNull(snapshot?.budgetCents ?? null, fold.budgetCents),
    lanes,
    messages: fold.messages,
    ended: endStatus !== null,
    submissions: Math.max(fold.submissions, snapshot?.submitAttempts ?? 0),
    rejections: fold.rejections,
    planAccepted: fold.planAccepted || status === "ready",
    planReady: status === "ready",
    openChoice: openChoiceOf(fold, snapshot, status),
    failureReason: snapshot?.failureReason ?? null,
    announcement: changed.length > 0 ? { id: lastId + 1, text: changed.join("; ") } : (previous?.announcement ?? null),
    fold,
    snapshot,
    endStatus,
  };
}

// --- public API -------------------------------------------------------------------------------

export function initialPlanLiveState(): PlanLiveState {
  return derive(null, [], emptyFold(), null, null);
}

function addEvents(state: PlanLiveState, incoming: readonly UIEvent[]): PlanLiveState {
  const sorted = [...incoming].sort((a, b) => a.seq - b.seq);
  let events = state.events;
  let fold = state.fold;
  let refold = false;
  const appended: UIEvent[] = [];
  for (const event of sorted) {
    const last = appended.length > 0 ? appended[appended.length - 1] : events[events.length - 1];
    if (last === undefined || event.seq > last.seq) {
      appended.push(event);
      if (!refold) fold = applyEvent(fold, event);
      continue;
    }
    if (event.seq === last.seq) continue;
    // Older than the newest event: insert unless already there, then refold everything.
    if (appended.length > 0) {
      events = [...events, ...appended];
      appended.length = 0;
    }
    const index = lowerBound(events, event.seq);
    if (events[index]?.seq === event.seq) continue;
    events = [...events.slice(0, index), event, ...events.slice(index)];
    refold = true;
  }
  if (appended.length === 0 && events === state.events) return state;
  if (appended.length > 0) events = [...events, ...appended];
  if (refold) fold = foldEvents(events);
  return derive(state, events, fold, state.snapshot, state.endStatus);
}

export function planEventsReducer(state: PlanLiveState, action: PlanEventsAction): PlanLiveState {
  switch (action.type) {
    case "reset":
      return initialPlanLiveState();
    case "events":
      return action.events.length === 0 ? state : addEvents(state, action.events);
    case "end":
      return derive(state, state.events, state.fold, state.snapshot, action.status);
    case "detail": {
      const { detail } = action;
      const snapshot: DetailSnapshot = {
        status: detail.status,
        costCents: detail.cost_cents,
        budgetCents: detail.budget_cents,
        createdAt: detail.created_at,
        updatedAt: detail.updated_at,
        failureReason: detail.failure_reason,
        submitAttempts: detail.submit_attempts,
        pendingChoice: readChoice(detail.pending_choice),
      };
      return derive(state, state.events, state.fold, snapshot, state.endStatus);
    }
  }
}

/** Build a state from a whole sequence at once (tests, replays). */
export function reducePlanEvents(
  events: readonly UIEvent[],
  options: { detail?: Extract<PlanEventsAction, { type: "detail" }>["detail"]; end?: PlanStatus } = {},
): PlanLiveState {
  let state = initialPlanLiveState();
  if (options.detail) state = planEventsReducer(state, { type: "detail", detail: options.detail });
  state = planEventsReducer(state, { type: "events", events });
  if (options.end) state = planEventsReducer(state, { type: "end", status: options.end });
  return state;
}

// --- selectors --------------------------------------------------------------------------------

/** Milliseconds shown as "tempo trascorso": from `startedAt` to `stoppedAt`, or to `nowMs`. */
export function elapsedMs(state: PlanLiveState, nowMs: number): number {
  const start = time(state.startedAt);
  if (Number.isNaN(start)) return 0;
  const stop = state.stoppedAt ? time(state.stoppedAt) : nowMs;
  return Math.max(0, stop - start);
}

/** Cost over budget for the cost bar, clamped to [0, 1]; null when either is unknown. */
export function costProgress(state: PlanLiveState): number | null {
  if (state.costCents === null || !state.budgetCents) return null;
  return Math.min(1, Math.max(0, state.costCents / state.budgetCents));
}

/** The lane to keep open on a phone: the most recently active working lane, else the
 * coordinator. */
export function activeLane(state: PlanLiveState): AgentName {
  let best: Lane | null = null;
  for (const agent of AGENTS) {
    const lane = state.lanes[agent];
    if (lane.state !== "working") continue;
    if (!best || time(lane.lastActivityAt) > time(best.lastActivityAt)) best = lane;
  }
  return best?.agent ?? "coordinator";
}
