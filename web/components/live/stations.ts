/**
 * The live screen's view of each lane: the reducer's state (lib/plan-events) turned into the
 * stations a Linee line draws (web/DESIGN.md, "Lane line"). Pure, so it is tested on the
 * backend's own fixtures.
 *
 * What it decides, beyond the reducer:
 * - A tool call is one station: its use gives the title ("Expedia · voli MXP→LIS · 14–18 nov")
 *   and its result, paired by `tool_use_id`, the second line (the duration, or the failure). The
 *   call still running is not a station: it is the live plate at the end of the line.
 * - Status events are stations only when they change what the lane is doing ("Incarico a voli",
 *   "Turno concluso", "Fermo: budget della sessione raggiunto") or come from the backend ("Piano
 *   avviato"). Thinking, model requests, usage and unknown types say nothing to the user.
 * - A message between two lanes shows on both (the backend sends one event, on the subagent's
 *   lane); the agent's own turn output (`agent.message`) stays on its lane. What agents write to
 *   each other is English (`lang="en"`).
 * - The waves of the run ("Ondata 1", "Scelta", "Ondata 2") are named stations on the
 *   coordinator's line (the Partitura borrowing): wave 1 opens with the first brief, the choice
 *   comes when every briefed subagent has reported, wave 2 opens with the next brief.
 * - The agents' file handling ("Scrive results/flights.json.tmp", "Comando: mv ...", reading a
 *   results file) is plumbing, not work the user decides on: reads and the coordinator's writes
 *   disappear, a subagent's writes merge into one quiet "Consegna l'esito" station, and the
 *   English "flights.json v1 written" hand-off shows only on the coordinator's line. The events
 *   stay in the data. A file call that failed is still shown.
 * - Messages between agents are English; their row says what they are in Italian ("coordinatore
 *   → voli: incarico", "voli → coordinatore: esito consegnato") and the English text stays inside
 *   the disclosure (`lang="en"`).
 * - The coordinator's questions to the traveller (`ask_traveller`, lib/choices.ts): the raw tool
 *   call, its result (even an error one: on an interrupt the answered "closed" event tells it) and
 *   the `requires_action` idle that waits on it are no stations. The open question is
 *   `LaneView.asking`, drawn as a plate at the end of the coordinator's line; its answer is a
 *   lozenge (`message`) with the question underneath; a question a stopped plan never got
 *   answered stays as a status station, "Senza risposta".
 * - A source that did not answer (an MCP server) is a notice on the lane whose tool used it, not
 *   a station and not a plan error; a retried error the plan survives is a red-ring station.
 */

import { ASK_TRAVELLER_TOOL, readAskedChoice, readChoiceAnswer } from "@/lib/choices";
import {
  isWarningError,
  readAgentState,
  readBudgetCents,
  readEventType,
  readMessage,
  readPendingEventIds,
  readPlanOutcome,
  readSourceFailure,
  readStopReason,
  readTool,
} from "@/lib/plan-events/detail";
import { AGENT_LABELS, AGENTS, type LaneBadgeState, type LaneState } from "@/lib/plan-events/labels";
import type { CurrentTool, PlanLiveState } from "@/lib/plan-events/reducer";
import type { PlanStatus } from "@/lib/schemas/api";
import type { AgentName, UIEvent } from "@/lib/schemas/generated/ui-event";

export type StationKind = "tool" | "failed" | "status" | "wave" | "message" | "error";

export interface StationMessage {
  /** "coordinatore → voli", as the backend titled it. */
  route: string;
  /** The message's first line from the title (cut by the backend), or null. */
  firstLine: string | null;
  /** The whole text, shown when the row is opened. */
  text: string | null;
  /** Language of the text: "en" for what agents write to each other and the backend's brief;
   * null inherits the page's Italian. */
  lang: "en" | null;
  /** Language of the first line in the title: the brief's is the backend's Italian name for it
   * ("richiesta di viaggio"), a quoted message's is the message's own. */
  firstLineLang: "en" | null;
}

export interface Station {
  /** Unique within the lane, stable across renders (React key). */
  key: string;
  /** The event the station stands for (a wave: the event that opened or closed it). */
  seq: number;
  kind: StationKind;
  ts: string;
  title: string;
  /** The second line: a duration, a failure, a wave's lanes. */
  meta: string | null;
  metaTone: "default" | "error";
  message: StationMessage | null;
}

export interface LaneNotice {
  key: string;
  /** The failed source (MCP server), when the event names it. */
  source: string | null;
  title: string;
}

