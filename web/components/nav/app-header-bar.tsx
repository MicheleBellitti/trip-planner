import Link from "next/link";
import type { ReactNode } from "react";

import { LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { iconButtonClasses } from "@/components/ui/icon-button";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/** The app's sections. "new" is the request form: it has no nav item, and no "Nuovo piano" there. */
export type AppSection = "plans" | "evals" | "new";

const SECTIONS = [
  { section: "plans", href: ROUTES.plans, label: "Piani" },
  { section: "evals", href: ROUTES.evals, label: "Collaudi" },
] as const;

/**
 * The header's bar (DESIGN.md, Navigation): the lockup as the link to the plans, the sections drawn
 * as stations on one line (the current one is the "you are here" ring), then `trailing` (AppHeader
 * puts the bare theme toggle there), then "Nuovo piano", always last and always a secondary action
 * (each view keeps its single primary). One line, at most 72 px, no menu drawer at 393 px, 44 px targets under a finger (the 40 px
 * icon controls grow). `compact` is the live screen's slim top row; it has no toggle (the sticky
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
        <div className="flex items-center gap-2">
          <nav aria-label="Sezioni">
            <ul className="flex">
              {SECTIONS.map((item, index) => (
                <Station
                  key={item.section}
                  href={item.href}
                  label={item.label}
                  current={current === item.section}
                  edge={index === 0 ? "first" : index === SECTIONS.length - 1 ? "last" : "middle"}
                />
              ))}
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

/**
 * One section on the header's line: its label above its station. The line runs through every
 * station and the same 24 px past the outer ones, a route that goes on beyond the edge of the map,
 * so the pair never reads as a two-step progress bar; 1 px on the phone, 2 px from 1080 px, where
 * the header has room for it. The current station is the larger "you are here" ring. The link is
 * positioned, so it paints above the line drawn before it.
 */
function Station({
  href,
  label,
  current,
  edge,
}: {
  href: string;
  label: string;
  current: boolean;
  edge: "first" | "middle" | "last";
}) {
  // The station's centre is 13.5 px above the item's bottom (8 px padding + half of its 11 px box).
  const half = "pointer-events-none absolute bottom-[13px] h-px bg-rule-strong lg:bottom-[12.5px] lg:h-0.5";
  return (
    <li className="relative flex">
      <span aria-hidden="true" data-line="" className={cx(half, edge === "first" ? "right-1/2 w-6" : "right-1/2 left-0")} />
      <span aria-hidden="true" data-line="" className={cx(half, edge === "last" ? "left-1/2 w-6" : "right-0 left-1/2")} />
      <Link
        href={href}
        aria-current={current ? "page" : undefined}
        className={cx(
          "group relative grid min-h-11 justify-items-center gap-1 rounded-xs px-2.5 pt-1 pb-2 text-small no-underline sm:px-3",
          current ? "font-semibold text-ink" : "text-ink-2 hover:text-ink",
        )}
      >
        <span>{label}</span>
        <span aria-hidden="true" className="grid size-[11px] place-items-center">
          <span
            data-testid="station"
            data-current={current}
            className={cx(
              "rounded-full bg-ground transition-colors duration-(--duration-hover) ease-out",
              current ? "size-[11px] border-[3px] border-ink" : "size-[9px] border-[1.5px] border-ink-2 group-hover:bg-ink-2",
            )}
          />
        </span>
      </Link>
    </li>
  );
}
