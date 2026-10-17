/**
 * Italian labels of the live timeline: agents, lane states, plan statuses, the stream's
 * connection. Code and keys are English; only these strings are shown to the user.
 */

import type { PlanStatus } from "../schemas/api";
import type { AgentName } from "../schemas/generated/ui-event";

/** The five lanes, in the order the timeline shows them. */
export const AGENTS: readonly AgentName[] = ["coordinator", "flights", "lodging", "activities", "transport"];

/** On-screen names of the agents: the spec's "coordinatore e quattro subagenti: voli, alloggio,
 * attività, spostamenti". */
export const AGENT_LABELS: Record<AgentName, string> = {
  coordinator: "Coordinatore",
  flights: "Voli",
  lodging: "Alloggio",
  activities: "Attività",
  transport: "Spostamenti",
};

/** What a lane is doing. The spec's four states (in attesa, al lavoro, finito, errore), plus
 * `stopped` for a lane that was working when the plan paused or stopped (budget reached,
 * interrupted, failed, blocked): it is neither working nor finished. */
export type LaneState = "waiting" | "working" | "done" | "error" | "stopped";

export const LANE_STATE_LABELS: Record<LaneState, string> = {
  waiting: "in attesa",
  working: "al lavoro",
  done: "finito",
  error: "errore",
  stopped: "fermato",
};

/** What a lane's badge can say: its state, or `not_started` for a lane of a plan that ended (or
 * stopped for good) before the lane ever got an event. "In attesa" promises work to come; this
 * lane will not get any, so the badge says what happened. */
export type LaneBadgeState = LaneState | "not_started";

export const LANE_BADGE_LABELS: Record<LaneBadgeState, string> = {
  ...LANE_STATE_LABELS,
  not_started: "non partita",
};

export const PLAN_STATUS_LABELS: Record<PlanStatus, string> = {
  running: "In corso",
  ready: "Pronto",
  failed: "Non riuscito",
  // "Limite", not "budget": the word "budget" stays with the trip's money (DESIGN.md, CostMeter).
  budget_paused: "Limite raggiunto",
  blocked: "Bloccato",
  interrupted: "Interrotto",
};

/** State of the SSE connection, for the discreet line at the top of the live page. */
export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

export const CONNECTION_LABELS: Record<ConnectionStatus, string> = {
  connecting: "Connessione in corso",
  open: "In diretta",
  reconnecting: "Stream in riconnessione",
  closed: "Stream chiuso",
};

/** "coordinatore → voli: incarico": the one-line form of a message between agents. Missing
 * ends are left out ("→ voli", "coordinatore →"). */
export function messageLine(from: AgentName | null, to: AgentName | null, subject?: string | null): string {
  const name = (agent: AgentName | null) => (agent ? AGENT_LABELS[agent].toLocaleLowerCase("it") : "");
  const route = [name(from), "→", name(to)].filter(Boolean).join(" ");
  return subject ? `${route}: ${subject}` : route;
}

/** The aria-live announcement of a lane's new state, e.g. "Voli: al lavoro". */
export function laneAnnouncement(agent: AgentName, state: LaneState): string {
  return `${AGENT_LABELS[agent]}: ${LANE_STATE_LABELS[state]}`;
}
