"use client";

/**
 * The quiet line that says where the month stands against the user's quota (GET /me `quota`,
 * lib/me.ts): "Questo mese: 3 piani su 10 · 4,20 $ impegnati su 15,00 $" ("impegnati": the
 * recorded cost plus the budget still reserved by the plans running, the figure the refusal and the
 * backend use too), and on its own line when a limit is reached, the day the next plan can start.
 * While the answer is on its way the line's height is reserved, so the list below never jumps when
 * it lands; nothing at all for the users exempt from the quota (admins), as soon as the tab knows
 * them. Plain ink-2 with a calendar glyph, like the cost estimate's wallet: amber belongs to
 * bookings due soon, never to a counter.
 */

import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { formatUsd } from "@/lib/format";
import { useMe, useRememberedAdmin } from "@/lib/me";
import type { Quota } from "@/lib/schemas/api";

import { formatResetDay, plansWord, quotaReached } from "../request/failure";

/** The line's words, for the component and its tests. */
export function monthUsageWords(quota: Quota): { summary: string; note: string | null } {
  const plans = `${plansWord(quota.plans_used)} su ${quota.plans_limit}`;
  const summary = `Questo mese: ${plans} · ${formatUsd(quota.cents_used)} impegnati su ${formatUsd(quota.cents_limit)}`;
  const note = quotaReached(quota) ? `Il prossimo piano dal ${formatResetDay(quota.resets_at)}.` : null;
  return { summary, note };
}

interface MonthUsageProps {
  className?: string;
  /** `small` (14.5 px) under a page title; `meta` (13.5 px) beside the form's cost estimate. */
  size?: "small" | "meta";
  /** Without the "next plan from" sentence: the form says it in its own notice. */
  withNote?: boolean;
}

export function MonthUsage({ className, size = "small", withNote = true }: MonthUsageProps) {
  const remembered = useRememberedAdmin();
  const me = useMe();
  const text = size === "meta" ? "text-meta" : "text-small";
  // An admin the tab remembers: nothing, and nothing reserved.
  if (me === null && remembered === true) return null;
  if (me === null) {
    // One empty line of this size until the answer lands: the page below stays where it is. A
    // no-break space, written as an escape so no editor turns it into a plain space, which would
    // collapse to a line box of no height.
    return (
      <p aria-hidden="true" className={cx(text, className)} data-testid="month-usage-pending">
        {"\u00a0"}
      </p>
    );
  }
  if (!me.quota) return null;
  const { summary, note } = monthUsageWords(me.quota);
  return (
    <div className={cx(text, "flex items-start gap-1.5 text-ink-2", className)} data-testid="month-usage">
      <Icon name="calendar-blank" size={15} className="mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p>{summary}</p>
        {withNote && note ? <p className="text-ink">{note}</p> : null}
      </div>
    </div>
  );
}
