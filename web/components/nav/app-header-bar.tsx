import Link from "next/link";
import type { ReactNode } from "react";

import { SessionRefresh } from "@/components/auth/session-refresh";
import { LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { iconButtonClasses } from "@/components/ui/icon-button";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

import { SectionStations } from "./section-stations";

/** The app's sections. "new" is the request form: it has no nav item, and no "Nuovo piano" there. */
export type AppSection = "plans" | "evals" | "new";

/**
 * The header's bar (DESIGN.md, Navigation): the lockup as the link to the plans, the sections drawn
 * as stations on one line (the current one is the "you are here" ring), then `trailing` (AppHeader
 * puts the bare theme toggle there), then "Nuovo piano", always last and always a secondary action
 * (each view keeps its single primary). "Piani" is everyone's; "Collaudi" is drawn only for the
 * users who manage the planner (SectionStations). One line, at most 72 px, no menu drawer at 393 px, 44 px targets under a finger (the 40 px
 * icon controls grow). `compact` is the live screen's slim top row; it has no toggle (the sticky
 * control bar carries it), and this file imports none, so the plan page ships no second copy.
 * Every signed-in page draws this bar, so it also carries SessionRefresh, which keeps the session
 * sliding.
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
      <SessionRefresh />
      <div
        className={cx(
          "mx-auto flex max-w-page items-center justify-between gap-2 px-4 lg:px-7",
          compact ? "min-h-14" : "min-h-16",
        )}
      >
        <Wordmark href={ROUTES.plans} compact />
        <div className="flex items-center gap-2">
          <nav aria-label="Sezioni">
            <ul className="flex">
              <SectionStations current={current} />
            </ul>
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
