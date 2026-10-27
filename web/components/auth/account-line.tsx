"use client";

import { useState } from "react";

import { cx } from "@/components/ui/cx";
import { authClient } from "@/lib/auth-client";
import { getAuthMode } from "@/lib/config";
import { useMe } from "@/lib/me";
import { ROUTES } from "@/lib/routes";

/**
 * The quiet line that names the account a page works in ("Sei dentro come a@b.it · Esci"), on the
 * plans page and over the request form. A magic link signs in whichever browser opens it, so a link
 * passed on by someone else would otherwise plan trips in that someone's account without a word on
 * screen. "Esci" is the app's own sign-out (AUTH_MODE=atlas, lib/auth-client.ts) and lands on the
 * login page; with TripTracker's accounts the line only names the address. The line's height is
 * reserved while GET /me answers, so the page never jumps when it lands.
 */
export function AccountLine({
  className,
  navigate = (url) => window.location.assign(url),
}: {
  className?: string;
  navigate?: (url: string) => void;
}) {
  const me = useMe();
  const [busy, setBusy] = useState(false);
  const classes = cx("text-meta text-ink-2", className);
  if (me === null) {
    return (
      <p aria-hidden="true" className={classes} data-testid="account-line-pending">
        {" "}
      </p>
    );
  }
  if (me.email === null) return null;
  const signOut = async () => {
    setBusy(true);
    try {
      await authClient.signOut();
    } catch {
      // The cookie may already be gone; the login page says who is in either way.
    }
    navigate(ROUTES.login);
  };
  return (
    <p className={classes} data-testid="account-line">
      Sei dentro come <span className="text-ink">{me.email}</span>
      {getAuthMode() === "atlas" ? (
        <>
          {" · "}
          <button
            type="button"
            onClick={signOut}
            disabled={busy}
            aria-busy={busy || undefined}
            className="-my-2 inline-flex min-h-11 cursor-pointer items-center rounded-xs text-ink underline-offset-[0.2em] hover:underline disabled:cursor-not-allowed disabled:opacity-55"
          >
            Esci
          </button>
        </>
      ) : null}
    </p>
  );
}
