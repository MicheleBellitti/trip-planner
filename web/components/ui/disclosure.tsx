import type { ReactNode } from "react";

import { cx } from "./cx";
import { Icon } from "./icon";

interface DisclosureProps {
  /** What the closed row says: the message line ("coordinatore → voli: incarico") or the section
   * title ("Alternative scartate"). */
  summary: ReactNode;
  /** Shown next to a section title in ink-2, e.g. a count ("3"). */
  meta?: ReactNode;
  children: ReactNode;
  /** `row`: one line inside a lane or a list (inter-agent messages); `section`: a full-width
   * closed section with a hairline above (discarded alternatives, the timeline under a plan). */
  variant?: "row" | "section";
  defaultOpen?: boolean;
  /** Same `name` on several disclosures: opening one closes the others (native exclusivity). */
  name?: string;
  /** Language of the hidden text: inter-agent messages are English (`lang="en"`). */
  contentLang?: string;
  className?: string;
}

/**
 * Native <details>/<summary>: keyboard, focus and the open state come from the browser, and it
 * works without JavaScript. The caret turns half a circle (220 ms, expo out) and the content
 * fades in (120 ms); with reduced motion the caret flips instantly and the fade stays (opacity is
 * not movement).
 */
export function Disclosure({
  summary,
  meta,
  children,
  variant = "row",
  defaultOpen,
  name,
  contentLang,
  className,
}: DisclosureProps) {
  const caret = (
    <Icon
      name="caret-down"
      size={variant === "row" ? 12 : 16}
      className={cx(
        "shrink-0 text-ink-2 transition-[rotate] duration-(--duration-toggle) ease-expo group-open/disclosure:rotate-180",
        "motion-reduce:transition-none",
        variant === "row" && "relative top-px",
      )}
    />
  );

  if (variant === "section") {
    return (
      <details name={name} open={defaultOpen} className={cx("group/disclosure border-t border-rule", className)}>
        <summary
          className={cx(
            "flex cursor-pointer list-none items-center justify-between gap-3 py-3 [&::-webkit-details-marker]:hidden",
            "rounded-xs",
          )}
        >
          <span className="flex items-baseline gap-2">
            <span className="font-cond text-title font-semibold">{summary}</span>
            {meta !== undefined ? <span className="text-meta text-ink-2">{meta}</span> : null}
          </span>
          {caret}
        </summary>
        <div lang={contentLang} className="animate-fade-in pb-4">
          {children}
        </div>
      </details>
    );
  }

  return (
    <details name={name} open={defaultOpen} className={cx("group/disclosure", className)}>
      <summary
        className={cx(
          "inline-flex cursor-pointer list-none items-baseline gap-1.5 rounded-xs text-small font-medium",
          "underline-offset-[0.2em] hover:underline [&::-webkit-details-marker]:hidden",
          // A target of 24 px with a mouse and 44 px under a finger (WCAG 2.5.8; DESIGN.md), the
          // padding cancelled by the margin so the rows keep their rhythm.
          "-my-0.5 py-0.5 pointer-coarse:-my-3 pointer-coarse:py-3",
        )}
      >
        {summary}
        {caret}
      </summary>
      <div
        lang={contentLang}
        className="mt-1.5 animate-fade-in border-l border-rule-strong py-0.5 pl-2.5 text-meta leading-[1.5] text-ink-2"
      >
        {children}
      </div>
    </details>
  );
}
