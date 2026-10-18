/**
 * Readers of `UIEvent.detail`, the open object the backend fills in `events.normalize` (and in
 * its own status and submit_plan events). schema/ui_event.json leaves `detail` free-form, so
 * every reader here is tolerant: a missing or mistyped key gives `null`, never an exception,
 * and the reducer then falls back to what `kind`, `agent` and `title` say.
 *
 * The vocabulary is the backend's (backend/app/events.py, "`detail` vocabulary"; consumer.py
 * and sessions.py for the events the backend makes itself). The first key is the backend's;
 * the others are older aliases, still accepted. __fixtures__/backend/ holds real events from
 * the backend's normalizer (web/scripts/gen-backend-fixtures.py), and the tests read them.
 *
 * | key                              | kinds       | meaning                                          |
 * |----------------------------------|-------------|--------------------------------------------------|
 * | event_type / type                | any         | Managed Agents type ("backend.status", "backend. |
 * |                                  |             | submit_plan" for the backend's own events)       |
 * | stop_reason (str or {type})      | status      | idle stop reason: end_turn, requires_action, ... |
 * | plan_status                      | status      | the plan's new status (backend.status events)    |
 * | budget_cents                     | status/usage| the session's budget cap ("Continua")            |
 * | lane_state / agent_state         | status      | explicit lane state: waiting/working/done/error  |
 * | tool / name                      | tool, plan  | tool name                                        |
 * | server / mcp_server(_name)       | tool, error | MCP server of the call, or of the failure        |
 * | params / input                   | tool        | main parameters (never results)                  |
 * | duration_ms / ms                 | tool        | duration, set on the tool's result               |
 * | tool_use_id                      | tool, plan  | pairs a result with its call                     |
 * | is_error                         | tool, plan  | the call failed                                  |
 * | sender / from, recipient / to    | message     | Italian lane label ("coordinatore", "voli", ...) |
 * |                                  |             | or AgentName; "utente" and others: not a lane    |
 * | text                             | message     | the message text ("clic per leggere")            |
 * | outcome / accepted               | plan        | submit_plan "accepted" / "rejected"              |
 * | errors                           | plan        | rejection lines                                  |
 * | error_type                       | error       | e.g. mcp_connection_failed_error                 |
 * | retry_status                     | error       | retrying, exhausted, terminal                    |
 * | severity                         | error       | warning (the plan goes on) or error              |
 * | source                           | error       | a failed source that is not an MCP server        |
 */

import type { PlanStatus } from "../schemas/api";
import type { AgentName, UIEvent } from "../schemas/generated/ui-event";
import { AGENTS, PLAN_STATUS_LABELS, type LaneState } from "./labels";

// Membership checks against the labels' own lists, not the zod enums: this module is on the demo's
// first load, and two enum checks would bring zod and every schema with them.
const AGENT_NAMES: ReadonlySet<string> = new Set(AGENTS);
const isAgentName = (value: string): value is AgentName => AGENT_NAMES.has(value);
const isPlanStatus = (value: unknown): value is PlanStatus =>
  typeof value === "string" && Object.hasOwn(PLAN_STATUS_LABELS, value);

type Detail = UIEvent["detail"];

function pick(detail: Detail, keys: readonly string[]): unknown {
  if (!detail) return undefined;
  for (const key of keys) {
    if (key in detail && detail[key] !== null && detail[key] !== undefined) return detail[key];
  }
  return undefined;
}

