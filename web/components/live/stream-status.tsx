import { InlineStatus } from "@/components/ui/notice";
import { SessionExpiredLine } from "@/components/states/session-expired";
import type { ConnectionStatus } from "@/lib/plan-events/labels";

interface StreamStatusProps {
  connection: ConnectionStatus;
  online: boolean;
  /** TripTracker's login that returns here, when the session expired. */
  loginUrl: string | null;
  /** When the state on screen was last true ("10:41"), for the offline line. */
  lastUpdate: string | null;
}

/**
 * The one discreet line under the header (spec, "Tutti gli stati sono disegnati"): signed out,
 * offline (the last known state, marked as not updated) or the stream reconnecting (missed
 * events arrive by themselves). Nothing when all is well. Never a live region: aria-live is
 * for lane state changes only.
 */
export function StreamStatus({ connection, online, loginUrl, lastUpdate }: StreamStatusProps) {
  let line = null;
  if (loginUrl) {
    line = <SessionExpiredLine loginUrl={loginUrl} />;
  } else if (!online) {
    line = (
      <InlineStatus icon="wifi-slash">
        Non aggiornato: sei offline{lastUpdate ? `, ultimo stato alle ${lastUpdate}` : ""}. Riprende da solo quando
        torna la rete.
      </InlineStatus>
    );
  } else if (connection === "reconnecting") {
    line = <InlineStatus turning>Stream in riconnessione. Gli eventi persi arrivano da soli.</InlineStatus>;
  }
  if (!line) return null;
  return <div className="mx-auto max-w-page px-4 pt-2.5 lg:px-7">{line}</div>;
}
