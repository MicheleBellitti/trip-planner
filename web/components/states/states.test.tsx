import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { PlanLoadFailed } from "./load-failed";
import { isEndedStatus, PlanEndedPanel } from "./plan-ended";
import { SessionExpiredLine } from "./session-expired";

afterEach(cleanup);

describe("PlanEndedPanel", () => {
  it("says what happened, what was saved and what can be done, for each ending", () => {
    render(<PlanEndedPanel status="interrupted" failureReason="Interrotto da te." costCents={14} />);
    const panel = screen.getByRole("region", { name: "Piano interrotto" });
    const facts = within(panel)
      .getAllByRole("term")
      .map((term) => term.textContent);
    expect(facts).toEqual(["Cosa è successo", "Cosa è stato salvato", "Cosa puoi fare"]);
    expect(within(panel).getByText(/^Interrotto da te\. Gli agenti hanno chiuso il passo/)).toBeTruthy();
    expect(within(panel).getByText(/Costo della sessione: 0,14 \$\./)).toBeTruthy();
  });

  it("writes the failures' title in error red with a glyph, the interruption in ink", () => {
    const { rerender } = render(<PlanEndedPanel status="blocked" failureReason={null} costCents={null} />);
    expect(screen.getByRole("region", { name: "Piano bloccato" }).getAttribute("data-tone")).toBe("error");
    expect(screen.getByText(/^Un agente aspettava una conferma/)).toBeTruthy();
    rerender(<PlanEndedPanel status="interrupted" failureReason={null} costCents={null} />);
    expect(screen.getByRole("region", { name: "Piano interrotto" }).getAttribute("data-tone")).toBe("neutral");
  });

  it("names the agent and the tool a blocked plan was waiting on", () => {
    render(
      <PlanEndedPanel
        status="blocked"
        blocker={{ agent: "flights", source: "lastminute.com" }}
        failureReason="Gli agenti aspettano una conferma che nessuno darà."
        costCents={9}
      />,
    );
    expect(
      screen.getByText(
        "L'agente Voli aspettava il permesso per usare lastminute.com, che questa app non può dare. Il piano non può continuare.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/nessuno darà/)).toBeNull();
  });

  it("knows which statuses are endings", () => {
    expect(["interrupted", "failed", "blocked"].every((status) => isEndedStatus(status as never))).toBe(true);
    expect(isEndedStatus("budget_paused")).toBe(false);
    expect(isEndedStatus("ready")).toBe(false);
    expect(isEndedStatus(null)).toBe(false);
  });
});

describe("PlanLoadFailed", () => {
  it("offers to try again only when trying again can help", () => {
    const { rerender } = render(<PlanLoadFailed error={new ApiError({ kind: "network", status: 0 })} onRetry={() => {}} />);
    expect(screen.getByRole("button", { name: "Riprova" })).toBeTruthy();
    rerender(<PlanLoadFailed error={new ApiError({ kind: "forbidden", status: 403 })} onRetry={() => {}} />);
    expect(screen.queryByRole("button", { name: "Riprova" })).toBeNull();
    expect(screen.getByText("Questo account non è abilitato al planner.")).toBeTruthy();
  });
});

describe("SessionExpiredLine", () => {
  it("links to the sign-in that returns here, in the same tab", () => {
    render(<SessionExpiredLine loginUrl="https://viaggi.test/accedi?returnTo=x" />);
    const link = screen.getByRole("link", { name: "Accedi di nuovo" });
    expect(link.getAttribute("href")).toBe("https://viaggi.test/accedi?returnTo=x");
    expect(link.getAttribute("target")).toBeNull();
  });
});

/** DESIGN.md's invariants over the live screen's own sources (components/ui has its own test). */
describe("live screen invariants", () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const dirs = [here, path.resolve(here, "../live"), path.resolve(here, "../../app/plans/[id]")];
  const files = dirs.flatMap((dir) =>
    readdirSync(dir)
      .filter((name) => /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name))
      .map((name) => path.join(dir, name)),
  );
  const read = (file: string) => readFileSync(file, "utf8");

  it("scans the sources", () => {
    expect(files.length).toBeGreaterThan(15);
  });

  it("puts no em dash on screen and never draws amber", () => {
    expect(files.filter((file) => read(file).includes("—")).map((file) => path.basename(file))).toEqual([]);
    expect(files.filter((file) => /-amber\b|var\(--amber/.test(read(file))).map((file) => path.basename(file))).toEqual([]);
  });

  it("has one aria-live region, the plan screen's, for lane state changes", () => {
    // The plan screen's view draws it, for the live plan and the demo alike.
    expect(files.filter((file) => read(file).includes("aria-live=")).map((file) => path.basename(file))).toEqual([
      "plan-screen-view.tsx",
    ]);
  });
});
