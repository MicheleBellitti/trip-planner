import { describe, expect, it } from "vitest";

import choices from "@/lib/plan-events/__fixtures__/backend/choices.json";
import budgetReached from "@/lib/plan-events/__fixtures__/backend/budget-reached.json";
import happyPath from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import mcpFailure from "@/lib/plan-events/__fixtures__/backend/mcp-failure.json";
import { reducePlanEvents } from "@/lib/plan-events/reducer";
import type { PlanDetail, PlanStatus } from "@/lib/schemas/api";
import { UIEventSchema, type UIEvent } from "@/lib/schemas/generated/ui-event";

import { buildLaneViews, findBlocker, firstSentence, formatDuration, joinItalian, laneToOpen, type Station } from "./stations";

function events(fixture: { events: unknown[] }): UIEvent[] {
  return fixture.events.map((event) => UIEventSchema.parse(event));
}

type DetailSnapshot = Pick<
  PlanDetail,
  "status" | "cost_cents" | "budget_cents" | "created_at" | "updated_at" | "failure_reason" | "submit_attempts"
>;

function detail(status: PlanStatus, events: UIEvent[]): DetailSnapshot {
  const last = events[events.length - 1];
  return {
    status,
    cost_cents: 0,
    budget_cents: 60,
    created_at: events[0]?.ts ?? "2026-10-12T10:00:00+02:00",
    updated_at: last?.ts ?? "2026-10-12T10:00:00+02:00",
    failure_reason: null,
    submit_attempts: 0,
  };
}

const titles = (stations: Station[]) => stations.map((station) => station.title);

describe("formatting", () => {
  it("formats durations the way a station's second line reads", () => {
    expect(formatDuration(184)).toBe("meno di 1 s");
    expect(formatDuration(2656)).toBe("2,7 s");
    expect(formatDuration(3000)).toBe("3 s");
    expect(formatDuration(65_000)).toBe("1 min 5 s");
    expect(formatDuration(120_000)).toBe("2 min");
  });

  it("joins lane names in Italian", () => {
    expect(joinItalian([])).toBe("");
    expect(joinItalian(["voli"])).toBe("voli");
    expect(joinItalian(["voli", "alloggio"])).toBe("voli e alloggio");
    expect(joinItalian(["voli", "alloggio", "attività"])).toBe("voli, alloggio e attività");
  });
});

describe("lane badges", () => {
  const started = (status: PlanStatus | null) => {
    const run = [
      {
        seq: 0,
        ts: "2026-10-12T10:00:00+02:00",
        agent: "coordinator",
        kind: "status",
        title: "Piano avviato",
        detail: null,
      },
    ] as unknown as UIEvent[];
    return buildLaneViews(reducePlanEvents(run, status ? { end: status } : {}));
  };

  it("keeps 'in attesa' for lanes that will still run: a plan that is running or paused on budget", () => {
    for (const status of [null, "running", "budget_paused"] as const) {
      const views = buildLaneViews(reducePlanEvents([], status ? { end: status } : {}));
      expect(views.transport.badge).toBe("waiting");
    }
    expect(started("budget_paused").transport.badge).toBe("waiting");
  });

  it("says 'non partita' for a lane with no events once the plan is over, whatever way it ended", () => {
    for (const status of ["ready", "failed", "blocked", "interrupted"] as const) {
      expect(started(status).transport.badge).toBe("not_started");
    }
  });
});

