"use client";

import { useIsAdmin } from "@/lib/me";
import { ROUTES } from "@/lib/routes";

import type { AppSection } from "./app-header-bar";
import { Station, stationEdge } from "./station";

/**
 * The header's stations. "Piani" is everyone's; "Collaudi" (the eval history) and "Inviti" (the
 * waitlist) are drawn only for the users who manage the planner (GET /me, lib/me.ts: the backend's
 * ADMIN_EMAILS), and on their own pages always, as the current station: the page says the rest.
 * Nothing is drawn for them while the answer is unknown, so a visitor who is no admin never sees
 * them appear and vanish. The line's outer edges go to the stations actually drawn: "Piani" ends
 * the line when it is alone, the last admin station when there is one.
 */
export function SectionStations({ current }: { current?: AppSection }) {
  const isAdmin = useIsAdmin();
  const stations: { section: AppSection; href: string; label: string }[] = [
    { section: "plans", href: ROUTES.plans, label: "Piani" },
  ];
  if (current === "evals" || isAdmin) stations.push({ section: "evals", href: ROUTES.evals, label: "Collaudi" });
  if (current === "invites" || isAdmin) stations.push({ section: "invites", href: ROUTES.invites, label: "Inviti" });
  return stations.map((item, index) => (
    <Station
      key={item.section}
      href={item.href}
      label={item.label}
      current={current === item.section}
      edge={stationEdge(index, stations.length)}
    />
  ));
}
