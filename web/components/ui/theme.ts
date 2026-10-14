/** The pinned theme. Absent means dark, the default ("Carta notturna", DESIGN.md "Colors"): the
 * system preference no longer decides. The toggle pins the other theme and stores it here; the
 * inline script in ./theme-script.tsx applies it before the first paint. */
export const THEME_STORAGE_KEY = "atlas-theme";

export type ThemeName = "light" | "dark";

/** The theme when nothing is pinned. */
export const DEFAULT_THEME: ThemeName = "dark";

/** The browser chrome's colour (<meta name="theme-color">) for each theme: its ground token.
 * tokens.test.ts keeps them equal to globals.css. */
export const THEME_COLORS: Record<ThemeName, string> = { dark: "#1b2230", light: "#f4efe4" };

export function isThemeName(value: unknown): value is ThemeName {
  return value === "light" || value === "dark";
}

/** The inline script: read the stored preference and pin it on <html>, before paint. ES5, no
 * dependencies, and silent when storage is blocked (private mode, disabled cookies). */
export const THEME_BOOTSTRAP = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;
