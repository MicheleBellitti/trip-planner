import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, UnauthorizedError } from "@/lib/api";
import { EvalRunSummarySchema, type EvalRunSummary } from "@/lib/schemas/api";

import list from "./__fixtures__/list.json";
import { EvalRunList } from "./eval-run-list";

const mocks = vi.hoisted(() => ({ listEvalRuns: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { listEvalRuns: mocks.listEvalRuns } };
});

const RUNS: EvalRunSummary[] = list.map((row) => EvalRunSummarySchema.parse(row));

beforeEach(() => {
  mocks.listEvalRuns.mockReset();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(Date.parse("2026-10-12T21:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function renderList(page = 1) {
  await act(async () => {
    render(<EvalRunList page={page} />);
  });
}

/** The list's answer: these rows, out of `total` stored runs (null: a backend that does not count). */
const answer = (runs: EvalRunSummary[], total: number | null = runs.length) => ({ runs, total });

/** `count` runs, newest first, a day apart, to fill pages. */
function manyRuns(count: number): EvalRunSummary[] {
  return Array.from({ length: count }, (_, index) => ({
    ...RUNS[2]!,
    id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    started_at: new Date(Date.parse("2026-10-12T09:00:00Z") - index * 86_400_000).toISOString(),
  }));
}

const pager = () => screen.queryByRole("navigation", { name: "Pagine dei collaudi" });

const rowOf = (name: RegExp) => screen.getByRole("link", { name }).closest("div") as HTMLElement;

describe("EvalRunList", () => {
  it("shows placeholder rows while loading, and reads no clock while rendering", () => {
    mocks.listEvalRuns.mockReturnValue(new Promise(() => {}));
    const now = vi.spyOn(Date, "now").mockImplementation(() => {
      throw new Error("Date.now() was read while rendering");
    });
    try {
      const html = renderToString(<EvalRunList page={1} />);
      expect(html).toContain("Carico i collaudi…");
      expect(html).toContain('aria-busy="true"');
    } finally {
      now.mockRestore();
    }
  });

  it("asks for the page's ten runs", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(RUNS));
    await renderList();
    expect(mocks.listEvalRuns).toHaveBeenCalledWith(expect.objectContaining({ limit: 10, offset: 0 }));
    cleanup();
    mocks.listEvalRuns.mockResolvedValue(answer([], 30));
    await renderList(3);
    expect(mocks.listEvalRuns).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 10, offset: 20 }));
  });

  it("numbers the pages when there are more runs than a page holds, the current one marked", async () => {
    const runs = manyRuns(25);
    mocks.listEvalRuns.mockResolvedValue(answer(runs.slice(10, 20), 25));
    await renderList(2);
    const nav = pager()!;
    const current = within(nav).getByRole("link", { name: "Pagina 2" });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "Pagina 1" }).getAttribute("href")).toBe("/evals");
    expect(within(nav).getByRole("link", { name: "Pagina 3" }).getAttribute("href")).toBe("/evals?pagina=3");
    expect(within(nav).getByRole("link", { name: /Più recenti/ }).getAttribute("href")).toBe("/evals");
    expect(within(nav).getByRole("link", { name: /Più vecchie/ }).getAttribute("href")).toBe("/evals?pagina=3");
    expect(document.body.textContent).toContain("Collaudi da 11 a 20 di 25");
  });

  it("has no pager when every run fits in one page", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(RUNS));
    await renderList();
    expect(pager()).toBeNull();
  });

  it("offers no pages with a backend older than the pages (it ignores the offset and counts nothing)", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(manyRuns(10), null));
    await renderList();
    expect(screen.getAllByRole("link").filter((link) => link.getAttribute("href")?.startsWith("/evals/"))).toHaveLength(10);
    expect(pager()).toBeNull();
  });

  it("never shows the newest runs again as a later page of such a backend", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(manyRuns(10), null));
    await renderList(2);
    expect(screen.queryAllByRole("link").filter((link) => link.getAttribute("href")?.startsWith("/evals/"))).toHaveLength(0);
    expect(screen.getByText("Le pagine non sono ancora disponibili")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Vai alle più recenti/ }).getAttribute("href")).toBe("/evals");
  });

  it("sends a page past the end back to the last one", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer([], 12));
    await renderList(5);
    expect(screen.getByText("I collaudi finiscono a pagina 2")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Vai a pagina 2/ }).getAttribute("href")).toBe("/evals?pagina=2");
  });

  it("colours a passed run green and a blocked one red, always with the word", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(RUNS));
    await renderList();
    const passed = within(rowOf(/Oggi, 17:30/)).getByText("Superato");
    expect(passed.className).toContain("text-success");
    const blocked = within(rowOf(/Oggi, 20:12/)).getByText("Bloccato");
    expect(blocked.className).toContain("text-error");
    expect(within(rowOf(/10 ott/)).getByText("Solo report").className).toContain("text-ink-2");
  });

  it("draws a row per run, newest first, each linking to its page", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(RUNS));
    await renderList();
    const links = screen.getAllByRole("link").filter((link) => link.getAttribute("href")?.startsWith("/evals/"));
    expect(links.map((link) => link.getAttribute("href"))).toEqual(RUNS.map((run) => `/evals/${run.id}`));
  });

  it("says when it started, the commit, the roster, the verdict, the plans, the cost and the judge's mean", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(RUNS));
    await renderList();
    // The synthetic blocked run: 20:12 Rome on the 12th, "today" for the frozen clock.
    const row = rowOf(/Oggi, 20:12/);
    expect(row.textContent).toContain("Esito Bloccato");
    expect(row.textContent).toContain("2/5 piani accettati");
    expect(row.textContent).toContain("Costo 2,88 $");
    expect(row.textContent).toContain("a91c3e0");
    expect(row.textContent).toContain("sviluppo");
    expect(row.textContent).toMatch(/Voto medio\s*(voto\s*)?4,0/);
    expect(within(row).getByText("a91c3e0").tagName).toBe("CODE");
  });

  it("tells the four verdicts in words, and a run nobody compared", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(RUNS));
    await renderList();
    expect(rowOf(/Oggi, 17:30/).textContent).toContain("Esito Superato");
    expect(rowOf(/Oggi, 22:49/).textContent).toContain("Esito Senza confronto");
    expect(rowOf(/Ieri, 11:04/).textContent).toContain("Esito Interrotto");
    expect(rowOf(/10 ott/).textContent).toContain("Esito Solo report");
  });

  it("says so when a run has no commit and no judge mean", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer(RUNS));
    await renderList();
    const row = rowOf(/Ieri, 11:04/);
    expect(row.textContent).toContain("commit non indicato");
    expect(row.textContent).toContain("nessuno");
  });

  it("links the GitHub run in a new tab, only when CI uploaded one and only to an http(s) address", async () => {
    mocks.listEvalRuns.mockResolvedValue(
      answer([...RUNS, { ...RUNS[0]!, id: "99999999-8a49-4c0e-9b7a-5e2c1f0a4d11", workflow_run_url: "javascript:alert(1)" }]),
    );
    await renderList();
    const external = screen.getAllByRole("link").filter((link) => link.getAttribute("target") === "_blank");
    expect(external).toHaveLength(2);
    for (const link of external) {
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
      expect(link.getAttribute("href")).toMatch(/^https:\/\/github\.com\//);
      expect(link.textContent).toContain("GitHub");
    }
  });

  it("is an invitation when there is no run yet, with the two ways runs arrive", async () => {
    mocks.listEvalRuns.mockResolvedValue(answer([]));
    await renderList();
    expect(screen.getByRole("heading", { name: "Il primo collaudo arriva dalla CI" })).toBeTruthy();
    expect(document.body.textContent).toContain("python -m app.cli import-evals");
    expect(document.body.textContent).toContain("la CI carica qui i risultati");
  });

  it("says what went wrong and tries again on 'Riprova'", async () => {
    mocks.listEvalRuns.mockRejectedValueOnce(new ApiError({ kind: "server", status: 500, message: "Il planner ha avuto un problema." }));
    await renderList();
    expect(screen.getByText("I collaudi non si sono caricati")).toBeTruthy();
    expect(screen.getByText("Il planner ha avuto un problema.")).toBeTruthy();

    mocks.listEvalRuns.mockResolvedValueOnce(answer(RUNS));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Riprova/ }));
    });
    expect(mocks.listEvalRuns).toHaveBeenCalledTimes(2);
    expect(screen.getAllByRole("link").length).toBeGreaterThan(RUNS.length - 1);
  });

  it("keeps the placeholder while the browser is sent to the login", async () => {
    mocks.listEvalRuns.mockRejectedValue(new UnauthorizedError({ status: 401 }, "https://viaggi.test/accedi"));
    await renderList();
    expect(document.querySelector("[aria-busy='true']")).toBeTruthy();
    expect(screen.queryByText("I collaudi non si sono caricati")).toBeNull();
  });
});
