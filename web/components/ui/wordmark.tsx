import Link from "next/link";

import { BRAND_NAME } from "@/lib/brand";

import { cx } from "./cx";
import { Mark } from "./mark";

/**
 * The lockup: the mark ("A di linee") and the name in the display face (Barlow Semi Condensed 600).
 * With `href` it is the header's link home. `compact`: below 400 px a crowded header keeps the mark
 * only, and the name stays the link's accessible name (DESIGN.md, Navigation).
 */
export function Wordmark({ href, className, compact = false }: { href?: string; className?: string; compact?: boolean }) {
  const classes = cx(
    "inline-flex items-center gap-2 font-cond text-title font-semibold tracking-[0.01em] text-ink no-underline",
    className,
  );
  const content = (
    <>
      <Mark className="size-7" small />
      <span className={cx(compact && "max-[25rem]:sr-only")}>{BRAND_NAME}</span>
    </>
  );
  if (href) {
    return (
      // Padded to a 44 px target (28 px mark + 2 × 8 px); the negative margin keeps the lockup in place.
      <Link href={href} className={cx(classes, "-mx-2 -my-2 rounded-xs px-2 py-2")}>
        {content}
      </Link>
    );
  }
  return <span className={classes}>{content}</span>;
}
