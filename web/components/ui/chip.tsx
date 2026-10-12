import type { ReactNode } from "react";

import type { AgentName } from "@/lib/schemas/generated/ui-event";

import { cx } from "./cx";

/**
 * A small static tag: a price's status ("verificato", "stimato"), a profile ("sviluppo"), a
 * count. Pill, 12.5 px semibold. `outline` has a 3:1 rule-strong border; `quiet` sits on the
 * notice wash. Never amber, never a status colour: a chip labels, the words carry the meaning.
 */
export function Chip({
  children,
  tone = "outline",
  className,
}: {
  children: ReactNode;
  tone?: "outline" | "quiet";
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2 text-micro font-semibold whitespace-nowrap text-ink",
        tone === "outline" ? "border border-rule-strong" : "border border-transparent bg-notice-wash",
        className,
      )}
    >
      {children}
    </span>
  );
}

interface ToolChipProps {
  agent: AgentName;
  /** The tool event's one-line Italian title, e.g. "Expedia · voli MXP→LIS · 14–18 nov". */
  title: string;
  /** How long it has been running, already formatted ("0:14"); omitted before the first tick. */
  elapsed?: string | null;
  /** `plate`: the live station at the end of the line, filled with the line colour.
   * `inline`: one line under the lane name (desktop) or in a collapsed lane (phone). */
  variant?: "plate" | "inline";
  /** `inline` only: keep the title (and the time after it) to two lines. */
  clamp?: boolean;
  className?: string;
}

/**
 * The tool an agent is running now. As a `plate` it is the "you are here" sign at the end of the
 * lane's line; `inline` repeats it under the lane's name on desktop (the Sala borrowing) and in
 * the one-line peek of a collapsed lane on the phone.
 */
export function ToolChip({ agent, title, elapsed, variant = "plate", clamp = false, className }: ToolChipProps) {
  if (variant === "inline") {
    return (
      <span data-agent={agent} className={cx("flex min-w-0 items-baseline gap-2 text-small text-ink", className)}>
        <span
          aria-hidden="true"
          className="relative top-[1px] inline-block size-[9px] shrink-0 rounded-full border-2 border-line"
        />
        <span className={cx("min-w-0 [overflow-wrap:anywhere]", clamp && "line-clamp-2")}>
          {title}
          {elapsed ? <span className="ml-1.5 whitespace-nowrap text-ink-2">in corso da {elapsed}</span> : null}
        </span>
      </span>
    );
  }
  return (
    <div
      data-agent={agent}
      className={cx("rounded-sm bg-line px-2.5 pt-[7px] pb-2 text-on-line shadow-plate", className)}
    >
      <p className="text-small leading-[1.3] font-semibold [overflow-wrap:anywhere]">{title}</p>
      {elapsed ? <p className="mt-0.5 text-micro opacity-92">in corso da {elapsed}</p> : null}
    </div>
  );
}