describe("buildLaneViews, happy path", () => {
  const all = events(happyPath);
  const state = reducePlanEvents(all, { end: "ready" });
  const views = buildLaneViews(state);
  const seqOf = (predicate: (event: UIEvent) => boolean) => {
    const found = all.find(predicate);
    if (!found) throw new Error("fixture event not found");
    return found.seq;
  };
  const typeOf = (event: UIEvent) => event.detail?.event_type;

  it("pairs each tool call with its result: one station, the duration underneath", () => {
    const flights = views.flights.stations;
    const expedia = flights.find((station) => station.title.startsWith("Expedia · voli"));
    expect(expedia).toMatchObject({ kind: "tool", meta: "2,7 s", metaTone: "default" });
    expect(titles(flights).some((title) => title.startsWith("Risultato ricevuto"))).toBe(false);
    expect(titles(flights).some((title) => title.startsWith("Risposta della fonte"))).toBe(false);
  });

  it("drops the noise and the repeated 'Al lavoro', keeps the lane's changes", () => {
    const flights = titles(views.flights.stations);
    expect(flights[0]).toBe("Incarico a voli");
    expect(flights).not.toContain("Al lavoro");
    expect(flights).not.toContain("Ragionamento in corso");
    expect(flights.at(-1)).toBe("Turno concluso");
    const coordinator = titles(views.coordinator.stations);
    expect(coordinator[0]).toBe("Piano avviato");
    expect(coordinator).not.toContain("Richiesta al modello");
    expect(coordinator.some((title) => title.startsWith("Costo finora"))).toBe(false);
    expect(coordinator).toContain("Piano accettato");
  });

  it("shows a message between two lanes on both, and the agent's own output on its lane only", () => {
    const briefSeq = seqOf((event) => event.title.startsWith("coordinatore → voli:"));
    const brief = views.coordinator.stations.find((station) => station.key === `${briefSeq}:coordinator`);
    expect(brief?.message).toMatchObject({ route: "coordinatore → voli", lang: "en" });
    expect(brief?.message?.text).toMatch(/^Find round-trip flights/);
    expect(views.flights.stations.some((station) => station.key === String(briefSeq))).toBe(true);
    const output = seqOf((event) => event.agent === "flights" && typeOf(event) === "agent.message");
    const reply = seqOf((event) => event.agent === "flights" && typeOf(event) === "agent.thread_message_received");
    expect(views.coordinator.stations.some((station) => station.seq === output)).toBe(false);
    expect(views.flights.stations.some((station) => station.seq === output)).toBe(true);
    expect(views.coordinator.stations.some((station) => station.key === `${reply}:coordinator`)).toBe(true);
  });

  it("marks only what agents write to each other as English", () => {
    const toUser = views.coordinator.stations.find((station) => station.title.startsWith("coordinatore → utente"));
    expect(toUser?.message?.lang).toBeNull();
    const brief = views.coordinator.stations.find((station) => station.title.startsWith("utente → coordinatore"));
    expect(brief?.message?.lang).toBe("en");
    // Its title names it in Italian ("richiesta di viaggio"); a quoted first line is English.
    expect(brief?.message?.firstLineLang).toBeNull();
    // What agents write to each other has an Italian row; the English stays in the disclosure.
    const toFlights = views.coordinator.stations.find((station) => station.title.startsWith("coordinatore → voli"));
    expect(toFlights?.title).toBe("coordinatore → voli: incarico");
    expect(toFlights?.message).toMatchObject({ firstLine: "incarico", firstLineLang: null, lang: "en" });
    expect(toFlights?.message?.text).toMatch(/^Find round-trip flights/);
  });

  it("calls a later brief to the same lane a new one", () => {
    const follow = views.activities.stations.filter((station) => station.title.startsWith("coordinatore → attività"));
    expect(follow.map((station) => station.title)).toEqual([
      "coordinatore → attività: incarico",
      "coordinatore → attività: nuovo incarico",
    ]);
  });

  it("leaves the agents' file handling out and merges a delivery into one quiet station", () => {
    const flights = views.flights.stations;
    expect(titles(flights).some((title) => title.startsWith("Scrive ") || title.startsWith("Comando:"))).toBe(false);
    const delivery = flights.find((station) => station.title === "Consegna l'esito");
    expect(delivery).toMatchObject({ kind: "tool", meta: "1 file" });
    // Two deliveries in two waves are two stations.
    expect(views.activities.stations.filter((station) => station.title === "Consegna l'esito")).toHaveLength(2);
    const coordinator = titles(views.coordinator.stations);
    expect(coordinator.some((title) => title.startsWith("Legge results/") || title.startsWith("Scrive shared/"))).toBe(false);
    expect(coordinator).not.toContain("Consegna l'esito");
    // Reading a web page is work the user may care about: it stays.
    expect(titles(views.activities.stations).some((title) => title.startsWith("Legge la pagina"))).toBe(true);
  });

  it("shows the English hand-off only on the coordinator's line, with an Italian row", () => {
    const reply = seqOf((event) => event.agent === "flights" && typeOf(event) === "agent.thread_message_received");
    expect(views.flights.stations.some((station) => station.seq === reply)).toBe(false);
    const onCoordinator = views.coordinator.stations.find((station) => station.key === `${reply}:coordinator`);
    expect(onCoordinator?.title).toBe("voli → coordinatore: esito consegnato");
    expect(onCoordinator?.message).toMatchObject({ lang: "en", firstLineLang: null });
    expect(onCoordinator?.message?.text).toMatch(/flights\.json v1 written/);
  });

  it("quotes the choice on its station: the first sentence of the decision", () => {
    const choice = views.coordinator.stations.find((station) => station.key === "wave:Scelta");
    expect(choice?.meta).toBe("Volo TAP diretto con bagaglio (812 €) e Hotel Lisboa Plaza in centro (736 € per 4 notti).");
  });

  it("names the waves on the coordinator's line, in order", () => {
    const stations = views.coordinator.stations;
    const waves = stations.filter((station) => station.kind === "wave");
    expect(titles(waves)).toEqual(["Ondata 1", "Scelta", "Ondata 2"]);
    expect(waves[0]?.meta).toBe("Incarichi a voli, alloggio e attività");
    expect(waves[1]?.meta).toMatch(/^Volo TAP diretto/);
    expect(waves[2]?.meta).toBe("Nuovi incarichi a spostamenti e attività");
    const index = (key: string) => stations.findIndex((station) => station.key === key);
    // Ondata 1 comes right before the first brief, Ondata 2 right before the next one.
    const firstBrief = seqOf((event) => event.title.startsWith("coordinatore → voli:"));
    expect(index("wave:Ondata 1")).toBe(index(`${firstBrief}:coordinator`) - 1);
    const secondBrief = seqOf((event) => event.title.startsWith("coordinatore → spostamenti:"));
    expect(index("wave:Ondata 2")).toBe(index(`${secondBrief}:coordinator`) - 1);
    // The choice comes after the last report of wave 1 and before the coordinator reads them.
    const lastReport = seqOf((event) => event.agent === "lodging" && typeOf(event) === "agent.thread_message_received");
    expect(index("wave:Scelta")).toBeGreaterThan(index(`${lastReport}:coordinator`));
    expect(stations[index("wave:Scelta") + 1]?.title).toMatch(/^coordinatore → utente: Scelta:/);
  });

  it("sums the finished lanes up in one line", () => {
    expect(views.flights.summary).toBe("Esito consegnato al coordinatore.");
    expect(views.coordinator.summary).toBe("Piano consegnato.");
    expect(views.flights.live).toBeNull();
  });

  it("keeps the running tool out of the stations: it is the live plate", () => {
    const call = seqOf((event) => event.kind === "tool" && event.title === "Expedia · voli MXP→LIS · 14–18 apr");
    const upToCall = all.filter((event) => event.seq <= call);
    const live = reducePlanEvents(upToCall, { detail: detail("running", upToCall) });
    const lanes = buildLaneViews(live);
    expect(lanes.flights.state).toBe("working");
    expect(lanes.flights.live?.title).toBe("Expedia · voli MXP→LIS · 14–18 apr");
    expect(lanes.flights.stations.some((station) => station.seq === call)).toBe(false);
    expect(laneToOpen(lanes, live)).toBe("flights");
  });

  it("opens only the first wave until every briefed subagent has reported", () => {
    const flightsDone = seqOf((event) => event.agent === "flights" && event.title === "Turno concluso");
    const partial = all.filter((event) => event.seq <= flightsDone);
    const waves = buildLaneViews(reducePlanEvents(partial)).coordinator.stations.filter((station) => station.kind === "wave");
    expect(titles(waves)).toEqual(["Ondata 1"]);
  });
});

