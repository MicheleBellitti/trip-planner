import { afterEach, describe, expect, it } from "vitest";

import { THEME_BOOTSTRAP, THEME_COLORS, THEME_STORAGE_KEY } from "./theme";

/** Runs the inline script the way the browser does while parsing <head>. */
function runBootstrap() {
  new Function(THEME_BOOTSTRAP)();
}

function themeColorMeta(): HTMLMetaElement {
  const meta = document.createElement("meta");
  meta.name = "theme-color";
  meta.content = THEME_COLORS.dark;
  document.head.append(meta);
  return meta;
}

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
  document.head.querySelectorAll('meta[name="theme-color"]').forEach((meta) => meta.remove());
  localStorage.clear();
});

describe("THEME_BOOTSTRAP", () => {
  it("pins a stored light theme and repaints every browser-chrome meta before the first paint", () => {
    const metas = [themeColorMeta(), themeColorMeta()];
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    runBootstrap();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(metas.map((meta) => meta.content)).toEqual([THEME_COLORS.light, THEME_COLORS.light]);
  });

  it("leaves the dark default alone when nothing is stored", () => {
    const meta = themeColorMeta();
    runBootstrap();
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
    expect(meta.content).toBe(THEME_COLORS.dark);
  });

  it("still pins the theme when the page has no theme-color meta", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(runBootstrap).not.toThrow();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
