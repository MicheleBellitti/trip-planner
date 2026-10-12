import { THEME_BOOTSTRAP } from "./theme";

/**
 * Applies a pinned theme before the first paint (Next.js guide "Preventing flash before
 * hydration", Themes). Render it once, in the root layout's <head>, with
 * `suppressHydrationWarning` on <html> because the script sets data-theme there.
 *
 * On the server the script is `text/javascript` and runs while the HTML is parsed; on the client
 * it is `text/plain`, so React never warns about rendering a script and never runs it twice.
 */
export function ThemeScript() {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }}
    />
  );
}
