"use client";

import { useIsAdmin } from "@/lib/me";
import { ROUTES } from "@/lib/routes";

import { Station } from "./station";

/**
 * The eval history's station, drawn only for the users who may open it (GET /me, lib/me.ts: the
 * backend's ADMIN_EMAILS). On the eval pages themselves it is always drawn as the current
 * station: the page says the rest. Nothing is drawn while the answer is unknown, so a visitor who
 * is no admin never sees it appear and vanish.
 */
export function EvalsStation({ current }: { current: boolean }) {
  const isAdmin = useIsAdmin();
  if (!current && !isAdmin) return null;
  return <Station href={ROUTES.evals} label="Valutazioni" current={current} />;
}