describe("buildLaneViews, a source that does not answer", () => {
  const state = reducePlanEvents(events(mcpFailure), { end: "ready" });
  const views = buildLaneViews(state);

  it("is one notice on the lane that called it, not a plan error", () => {
    expect(views.flights.notices).toEqual([
      {
        key: "source:kiwi",
        source: "kiwi",
        title: "Fonte Kiwi.com non raggiungibile: il piano prosegue con le altre fonti",
      },
    ]);
    expect(views.coordinator.notices).toEqual([]);
    expect(views.coordinator.stations.some((station) => station.kind === "error")).toBe(false);
  });

  it("keeps the failed call on the line with a red ring and the failure underneath", () => {
    const kiwi = views.flights.stations.find((station) => station.title.startsWith("Kiwi.com"));
    expect(kiwi).toMatchObject({
      kind: "failed",
      meta: "La fonte ha restituito un errore dopo 7,5 s",
      metaTone: "error",
    });
  });
});

describe("buildLaneViews, budget reached", () => {
  const all = events(budgetReached);
  const pausedAfter = budgetReached.statuses.find((change) => change.status === "budget_paused")?.after_seq ?? 0;
  const paused = all.filter((event) => event.seq <= pausedAfter);
  const state = reducePlanEvents(paused, { detail: detail("budget_paused", paused) });
  const views = buildLaneViews(state);

  it("stops the working lane and says why, without a live plate", () => {
    expect(views.lodging.state).toBe("stopped");
    expect(views.lodging.live).toBeNull();
    expect(views.lodging.summary).toBe("Fermo: budget della sessione raggiunto.");
    expect(titles(views.lodging.stations)).toContain("Fermo: budget della sessione raggiunto");
  });

  it("shows the resumption on the coordinator's line", () => {
    const resumed = buildLaneViews(reducePlanEvents(all, { end: "ready" })).coordinator.stations;
    expect(titles(resumed)).toContain("Budget aumentato: si riprende");
    expect(titles(resumed)).toContain("Budget della sessione portato a 2,61 $");
  });
});

