import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";

/**
 * The header of the home page and the request form (DESIGN.md, Navigation): the wordmark as the
 * link home, the page's own actions, the theme toggle. One line, never taller than 72 px. Not
 * sticky and not translucent: the live screen's control bar is the only glass surface.
 */
export function SiteHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex min-h-16 max-w-page items-center justify-between gap-3 px-4 py-3 lg:px-7">
        <Wordmark href="/" />
        <div className="flex items-center gap-2">
          {children}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
