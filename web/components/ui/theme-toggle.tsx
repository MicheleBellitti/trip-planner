"use client";

import { useLayoutEffect, useSyncExternalStore } from "react";

import { cx } from "./cx";
import { Icon } from "./icon";
import { isThemeName, THEME_STORAGE_KEY, type ThemeName } from "./theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";
const THEME_EVENT = "atlas-theme-change";

function readStored(): ThemeName | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeName(value) ? value : null;
  } catch {
    return null;
  }
}

/** The theme on screen: the pinned one, else the system's. */
function resolvedTheme(): ThemeName {
  const pinned = document.documentElement.getAttribute("data-theme");
  if (isThemeName(pinned)) return pinned;
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", onChange);
  window.addEventListener(THEME_EVENT, onChange);
  return () => {
    media.removeEventListener("change", onChange);
    window.removeEventListener(THEME_EVENT, onChange);
  };
}

/**
 * The theme toggle: a round icon button that pins the opposite of the theme on screen and
 * remembers it (localStorage, read before paint by ThemeScript). The glyph is chosen by CSS
 * (inherited --show-in-light / --show-in-dark), so it is right on the first paint; only the
 * accessible name waits for the client.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const theme = useSyncExternalStore<ThemeName | null>(subscribe, resolvedTheme, () => null);

  // React's Strict Mode remount in development resets <html>'s attributes: re-apply the pinned
  // theme before paint (a no-op in production, where the inline script already set it).
  useLayoutEffect(() => {
    const stored = readStored();
    if (stored && document.documentElement.getAttribute("data-theme") !== stored) {
      document.documentElement.setAttribute("data-theme", stored);
      window.dispatchEvent(new Event(THEME_EVENT));
    }
  }, []);

  function toggle() {
    const next: ThemeName = resolvedTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
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
      className={cx(
        "inline-grid size-10 shrink-0 place-items-center rounded-full border-[1.5px] border-rule-strong bg-transparent text-ink",
        "transition-[background-color,scale] duration-(--duration-hover) ease-out hover:bg-notice-wash",
        "active:scale-[0.96] active:duration-(--duration-press) motion-reduce:active:scale-100",
        className,
      )}
    >
      <Icon name="moon" size={18} className="[display:var(--show-in-light)]" />
      <Icon name="sun" size={18} className="[display:var(--show-in-dark)]" />
    </button>
  );
}