describe("firstSentence", () => {
  it("takes the first sentence, drops the 'Scelta:' lead and keeps it within about 90 characters", () => {
    expect(firstSentence("Scelta: volo TAP. Aggiorno i vincoli.")).toBe("Volo TAP.");
    expect(firstSentence("Nessun punto fermo qui")).toBe("Nessun punto fermo qui");
    const long = firstSentence(`Scelta: ${"parola ".repeat(30)}fine.`);
    expect(long.length).toBeLessThanOrEqual(90);
    expect(long.endsWith("…")).toBe(true);
  });
});

describe("buildLaneViews, synthetic cases", () => {
  const at = (second: number) => `2026-10-12T10:00:${String(second).padStart(2, "0")}+02:00`;
  const make = (seq: number, agent: UIEvent["agent"], kind: UIEvent["kind"], title: string, detailValue: UIEvent["detail"]): UIEvent => ({
    seq,
    ts: at(seq),
    agent,
    kind,
    title,
    detail: detailValue,
    cost_cents: null,
  });

  it("draws a rejected submission as a failed station and an agent error as a break in the line", () => {
    const state = reducePlanEvents([
      make(0, "coordinator", "status", "Piano avviato", null),
      make(1, "coordinator", "plan", "Piano inviato per la verifica", { event_type: "agent.custom_tool_use", tool: "submit_plan", tool_use_id: "u1" }),
      make(2, "coordinator", "plan", "Piano respinto: 1 problema da correggere (tentativo 1 di 3)", {
        event_type: "backend.submit_plan",
        outcome: "rejected",
        tool_use_id: "u1",
      }),
      make(3, "coordinator", "tool", "Esito inviato all'agente: da correggere", { event_type: "user.custom_tool_result", tool_use_id: "u1", is_error: true }),
      make(4, "activities", "status", "Incarico ad attività", { event_type: "session.thread_created", lane_state: "working" }),
      make(5, "activities", "error", "Errore: ricerca interrotta", { event_type: "session.error", severity: "error" }),
    ]);
    const views = buildLaneViews(state);
    expect(views.coordinator.stations.map((station) => [station.title, station.kind])).toEqual([
      ["Piano avviato", "status"],
      ["Piano inviato per la verifica", "tool"],
      ["Piano respinto: 1 problema da correggere (tentativo 1 di 3)", "failed"],
      ["Ondata 1", "wave"],
      ["Scelta", "wave"],
    ]);
    expect(views.activities.state).toBe("error");
    expect(views.activities.stations.at(-1)).toMatchObject({ kind: "error", title: "Errore: ricerca interrotta" });
    expect(views.activities.errorTitle).toBe("Errore: ricerca interrotta");
    expect(views.activities.summary).toBe("Errore: ricerca interrotta");
  });

  it("shows a retried error as a red ring, not as a stop", () => {
    const state = reducePlanEvents([
      make(0, "coordinator", "status", "Al lavoro", { event_type: "session.status_running", lane_state: "working" }),
      make(1, "coordinator", "error", "Modello sovraccarico: nuovo tentativo in corso", {
        event_type: "session.error",
        retry_status: "retrying",
        severity: "warning",
      }),
    ]);
    const view = buildLaneViews(state).coordinator;
    expect(view.state).toBe("working");
    expect(view.stations.at(-1)).toMatchObject({ kind: "failed", title: "Modello sovraccarico: nuovo tentativo in corso" });
    expect(view.notices).toEqual([]);
  });

  it("says what a working lane does now: the coordinator what it waits for, a subagent where it got to", () => {
    const state = reducePlanEvents([
      make(0, "coordinator", "status", "Al lavoro", { event_type: "session.status_running", lane_state: "working" }),
      make(1, "flights", "status", "Incarico a voli", { event_type: "session.thread_created", lane_state: "working" }),
      make(2, "transport", "status", "Incarico a spostamenti", { event_type: "session.thread_created", lane_state: "working" }),
      make(3, "flights", "message", "voli → coordinatore: Trovato un volo.", { event_type: "agent.message", sender: "voli", recipient: "coordinatore", text: "Trovato un volo." }),
      make(4, "flights", "status", "Turno concluso", { event_type: "session.thread_status_idle", stop_reason: "end_turn", lane_state: "done" }),
    ]);
    const views = buildLaneViews(state);
    expect(views.coordinator.state).toBe("working");
    expect(views.coordinator.summary).toBe("Aspetta spostamenti.");
    expect(views.transport.summary).toBe("Ultimo passo: Incarico a spostamenti");
    expect(views.flights.state).toBe("done");
  });

  it("waits in place before the session runs", () => {
    const state = reducePlanEvents([make(0, "coordinator", "status", "Piano avviato", null)]);
    const views = buildLaneViews(state);
    expect(views.coordinator.summary).toBe("Avvio della sessione.");
    expect(views.transport.summary).toBe("Aspetta l'incarico del coordinatore.");
    expect(views.transport.stations).toEqual([]);
  });

  it("marks a call left without an answer when the lane stopped", () => {
    const run = [
      make(0, "flights", "status", "Incarico a voli", { event_type: "session.thread_created", lane_state: "working" }),
      make(1, "flights", "tool", "Expedia · voli MXP→LIS · 14–18 apr", { event_type: "agent.mcp_tool_use", server: "expedia", tool_use_id: "t1" }),
    ];
    const state = reducePlanEvents(run, { end: "interrupted" });
    const view = buildLaneViews(state).flights;
    expect(view.state).toBe("stopped");
    expect(view.live).toBeNull();
    expect(view.stations.at(-1)).toMatchObject({ title: "Expedia · voli MXP→LIS · 14–18 apr", meta: "Non concluso" });
    expect(view.summary).toBe("Fermo: il piano è stato interrotto.");
  });
});

