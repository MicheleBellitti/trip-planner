import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";

import { pageCount, pageHref, pageItems } from "./eval-model";

/**
 * The list's pages, as stations on a line: "Più recenti" and "Più vecchie" at the ends, and from
 * 640 px the page numbers between them, the current one a filled ink disc (the line's "you are
 * here"). Plain links (`?pagina=N`), so the back button, a reload and a shared address all land on
 * the same page; a click keeps the scroll (the dashboard above keeps its height, so the list stays
 * where it was). It needs `total`: a backend that does not send it also ignores the offset, so
 * the list draws no pager for it (EvalRunList).
 */
export function RunPager({
  page,
  total,
  pageSize,
  className,
}: {
  page: number;
  /** Every stored run. */
  total: number;
  pageSize: number;
  className?: string;
}) {
  const count = pageCount(total, pageSize);
  const hasNewer = page > 1;
  const hasOlder = page < count;
  if (!hasNewer && !hasOlder) return null;
  return (
    <nav aria-label="Pagine delle valutazioni" className={cx("flex items-center justify-between gap-3", className)}>
      <End href={hasNewer ? pageHref(page - 1) : null} direction="newer" />
      <p className="text-meta text-ink-2 sm:hidden">
        Pagina {page} di {count}
      </p>
      <ol className="hidden items-center gap-1 sm:flex">
        {pageItems(page, count).map((item, index) =>
          item === "gap" ? (
            <li key={`gap-${index}`} aria-hidden="true" className="w-6 text-center text-meta text-ink-2">
              …
            </li>
          ) : (
            <li key={item}>
              <Link
                href={pageHref(item)}
                scroll={false}
                aria-current={item === page ? "page" : undefined}
                aria-label={`Pagina ${item}`}
                className={cx(
                  "grid size-8 place-items-center rounded-full text-meta font-semibold no-underline",
                  "transition-[background-color,color] duration-(--duration-hover) ease-out pointer-coarse:size-11",
                  item === page ? "bg-action text-on-action" : "text-ink hover:bg-notice-wash",
                )}
              >
                {item}
              </Link>
            </li>
          ),
        )}
      </ol>
      <End href={hasOlder ? pageHref(page + 1) : null} direction="older" />
    </nav>
  );
}

/** One end of the pager. Without a page beyond it, it keeps its place, dimmed, so the numbers
 * never shift sideways between the first and the last page. */
function End({ href, direction }: { href: string | null; direction: "newer" | "older" }) {
  return (
    <StepLink href={href} direction={direction} keepScroll>
      {direction === "newer" ? "Più recenti" : "Più vecchie"}
    </StepLink>
  );
}

/** A step along the list, toward the newer runs (left, as the list reads) or the older ones
 * (right): the pager's ends and a run page's neighbours. Without a target it keeps its place,
 * dimmed and hidden from screen readers. `keepScroll`: the pager keeps the reader where they are;
 * another run's page starts from its top. */
export function StepLink({
  href,
  direction,
  keepScroll = false,
  children,
}: {
  href: string | null;
  direction: "newer" | "older";
  keepScroll?: boolean;
  children: ReactNode;
}) {
  const newer = direction === "newer";
  const content = (
    <>
      {newer ? <Icon name="arrow-left" size={14} /> : null}
      {children}
      {newer ? null : <Icon name="arrow-right" size={14} />}
    </>
  );
  const classes = cx(
    "inline-flex min-h-8 items-center gap-1.5 rounded-full px-3 text-meta font-semibold whitespace-nowrap no-underline",
    "pointer-coarse:min-h-11",
    newer ? "-ml-3" : "-mr-3",
  );
  if (href === null) {
    return (
      <span aria-hidden="true" className={cx(classes, "text-ink-2 opacity-55")}>
        {content}
      </span>
    );
  }
  return (
    <Link
      href={href}
      scroll={!keepScroll}
      rel={newer ? "prev" : "next"}
      className={cx(classes, "text-ink transition-[background-color] duration-(--duration-hover) ease-out hover:bg-notice-wash")}
    >
      {content}
    </Link>
  );
}
