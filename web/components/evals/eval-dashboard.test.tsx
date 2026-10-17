import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { EvalRunSummarySchema, type EvalRunSummary } from "@/lib/schemas/api";

import list from "./__fixtures__/list.json";
import { EvalDashboard } from "./eval-dashboard";

const mocks = vi.hoisted(() => ({ listEvalRuns: vi.fn(), push: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { listEvalRuns: mocks.listEvalRuns } };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));

/** Newest first: 22:49 (no comparison), 20:12 (blocked), 17:30 (passed), 11 Oct (aborted), 10 Oct (report only). */
const RUNS: EvalRunSummary[] = list.map((row) => EvalRunSummarySchema.parse(row));
const answer = (runs: EvalRunSummary[]) => ({ runs, total: runs.length });

beforeEach(() => {
  mocks.listEvalRuns.mockReset();
  mocks.push.mockReset();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(Date.parse("2026-10-12T21:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function renderDashboard(runs: EvalRunSummary[] = RUNS) {
  mocks.listEvalRuns.mockResolvedValue(answer(runs));
  await act(async () => {
    render(<EvalDashboard />);
  });
}

const latest = () => screen.getByRole("heading", { name: "Ultimo collaudo" }).closest("section") as HTMLElement;
const fact = (label: string) => within(latest()).getByText(label).closest("div") as HTMLElement;

describe("EvalDashboard", () => {
  it("holds its place while loading", () => {
    mocks.listEvalRuns.mockReturnValue(new Promise(() => {}));
    render(<EvalDashboard />);
    expect(document.querySelector("[aria-busy='true']")).toBeTruthy();
    expect(screen.getByText("Carico il riepilogo…")).toBeTruthy();
  });

  it("asks for the twenty newest runs, whatever page the list is on", async () => {
    await renderDashboard();
    expect(mocks.listEvalRuns).toHaveBeenCalledWith(expect.objectContaining({ limit: 20 }));
    expect(mocks.listEvalRuns.mock.calls[0]?.[0]?.offset ?? 0).toBe(0);
  });

  it("leads with the newest run: its verdict, what it means and the way to open it", async () => {
    await renderDashboard([RUNS[1]!, ...RUNS.slice(2)]);
    const panel = latest();
    const pill = within(panel).getByText("Bloccato");
    expect(pill.closest("[data-verdict]")?.className).toContain("bg-error-wash");
    expect(panel.textContent).toContain("Il confronto con il riferimento non lascia passare questa modifica.");
    expect(panel.textContent).toContain("Oggi, 20:12");
    expect(within(panel).getByRole("link", { name: /Apri il collaudo/ }).getAttribute("href")).toBe(
      `/evals/${RUNS[1]!.id}`,
    );
  });

  it("gives each figure with how it moved since the previous run, in a sign and a colour", async () => {
    await renderDashboard();
    // 22:49 against 20:12: no plan accepted (was 2), 3,09 $ (was 2,88 $), no judge mean.
    expect(fact("Piani accettati").textContent).toContain("0/5");
    const fewer = within(fact("Piani accettati")).getByText(/−2/);
    expect(fewer.className).toContain("text-error");
    expect(fewer.textContent).toContain("rispetto alla precedente");
    const dearer = within(fact("Costo")).getByText(/\+0,21 \$/);
    expect(dearer.className).toContain("text-error");
    expect(fact("Voto medio").textContent).toContain("nessuno");
    // What the changes are measured against, in words.
    expect(latest().textContent).toContain("Variazioni rispetto al collaudo precedente (oggi, 20:12).");
  });

  it("colours a figure that improved green", async () => {
    await renderDashboard([RUNS[2]!, RUNS[3]!]);
    // 17:30 (5 accepted, 4,2, 2,71 $) against the aborted run of the 11th (2 accepted, 1,58 $).
    expect(within(fact("Piani accettati")).getByText(/\+3/).className).toContain("text-success");
    expect(within(fact("Costo")).getByText(/\+1,13 \$/).className).toContain("text-error");
    expect(latest().querySelector("[data-verdict='passed']")?.className).toContain("text-success");
  });

  it("draws the verdicts on their own line, then three charts over the runs, each with its numbers in a table", async () => {
    await renderDashboard();
    const trends = screen.getByRole("heading", { name: "Andamento" }).closest("section") as HTMLElement;
    const charts = within(trends).getAllByRole("figure");
    expect(charts.map((chart) => within(chart).getByRole("heading").textContent)).toEqual([
      "Esito",
      "Voto medio",
      "Costo a piano",
      "Piani accettati",
    ]);
    const judge = charts[1]!;
    // Oldest first, a row per run; a run without a judge mean says so.
    const rows = within(judge).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    expect(rows[0]?.textContent).toContain("4,6");
    expect(rows[0]?.textContent).toContain("Solo report");
    expect(rows[1]?.textContent).toContain("nessun voto");
    expect(within(judge).getByRole("group").getAttribute("aria-label")).toBe(
      "Voto medio negli ultimi 5 collaudi: da 4,0 a 4,6, l'ultimo 4,0.",
    );
    expect(within(charts[2]!).getByRole("group").getAttribute("aria-label")).toBe(
      "Costo a piano negli ultimi 5 collaudi: da 0,32 $ a 2,53 $, l'ultimo 0,62 $.",
    );
    expect(within(charts[0]!).getByRole("group").getAttribute("aria-label")).toBe(
      "Esito negli ultimi 5 collaudi, dal meno recente: solo report, interrotto, superato, bloccato, senza confronto.",
    );
    // The table is for screen readers, inside a box that never widens the page, read in its place
    // (not again as the chart's description).
    expect(judge.querySelector("table")?.parentElement?.className).toContain("sr-only");
    expect(within(judge).getByRole("group").hasAttribute("aria-describedby")).toBe(false);
    // The time axis is named by its two ends.
    expect(judge.querySelector("[data-axis='time']")?.textContent).toBe("10 ottOggi");
  });

  it("rings the verdicts on the Esito line only: the figures' stations stay ink", async () => {
    await renderDashboard();
    const [verdicts, , cost] = screen.getAllByRole("figure");
    const marks = [...verdicts!.querySelectorAll("[data-station]")];
    expect(marks.map((station) => station.getAttribute("data-verdict"))).toEqual([
      "report_only",
      "aborted",
      "passed",
      "blocked",
      "unknown",
    ]);
    expect(marks[2]?.className).toContain("text-success");
    expect(marks[3]?.className).toContain("text-error");
    const stations = [...cost!.querySelectorAll("[data-station]")];
    expect(stations).toHaveLength(5);
    expect(stations.some((station) => /success|error/.test(station.className))).toBe(false);
  });

  it("draws the baseline the gate measures against as a dashed reference, and says it", async () => {
    await renderDashboard([{ ...RUNS[0]!, reference_judge_mean: 4.1, reference_cost_per_plan_cents: 52.5 }, ...RUNS.slice(1)]);
    const [, judge, cost, accepted] = screen.getAllByRole("figure");
    expect(judge!.querySelector("[data-reference]")?.textContent).toBe("riferimento 4,1");
    expect(cost!.querySelector("[data-reference]")?.textContent).toBe("riferimento 0,53 $");
    expect(accepted!.querySelector("[data-reference]")).toBeNull();
    expect(within(judge!).getByRole("group").getAttribute("aria-label")).toContain("Riferimento 4,1.");
  });

  it("draws no reference without a baseline", async () => {
    await renderDashboard();
    expect(document.querySelector("[data-reference]")).toBeNull();
  });

  it("says why the newest run stopped: its first blocking findings, each linked to its request", async () => {
    const findings = [
      { rule: "deterministic checks", message: "2 prices without a source_url", request_id: "sea-week-family", request_title: "Settimana al mare con bambini" },
      { rule: "run", message: "the run was interrupted", request_id: null, request_title: null },
      { rule: "judge criteria", message: "Realistic transfers dropped", request_id: null, request_title: null },
    ];
    await renderDashboard([{ ...RUNS[1]!, blocking_findings: findings }, ...RUNS.slice(2)]);
    const reasons = within(latest()).getByRole("list", { name: "Perché si è fermata" });
    const items = within(reasons).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]?.textContent).toContain("Controlli");
    const link = within(items[0]!).getByRole("link", { name: "Settimana al mare con bambini" });
    expect(link.getAttribute("href")).toBe(`/evals/${RUNS[1]!.id}#richiesta-sea-week-family`);
    expect(items[0]?.querySelector("[lang='en']")?.textContent).toBe("2 prices without a source_url");
    expect(items[1]?.textContent).toContain("Esecuzione");
    const more = within(latest()).getByRole("link", { name: "Un altro motivo nel collaudo" });
    expect(more.getAttribute("href")).toBe(`/evals/${RUNS[1]!.id}#confronto`);
  });

  it("names no reasons for a run that passed", async () => {
    await renderDashboard([RUNS[2]!, ...RUNS.slice(3)]);
    expect(within(latest()).queryByRole("list", { name: "Perché si è fermata" })).toBeNull();
  });

  it("reads a chart from the keyboard, saying each run it moves to, and opens the run on Enter", async () => {
    await renderDashboard();
    const chart = screen.getAllByRole("figure")[2]!;
    const plot = within(chart).getByRole("group");
    const readout = () => chart.querySelector("[data-readout]")?.textContent ?? "";
    const spoken = () => chart.querySelector("[aria-live='polite']")?.textContent ?? "";
    // At rest the caption reads the newest run.
    expect(readout()).toContain("0,62 $");
    await act(async () => {
      fireEvent.focus(plot);
    });
    expect(readout()).toContain("0,62 $");
    await act(async () => {
      fireEvent.keyDown(plot, { key: "ArrowLeft" });
    });
    expect(readout()).toContain("0,58 $");
    expect(readout()).toContain("Bloccato");
    expect(spoken()).toBe("0,58 $, 12 ott 2026, 20:12, bloccato");
    await act(async () => {
      fireEvent.keyDown(plot, { key: "Home" });
    });
    expect(readout()).toContain("2,53 $");
    await act(async () => {
      fireEvent.keyDown(plot, { key: "Enter" });
    });
    expect(mocks.push).toHaveBeenCalledWith(`/evals/${RUNS[4]!.id}`);
  });

  it("waits for a third run before drawing trends", async () => {
    await renderDashboard(RUNS.slice(0, 2));
    expect(screen.queryByRole("figure")).toBeNull();
    expect(document.body.textContent).toContain("L'andamento compare dal terzo collaudo.");
  });

  it("draws nothing before the first run: the list below is the invitation", async () => {
    await renderDashboard([]);
    expect(document.body.textContent).toBe("");
  });

  it("says what went wrong and tries again on 'Riprova'", async () => {
    mocks.listEvalRuns.mockRejectedValueOnce(new ApiError({ kind: "server", status: 500, message: "Il planner ha avuto un problema." }));
    await act(async () => {
      render(<EvalDashboard />);
    });
    expect(screen.getByText("Il riepilogo non si è caricato")).toBeTruthy();
    mocks.listEvalRuns.mockResolvedValueOnce(answer(RUNS));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Riprova/ }));
    });
    expect(screen.getByRole("heading", { name: "Ultimo collaudo" })).toBeTruthy();
  });
});