describe("buildLaneViews, a plan that was stopped", () => {
  const at = (second: number) => `2026-10-12T10:00:${String(second).padStart(2, "0")}+02:00`;
  const make = (seq: number, agent: UIEvent["agent"], kind: UIEvent["kind"], title: string, detailValue: UIEvent["detail"]): UIEvent => ({
    seq,
    ts: at(seq),
    agent,
    kind,
    title,
    detail: detailValue,
    cost_cents: null,
  });
  const idle = { event_type: "session.thread_status_idle", stop_reason: "end_turn" };

  it("does not call a lane finished when it delivered nothing before the interrupt", () => {
    const run = [
      make(0, "coordinator", "status", "Piano avviato", null),
      make(1, "coordinator", "status", "Al lavoro", { event_type: "session.status_running", lane_state: "working" }),
      make(2, "flights", "status", "Incarico a voli", { event_type: "session.thread_created", lane_state: "working" }),
      make(3, "flights", "message", "voli → coordinatore: Trovato un volo.", { event_type: "agent.message", sender: "voli", recipient: "coordinatore", text: "Trovato un volo." }),
      make(4, "flights", "status", "Turno concluso", idle),
      make(5, "lodging", "status", "Incarico ad alloggio", { event_type: "session.thread_created", lane_state: "working" }),
      make(6, "lodging", "status", "Turno concluso", idle),
      make(7, "coordinator", "status", "Turno concluso", { event_type: "session.status_idle", stop_reason: "end_turn" }),
    ];
    const views = buildLaneViews(reducePlanEvents(run, { end: "interrupted" }));
    expect(views.flights.state).toBe("done");
    expect(views.lodging.state).toBe("stopped");
    expect(views.lodging.summary).toBe("Fermo: il piano è stato interrotto.");
    expect(views.coordinator.state).toBe("stopped");
    // A lane that never started keeps waiting, but on an ended plan its badge says it did not start
    // ("In attesa" would promise work that will not come).
    expect(views.transport.state).toBe("waiting");
    expect(views.transport.badge).toBe("not_started");
    expect(views.flights.badge).toBe("done");
    expect(views.lodging.badge).toBe("stopped");
  });

  it("draws no 'Scelta' when the interrupt ended the subagents' turns before anyone delivered", () => {
    const run = [
      make(0, "coordinator", "status", "Piano avviato", null),
      make(1, "flights", "status", "Incarico a voli", { event_type: "session.thread_created", lane_state: "working" }),
      make(2, "lodging", "status", "Incarico ad alloggio", { event_type: "session.thread_created", lane_state: "working" }),
      make(3, "flights", "status", "Turno concluso", { ...idle, lane_state: "done" }),
      make(4, "lodging", "status", "Turno concluso", { ...idle, lane_state: "done" }),
      make(5, "coordinator", "status", "Interruzione richiesta", { event_type: "user.interrupt" }),
    ];
    const views = buildLaneViews(reducePlanEvents(run, { end: "interrupted" }));
    expect(titles(views.coordinator.stations)).not.toContain("Scelta");
    expect(titles(views.coordinator.stations)).toContain("Ondata 1");
  });

  it("still draws the 'Scelta' when every briefed subagent delivered before the interrupt", () => {
    const run = [
      make(0, "coordinator", "status", "Piano avviato", null),
      make(1, "flights", "status", "Incarico a voli", { event_type: "session.thread_created", lane_state: "working" }),
      make(2, "flights", "message", "voli → coordinatore: Trovato un volo.", { event_type: "agent.message", sender: "voli", recipient: "coordinatore", text: "Trovato un volo." }),
      make(3, "flights", "status", "Turno concluso", { ...idle, lane_state: "done" }),
    ];
    const views = buildLaneViews(reducePlanEvents(run, { end: "interrupted" }));
    expect(titles(views.coordinator.stations)).toContain("Scelta");
  });

  it("names the agent and the source a blocked plan was waiting on, and stops that lane", () => {
    const run = [
      make(0, "coordinator", "status", "Piano avviato", null),
      make(1, "flights", "status", "Incarico a voli", { event_type: "session.thread_created", lane_state: "working" }),
      make(2, "flights", "tool", "lastminute.com · voli MXP→LIS · 14–18 apr (attende conferma)", {
        event_type: "agent.mcp_tool_use",
        server: "lastminute",
        tool_use_id: "t1",
      }),
      make(3, "flights", "status", "In attesa di una risposta", {
        event_type: "session.thread_status_idle",
        stop_reason: "requires_action",
        event_ids: ["t1"],
        lane_state: "waiting",
      }),
    ];
    const state = reducePlanEvents(run, { end: "blocked" });
    expect(findBlocker(state)).toEqual({ agent: "flights", source: "lastminute.com" });
    const views = buildLaneViews(state);
    expect(views.flights.state).toBe("stopped");
    expect(views.flights.summary).toBe("Aspettava il permesso per usare lastminute.com.");
    expect(views.coordinator.state).toBe("error");
    expect(laneToOpen(views, state)).toBe("flights");
  });

  it("shows a failed file call, and hides a quiet one", () => {
    const run = [
      make(0, "flights", "status", "Incarico a voli", { event_type: "session.thread_created", lane_state: "working" }),
      make(1, "flights", "tool", "Scrive results/flights.json.tmp", { event_type: "agent.tool_use", tool: "write", tool_use_id: "w1" }),
      make(2, "flights", "tool", "Errore: scrittura rifiutata", { event_type: "agent.tool_result", tool_use_id: "w1", is_error: true }),
      make(3, "flights", "tool", "Legge results/flights.json", { event_type: "agent.tool_use", tool: "read", tool_use_id: "r1" }),
      make(4, "flights", "tool", "Risultato ricevuto in 90 ms", { event_type: "agent.tool_result", tool_use_id: "r1", duration_ms: 90 }),
    ];
    const view = buildLaneViews(reducePlanEvents(run, { end: "failed" })).flights;
    expect(view.stations.map((station) => [station.title, station.kind])).toEqual([
      ["Incarico a voli", "status"],
      ["Consegna l'esito", "failed"],
    ]);
    expect(view.stations[1]?.meta).toBe("Errore: scrittura rifiutata");
  });
});

