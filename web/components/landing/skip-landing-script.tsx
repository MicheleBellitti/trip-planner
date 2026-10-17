import { SKIP_LANDING_BOOTSTRAP } from "@/lib/returning";

/**
 * Sends a returning, signed-in visitor from "/" to the plans before the landing paints. It uses the
 * ThemeScript pattern: text/javascript on the server, text/plain on the client, so React never runs
 * it twice. Render it first in the landing's markup. Only a full load of "/" runs it; client-side
 * navigation never executes inline scripts.
 */
export function SkipLandingScript() {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: SKIP_LANDING_BOOTSTRAP }}
    />
  );
}