export interface LaneView {
  agent: AgentName;
  state: LaneState;
  /** What the lane's badge says: `state`, except "non partita" for a lane that never got an event
   * on a plan that is over (it will not run any more, so "in attesa" would promise too much). */
  badge: LaneBadgeState;
  stations: Station[];
  /** The tool running now: the live plate. Null unless the lane works on a running plan. */
  live: CurrentTool | null;
  /** The traveller's open question, the coordinator's only: the plate that waits at the end of
   * its line. `seq` is null when the question comes from the snapshot. */
  asking: { title: string; seq: number | null; ts: string } | null;
  /** Sources that did not answer, one per source, newest wording. */
  notices: LaneNotice[];
  /** One line for a collapsed lane, and under the name on desktop when no tool runs. */
  summary: string;
  /** The lane's error, when it stopped on one. */
  errorTitle: string | null;
}

/** Shown under a question the plan stopped on without an answer. */
export const UNANSWERED_META = "Senza risposta";

export const WAVE_NAMES = { first: "Ondata 1", choice: "Scelta", second: "Ondata 2" } as const;

const RUNNING_TYPES = new Set(["session.thread_status_running", "session.status_running"]);
const IDLE_TYPES = new Set(["session.thread_status_idle", "session.status_idle"]);
const ENDED_TYPES = new Set(["session.thread_status_terminated", "session.status_terminated", "session.deleted"]);
/** Tool results (the reducer's list): they close a call, they are not stations. */
const RESULT_TYPES = new Set(["agent.tool_result", "agent.mcp_tool_result", "user.custom_tool_result", "user.tool_result"]);
const SUBAGENTS: readonly AgentName[] = AGENTS.filter((agent) => agent !== "coordinator");

/** How a file-handling call shows: `handover` (a subagent writing its result) merges into one
 * station, `hidden` leaves no trace. Null: a call the user should see. */
export type Plumbing = "handover" | "hidden";

const FILE_WRITE_TOOLS = new Set(["write", "edit", "multiedit", "str_replace_based_edit_tool"]);
const FILE_READ_TOOLS = new Set(["read", "glob", "grep", "ls"]);
const SHELL_WRITE = /^Comando:\s*(mv|cp|mkdir|touch|tee)\b/;

/** Reads a tool call's fields (the event's, or the reducer's `CurrentTool`). */
export function plumbingOf(agent: AgentName, call: { tool: string | null; title: string }): Plumbing | null {
  const tool = call.tool?.toLowerCase() ?? null;
  const title = call.title;
  let writes: boolean;
  if ((tool !== null && FILE_WRITE_TOOLS.has(tool)) || title.startsWith("Scrive ")) writes = true;
  else if ((tool !== null && FILE_READ_TOOLS.has(tool)) || (title.startsWith("Legge ") && !title.startsWith("Legge la pagina"))) writes = false;
  else if (title.startsWith("Comando:")) writes = SHELL_WRITE.test(title);
  else return null;
  return writes && agent !== "coordinator" ? "handover" : "hidden";
}

/** True for a call that adds a file (a rename of one already counted adds none). */
function addsFile(call: { tool: string | null; title: string }): boolean {
  const tool = call.tool?.toLowerCase() ?? null;
  return (tool !== null && FILE_WRITE_TOOLS.has(tool)) || call.title.startsWith("Scrive ");
}

export const HANDOVER_TITLE = "Consegna l'esito";

/** What a station list last said the lane was doing, to drop repeated "Al lavoro". */
type Shown = LaneState | "paused" | null;

// --- small formatting ---------------------------------------------------------------------------

function decimal(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1).replace(".", ",");
}

