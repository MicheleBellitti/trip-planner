import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LandingPage from "@/app/page";
import { SKIP_LANDING_BOOTSTRAP } from "@/lib/returning";
import { ROUTES } from "@/lib/routes";

vi.mock("@/components/ui/theme-toggle", () => ({ ThemeToggle: () => <button type="button">Tema</button> }));

afterEach(cleanup);

describe("the landing", () => {
  it("runs the landing skip before anything else on the page", () => {
    const { container } = render(<LandingPage />);
    const first = container.firstElementChild;
    expect(first?.tagName).toBe("SCRIPT");
    expect(first?.innerHTML).toBe(SKIP_LANDING_BOOTSTRAP);
  });

  it("has a public header: the lockup home, how it works, sign in to the plans", () => {
    render(<LandingPage />);
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Atlas" }).getAttribute("href")).toBe(ROUTES.home);
    expect(within(header).getByRole("link", { name: "Come funziona" }).getAttribute("href")).toBe("#come-funziona");
    expect(within(header).getByRole("link", { name: "Accedi" }).getAttribute("href")).toBe(ROUTES.plans);
  });
});
