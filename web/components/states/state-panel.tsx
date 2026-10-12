import type { ReactNode } from "react";

import { cx } from "@/components/ui/cx";
import { Icon, type IconName } from "@/components/ui/icon";

interface StatePanelProps {
  /** The state's glyph (DESIGN.md, Iconography): pause-circle, stop-circle, x-circle, prohibit... */
  icon: IconName;
  /** `error` writes the title in error red (failed, blocked); everything else stays ink. */
  tone?: "neutral" | "error";
  title: ReactNode;
  /** Usually three StateFact: what happened, what was saved, what can be done. */
  children?: ReactNode;
  actions?: ReactNode;
  /** Below the facts: a Notice that answers the user's own action. */
  footer?: ReactNode;
  headingId: string;
  className?: string;
}

/**
 * A plan state that needs words (spec, "Tutti gli stati sono disegnati"): a title with its
 * glyph (never colour alone), then what happened, what was saved and what can be done, then the
 * actions. A flat surface card like a lane card; on desktop the three facts sit side by side.
 */
export function StatePanel({ icon, tone = "neutral", title, children, actions, footer, headingId, className }: StatePanelProps) {
  return (
    <section
      aria-labelledby={headingId}
      data-tone={tone}
      className={cx("rounded-md border border-rule bg-surface px-4 py-3.5 lg:px-5 lg:py-4", className)}
    >
      <h2
        id={headingId}
        className={cx(
          "flex items-center gap-2 font-cond text-heading font-semibold",
          tone === "error" ? "text-error" : "text-ink",
        )}
      >
        <Icon name={icon} size={20} />
        {title}
      </h2>
      {children ? <dl className="mt-3 grid gap-3 lg:grid-cols-3 lg:gap-6">{children}</dl> : null}
      {footer ? <div className="mt-3">{footer}</div> : null}
      {actions ? <div className="mt-4 flex flex-wrap items-center gap-2">{actions}</div> : null}
    </section>
  );
}

/** One labelled fact of a state: "Cosa è successo", "Cosa è stato salvato", "Cosa puoi fare". */
export function StateFact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-meta font-semibold text-ink-2">{label}</dt>
      <dd className="m-0 mt-0.5 max-w-prose text-small text-ink">{children}</dd>
    </div>
  );
}
