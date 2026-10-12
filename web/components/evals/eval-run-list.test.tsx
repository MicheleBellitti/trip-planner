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

async function renderList() {
  await act(async () => {
    render(<EvalRunList />);
  });
}

const rowOf = (name: RegExp) => screen.getByRole("link", { name }).closest("div") as HTMLElement;

describe("EvalRunList", () => {
  it("shows placeholder rows while loading, and reads no clock while rendering", () => {
    mocks.listEvalRuns.mockReturnValue(new Promise(() => {}));
    const now = vi.spyOn(Date, "now").mockImplementation(() => {
      throw new Error("Date.now() was read while rendering");
    });
    try {
      const html = renderToString(<EvalRunList />);
      expect(html).toContain("Carico le valutazioni…");
      expect(html).toContain('aria-busy="true"');
    } finally {
      now.mockRestore();
    }
  });

  it("asks for the 50 most recent runs", async () => {
    mocks.listEvalRuns.mockResolvedValue(RUNS);
    await renderList();
    expect(mocks.listEvalRuns).toHaveBeenCalledWith(expect.objectContaining({ limit: 50 }));
  });

  it("draws a row per run, newest first, each linking to its page", async () => {
    mocks.listEvalRuns.mockResolvedValue(RUNS);
    await renderList();
    const links = screen.getAllByRole("link").filter((link) => link.getAttribute("href")?.startsWith("/evals/"));
    expect(links.map((link) => link.getAttribute("href"))).toEqual(RUNS.map((run) => `/evals/${run.id}`));
  });

  it("says when it started, the commit, the roster, the verdict, the plans, the cost and the judge's mean", async () => {
    mocks.listEvalRuns.mockResolvedValue(RUNS);
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
    mocks.listEvalRuns.mockResolvedValue(RUNS);
    await renderList();
    expect(rowOf(/Oggi, 17:30/).textContent).toContain("Esito Superato");
    expect(rowOf(/Oggi, 22:49/).textContent).toContain("Esito Senza confronto");
    expect(rowOf(/Ieri, 11:04/).textContent).toContain("Esito Interrotto");
    expect(rowOf(/10 ott/).textContent).toContain("Esito Solo report");
  });

  it("says so when a run has no commit and no judge mean", async () => {
    mocks.listEvalRuns.mockResolvedValue(RUNS);
    await renderList();
    const row = rowOf(/Ieri, 11:04/);
    expect(row.textContent).toContain("commit non indicato");
    expect(row.textContent).toContain("nessuno");
  });

  it("links the GitHub run in a new tab, only when CI uploaded one and only to an http(s) address", async () => {
    mocks.listEvalRuns.mockResolvedValue([
      ...RUNS,
      { ...RUNS[0]!, id: "99999999-8a49-4c0e-9b7a-5e2c1f0a4d11", workflow_run_url: "javascript:alert(1)" },
    ]);
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
    mocks.listEvalRuns.mockResolvedValue([]);
    await renderList();
    expect(screen.getByRole("heading", { name: "La prima valutazione arriva dalla CI" })).toBeTruthy();
    expect(document.body.textContent).toContain("python -m app.cli import-evals");
    expect(document.body.textContent).toContain("la CI carica qui i risultati");
  });

  it("says what went wrong and tries again on 'Riprova'", async () => {
    mocks.listEvalRuns.mockRejectedValueOnce(new ApiError({ kind: "server", status: 500, message: "Il planner ha avuto un problema." }));
    await renderList();
    expect(screen.getByText("Le valutazioni non si sono caricate")).toBeTruthy();
    expect(screen.getByText("Il planner ha avuto un problema.")).toBeTruthy();

    mocks.listEvalRuns.mockResolvedValueOnce(RUNS);
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
    expect(screen.queryByText("Le valutazioni non si sono caricate")).toBeNull();
  });
});
