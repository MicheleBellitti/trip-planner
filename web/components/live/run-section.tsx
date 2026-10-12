import type { ReactNode } from "react";

import { Icon } from "@/components/ui/icon";

/**
 * The run's timeline under the finished plan: a closed section like Disclosure's `section`
 * variant (hairline above, condensed title, a count, a caret that turns half a circle).
 * Written locally because the lanes inside hold message Disclosures, and Disclosure's caret
 * follows the nearest open `group/disclosure` ancestor: inside an open Disclosure every
 * message caret would point up while closed. Its own group name keeps them apart.
 */
export function RunSection({ title, meta, children }: { title: string; meta?: string; children: ReactNode }) {
  return (
    <details className="group/run border-t border-rule">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-xs py-3 [&::-webkit-details-marker]:hidden">
        <span className="flex items-baseline gap-2">
          <h2 className="font-cond text-title font-semibold">{title}</h2>
          {meta ? <span className="text-meta text-ink-2">{meta}</span> : null}
        </span>
        <Icon
          name="caret-down"
          size={16}
          className="shrink-0 text-ink-2 transition-[rotate] duration-(--duration-toggle) ease-expo group-open/run:rotate-180 motion-reduce:transition-none"
        />
      </summary>
      <div className="animate-fade-in pb-4">{children}</div>
    </details>
  );
}
