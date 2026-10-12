import Link from "next/link";

import { BRAND_NAME } from "@/lib/brand";

import { cx } from "./cx";

/**
 * The product's name set in the display face (Barlow Semi Condensed 600): Atlas has no logo and
 * none is invented (web/PRODUCT.md, "Evidence on Hand"). With `href` it is the header's link
 * home ("/", the list of plans).
 */
export function Wordmark({ href, className }: { href?: string; className?: string }) {
  const classes = cx("font-cond text-title font-semibold tracking-[0.01em] text-ink no-underline", className);
  if (href) {
    return (
      // Padded to a 44 px target; the negative margin keeps the lettering where it was.
      <Link href={href} className={cx(classes, "-mx-2 -my-3 inline-block rounded-xs px-2 py-3")}>
        {BRAND_NAME}
      </Link>
    );
  }
  return <span className={classes}>{BRAND_NAME}</span>;
}
