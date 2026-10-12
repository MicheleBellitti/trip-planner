/** The theme preference: absent means "follow the system" (prefers-color-scheme). The toggle
 * pins the opposite of what is showing and stores it here; the inline script in
 * ./theme-script.tsx applies it before the first paint. */
export const THEME_STORAGE_KEY = "atlas-theme";

export type ThemeName = "light" | "dark";

export function isThemeName(value: unknown): value is ThemeName {
  return value === "light" || value === "dark";
}

/** The inline script: read the stored preference and pin it on <html>, before paint. ES5, no
 * dependencies, and silent when storage is blocked (private mode, disabled cookies). */
export const THEME_BOOTSTRAP = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;
