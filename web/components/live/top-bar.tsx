import type { ReactNode } from "react";

import { Wordmark } from "@/components/ui/wordmark";

/** The slim row above the plan: the wordmark, the link home to the list of plans, and the page's
 * own controls when the sticky bar does not carry them (the finished plan). */
export function TopBar({ children }: { children?: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-14 max-w-page items-center justify-between gap-3 px-4 lg:px-7">
      <Wordmark href="/" />
      {children}
    </div>
  );
}
