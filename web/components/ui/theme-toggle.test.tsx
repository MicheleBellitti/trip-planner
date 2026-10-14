import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { THEME_STORAGE_KEY } from "./theme";
import { ThemeToggle } from "./theme-toggle";

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  document.head.querySelector('meta[name="theme-color"]')?.remove();
  try {
    localStorage.clear();
  } catch {
    // A test blocked storage on purpose.
  }
});

function themeColorMeta(content: string): HTMLMetaElement {
  const meta = document.createElement("meta");
  meta.name = "theme-color";
  meta.content = content;
  document.head.append(meta);
  return meta;
}

describe("ThemeToggle", () => {
  it("treats a page with nothing pinned as dark, the default", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Passa al tema chiaro" })).toBeTruthy();
  });

  it("keeps a light theme that was pinned before dark became the default", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(<ThemeToggle />);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(screen.getByRole("button", { name: "Passa al tema scuro" })).toBeTruthy();
  });

  it("keeps a pinned dark theme dark", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Passa al tema chiaro" })).toBeTruthy();
  });

  it("pins light from the default, remembers it and repaints the browser chrome", () => {
    const meta = themeColorMeta("#1b2230");
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Passa al tema chiaro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(meta.content).toBe("#f4efe4");
    expect(screen.getByRole("button", { name: "Passa al tema scuro" })).toBeTruthy();
  });

  it("still switches for the session when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Passa al tema chiaro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
