import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ROUTES } from "@/lib/routes";

import { AppHeader } from "./app-header";
import { AppHeaderBar } from "./app-header-bar";

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
    expect(within(nav).queryByRole("link", { name: "Valutazioni" })).toBeNull();
    unmount();

    isAdmin.mockReturnValue(null); // not known yet: nothing appears and vanishes
    render(<AppHeader current="plans" />);
    expect(screen.queryByRole("link", { name: "Valutazioni" })).toBeNull();
  });

  it("on the eval pages the station is always there, as the current one, whoever is looking", () => {
    isAdmin.mockReturnValue(false);
    render(<AppHeader current="evals" />);
    expect(screen.getByRole("link", { name: "Valutazioni" }).getAttribute("aria-current")).toBe("page");
  });

  it("links the lockup to the plans and draws both sections as stations, the current one filled", () => {
    render(<AppHeader current="plans" />);
    expect(screen.getByRole("link", { name: "Atlas" }).getAttribute("href")).toBe(ROUTES.plans);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    const plans = within(nav).getByRole("link", { name: "Piani" });
    const evals = within(nav).getByRole("link", { name: "Valutazioni" });
    expect(plans.getAttribute("href")).toBe(ROUTES.plans);
    expect(plans.getAttribute("aria-current")).toBe("page");
    expect(evals.getAttribute("href")).toBe(ROUTES.evals);
    expect(evals.getAttribute("aria-current")).toBeNull();
  });

  it("marks the eval history as the current section on the eval pages", () => {
    render(<AppHeader current="evals" />);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    expect(within(nav).getByRole("link", { name: "Valutazioni" }).getAttribute("aria-current")).toBe("page");
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
    const current = within(screen.getByRole("link", { name: "Valutazioni" })).getByTestId("station");
    const other = within(screen.getByRole("link", { name: "Piani" })).getByTestId("station");
    expect(current.getAttribute("data-current")).toBe("true");
    expect(other.getAttribute("data-current")).toBe("false");
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
