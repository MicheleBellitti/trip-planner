import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ROUTES } from "@/lib/routes";

import { AppHeader } from "./app-header";
import { AppHeaderBar } from "./app-header-bar";
import { stationEdge } from "./station";

const isAdmin = vi.fn<() => boolean | null>(() => true);

vi.mock("@/lib/me", () => ({ useIsAdmin: () => isAdmin() }));

vi.mock("@/components/ui/theme-toggle", () => ({
  ThemeToggle: ({ className, variant }: { className?: string; variant?: string }) => (
    <button type="button" className={className} data-variant={variant ?? "outline"}>
      Tema
    </button>
  ),
}));

afterEach(() => {
  cleanup();
  isAdmin.mockReset();
  isAdmin.mockReturnValue(true);
});

describe("AppHeader", () => {
  it("draws the eval history's station only for the users who manage the planner", () => {
    isAdmin.mockReturnValue(false);
    const { unmount } = render(<AppHeader current="plans" />);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    expect(within(nav).getByRole("link", { name: "Piani" })).toBeTruthy();
    expect(within(nav).queryByRole("link", { name: "Collaudi" })).toBeNull();
    unmount();

    isAdmin.mockReturnValue(null); // not known yet: nothing appears and vanishes
    render(<AppHeader current="plans" />);
    expect(screen.queryByRole("link", { name: "Collaudi" })).toBeNull();
  });

  it("on the eval pages the station is always there, as the current one, whoever is looking", () => {
    isAdmin.mockReturnValue(false);
    render(<AppHeader current="evals" />);
    expect(screen.getByRole("link", { name: "Collaudi" }).getAttribute("aria-current")).toBe("page");
  });

  it("links the lockup to the plans and draws both sections as stations, the current one filled", () => {
    render(<AppHeader current="plans" />);
    expect(screen.getByRole("link", { name: "Atlas" }).getAttribute("href")).toBe(ROUTES.plans);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    const plans = within(nav).getByRole("link", { name: "Piani" });
    const evals = within(nav).getByRole("link", { name: "Collaudi" });
    expect(plans.getAttribute("href")).toBe(ROUTES.plans);
    expect(plans.getAttribute("aria-current")).toBe("page");
    expect(evals.getAttribute("href")).toBe(ROUTES.evals);
    expect(evals.getAttribute("aria-current")).toBeNull();
  });

  it("marks the eval history as the current section on the eval pages", () => {
    render(<AppHeader current="evals" />);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    expect(within(nav).getByRole("link", { name: "Collaudi" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "Piani" }).getAttribute("aria-current")).toBeNull();
  });

  it("always offers a new plan as a secondary action, named on the phone's icon too", () => {
    render(<AppHeader current="plans" />);
    const links = screen.getAllByRole("link", { name: "Nuovo piano" });
    expect(links).toHaveLength(2); // the labelled button from 640 px, the icon below
    for (const link of links) {
      expect(link.getAttribute("href")).toBe(ROUTES.newPlan);
      expect(link.className).not.toMatch(/\bbg-action\b/);
    }
  });

  it("gives its 40 px icon controls a 44 px target under a finger", () => {
    render(<AppHeader current="plans" />);
    const icon = screen.getAllByRole("link", { name: "Nuovo piano" }).find((link) => link.getAttribute("aria-label"));
    expect(icon?.className).toMatch(/\bpointer-coarse:size-11\b/);
    expect(screen.getByRole("button", { name: "Tema" }).className).toMatch(/\bpointer-coarse:size-11\b/);
  });

  it("keeps the new-plan action in its place on the form itself, marked as the current page", () => {
    render(<AppHeader current="new" />);
    const links = screen.getAllByRole("link", { name: "Nuovo piano" });
    expect(links).toHaveLength(2);
    for (const link of links) expect(link.getAttribute("aria-current")).toBe("page");
  });

  it("ends every header with \"Nuovo piano\", after a quiet ring-less theme toggle", () => {
    const { container } = render(<AppHeader current="plans" />);
    const controls = [...container.querySelectorAll("header a, header button")];
    expect(controls.at(-1)?.getAttribute("aria-label")).toBe("Nuovo piano");
    const toggle = screen.getByRole("button", { name: "Tema" });
    expect(controls.indexOf(toggle)).toBeLessThan(controls.length - 2);
    expect(toggle.getAttribute("data-variant")).toBe("bare");
  });

  it("draws the line past the outer stations and the current one as the larger ring", () => {
    render(<AppHeader current="evals" />);
    const items = [...screen.getByRole("navigation", { name: "Sezioni" }).querySelectorAll("li")];
    for (const item of items) expect(item.querySelectorAll("[data-line]")).toHaveLength(2);
    const current = within(screen.getByRole("link", { name: "Collaudi" })).getByTestId("station");
    const other = within(screen.getByRole("link", { name: "Piani" })).getByTestId("station");
    expect(current.getAttribute("data-current")).toBe("true");
    expect(other.getAttribute("data-current")).toBe("false");
  });

  it("runs the line a fixed 24 px past the outer stations, 2 px from 1080 px, never over a click", () => {
    render(<AppHeader current="plans" />);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    const items = [...nav.querySelectorAll("li")];
    const firstOuter = items[0]!.querySelectorAll("[data-line]")[0]!;
    const lastOuter = items.at(-1)!.querySelectorAll("[data-line]")[1]!;
    expect(firstOuter.className).toMatch(/\bright-1\/2\b/);
    expect(firstOuter.className).toMatch(/\bw-6\b/);
    expect(lastOuter.className).toMatch(/\bleft-1\/2\b/);
    expect(lastOuter.className).toMatch(/\bw-6\b/);
    // Each link paints above every line, so no line notches a station's focus ring.
    for (const link of nav.querySelectorAll("a")) expect(link.className).toMatch(/\bz-\[1\]/);
    for (const line of nav.querySelectorAll("[data-line]")) {
      expect(line.className).toContain("pointer-events-none");
      expect(line.className).toMatch(/\bh-px\b/);
      expect(line.className).toContain("lg:h-0.5");
    }
  });

  it("ends the line at the last station drawn: \"Piani\" alone for a visitor who is no admin", () => {
    isAdmin.mockReturnValue(false);
    render(<AppHeader current="plans" />);
    const items = [...screen.getByRole("navigation", { name: "Sezioni" }).querySelectorAll("li")];
    expect(items).toHaveLength(1);
    const [before, after] = [...items[0]!.querySelectorAll("[data-line]")];
    expect(before!.className).toMatch(/\bright-1\/2\b/);
    expect(before!.className).toMatch(/\bw-6\b/);
    expect(after!.className).toMatch(/\bleft-1\/2\b/);
    expect(after!.className).toMatch(/\bw-6\b/);
    expect(after!.className).not.toMatch(/\bright-0\b/);
  });

  it("ends the line at \"Collaudi\" for an admin, and runs it on from \"Piani\" to it", () => {
    render(<AppHeader current="plans" />);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    const [plans, evals] = [...nav.querySelectorAll("li")];
    expect(within(plans!).getByRole("link").textContent).toBe("Piani");
    expect(within(evals!).getByRole("link").textContent).toBe("Collaudi");
    const [plansBefore, plansAfter] = [...plans!.querySelectorAll("[data-line]")];
    const [evalsBefore, evalsAfter] = [...evals!.querySelectorAll("[data-line]")];
    expect(plansBefore!.className).toMatch(/\bw-6\b/);
    // Between the two stations the halves meet: no overhang, edge to edge.
    expect(plansAfter!.className).toMatch(/\bright-0\b/);
    expect(plansAfter!.className).not.toMatch(/\bw-6\b/);
    expect(evalsBefore!.className).toMatch(/\bleft-0\b/);
    expect(evalsBefore!.className).not.toMatch(/\bw-6\b/);
    expect(evalsAfter!.className).toMatch(/\bleft-1\/2\b/);
    expect(evalsAfter!.className).toMatch(/\bw-6\b/);
  });

  it("gives the edges from the stations drawn, whatever their number", () => {
    expect(stationEdge(0, 1)).toBe("only");
    expect([0, 1].map((index) => stationEdge(index, 2))).toEqual(["first", "last"]);
    expect([0, 1, 2].map((index) => stationEdge(index, 3))).toEqual(["first", "middle", "last"]);
  });

  it("leaves the theme toggle to the live screen's bar in the compact bar", () => {
    const { unmount } = render(<AppHeader current="plans" />);
    expect(screen.getByRole("button", { name: "Tema" })).toBeTruthy();
    unmount();
    render(<AppHeaderBar current="plans" compact />);
    expect(screen.getByRole("link", { name: "Piani" }).getAttribute("aria-current")).toBe("page");
    expect(screen.queryByRole("button", { name: "Tema" })).toBeNull();
  });

  it("keeps the theme toggle's code out of the compact bar (the plan page's JS budget)", () => {
    const bar = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "app-header-bar.tsx"), "utf8");
    expect(bar).not.toMatch(/theme-toggle/);
  });
});
