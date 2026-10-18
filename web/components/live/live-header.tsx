"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { CostMeter } from "@/components/ui/cost-meter";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { Skeleton } from "@/components/ui/skeleton";
import { PlanStatusBadge } from "@/components/ui/status-badge";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { formatUsd } from "@/lib/format";
import type { PlanStatus } from "@/lib/schemas/api";

/** The id the page moves the focus to after "Interrompi il piano", so a screen reader reads the
 * new state ("In interruzione") instead of losing the focus on a disabled button. */
export const PLAN_STATE_ID = "plan-state";

/** The plan's state in the header: PlanStatusBadge, or "In interruzione" while an interrupt is on
 * its way (still `running` for the backend). */
function PlanStateLabel({ status, interrupting }: { status: PlanStatus | null; interrupting: boolean }) {
  if (status === null) return <Skeleton className="h-5 w-24" />;
  return (
    <span id={PLAN_STATE_ID} tabIndex={-1} className="rounded-xs focus:outline-none">
      {interrupting && status === "running" ? (
        <span className="inline-flex items-center gap-2 font-cond text-title font-semibold text-ink">
          <Icon name="stop-circle" size={18} />
          In interruzione
        </span>
      ) : (
        <PlanStatusBadge status={status} size="lg" />
      )}
    </span>
  );
}

/** The state group's areas, spelled whole so Tailwind sees every class: the state and its
 * actions, the meter while the plan runs, and the demo's bar on a row of its own. */
function gridAreas(finished: boolean, bar: boolean): string {
  if (finished) {
    return bar
      ? "[grid-template-areas:'status_actions'_'bar_bar'] lg:[grid-template-areas:'status_actions'_'bar_bar']"
      : "[grid-template-areas:'status_actions'] lg:[grid-template-areas:'status_actions']";
  }
  return bar
    ? "[grid-template-areas:'status_actions'_'meter_meter'_'bar_bar'] lg:[grid-template-areas:'status_meter_actions'_'bar_bar_bar']"
    : "[grid-template-areas:'status_actions'_'meter_meter'] lg:[grid-template-areas:'status_meter_actions']";
}

interface LiveHeaderProps {
  title: string;
  /** "Da Milano, 2 adulti e 2 bambini (8 e 11 anni), budget 2.400 €". */
  summary: string | null;
  status: PlanStatus | null;
  interrupting: boolean;
  /** Elapsed time, already formatted; null before the first tick. */
  elapsed: string | null;
  costCents: number | null;
  budgetCents: number | null;
  /** No cost has been reported yet: the meter says so instead of showing 0,00 $. */
  costPending?: boolean;
  /** "Interrompi", when the plan can still be stopped. */
  action?: ReactNode;
  /** A row of its own across the state group, under the state and the meter: the demo's bar
   * (what this run is, and its controls). */
  bar?: ReactNode;
  /** How a finished plan's cost is named: "Costo del piano", or the demo's recorded run. */
  costLabel?: string;
  /** The bar stays on screen while scrolling (a running or paused plan). The finished plan
   * scrolls with the page: there is nothing left to watch. */
  sticky?: boolean;
}

/**
 * The top of the live screen (DESIGN.md, Layout). Phone: the title block, then a sticky control
 * bar (state and elapsed time, "Interrompi" and the theme toggle, the cost meter across the
 * bottom). From 1080 px: one sticky top bar with the title on the left and the controls on the
 * right. The header is `display: contents` on the phone so the bar sticks for the whole page.
 */
export function LiveHeader({
  title,
  summary,
  status,
  interrupting,
  elapsed,
  costCents,
  budgetCents,
  costPending = false,
  action,
  bar,
  costLabel = "Costo del piano",
  sticky = true,
}: LiveHeaderProps) {
  const running = status === "running" || status === null;
  // A finished plan's cost no longer changes: one quiet line, not a gauge that reads as the trip's.
  const finished = status === "ready";
  const ref = useRef<HTMLElement>(null);
  const groupRef = useRef<HTMLDivElement>(null);

  // The lanes' sticky heads (AgentLanes) stick right under the bar, and the page keeps focused or
  // scrolled-to things clear of it (`scroll-padding-top` in globals.css): publish its height. On
  // the phone `header` is `display: contents` (it has no box) and the sticky bar is the state
  // group; from 1080 px the header itself is.
  useEffect(() => {
    const header = ref.current;
    const group = groupRef.current;
    const root = document.documentElement;
    if (!header || !group) return;
    const publish = () => {
      const bar = getComputedStyle(header).display === "contents" ? group : header;
      root.style.setProperty("--live-bar-h", `${sticky ? Math.round(bar.getBoundingClientRect().height) : 0}px`);
    };
    publish();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    observer?.observe(header);
    observer?.observe(group);
    return () => {
      observer?.disconnect();
      root.style.removeProperty("--live-bar-h");
    };
  }, [sticky]);

  return (
    <header
      ref={ref}
      className={cx(
        "contents",
        "lg:block lg:border-b lg:border-rule",
        sticky && "lg:sticky lg:top-0 lg:z-20 lg:bg-[color-mix(in_srgb,var(--ground)_92%,transparent)] lg:backdrop-blur-[8px]",
      )}
    >
      <div className="contents lg:mx-auto lg:grid lg:max-w-page lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-6 lg:px-7 lg:pt-4 lg:pb-3.5">
        <div className="px-4 pt-1 pb-3 lg:p-0">
          <h1 className="font-cond text-display font-semibold lg:text-display-lg xl:text-display-xl">{title}</h1>
          {summary ? <p className="mt-1 text-small text-ink-2">{summary}</p> : null}
        </div>

        <div
          ref={groupRef}
          aria-label="Stato del piano"
          role="group"
          className={cx(
            "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2.5 border-b border-rule px-4 pt-3 pb-3.5",
            gridAreas(finished, bar !== undefined && bar !== null),
            sticky && "sticky top-0 z-20 bg-[color-mix(in_srgb,var(--ground)_92%,transparent)] backdrop-blur-[8px]",
            "lg:static lg:z-auto lg:gap-x-7 lg:border-0 lg:bg-transparent lg:p-0 lg:backdrop-blur-none",
            finished ? "lg:grid-cols-[auto_auto]" : "lg:grid-cols-[auto_minmax(15rem,18.75rem)_auto]",
          )}
        >
          <div className="flex min-w-0 flex-col gap-px [grid-area:status]">
            <PlanStateLabel status={status} interrupting={interrupting} />
            <span className="text-small text-ink-2">
              {running || status === "budget_paused" ? "Trascorsi" : "Durata"}{" "}
              <b className="font-semibold text-ink">{elapsed ?? "…"}</b>
              {finished && costCents !== null ? (
                <>
                  {" · "}
                  {costLabel} <b className="font-semibold text-ink">{formatUsd(costCents)}</b>
                </>
              ) : null}
            </span>
          </div>
          {finished ? null : (
            <CostMeter
              costCents={costCents}
              budgetCents={budgetCents}
              pending={costPending}
              hint={running && !costPending ? "Aggiornato a fine turno" : undefined}
              className="[grid-area:meter]"
            />
          )}
          <div className="flex items-center gap-2 [grid-area:actions]">
            {action}
            <ThemeToggle variant="bare" className="pointer-coarse:size-11" />
          </div>
          {bar ? <div className="min-w-0 [grid-area:bar]">{bar}</div> : null}
        </div>
      </div>
    </header>
  );
}
