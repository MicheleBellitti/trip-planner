"use client";

import { useIsAdmin } from "@/lib/me";
import { ROUTES } from "@/lib/routes";

import type { AppSection } from "./app-header-bar";
import { Station } from "./station";

/**
 * The stations of the users who manage the planner (GET /me, lib/me.ts: the backend's
 * ADMIN_EMAILS): the eval history and the invitations. On their own pages each is always drawn as
 * the current station: the page says the rest. Nothing is drawn while the answer is unknown, so a
 * visitor who is no admin never sees them appear and vanish.
 */
export function AdminStations({ current }: { current?: AppSection }) {
  const isAdmin = useIsAdmin();
  return (
    <>
      {current === "evals" || isAdmin ? <Station href={ROUTES.evals} label="Valutazioni" current={current === "evals"} /> : null}
      {current === "invites" || isAdmin ? <Station href={ROUTES.invites} label="Inviti" current={current === "invites"} /> : null}
    </>
  );
}
