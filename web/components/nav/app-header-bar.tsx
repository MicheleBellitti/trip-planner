import Link from "next/link";
import type { ReactNode } from "react";

import { LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { iconButtonClasses } from "@/components/ui/icon-button";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

import { AdminStations } from "./admin-stations";
import { ScrollToCurrent } from "./scroll-to-current";
import { Station } from "./station";

/** The app's sections. "new" is the request form: it has no nav item, and no "Nuovo piano" there;
 * "evals" and "invites" are the admins' (AdminStations). */
export type AppSection = "plans" | "evals" | "invites" | "new";

/**
 * The header's bar (DESIGN.md, Navigation): the lockup as the link to the plans, the sections drawn
 * as stations on one line (the current one is the "you are here" ring), then `trailing` (AppHeader
 * puts the bare theme toggle there), then "Nuovo piano", always last and always a secondary action
 * (each view keeps its single primary). "Piani" is everyone's; "Valutazioni" and "Inviti" (AdminStations)
 * are drawn only for the users who manage the planner. One line, at most 72 px, no menu drawer at 393 px, 44 px targets under a finger (the 40 px
 * icon controls grow). Below about 360 px the three admin stations no longer fit beside the
 * controls: the strip scrolls sideways (the line runs past the edge, as it does past the outer
 * stations) instead of pushing the page wider, and ScrollToCurrent keeps the current one in view. `compact` is the live screen's slim top row; it has no toggle (the sticky
 * control bar carries it), and this file imports none, so the plan page ships no second copy.
 */
export function AppHeaderBar({
  current,
  compact = false,
  trailing,
}: {
  current?: AppSection;
  compact?: boolean;
  trailing?: ReactNode;
}) {
  return (
    <header className={cx(!compact && "border-b border-rule")}>
      <div
        className={cx(
          "mx-auto flex max-w-page items-center justify-between gap-2 px-4 lg:px-7",
          compact ? "min-h-14" : "min-h-16",
        )}
      >
        <Wordmark href={ROUTES.plans} compact />
        <div className="flex min-w-0 items-center gap-2">
          {/* The vertical padding keeps the links' focus ring inside the scroll container. */}
          <nav aria-label="Sezioni" className="-my-1 min-w-0 overflow-x-auto py-1 [scrollbar-width:none]">
            <ul className="flex">
              <Station href={ROUTES.plans} label="Piani" current={current === "plans"} />
              <AdminStations current={current} />
            </ul>
            <ScrollToCurrent />
          </nav>
          {trailing}
          <NewPlan current={current === "new"} />
        </div>
      </div>
    </header>
  );
}

/**
 * "Nuovo piano", always the header's last item so the corner never changes meaning: the labelled
 * secondary button from 640 px, a ringed "+" below it (the theme toggle beside it is bare). On the
 * form itself it stays in place, marked as the current page, so nothing shifts.
 */
function NewPlan({ current }: { current: boolean }) {
  const page = current ? "page" : undefined;
  return (
    <>
      <LinkButton
        href={ROUTES.newPlan}
        variant="secondary"
        icon="plus"
        aria-current={page}
        className="max-sm:hidden"
      >
        Nuovo piano
      </LinkButton>
      <Link
        href={ROUTES.newPlan}
        aria-label="Nuovo piano"
        aria-current={page}
        title="Nuovo piano"
        className={cx(iconButtonClasses(), "pointer-coarse:size-11 sm:hidden")}
      >
        <Icon name="plus" size={18} />
      </Link>
    </>
  );
}
