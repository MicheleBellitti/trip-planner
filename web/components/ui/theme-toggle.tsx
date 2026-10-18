"use client";

import { useLayoutEffect, useSyncExternalStore } from "react";

import { cx } from "./cx";
import { Icon } from "./icon";
import { iconButtonClasses } from "./icon-button";
import { DEFAULT_THEME, isThemeName, THEME_COLORS, THEME_EVENT, THEME_STORAGE_KEY, type ThemeName } from "./theme";

function readStored(): ThemeName | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeName(value) ? value : null;
  } catch {
    return null;
  }
}

/** The theme on screen: the pinned one, else the dark default. */
function resolvedTheme(): ThemeName {
  const pinned = document.documentElement.getAttribute("data-theme");
  return isThemeName(pinned) ? pinned : DEFAULT_THEME;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(THEME_EVENT, onChange);
  return () => window.removeEventListener(THEME_EVENT, onChange);
}

/** The browser chrome (iOS status bar, Android toolbar) follows the theme on screen. Every
 * theme-color meta: Next streams the metadata, so a page can carry a second one. */
function syncThemeColor(theme: ThemeName) {
  for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
    meta.setAttribute("content", THEME_COLORS[theme]);
  }
}

/** The latest swap: only its frames take the guard off, so quick toggles never strand it on. */
let latestSwap = 0;

/** The swap repaints every colour at once. Transitions (hover washes, borders) would fade the
 * old colours into the new ones through grey, so `data-theme-swap` turns them off (globals.css)
 * until two frames later, when the new theme is on screen. */
function guardSwap() {
  const root = document.documentElement;
  const swap = ++latestSwap;
  root.setAttribute("data-theme-swap", "");
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      if (swap === latestSwap) root.removeAttribute("data-theme-swap");
    }),
  );
}

/**
 * The theme toggle: a round icon button that pins the other theme (dark is the default) and
 * remembers it (localStorage, read before paint by ThemeScript). `bare` drops the ring. The glyph is chosen by CSS
 * (inherited --show-in-light / --show-in-dark), so it is right on the first paint; only the
 * accessible name waits for the client.
 */
export function ThemeToggle({ className, variant = "outline" }: { className?: string; variant?: "outline" | "bare" }) {
  const theme = useSyncExternalStore<ThemeName | null>(subscribe, resolvedTheme, () => null);

  // React's Strict Mode remount in development resets <html>'s attributes: re-apply the pinned
  // theme before paint (a no-op in production, where the inline script already set it).
  useLayoutEffect(() => {
    const stored = readStored();
    if (stored && document.documentElement.getAttribute("data-theme") !== stored) {
      document.documentElement.setAttribute("data-theme", stored);
      window.dispatchEvent(new Event(THEME_EVENT));
    }
    syncThemeColor(resolvedTheme());
  }, []);

  function toggle() {
    const next: ThemeName = resolvedTheme() === "dark" ? "light" : "dark";
    guardSwap();
    document.documentElement.setAttribute("data-theme", next);
    syncThemeColor(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage blocked: the choice lasts until the page is reloaded.
    }
    window.dispatchEvent(new Event(THEME_EVENT));
  }

  const label =
    theme === null ? "Cambia tema" : theme === "dark" ? "Passa al tema chiaro" : "Passa al tema scuro";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      // `bare`: no ring, beside another round control (the header's "Nuovo piano"), so the two
      // never read as twins.
      className={cx(iconButtonClasses("md", variant), className)}
    >
      <Icon name="moon" size={18} className="[display:var(--show-in-light)]" />
      <Icon name="sun" size={18} className="[display:var(--show-in-dark)]" />
    </button>
  );
}
