import Link from "next/link";

import { LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { iconButtonClasses } from "@/components/ui/icon-button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/** The app's sections. "new" is the request form: it has no nav item, and no "Nuovo piano" there. */
export type AppSection = "plans" | "evals" | "new";

const SECTIONS = [
  { section: "plans", href: ROUTES.plans, label: "Piani" },
  { section: "evals", href: ROUTES.evals, label: "Valutazioni" },
] as const;

/**
 * The header of every signed-in page (DESIGN.md, Navigation): the lockup as the link to the plans,
 * the sections drawn as stations on one line (the current one filled), "Nuovo piano" always at hand
 * as a secondary action (each view keeps its single primary), the theme toggle. One line, at most
 * 72 px, no menu drawer at 393 px, 44 px targets under a finger (the 40 px icon controls grow). `compact` is the live screen's slim top row: its sticky control
 * bar carries the toggle.
 */
export function AppHeader({ current, compact = false }: { current?: AppSection; compact?: boolean }) {
  return (
    <header className={cx(!compact && "border-b border-rule")}>
      <div
        className={cx(
          "mx-auto flex max-w-page items-center justify-between gap-2 px-4 lg:px-7",
          compact ? "min-h-14" : "min-h-16",
        )}
      >
        <Wordmark href={ROUTES.plans} compact />
        <div className="flex items-center gap-1 sm:gap-2">
          <nav aria-label="Sezioni">
            <ul className="flex">
              {SECTIONS.map((item, index) => (
                <Station
                  key={item.section}
                  href={item.href}
                  label={item.label}
                  current={current === item.section}
                  first={index === 0}
                  last={index === SECTIONS.length - 1}
                />
              ))}
            </ul>
          </nav>
          {current === "new" ? null : (
            <>
              <LinkButton href={ROUTES.newPlan} variant="secondary" icon="plus" className="max-sm:hidden">
                Nuovo piano
              </LinkButton>
              <Link
                href={ROUTES.newPlan}
                aria-label="Nuovo piano"
                title="Nuovo piano"
                className={cx(iconButtonClasses(), "pointer-coarse:size-11 sm:hidden")}
              >
                <Icon name="plus" size={18} />
              </Link>
            </>
          )}
          {compact ? null : <ThemeToggle className="pointer-coarse:size-11" />}
        </div>
      </div>
    </header>
  );
}

/**
 * One section on the header's line: its label above its station. The line runs from the first
 * station to the last, behind them (each item draws the halves that face its neighbours). The
 * link is positioned, so it paints above the line drawn before it.
 */
function Station({
  href,
  label,
  current,
  first,
  last,
}: {
  href: string;
  label: string;
  current: boolean;
  first: boolean;
  last: boolean;
}) {
  // The station's centre is 11.5 px above the item's bottom (8 px padding + half of 7 px).
  const half = "pointer-events-none absolute bottom-[11px] h-px bg-rule-strong";
  return (
    <li className="relative flex">
      {first ? null : <span aria-hidden="true" className={cx(half, "right-1/2 left-0")} />}
      {last ? null : <span aria-hidden="true" className={cx(half, "right-0 left-1/2")} />}
      <Link
        href={href}
        aria-current={current ? "page" : undefined}
        className={cx(
          "group relative grid min-h-11 justify-items-center gap-1 rounded-xs px-2.5 pt-1 pb-2 text-small no-underline sm:px-3",
          current ? "font-semibold text-ink" : "text-ink-2 hover:text-ink",
        )}
      >
        <span>{label}</span>
        <span
          aria-hidden="true"
          className={cx(
            "size-[7px] rounded-full border-[1.5px] transition-colors duration-(--duration-hover) ease-out",
            current ? "border-ink bg-ink" : "border-ink-2 bg-ground group-hover:bg-ink-2",
          )}
        />
      </Link>
    </li>
  );
}
