import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cx } from "./cx";
import { Icon, type IconName } from "./icon";

export type NoticeTone = "info" | "warning" | "error";

const TONES: Record<NoticeTone, { box: string; icon: IconName; iconClass: string }> = {
  // A plain note on the notice wash: lane notes that need a frame, "Prezzi stimati".
  info: { box: "border border-transparent bg-notice-wash", icon: "info", iconClass: "text-ink-2" },
  // The MCP-source warning: dashed rule-strong edge, warning glyph in ink. Not amber, not red:
  // a source that did not answer is a note on its lane, not a plan error.
  warning: { box: "border border-dashed border-rule-strong bg-notice-wash", icon: "warning", iconClass: "text-ink" },
  // Something failed: error wash, a soft error edge, the cross in error red.
  error: {
    box: "border border-[color-mix(in_srgb,var(--error)_55%,transparent)] bg-error-wash",
    icon: "x-circle",
    iconClass: "text-error",
  },
};

interface NoticeProps extends Omit<ComponentPropsWithoutRef<"div">, "title"> {
  tone?: NoticeTone;
  /** Optional first line in semibold. Errors say what happened here, then what was saved and
   * what to do in the body. */
  title?: ReactNode;
  children?: ReactNode;
  /** A follow-up action, usually a quiet small Button ("Riprova") or a link. */
  action?: ReactNode;
}

/**
 * A framed note (info, warning, error): icon, text, optional action. It announces nothing by
 * itself: pass role="alert" only for an error that answers the user's own action (a failed
 * "Interrompi"), never for stream events (aria-live is reserved for lane state changes).
 */
export function Notice({ tone = "info", title, children, action, className, ...props }: NoticeProps) {
  const style = TONES[tone];
  return (
    <div
      data-tone={tone}
      className={cx("flex items-start gap-2 rounded-sm px-2.5 py-2 text-meta text-ink", style.box, className)}
      {...props}
    >
      <Icon name={style.icon} size={17} className={cx("mt-px", style.iconClass)} />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={title ? "mt-0.5" : undefined}>{children}</div> : null}
        {action ? <div className="mt-2 flex flex-wrap gap-2">{action}</div> : null}
      </div>
    </div>
  );
}

/**
 * The discreet one-line status under the header: "Stream in riconnessione. Gli eventi persi
 * arrivano da soli.", "Non aggiornato: ultimo stato alle 10:41". No frame, ink-2, a glyph that
 * turns only while `turning` (reconnecting) and never with reduced motion. Not a live region.
 */
export function InlineStatus({
  icon = "arrows-clockwise",
  turning = false,
  children,
  className,
}: {
  icon?: IconName;
  turning?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <p className={cx("flex items-center gap-2 text-meta text-ink-2", className)}>
      <Icon name={icon} size={15} className={turning ? "motion-safe:animate-turn" : undefined} />
      <span>{children}</span>
    </p>
  );
}
