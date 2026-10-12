import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SiteHeader } from "./site-header";

// The toggle reads matchMedia, which jsdom does not have.
vi.mock("@/components/ui/theme-toggle", () => ({ ThemeToggle: () => null }));

afterEach(cleanup);

describe("SiteHeader", () => {
  it("links the eval history next to the home link, quietly", () => {
    render(<SiteHeader />);
    const link = screen.getByRole("link", { name: "Valutazioni" });
    expect(link.getAttribute("href")).toBe("/evals");
    expect(link.getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("navigation", { name: "Altre pagine" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Atlas" }).getAttribute("href")).toBe("/");
  });

  it("marks the link as the current page on the eval pages", () => {
    render(<SiteHeader current="evals" />);
    expect(screen.getByRole("link", { name: "Valutazioni" }).getAttribute("aria-current")).toBe("page");
  });
});
