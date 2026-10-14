import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { EvalRunDetailSchema, EvalRunSummarySchema, type EvalRunDetail } from "@/lib/schemas/api";

import list from "./__fixtures__/list.json";
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
/** Newest first: 22:49 (no comparison), 20:12 (the accepted fixture's own run), 17:30 (passed). */
const [NEWER, , OLDER] = list.map((row) => EvalRunSummarySchema.parse(row));
const BETWEEN: EvalRunDetail = { ...ACCEPTED, previous_run: OLDER!, next_run: NEWER! };

beforeEach(() => {
  mocks.getEvalRun.mockReset();
});
afterEach(() => {
  cleanup();
  window.location.hash = "";
});

async function renderRun(run: EvalRunDetail) {
  mocks.getEvalRun.mockResolvedValue(run);
  await act(async () => {
    render(<EvalRunScreen runId={run.id} />);
  });
}

function section(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("section") as HTMLElement;
}

/** A request's row: the <details> whose summary carries its title as a heading. */
function request(title: string): HTMLDetailsElement {
  return screen.getByRole("heading", { name: title }).closest("details") as HTMLDetailsElement;
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
    expect(screen.getByText("Bloccato").closest("[data-verdict]")?.className).toContain("bg-error-wash");
    expect(screen.getByText("Il confronto con il riferimento non lascia passare questa modifica.")).toBeTruthy();
    const facts = document.querySelector("dl") as HTMLElement;
    expect(facts.textContent).toContain("Piani accettati2/5");
    expect(facts.textContent).toContain("Costo2,88 $");
    expect(facts.textContent).toContain("0,58 $ a piano, stima 0,55 $");
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

  it("lists every request as a closed row, the ones that stopped the gate first", async () => {
    await renderRun(ACCEPTED);
    const rows = [...document.querySelectorAll<HTMLDetailsElement>("details[data-request]")];
    expect(rows.map((row) => row.querySelector("summary h3")?.textContent)).toEqual([
      "Settimana al mare con bambini",
      "Suggeriscimi tu, budget basso",
      "Viaggio in treno",
      "Date flessibili",
      "Weekend in città europea",
    ]);
    expect(rows.every((row) => !row.open)).toBe(true);
  });

  it("says in the closed row how the request went: its glyph and colour, the plan, the checks, the score", async () => {
    await renderRun(ACCEPTED);
    const failed = request("Settimana al mare con bambini").querySelector("summary") as HTMLElement;
    expect(failed.querySelector("[data-outcome]")?.className).toContain("text-error");
    expect(failed.textContent).toContain("1 controllo bloccante non superato");
    expect(failed.textContent).toContain("voto 3,6");
    const passed = request("Weekend in città europea").querySelector("summary") as HTMLElement;
    expect(passed.querySelector("[data-outcome]")?.className).toContain("text-success");
  });

  it("names in the closed row what stopped a request and its low scores, so the row says whether to open it", async () => {
    await renderRun(ACCEPTED);
    const failed = request("Settimana al mare con bambini").querySelector("summary") as HTMLElement;
    const blocking = failed.querySelector("[data-blocking]") as HTMLElement;
    expect(blocking.textContent).toBe("Ogni prezzo ha una fonte e una data");
    expect(blocking.className).toContain("text-error");
    // The check's name says what it checks: the row says it did not pass, in words.
    expect(failed.textContent).toContain("Non superato: Ogni prezzo ha una fonte e una data");
    expect(failed.querySelector("[data-low-scores]")?.textContent).toBe("1 voto scarso: Realismo degli spostamenti");
    const two = request("Suggeriscimi tu, budget basso").querySelector("[data-blocking]");
    expect(two?.textContent).toBe("Il piano e il viaggio rispettano gli schemi e un altro");
    const passed = request("Weekend in città europea").querySelector("summary") as HTMLElement;
    expect(passed.querySelector("[data-blocking]")).toBeNull();
    expect(passed.querySelector("[data-low-scores]")).toBeNull();
  });

  it("counts every low score in the closed row, naming the first", async () => {
    const run = structuredClone(ACCEPTED);
    const sea = run.results.requests.find((request) => request.id === "sea-week-family")!;
    sea.judge!.scores!.time_coherence!.score = 1;
    await renderRun(run);
    const low = request("Settimana al mare con bambini").querySelector("[data-low-scores]");
    expect(low?.textContent).toBe("2 voti scarsi: Coerenza degli orari e un altro");
  });

  it("titles the parts of an open request one level under the request", async () => {
    await renderRun(ACCEPTED);
    const row = request("Weekend in città europea");
    expect([...row.querySelectorAll("h4")].map((heading) => heading.childNodes[0]?.textContent?.trim())).toEqual([
      "Controlli",
      "Giudice",
      "Piano accettato",
    ]);
  });

  it("opens the request the address points to, and takes the focus to it", async () => {
    window.location.hash = "#richiesta-city-weekend-lisbon";
    await renderRun(ACCEPTED);
    expect(request("Weekend in città europea").open).toBe(true);
    expect(document.activeElement).toBe(request("Weekend in città europea").querySelector("summary"));
    expect(request("Viaggio in treno").open).toBe(false);
  });

  it("colours passed checks green, failed ones red, each with its word", async () => {
    await renderRun(ACCEPTED);
    const row = request("Settimana al mare con bambini");
    expect(within(row).getByText("Non superato").className).toContain("text-error");
    expect(within(row).getAllByText("Superato")[0]?.className).toContain("text-success");
  });

  it("lists a request's checks failures first, with a word, the Italian name and the file's own sentence", async () => {
    await renderRun(ACCEPTED);
    const row = request("Settimana al mare con bambini");
    const rows = within(row).getAllByRole("listitem").filter((item) => item.querySelector("svg"));
    expect(rows[0]?.textContent).toContain("Ogni prezzo ha una fonte e una dataNon superatobloccante");
    expect(rows[0]?.textContent).toContain("2 prices without a source_url");
    expect(rows[1]?.textContent).toContain("Il totale sta nel budget, o il piano lo segnalaAvviso");
    // Passed checks follow; the skipped one is folded into a closed row.
    expect(row.textContent).toContain("Superato");
    expect(within(row).getByText("Un controllo saltato")).toBeTruthy();
  });

  it("gives the judge's scores per criterion with a number, a word and the judge's reason", async () => {
    await renderRun(ACCEPTED);
    const row = request("Settimana al mare con bambini");
    const scores = row.querySelectorAll("[data-score]");
    expect([...scores].map((score) => score.getAttribute("data-score"))).toEqual(["3", "2", "5", "4", "4"]);
    expect(row.querySelector("[data-score='5']")?.className).toContain("text-success");
    expect(row.querySelector("[data-score='2']")?.className).toContain("text-error");
    expect(row.textContent).toContain("Realismo degli spostamentiScarso");
    expect(row.textContent).toContain("The ferry crossing is shown as 20 minutes");
    // The judge's English reason is marked as English.
    expect(row.querySelector("[data-score='2']")?.closest("li")?.querySelector("[lang='en']")?.textContent).toContain(
      "ferry crossing",
    );
  });

  it("says why the judge gave nothing for a request", async () => {
    await renderRun(ACCEPTED);
    const failed = request("Suggeriscimi tu, budget basso");
    expect(failed.textContent).toContain("Il giudice non ha dato i voti.");
    expect(failed.textContent).toContain("judge reply was cut off (max_tokens)");
    expect(failed.textContent).toContain("Il planner non ha prodotto un piano valido dopo due tentativi.");
  });

  it("sums the accepted plan up (title, days, bookings) and keeps the raw request behind a disclosure", async () => {
    await renderRun(ACCEPTED);
    const row = request("Weekend in città europea");
    expect(row.textContent).toContain("Piano accettato");
    expect(row.textContent).toContain("Weekend a Lisbona, 12-14 novembre 2027");
    expect(row.textContent).toContain("3 giorni, 5 prenotazioni");
    const details = row.querySelectorAll("details");
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

  it("links a comparison finding to the request it is about", async () => {
    await renderRun(ACCEPTED);
    const comparison = section("Confronto con il riferimento");
    const link = within(comparison).getAllByRole("link", { name: "Settimana al mare con bambini" })[0]!;
    expect(link.getAttribute("href")).toBe("#richiesta-sea-week-family");
    expect(document.getElementById("richiesta-sea-week-family")?.tagName).toBe("DETAILS");
  });

  it("steps to the newer and the older run, in the list's direction", async () => {
    await renderRun(BETWEEN);
    const steps = screen.getByRole("navigation", { name: "Valutazioni vicine" });
    expect(within(steps).getByRole("link", { name: /Più recente/ }).getAttribute("href")).toBe(`/evals/${NEWER!.id}`);
    expect(within(steps).getByRole("link", { name: /Più vecchia/ }).getAttribute("href")).toBe(`/evals/${OLDER!.id}`);
  });

  it("has no step past the newest or the oldest run", async () => {
    await renderRun({ ...ACCEPTED, previous_run: OLDER!, next_run: null });
    const steps = screen.getByRole("navigation", { name: "Valutazioni vicine" });
    expect(within(steps).queryByRole("link", { name: /Più recente/ })).toBeNull();
    expect(within(steps).getByRole("link", { name: /Più vecchia/ })).toBeTruthy();
  });

  it("gives the run's figures with how they moved since the run before it", async () => {
    await renderRun(BETWEEN);
    // 20:12 against 17:30: 2 plans accepted (was 5), 2,88 $ (was 2,71 $), judge 4,0 (was 4,2).
    const facts = document.querySelector("dl") as HTMLElement;
    const accepted = within(facts).getByText("Piani accettati").closest("div") as HTMLElement;
    expect(within(accepted).getByText(/−3/).className).toContain("text-error");
    const cost = within(facts).getByText("Costo").closest("div") as HTMLElement;
    expect(within(cost).getByText(/\+0,17 \$/).className).toContain("text-error");
    expect(document.body.textContent).toContain("Variazioni rispetto alla valutazione precedente (12 ott 2026, 17:30).");
  });

  it("says nothing moved when there is no run before it", async () => {
    await renderRun(ACCEPTED);
    expect(document.body.textContent).not.toContain("Variazioni rispetto alla valutazione precedente");
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
