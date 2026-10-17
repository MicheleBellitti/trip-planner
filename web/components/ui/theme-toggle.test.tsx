import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { iconButtonClasses } from "./icon-button";
import { THEME_STORAGE_KEY } from "./theme";
import { ThemeToggle } from "./theme-toggle";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-theme-swap");
  document.head.querySelectorAll('meta[name="theme-color"]').forEach((meta) => meta.remove());
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
  it("is drawn by the icon button's own classes", () => {
    render(<ThemeToggle variant="bare" />);
    const classes = screen.getByRole("button").className.split(/\s+/);
    for (const name of iconButtonClasses("md", "bare").split(/\s+/)) expect(classes).toContain(name);
  });

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
    // Next streams the metadata, so a page can carry a second theme-color meta: repaint every one.
    const metas = [themeColorMeta("#1b2230"), themeColorMeta("#1b2230")];
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Passa al tema chiaro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(metas.map((meta) => meta.content)).toEqual(["#f4efe4", "#f4efe4"]);
    expect(screen.getByRole("button", { name: "Passa al tema scuro" })).toBeTruthy();
  });

  it("drops its ring when bare, beside another round control", () => {
    const { unmount } = render(<ThemeToggle />);
    expect(screen.getByRole("button").className).toMatch(/\bborder-rule-strong\b/);
    unmount();
    render(<ThemeToggle variant="bare" />);
    expect(screen.getByRole("button").className).not.toMatch(/\bborder-rule-strong\b/);
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

describe("the theme swap", () => {
  function queueFrames(): FrameRequestCallback[] {
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      frames.push(callback);
      return frames.length;
    });
    return frames;
  }
  const guarded = () => document.documentElement.hasAttribute("data-theme-swap");

  it("turns transitions off until the new theme has painted, so nothing fades through grey", () => {
    const frames = queueFrames();
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button"));
    expect(guarded()).toBe(true);
    frames.shift()!(0);
    expect(guarded()).toBe(true);
    frames.shift()!(0);
    expect(guarded()).toBe(false);
  });

  it("never leaves the guard on after two quick toggles", () => {
    const frames = queueFrames();
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByRole("button"));
    while (frames.length > 0) frames.shift()!(0);
    expect(guarded()).toBe(false);
  });
});