function readString(detail: Detail, ...keys: string[]): string | null {
  const value = pick(detail, keys);
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function readInt(detail: Detail, ...keys: string[]): number | null {
  const value = pick(detail, keys);
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function readBoolean(detail: Detail, ...keys: string[]): boolean | null {
  const value = pick(detail, keys);
  return typeof value === "boolean" ? value : null;
}

/** The backend's Italian lane labels (events.AGENT_LABELS), as `sender` / `recipient` carry
 * them. Other labels ("utente", "subagente", "consulente", an unknown agent's name) are not a
 * lane. */
const AGENT_BY_LABEL: ReadonlyMap<string, AgentName> = new Map<string, AgentName>([
  ["coordinatore", "coordinator"],
  ["voli", "flights"],
  ["alloggio", "lodging"],
  ["attività", "activities"],
  ["spostamenti", "transport"],
]);

function readAgent(detail: Detail, ...keys: string[]): AgentName | null {
  const value = pick(detail, keys);
  if (typeof value !== "string") return null;
  const key = value.trim().normalize("NFC").toLocaleLowerCase("it");
  if (isAgentName(key)) return key;
  return AGENT_BY_LABEL.get(key) ?? null;
}

/** The Managed Agents event type behind the UI event, e.g. "session.thread_status_idle", or the
 * backend's own ("backend.status", "backend.submit_plan"). */
export function readEventType(detail: Detail): string | null {
  return readString(detail, "event_type", "type");
}

/** `stop_reason` of an idle event, as a plain string ("end_turn", "budget_reached", ...). */
export function readStopReason(detail: Detail): string | null {
  const value = pick(detail, ["stop_reason"]);
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && "type" in value && typeof value.type === "string") {
    return value.type;
  }
  return null;
}

/** `event_ids` of a `requires_action` idle: the tool calls the agent is waiting on. */
export function readPendingEventIds(detail: Detail): string[] {
  const value = pick(detail, ["event_ids"]);
  return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
}

export function readPlanStatus(detail: Detail): PlanStatus | null {
  const value = pick(detail, ["plan_status"]);
  return isPlanStatus(value) ? value : null;
}

export function readBudgetCents(detail: Detail): number | null {
  return readInt(detail, "budget_cents");
}

const EXPLICIT_LANE_STATES: ReadonlySet<string> = new Set(["waiting", "working", "done", "error"]);

export function readAgentState(detail: Detail): LaneState | null {
  const value = readString(detail, "lane_state", "agent_state");
  return value && EXPLICIT_LANE_STATES.has(value) ? (value as LaneState) : null;
}

export interface ToolDetail {
  tool: string | null;
  server: string | null;
  params: Record<string, unknown> | null;
  durationMs: number | null;
  toolUseId: string | null;
  isError: boolean;
}

export function readTool(detail: Detail): ToolDetail {
  const params = pick(detail, ["params", "input"]);
  return {
    tool: readString(detail, "tool", "name"),
    server: readString(detail, "server", "mcp_server", "mcp_server_name"),
    params:
      params && typeof params === "object" && !Array.isArray(params)
        ? (params as Record<string, unknown>)
        : null,
    durationMs: readInt(detail, "duration_ms", "ms"),
    toolUseId: readString(detail, "tool_use_id"),
    isError: readBoolean(detail, "is_error") ?? false,
  };
}

export interface MessageDetail {
  from: AgentName | null;
  to: AgentName | null;
  text: string | null;
}

export function readMessage(detail: Detail): MessageDetail {
  return {
    from: readAgent(detail, "sender", "from"),
    to: readAgent(detail, "recipient", "to"),
    text: readString(detail, "text"),
  };
}

export interface PlanOutcome {
  /** True when submit_plan was accepted, false when rejected, null when the event doesn't say. */
  accepted: boolean | null;
  errors: string[];
}

export function readPlanOutcome(detail: Detail): PlanOutcome {
  let accepted = readBoolean(detail, "accepted");
  if (accepted === null) {
    const outcome = readString(detail, "outcome");
    if (outcome === "accepted") accepted = true;
    else if (outcome === "rejected") accepted = false;
  }
  const errors = pick(detail, ["errors"]);
  return {
    accepted,
    errors: Array.isArray(errors) ? errors.filter((line): line is string => typeof line === "string") : [],
  };
}

export interface SourceFailure {
  /** The MCP server or source that failed, e.g. "kiwi"; null when unnamed. */
  source: string | null;
}

/** An `error` event that reports a failed SOURCE (an MCP server that didn't answer), which the
 * lane shows as a warning, not as an agent error. Null for any other error. */
export function readSourceFailure(detail: Detail): SourceFailure | null {
  const server = readString(detail, "server", "mcp_server", "mcp_server_name");
  const errorType = readString(detail, "error_type");
  const source = readString(detail, "source");
  if (server || source || errorType?.startsWith("mcp_")) {
    return { source: server ?? source };
  }
  return null;
}

/** An error the plan survives: the backend marks it `severity: warning`, or the platform is
 * still retrying it (`retry_status: retrying`). A lane warning, not a failure. */
export function isWarningError(detail: Detail): boolean {
  return readString(detail, "severity") === "warning" || readString(detail, "retry_status") === "retrying";
}

/** Managed Agents events the consumer may change the plan's status with, in the same
 * transaction (backend-interfaces §5): `session.status_idle` (budget_paused, ready, failed,
 * blocked), the session's end, a terminal error. `budget_paused` is not terminal, so no
 * `event: end` follows it: the page re-reads GET /plans/{id} after these. */
const PLAN_STATUS_EVENT_TYPES: ReadonlySet<string> = new Set([
  "session.status_idle",
  "session.status_terminated",
  "session.deleted",
  "session.error",
]);

/** True when the event may come with a new plan status, so the GET /plans/{id} snapshot is
 * worth re-reading: an explicit `plan_status` (the backend's status events) or one of
 * `PLAN_STATUS_EVENT_TYPES`. */
export function mayChangePlanStatus(detail: Detail): boolean {
  if (readPlanStatus(detail)) return true;
  const type = readEventType(detail);
  return type !== null && PLAN_STATUS_EVENT_TYPES.has(type);
}
