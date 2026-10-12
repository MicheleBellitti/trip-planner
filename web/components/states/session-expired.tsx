import { buttonClasses } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { InlineStatus } from "@/components/ui/notice";

import { StatePanel } from "./state-panel";

/** The sign-in link: TripTracker's login, which brings the user back to this page. Same tab:
 * it is a step of this page, not another site to keep open. */
function SignInLink({ href, variant }: { href: string; variant: "primary" | "inline" }) {
  if (variant === "inline") {
    return (
      <a href={href} className="rounded-xs font-semibold text-ink underline">
        Accedi di nuovo
      </a>
    );
  }
  return (
    <a href={href} className={buttonClasses("primary")}>
      <Icon name="sign-in" size={16} />
      Accedi di nuovo
    </a>
  );
}

/** Signed out with nothing on screen yet: what happened and the way back in. */
export function SessionExpiredPanel({ loginUrl }: { loginUrl: string }) {
  return (
    <StatePanel
      icon="sign-in"
      title="Sessione scaduta"
      headingId="state-expired"
      actions={<SignInLink href={loginUrl} variant="primary" />}
    >
      <div className="min-w-0 lg:col-span-3">
        <dt className="sr-only">Cosa è successo</dt>
        <dd className="m-0 max-w-prose text-small text-ink">
          L&apos;accesso a TripTracker è scaduto. Accedi di nuovo: tornerai qui, al tuo piano.
        </dd>
      </div>
    </StatePanel>
  );
}

/** Signed out while the page shows the plan: the last known state stays, with this line on top. */
export function SessionExpiredLine({ loginUrl, className }: { loginUrl: string; className?: string }) {
  return (
    <InlineStatus icon="sign-in" className={className}>
      Sessione scaduta: quello che vedi non si aggiorna più. <SignInLink href={loginUrl} variant="inline" /> per
      tornare qui.
    </InlineStatus>
  );
}
