import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/components/ui/cx";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";

/**
 * The header of the home page and the request form (DESIGN.md, Navigation): the wordmark as the
 * link home, the page's own actions, the theme toggle. One line, never taller than 72 px. Not
 * sticky and not translucent: the live screen's control bar is the only glass surface. "Valutazioni"
 * (the eval history) is a quiet text link next to the page's actions; `current="evals"` marks it
 * on the eval pages.
 */
export function SiteHeader({ children, current }: { children?: ReactNode; current?: "evals" }) {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex min-h-16 max-w-page items-center justify-between gap-3 px-4 py-3 lg:px-7">
        <Wordmark href="/" />
        <div className="flex items-center gap-2">
          {children}
          <nav aria-label="Altre pagine">
            <Link
              href="/evals"
              aria-current={current === "evals" ? "page" : undefined}
              className={cx(
                "inline-flex min-h-11 items-center rounded-full px-3 text-small no-underline transition-[background-color,color] duration-(--duration-hover) ease-out",
                "hover:bg-notice-wash hover:text-ink",
                current === "evals" ? "font-semibold text-ink underline decoration-ink underline-offset-[0.35em]" : "text-ink-2",
              )}
            >
              Valutazioni
            </Link>
          </nav>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