describe("buildLaneViews, the traveller's choices", () => {
  const all = events(choices);
  const upTo = (seq: number) => all.filter((event) => event.seq <= seq);
  const waiting = buildLaneViews(reducePlanEvents(upTo(55)));

  it("while a question waits, the coordinator's line ends at 'Tocca a te: scegli cosa vedere', no tool plate", () => {
    const { coordinator } = waiting;
    expect(coordinator.asking).toMatchObject({ title: "Tocca a te: scegli cosa vedere", seq: 53 });
    expect(coordinator.summary).toBe("Tocca a te: scegli cosa vedere");
    expect(coordinator.live).toBeNull();
    expect(titles(coordinator.stations)).not.toContain("Domanda al viaggiatore");
    expect(titles(coordinator.stations)).not.toContain("Tocca a te: scegli cosa vedere");
    expect(waiting.flights.asking).toBeNull();
  });

  it("after the answer, a lozenge 'Hai scelto: …' with the question as its second line; no 'Domanda al viaggiatore'", () => {
    const views = buildLaneViews(reducePlanEvents(upTo(58)));
    const answered = views.coordinator.stations.find((station) => station.seq === 56);
    expect(answered).toMatchObject({
      key: "56",
      kind: "message",
      title: "Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra",
      meta: "Cosa ti va di vedere?",
    });
    expect(views.coordinator.asking).toBeNull();
    expect(titles(views.coordinator.stations)).not.toContain("Domanda al viaggiatore");
    expect(titles(views.coordinator.stations)).not.toContain("Esito inviato all'agente");
  });

  it("right after the answer the coordinator's line says it, until the coordinator moves on", () => {
    // Its card is closed on the phone: the line is the receipt.
    const answered = buildLaneViews(reducePlanEvents(upTo(58)));
    expect(answered.coordinator.state).toBe("working");
    expect(answered.coordinator.summary).toBe("Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra");
    // Alloggio delivers: the coordinator's newest station is its hand-off, and its line says what is
    // true again.
    const movedOn = buildLaneViews(reducePlanEvents(upTo(64)));
    expect(movedOn.coordinator.summary).not.toMatch(/^Hai scelto/);
    // Only the coordinator's line: a subagent's is its own.
    expect(answered.lodging.summary).not.toMatch(/^Hai scelto/);
  });

  it("draws no 'In attesa di una risposta' station for a pause on the traveller", () => {
    expect(titles(waiting.coordinator.stations)).not.toContain("In attesa di una risposta");
    const after = buildLaneViews(reducePlanEvents(upTo(58)));
    expect(titles(after.coordinator.stations)).not.toContain("In attesa di una risposta");
  });

  it("an interrupt's closed answer leaves no failed-call station", () => {
    const failedResult: UIEvent = {
      seq: 56,
      ts: "2026-10-12T10:00:34+02:00",
      agent: "coordinator",
      kind: "tool",
      title: "Risposta della fonte non riuscita",
      detail: { event_type: "agent.tool_result", tool_use_id: "sevt_022CZchoiceActivitiesPa1", is_error: true },
      cost_cents: null,
    };
    const run = [...upTo(55), failedResult];
    const views = buildLaneViews(reducePlanEvents(run, { end: "interrupted" }));
    expect(views.coordinator.stations.some((station) => station.kind === "failed")).toBe(false);
    expect(titles(views.coordinator.stations)).not.toContain("Un passaggio sui file non è riuscito");
    expect(titles(views.coordinator.stations)).not.toContain("Domanda al viaggiatore");
  });

  it("a question left open on a stopped plan reads 'Senza risposta'", () => {
    const views = buildLaneViews(reducePlanEvents(upTo(55), { end: "interrupted" }));
    const left = views.coordinator.stations.find((station) => station.seq === 53);
    expect(left).toMatchObject({ kind: "status", title: "Tocca a te: scegli cosa vedere", meta: "Senza risposta" });
    expect(views.coordinator.asking).toBeNull();
  });

  it("the whole recording ends with both answers and no leftover question", () => {
    const views = buildLaneViews(reducePlanEvents(all, { end: "ready" }));
    const coordinator = views.coordinator.stations;
    expect(coordinator.filter((station) => station.title.startsWith("Hai scelto"))).toHaveLength(2);
    expect(coordinator.some((station) => station.meta === "Senza risposta")).toBe(false);
  });
});
