"use client";

/**
 * The quiet line that says where the month stands against the user's quota (GET /me `quota`,
 * lib/me.ts): "Questo mese: 3 piani su 10 · 4,20 $ su 15,00 $", and when a limit is reached, that
 * the next plan waits for the month to turn. Nothing is drawn while the answer is on its way or
 * for the users exempt from the quota (admins), so the page never shifts for them. Plain ink-2:
 * amber belongs to bookings due soon, never to a counter.
 */

import { cx } from "@/components/ui/cx";
import { formatUsd } from "@/lib/format";
import { useMe } from "@/lib/me";
import type { Quota } from "@/lib/schemas/api";

import { formatResetDay } from "../request/failure";

/** The line's words, for the component and its tests. */
export function monthUsageWords(quota: Quota): { summary: string; note: string | null } {
  const plans = `${quota.plans_used} ${quota.plans_used === 1 ? "piano" : "piani"} su ${quota.plans_limit}`;
  const summary = `Questo mese: ${plans} · ${formatUsd(quota.cents_used)} su ${formatUsd(quota.cents_limit)}`;
  const reached = quota.plans_used >= quota.plans_limit || quota.cents_used >= quota.cents_limit;
  const note = reached ? `Hai usato quanto previsto per questo mese: il prossimo piano dal ${formatResetDay(quota.resets_at)}.` : null;
  return { summary, note };
}

export function MonthUsage({ className }: { className?: string }) {
  const me = useMe();
  if (!me?.quota) return null;
  const { summary, note } = monthUsageWords(me.quota);
  return (
    <p className={cx("text-small text-ink-2", className)} data-testid="month-usage">
      {summary}
      {note ? (
        <>
          {" "}
          <span className="text-ink">{note}</span>
        </>
      ) : null}
    </p>
  );
}