/** A tool call's duration: "meno di 1 s", "2,7 s", "1 min 5 s". */
export function formatDuration(ms: number): string {
  if (ms < 1000) return "meno di 1 s";
  if (ms < 60_000) return `${decimal(ms / 1000)} s`;
  const seconds = Math.round(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** "voli", "voli e alloggio", "voli, alloggio e attività". */
export function joinItalian(items: readonly string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} e ${items[items.length - 1]}`;
}

function laneName(agent: AgentName): string {
  return AGENT_LABELS[agent].toLocaleLowerCase("it");
}

/** "a voli, alloggio e attività", "ad alloggio": the euphonic d before a vowel a. */
function toLanes(agents: readonly AgentName[]): string {
  const list = joinItalian(agents.map(laneName));
  return list.startsWith("a") ? `ad ${list}` : `a ${list}`;
}

/** "coordinatore → voli: Find round-trip…" -> route and first line. */
function splitMessageTitle(title: string): { route: string; firstLine: string | null } {
  const arrow = title.indexOf("→");
  const colon = arrow >= 0 ? title.indexOf(": ", arrow) : -1;
  if (colon < 0) return { route: title, firstLine: null };
  return { route: title.slice(0, colon), firstLine: title.slice(colon + 2) || null };
}

function isEmptyDetail(detail: UIEvent["detail"]): boolean {
  return !detail || Object.keys(detail).length === 0;
}

// --- waves --------------------------------------------------------------------------------------

/** The subagent an event briefs: a thread created for it, or a message the coordinator sends it.
 * Null for anything else. */
function briefTarget(event: UIEvent): AgentName | null {
  const type = readEventType(event.detail);
  if (event.kind === "status" && type === "session.thread_created" && event.agent !== "coordinator") {
    return event.agent;
  }
  if (event.kind === "message" && type !== "agent.message") {
    const { from, to } = readMessage(event.detail);
    if (from === "coordinator" && to !== null && to !== "coordinator") return to;
  }
  return null;
}

/** How a subagent's event closes its turn: `failed` (an error ended it: the coordinator reads the
 * failure), `ended` (it went idle or was terminated: that is a hand-over only when it delivered
 * something, an interrupted lane ends its turn with nothing to read), or null. */
function turnEnd(event: UIEvent): "failed" | "ended" | null {
  if (event.agent === "coordinator") return null;
  const detail = event.detail;
  if (event.kind === "error") return !readSourceFailure(detail) && !isWarningError(detail) ? "failed" : null;
  if (event.kind !== "status") return null;
  const type = readEventType(detail);
  if (readAgentState(detail) === "error") return "failed";
  if (type && ENDED_TYPES.has(type)) return "ended";
  if (type && IDLE_TYPES.has(type)) {
    const reason = readStopReason(detail);
    return reason !== "budget_reached" && reason !== "requires_action" ? "ended" : null;
  }
  return readAgentState(detail) === "done" ? "ended" : null;
}

interface WaveTracker {
  phase: "before" | "first" | "choice" | "second";
  outstanding: Set<AgentName>;
  current: Station | null;
  lanes: AgentName[];
  /** The "Scelta" station still waiting for the coordinator's decision to quote on it. */
  choice: Station | null;
  /** Subagents that delivered (a message to the coordinator or a results file) since their last
   * brief: only a delivery lets an idle turn count as a report. */
  delivered: Set<AgentName>;
  /** Deliveries in the wave now open: a wave nobody delivered in leaves nothing to choose from. */
  waveDeliveries: number;
}

function markDelivered(waves: WaveTracker, agent: AgentName): void {
  if (waves.phase === "before" || waves.delivered.has(agent)) return;
  waves.delivered.add(agent);
  waves.waveDeliveries += 1;
}

function waveStation(name: string, event: UIEvent, meta: string): Station {
  return {
    key: `wave:${name}`,
    seq: event.seq,
    kind: "wave",
    ts: event.ts,
    title: name,
    meta,
    metaTone: "default",
    message: null,
  };
}

// --- lanes --------------------------------------------------------------------------------------

interface OpenCall {
  station: Station;
  toolUseId: string | null;
  /** A submit_plan call: its verdict is a station of its own ("Piano respinto: ..."), so the
   * answer closes it without changing it. */
  submission: boolean;
  /** A file-handling call: its station is shared (handover) or not drawn (hidden). */
  plumbing: Plumbing | null;
}

interface LaneBuild {
  stations: Station[];
  shown: Shown;
  open: OpenCall[];
  notices: Map<string, LaneNotice>;
  reported: boolean;
  /** The lane's "Consegna l'esito" station, while it is the one the next write may join. */
  handover: Station | null;
  /** The English hand-off message that follows it was already left out of this lane. */
  handoverClaimed: boolean;
  files: number;
  /** Briefs this lane received from the coordinator ("incarico", then "nuovo incarico"). */
  briefs: number;
}

function statusStation(event: UIEvent, shown: Shown, asks: ReadonlySet<string>): { station: Station | null; next: Shown } {
  const detail = event.detail;
  const base = { key: String(event.seq), seq: event.seq, ts: event.ts, title: event.title, meta: null, metaTone: "default" as const, message: null };
  const show = (kind: StationKind, next: Shown) => ({ station: { ...base, kind }, next });
  const hide = (next: Shown = shown) => ({ station: null, next });
  const type = readEventType(detail);

  // The backend's own events ("Piano avviato", "Budget aumentato: si riprende").
  if (isEmptyDetail(detail) || type === null || type.startsWith("backend.")) return show("status", shown);
  if (type === "session.thread_created") return show("status", "working");
  if (IDLE_TYPES.has(type)) {
    switch (readStopReason(detail)) {
      case "budget_reached":
        return show("status", "paused");
      case "requires_action": {
        // A pause on the traveller is told by the question's own station, not by this one.
        const pending = readPendingEventIds(detail);
        if (pending.length > 0 && pending.every((id) => asks.has(id))) return hide();
        return show("status", "waiting");
      }
      case "retries_exhausted":
      case "refusal":
        return show("error", "error");
      default:
        return show("status", "done");
    }
  }
  if (RUNNING_TYPES.has(type)) return shown === "working" ? hide("working") : show("status", "working");
  if (ENDED_TYPES.has(type)) return shown === "done" ? hide("done") : show("status", "done");
  if (type === "session.status_rescheduled") return show("status", shown);
  if (type === "session.updated" && readBudgetCents(detail) !== null) return show("status", shown);
  const explicit = readAgentState(detail);
  if (explicit && explicit !== shown) return show(explicit === "error" ? "error" : "status", explicit);
  // Thinking, model requests, unknown event types: the lane is alive, nothing to draw.
  return hide();
}

/** What an agent-to-agent message is, in Italian: the row's subject ("coordinatore → voli:
 * incarico"). Null for a message that is already Italian prose (the agent's own turn output). */
function messageSubject(event: UIEvent, briefs: number): string | null {
  const type = readEventType(event.detail);
  if (type === "agent.message" || type === "user.message") return null;
  const { from, to } = readMessage(event.detail);
  if (from === "coordinator" && to !== null && to !== "coordinator") return briefs > 1 ? "nuovo incarico" : "incarico";
  if (to === "coordinator" && from !== null) return "esito consegnato";
  return null;
}

function messageStation(event: UIEvent, key: string, subject: string | null): Station {
  const { from, to, text } = readMessage(event.detail);
  const type = readEventType(event.detail);
  const { route, firstLine } = splitMessageTitle(event.title);
  const brief = type === "user.message";
  const english = (from !== null && to !== null) || brief;
  // An English message gets an Italian row; its text stays English inside the disclosure.
  const italian = english && !brief && subject !== null;
  return {
    key,
    seq: event.seq,
    kind: "message",
    ts: event.ts,
    title: italian ? `${route}: ${subject}` : event.title,
    meta: null,
    metaTone: "default",
    message: {
      route,
      firstLine: italian ? subject : firstLine,
      text,
      lang: english ? "en" : null,
      firstLineLang: english && !brief && !italian ? "en" : null,
    },
  };
}

/** True for the English hand-off a subagent sends the coordinator once its result file is
 * written ("flights.json v1 written: ..."). */
function isHandoff(event: UIEvent): boolean {
  if (event.agent === "coordinator" || event.kind !== "message") return false;
  if (readEventType(event.detail) === "agent.message") return false;
  const { from, to } = readMessage(event.detail);
  return from === event.agent && to === "coordinator";
}

/** The first sentence of a coordinator's message, about 90 characters, for a wave's second line. */
export function firstSentence(text: string, limit = 90): string {
  const flat = text.replace(/\s+/g, " ").trim().replace(/^Scelta:\s*/i, "");
  const end = flat.search(/[.!?](\s|$)/);
  const sentence = end >= 0 ? flat.slice(0, end + 1) : flat;
  const cleaned = sentence.charAt(0).toLocaleUpperCase("it") + sentence.slice(1);
  if (cleaned.length <= limit) return cleaned;
  const cut = cleaned.slice(0, limit - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > limit / 2 ? cut.slice(0, space) : cut).replace(/[\s,;:(]+$/, "")}…`;
}

/** The lanes a message also shows on: the other party, when both ends are lanes. */
function mirrorLanes(event: UIEvent): AgentName[] {
  if (readEventType(event.detail) === "agent.message") return [];
  const { from, to } = readMessage(event.detail);
  if (from === null || to === null || from === to) return [];
  return [from, to].filter((agent) => agent !== event.agent);
}

function closeCall(build: LaneBuild, event: UIEvent): void {
  const tool = readTool(event.detail);
  let index = tool.toolUseId ? build.open.findIndex((call) => call.toolUseId === tool.toolUseId) : -1;
  if (index < 0 && !tool.toolUseId) index = build.open.length - 1;
  const call = index >= 0 ? build.open[index] : undefined;
  if (!call) return;
  build.open.splice(index, 1);
  if (call.submission) return;
  const station = call.station;
  if (call.plumbing) {
    // Quiet unless it failed: then the lane says so in plain words.
    if (!tool.isError) return;
    if (call.plumbing === "handover" && build.handover) {
      build.handover.kind = "failed";
      build.handover.meta = event.title;
      build.handover.metaTone = "error";
    } else {
      build.stations.push({ ...station, kind: "failed", title: "Un passaggio sui file non è riuscito", meta: event.title, metaTone: "error" });
    }
    return;
  }
  if (tool.isError) {
    station.kind = "failed";
    station.meta = event.title;
    station.metaTone = "error";
  } else if (tool.durationMs !== null) {
    station.meta = formatDuration(tool.durationMs);
  }
}

/** What the present holds beyond the lane's own tool, for the line under a working lane's name. */
interface Present {
  /** Briefed subagents that have not delivered yet, in the roster's order. */
  outstanding: readonly AgentName[];
  /** The coordinator sent the plan and waits for the backend's verdict. */
  verifying: boolean;
  /** The lane's newest station. */
  last: Station | null;
  /** The traveller's answer, while it is the lane's newest station (the coordinator's). */
  answer: string | null;
}

/** A working lane with no tool running says something true about now, not "thinking" twice:
 * the coordinator what it waits for, a subagent where it got to. Right after the traveller
 * answered, the coordinator's line says the answer ("Hai scelto: …"), until it moves on: on the
 * phone its card is closed, and the line is all that shows of it. */
function workingLine(agent: AgentName, present: Present): string {
  if (agent === "coordinator") {
    if (present.answer) return present.answer;
    if (present.verifying) return "Verifica il piano.";
    if (present.outstanding.length > 0) return `Aspetta ${joinItalian(present.outstanding.map(laneName))}.`;
    return "Ragiona sul prossimo passo.";
  }
  if (present.last) return `Ultimo passo: ${present.last.title}`;
  return "Ragiona sul prossimo passo.";
}

function summaryFor(
  agent: AgentName,
  state: LaneState,
  build: LaneBuild,
  planStatus: PlanStatus | null,
  planAccepted: boolean,
  hasWork: boolean,
  blocker: Blocker | null,
  present: Present,
): string {
  switch (state) {
    case "waiting": {
      const over = planStatus !== null && planStatus !== "running" && planStatus !== "budget_paused";
      if (hasWork) return "Aspetta una risposta.";
      if (over) return "Non è partito.";
      return agent === "coordinator" ? "Avvio della sessione." : "Aspetta l'incarico del coordinatore.";
    }
    case "working":
      return workingLine(agent, present);
    case "done":
      if (agent === "coordinator") return planAccepted ? "Piano consegnato." : "Turno concluso.";
      return build.reported ? "Esito consegnato al coordinatore." : "Turno concluso.";
    case "error":
      // The coordinator of a failed or blocked plan: the state panel above says why.
      if (agent === "coordinator" && (planStatus === "failed" || planStatus === "blocked")) return "Il piano si è fermato.";
      return "Si è fermato per un errore.";
    case "stopped":
      if (blocker?.agent === agent) {
        return blocker.source ? `Aspettava il permesso per usare ${blocker.source}.` : "Aspettava un permesso che nessuno può dare.";
      }
      if (planStatus === "budget_paused") return "Fermo: budget della sessione raggiunto.";
      if (planStatus === "interrupted") return "Fermo: il piano è stato interrotto.";
      return "Fermo: il piano si è chiuso.";
  }
}

/** The agent and the source a blocked plan was waiting on: the permission an `always_ask` tool
 * asked for and nobody can give (the web app has no way to confirm it). */
export interface Blocker {
  agent: AgentName;
  /** The tool's source as the title names it ("lastminute.com"); null when it names none. */
  source: string | null;
}

export function findBlocker(state: PlanLiveState): Blocker | null {
  for (let index = state.events.length - 1; index >= 0; index -= 1) {
    const event = state.events[index];
    if (!event || event.kind !== "status" || event.agent === "coordinator") continue;
    if (!IDLE_TYPES.has(readEventType(event.detail) ?? "") || readStopReason(event.detail) !== "requires_action") continue;
    const pending = new Set(readPendingEventIds(event.detail));
    const call = state.lanes[event.agent].events.findLast((candidate) => {
      const id = candidate.kind === "tool" ? readTool(candidate.detail).toolUseId : null;
      return id !== null && pending.has(id);
    });
    const first = call && call.title.includes(" · ") ? (call.title.split(" · ")[0] ?? "") : "";
    const source = first.replace(/\s*\(attende conferma\)$/, "").trim();
    return { agent: event.agent, source: source === "" ? null : source };
  }
  return null;
}

/** Where a failed source's notice goes: the lane whose tool last called that server. */
function sourceLane(calls: readonly { seq: number; server: string; lane: AgentName }[], source: string, seq: number): AgentName | null {
  const wanted = source.toLocaleLowerCase("en");
  let before: AgentName | null = null;
  let after: AgentName | null = null;
  for (const call of calls) {
    if (call.server.toLocaleLowerCase("en") !== wanted) continue;
    if (call.seq <= seq) before = call.lane;
    else if (after === null) after = call.lane;
  }
  return before ?? after;
}

/** Every lane's stations, live tool, notices and one-line summary. */
export function buildLaneViews(state: PlanLiveState): Record<AgentName, LaneView> {
  const emptyBuild = (): LaneBuild => ({
    stations: [],
    shown: null,
    open: [],
    notices: new Map(),
    reported: false,
    handover: null,
    handoverClaimed: false,
    files: 0,
    briefs: 0,
  });
  const builds: Record<AgentName, LaneBuild> = {
    coordinator: emptyBuild(),
    flights: emptyBuild(),
    lodging: emptyBuild(),
    activities: emptyBuild(),
    transport: emptyBuild(),
  };
  const waves: WaveTracker = { phase: "before", outstanding: new Set(), current: null, lanes: [], choice: null, delivered: new Set(), waveDeliveries: 0 };
  const serverCalls: { seq: number; server: string; lane: AgentName }[] = [];
  const failures: { event: UIEvent; source: string | null }[] = [];
  /** Tool use ids of the `ask_traveller` calls. */
  const asks = new Set<string>();
  /** Asked questions by choice id: the question for the answer's second line, and the station a
   * stopped plan keeps when nobody answered. */
  const asked = new Map<string, { question: string; station: Station }>();
  /** The keys of the answers' stations: while one is the coordinator's newest, its line says it. */
  const answers = new Set<string>();

  for (const event of state.events) {
    const build = builds[event.agent];
    const coordinator = builds.coordinator;

    // Waves open before the brief that starts them.
    const target = briefTarget(event);
    if (target && event.kind === "message") builds[target].briefs += 1;
    if (target) {
      if (waves.phase === "before" || waves.phase === "choice") {
        const second = waves.phase === "choice";
        waves.phase = second ? "second" : "first";
        waves.choice = null;
        waves.lanes = [];
        waves.waveDeliveries = 0;
        waves.current = waveStation(second ? WAVE_NAMES.second : WAVE_NAMES.first, event, "");
        coordinator.stations.push(waves.current);
      }
      if (waves.current && !waves.lanes.includes(target)) {
        waves.lanes.push(target);
        const prefix = waves.current.title === WAVE_NAMES.first ? "Incarichi" : "Nuovi incarichi";
        waves.current.meta = `${prefix} ${toLanes(waves.lanes)}`;
      }
      waves.outstanding.add(target);
      waves.delivered.delete(target);
    }

    switch (event.kind) {
      case "status": {
        const { station, next } = statusStation(event, build.shown, asks);
        build.shown = next;
        if (station) build.stations.push(station);
        break;
      }
      case "tool": {
        const tool = readTool(event.detail);
        const type = readEventType(event.detail);
        // The question is told by its `choice` events; its result closes it without a trace.
        if (tool.tool === ASK_TRAVELLER_TOOL && tool.toolUseId) asks.add(tool.toolUseId);
        if (tool.toolUseId && asks.has(tool.toolUseId)) break;
        if (tool.durationMs !== null || (type !== null && RESULT_TYPES.has(type))) {
          closeCall(build, event);
          break;
        }
        const call = { tool: tool.tool, title: event.title };
        const plumbing = plumbingOf(event.agent, call);
        const station: Station = {
          key: String(event.seq),
          seq: event.seq,
          kind: "tool",
          ts: event.ts,
          title: event.title,
          meta: null,
          metaTone: "default",
          message: null,
        };
        if (plumbing === "handover") {
          // One quiet station per delivery: later writes of the same turn join it.
          if (build.handover && build.stations[build.stations.length - 1] === build.handover) {
            if (addsFile(call)) build.files += 1;
          } else {
            build.files = 1;
            build.handoverClaimed = false;
            build.handover = { ...station, title: HANDOVER_TITLE };
            build.stations.push(build.handover);
            markDelivered(waves, event.agent);
          }
          build.handover.meta = `${build.files} file`;
        } else if (plumbing === null) {
          build.stations.push(station);
        }
        build.open.push({ station, toolUseId: tool.toolUseId, submission: false, plumbing });
        if (tool.server) serverCalls.push({ seq: event.seq, server: tool.server, lane: event.agent });
        break;
      }
      case "plan": {
        const outcome = readPlanOutcome(event.detail);
        const station: Station = {
          key: String(event.seq),
          seq: event.seq,
          kind: outcome.accepted === false ? "failed" : outcome.accepted === true ? "status" : "tool",
          ts: event.ts,
          title: event.title,
          meta: null,
          metaTone: "default",
          message: null,
        };
        build.stations.push(station);
        // The submission is a call: the backend's answer (a tool result) closes it.
        if (outcome.accepted === null) {
          build.open.push({ station, toolUseId: readTool(event.detail).toolUseId, submission: true, plumbing: null });
        }
        break;
      }
      case "message": {
        const { from, to } = readMessage(event.detail);
        const handoff = isHandoff(event);
        const subject = messageSubject(event, target ? builds[target].briefs : 0);
        // The delivery already has its own station on the subagent's line.
        if (handoff && build.handover && !build.handoverClaimed) build.handoverClaimed = true;
        else build.stations.push(messageStation(event, String(event.seq), subject));
        if (from === event.agent && to === "coordinator") {
          build.reported = true;
          markDelivered(waves, event.agent);
        }
        for (const other of mirrorLanes(event)) {
          builds[other].stations.push(messageStation(event, `${event.seq}:${other}`, subject));
        }
        // The coordinator's decision after the choice: quoted on the "Scelta" station.
        if (
          event.agent === "coordinator" &&
          waves.choice &&
          waves.phase === "choice" &&
          readEventType(event.detail) === "agent.message"
        ) {
          const text = readMessage(event.detail).text;
          if (text) waves.choice.meta = firstSentence(text);
          waves.choice = null;
        }
        break;
      }
      case "error": {
        const failure = readSourceFailure(event.detail);
        if (failure) {
          failures.push({ event, source: failure.source });
        } else if (isWarningError(event.detail)) {
          build.stations.push({
            key: String(event.seq),
            seq: event.seq,
            kind: "failed",
            ts: event.ts,
            title: event.title,
            meta: null,
            metaTone: "default",
            message: null,
          });
        } else {
          build.stations.push({
            key: String(event.seq),
            seq: event.seq,
            kind: "error",
            ts: event.ts,
            title: event.title,
            meta: null,
            metaTone: "default",
            message: null,
          });
          build.shown = "error";
        }
        break;
      }
      case "choice": {
        const question = readAskedChoice(event.detail);
        if (question) {
          // Kept in the line until the answer takes its place; the end drops it from a plan
          // that is still running (its question is the plate then).
          const station: Station = {
            key: String(event.seq),
            seq: event.seq,
            kind: "status",
            ts: event.ts,
            title: event.title,
            meta: UNANSWERED_META,
            metaTone: "default",
            message: null,
          };
          asked.set(question.id, { question: question.question, station });
          build.stations.push(station);
        }
        const answer = readChoiceAnswer(event.detail);
        if (answer) {
          const open = asked.get(answer.choiceId);
          if (open) {
            const at = build.stations.indexOf(open.station);
            if (at >= 0) build.stations.splice(at, 1);
          }
          build.stations.push({
            key: String(event.seq),
            seq: event.seq,
            kind: "message",
            ts: event.ts,
            title: event.title,
            meta: open?.question ?? null,
            metaTone: "default",
            message: null,
          });
          asked.delete(answer.choiceId);
          answers.add(String(event.seq));
        }
        break;
      }
      case "usage":
        break;
    }

    // The choice comes after the report that leaves no briefed subagent at work. A turn that ends
    // without a delivery (an interrupt) reports nothing; and a stopped plan whose wave delivered
    // nothing has nothing to choose from.
    const end = turnEnd(event);
    if (end === "failed" || (end === "ended" && waves.delivered.has(event.agent))) {
      waves.outstanding.delete(event.agent);
      const stopped = state.status === "interrupted" || state.status === "failed" || state.status === "blocked";
      if (waves.phase === "first" && waves.outstanding.size === 0 && !(stopped && waves.waveDeliveries === 0)) {
        waves.phase = "choice";
        waves.current = null;
        waves.choice = waveStation(WAVE_NAMES.choice, event, "Il coordinatore legge gli esiti e sceglie");
        coordinator.stations.push(waves.choice);
      }
    }
  }

  // A failed source is a notice on the lane that called it, newest wording per source.
  for (const { event, source } of failures) {
    const lane = (source ? sourceLane(serverCalls, source, event.seq) : null) ?? event.agent;
    const id = source ? `source:${source.toLocaleLowerCase("en")}` : `event:${event.seq}`;
    builds[lane].notices.set(id, { key: id, source, title: event.title });
  }

  const running = state.status === null || state.status === "running";
  // On a plan still going the unanswered question is the open one (the plate), not a station.
  if (running) {
    for (const { station } of asked.values()) {
      const at = builds.coordinator.stations.indexOf(station);
      if (at >= 0) builds.coordinator.stations.splice(at, 1);
    }
  }
  const blocker = state.status === "blocked" ? findBlocker(state) : null;
  const views = {} as Record<AgentName, LaneView>;
  for (const agent of AGENTS) {
    const lane = state.lanes[agent];
    const build = builds[agent];
    const open = state.openChoice;
    const asking = agent === "coordinator" && open ? { title: open.title, seq: open.seq, ts: open.ts } : null;
    let live = running && lane.state === "working" && lane.currentTool ? lane.currentTool : null;
    // The question is not a tool running: its plate is `asking`.
    if (live && live.tool === ASK_TRAVELLER_TOOL) live = null;
    let stations = build.stations;
    if (live) {
      const current = live;
      // A file call is not "where the lane is" (a delivery already has its station).
      if (plumbingOf(agent, current) !== null) live = null;
      stations = stations.filter((station) => station.key !== String(current.seq));
    }
    // Calls that never got an answer and are not running any more.
    if (lane.state !== "working" || !running) {
      for (const call of build.open) {
        if (!call.plumbing && call.station.meta === null && call.station.kind === "tool") call.station.meta = "Non concluso";
      }
    }
    const hasWork = lane.events.some((event) => event.kind !== "status" || !isEmptyDetail(event.detail));
    const planOver = state.status !== null && state.status !== "running" && state.status !== "budget_paused";
    const last = stations.findLast((station) => station.kind !== "wave") ?? null;
    views[agent] = {
      agent,
      state: lane.state,
      badge: lane.state === "waiting" && !hasWork && planOver ? "not_started" : lane.state,
      stations,
      live,
      asking,
      notices: [...build.notices.values()],
      summary:
        lane.state === "error" && lane.lastError
          ? lane.lastError.title
          : asking
            ? asking.title
            : summaryFor(agent, lane.state, build, state.status, state.planAccepted, hasWork, blocker, {
              outstanding: AGENTS.filter((other) => waves.outstanding.has(other)),
              verifying: build.open.some((call) => call.submission),
              last,
              answer: last !== null && answers.has(last.key) ? last.title : null,
            }),
      errorTitle: lane.state === "error" ? (lane.lastError?.title ?? null) : null,
    };
  }
  return views;
}

/** The lane to open on the phone: a subagent in error once the plan stopped; else the subagent
 * at work most recently active (that is where the work shows: the coordinator mostly waits for
 * them); else the coordinator. */
export function laneToOpen(views: Record<AgentName, LaneView>, state: PlanLiveState): AgentName {
  const failing = SUBAGENTS.find((agent) => views[agent].state === "error");
  if (failing && state.status !== "running") return failing;
  const stuck = state.status === "blocked" ? findBlocker(state) : null;
  if (stuck) return stuck.agent;
  let best: AgentName | null = null;
  let bestAt = Number.NEGATIVE_INFINITY;
  for (const agent of SUBAGENTS) {
    const lane = state.lanes[agent];
    if (lane.state !== "working") continue;
    const at = Date.parse(lane.lastActivityAt ?? "");
    if (best === null || at > bestAt) {
      best = agent;
      bestAt = at;
    }
  }
  return best ?? "coordinator";
}
