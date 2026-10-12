import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { EvalRunDetailSchema, type EvalRunDetail } from "@/lib/schemas/api";

import accepted from "./__fixtures__/run-accepted.json";
import real from "./__fixtures__/run-real.json";
import { EvalRunScreen } from "./eval-run-screen";

const mocks = vi.hoisted(() => ({ getEvalRun: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { getEvalRun: mocks.getEvalRun } };
});
// The toggle reads matchMedia, which jsdom does not have; the header is not what these test.
vi.mock("@/components/ui/theme-toggle", () => ({ ThemeToggle: () => null }));

const ACCEPTED: EvalRunDetail = EvalRunDetailSchema.parse(accepted);
const REAL: EvalRunDetail = EvalRunDetailSchema.parse(real);

beforeEach(() => {
  mocks.getEvalRun.mockReset();
});
afterEach(cleanup);

async function renderRun(run: EvalRunDetail) {
  mocks.getEvalRun.mockResolvedValue(run);
  await act(async () => {
    render(<EvalRunScreen runId={run.id} />);
  });
}

function section(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("section") as HTMLElement;
}

describe("EvalRunScreen", () => {
  it("shows the skeleton in the page's shape while loading", () => {
    mocks.getEvalRun.mockReturnValue(new Promise(() => {}));
    render(<EvalRunScreen runId={ACCEPTED.id} />);
    expect(screen.getByText("Carico la valutazione…")).toBeTruthy();
    expect(document.querySelector("[aria-busy='true']")).toBeTruthy();
  });

  it("titles the page with the run's date, and gives its facts: commit, roster, duration and the CI run", async () => {
    await renderRun(ACCEPTED);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Valutazione del 12 ott 2026, 20:12");
    expect(screen.getByText("a91c3e0").tagName).toBe("CODE");
    expect(screen.getByText("sviluppo")).toBeTruthy();
    expect(screen.getByText("5 min 37 s")).toBeTruthy();
    const ci = screen.getByRole("link", { name: /Esecuzione su GitHub/ });
    expect(ci.getAttribute("target")).toBe("_blank");
    expect(ci.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("states the verdict in a word with what it means, and the figures of the whole run", async () => {
    await renderRun(ACCEPTED);
    expect(screen.getByText("Bloccato")).toBeTruthy();
    expect(screen.getByText("Il confronto con il riferimento non lascia passare questa modifica.")).toBeTruthy();
    const facts = document.querySelector("dl") as HTMLElement;
    expect(facts.textContent).toContain("Piani accettati2/5");
    expect(facts.textContent).toContain("Costo2,88 $");
    expect(facts.textContent).toContain("stima 0,55 $ a piano");
    expect(facts.textContent).toContain("Ricerche web61");
    expect(facts.textContent).toContain("Voto medio4,0");
    expect(facts.textContent).toContain("0,15 $ spesi su 1,00 $");
  });

  it("lists the comparison's blocking findings plainly, then the figures against the baseline", async () => {
    await renderRun(ACCEPTED);
    const comparison = section("Confronto con il riferimento");
    expect(comparison.textContent).toContain("3 problemi bloccano il confronto");
    const items = within(comparison).getAllByRole("listitem");
    expect(items[0]?.textContent).toContain("BloccaControlliSettimana al mare con bambini");
    expect(items[0]?.textContent).toContain("prices_have_source fail: 2 prices without a source_url");
    expect(items[0]?.querySelector("[lang='en']")).toBeTruthy();
    expect(items[2]?.textContent).toContain("Blocca" + "Voti del giudice");
    // The non-blocking finding comes after the blocking ones.
    expect(items[3]?.textContent).toContain("SegnalaCosto medio per piano");
    expect(comparison.textContent).toContain("Realismo degli spostamenti3,0 (era 4,0)");
    expect(comparison.textContent).toContain("Costo medio per piano0,55 $ (era 0,50 $)");
  });

  it("says a run has no stored comparison, without inventing a verdict", async () => {
    await renderRun(REAL);
    expect(screen.getByText("Senza confronto")).toBeTruthy();
    expect(section("Confronto con il riferimento").textContent).toContain("Nessun confronto salvato");
  });

  it("has one section per request, the ones that stopped the gate first", async () => {
    await renderRun(ACCEPTED);
    const titles = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent)
      .filter((title) => title && !/^(Confronto|Richieste|Versioni)/.test(title));
    expect(titles).toEqual([
      "Settimana al mare con bambini",
      "Suggeriscimi tu, budget basso",
      "Viaggio in treno",
      "Date flessibili",
      "Weekend in città europea",
    ]);
  });

  it("lists a request's checks failures first, with a word, the Italian name and the file's own sentence", async () => {
    await renderRun(ACCEPTED);
    const request = section("Settimana al mare con bambini");
    const rows = within(request).getAllByRole("listitem").filter((item) => item.querySelector("svg"));
    expect(rows[0]?.textContent).toContain("Ogni prezzo ha una fonte e una dataNon superatobloccante");
    expect(rows[0]?.textContent).toContain("2 prices without a source_url");
    expect(rows[1]?.textContent).toContain("Il totale sta nel budget, o il piano lo segnalaAvviso");
    // Passed checks follow; the skipped one is folded into a closed row.
    expect(request.textContent).toContain("Superato");
    expect(within(request).getByText("Un controllo saltato")).toBeTruthy();
  });

  it("gives the judge's scores per criterion with a number, a word and the judge's reason", async () => {
    await renderRun(ACCEPTED);
    const request = section("Settimana al mare con bambini");
    const scores = request.querySelectorAll("[data-score]");
    expect([...scores].map((score) => score.getAttribute("data-score"))).toEqual(["3", "2", "5", "4", "4"]);
    expect(request.textContent).toContain("Realismo degli spostamentiScarso");
    expect(request.textContent).toContain("The ferry crossing is shown as 20 minutes");
    // The judge's English reason is marked as English.
    expect(request.querySelector("[data-score='2']")?.closest("li")?.querySelector("[lang='en']")?.textContent).toContain(
      "ferry crossing",
    );
  });

  it("says why the judge gave nothing for a request", async () => {
    await renderRun(ACCEPTED);
    const failed = section("Suggeriscimi tu, budget basso");
    expect(failed.textContent).toContain("Il giudice non ha dato i voti.");
    expect(failed.textContent).toContain("judge reply was cut off (max_tokens)");
    expect(failed.textContent).toContain("Il planner non ha prodotto un piano valido dopo due tentativi.");
  });

  it("sums the accepted plan up (title, days, bookings) and keeps the raw request behind a disclosure", async () => {
    await renderRun(ACCEPTED);
    const request = section("Weekend in città europea");
    expect(request.textContent).toContain("Piano accettato");
    expect(request.textContent).toContain("Weekend a Lisbona, 12-14 novembre 2027");
    expect(request.textContent).toContain("3 giorni, 5 prenotazioni");
    const details = request.querySelectorAll("details");
    const raw = [...details].find((detail) => detail.textContent?.includes("Mostra la richiesta come JSON")) as HTMLDetailsElement;
    expect(raw.open).toBe(false);
    expect(raw.querySelector("pre")?.textContent).toContain('"destination": "Lisbona"');
  });

  it("keeps the agent versions in a closed disclosure at the end", async () => {
    await renderRun(ACCEPTED);
    const versions = screen.getByText("Versioni degli agenti").closest("details") as HTMLDetailsElement;
    expect(versions.open).toBe(false);
    expect(versions.textContent).toContain("agent_01JznpMrk3fnHyBcuf2RCc8i");
    expect(versions.textContent).toContain("Coordinatore");
    expect(versions.textContent).toContain("Skill booking-links");
  });

  it("jumps from the index to a request's section", async () => {
    await renderRun(ACCEPTED);
    const link = screen.getByRole("link", { name: /Weekend in città europea/ });
    expect(link.getAttribute("href")).toBe("#richiesta-city-weekend-lisbon");
    expect(document.getElementById("richiesta-city-weekend-lisbon")).toBeTruthy();
  });

  it("says a run is missing, with the way back", async () => {
    mocks.getEvalRun.mockRejectedValue(new ApiError({ kind: "not_found", status: 404, code: "eval_run_not_found", message: "Questa valutazione non c'è." }));
    await act(async () => {
      render(<EvalRunScreen runId="00000000-0000-4000-8000-000000000000" />);
    });
    expect(screen.getByRole("heading", { name: "Questa valutazione non c'è" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Torna alle valutazioni/ }).getAttribute("href")).toBe("/evals");
  });

  it("says what went wrong and tries again on 'Riprova'", async () => {
    mocks.getEvalRun.mockRejectedValueOnce(new ApiError({ kind: "network", status: 0 }));
    await act(async () => {
      render(<EvalRunScreen runId={ACCEPTED.id} />);
    });
    expect(screen.getByText("La valutazione non si è caricata")).toBeTruthy();
    mocks.getEvalRun.mockResolvedValueOnce(ACCEPTED);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Riprova/ }));
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Valutazione del");
  });
});
