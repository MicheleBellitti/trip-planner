import Link from "next/link";

import { cx } from "@/components/ui/cx";

/**
 * One section on the header's line: its label above its station. The line runs through every
 * station and past the outer ones, a route that goes on beyond the edge of the map, so the pair
 * never reads as a two-step progress bar. The current station is the larger "you are here" ring.
 * The link is positioned, so it paints above the line drawn before it.
 */
export function Station({ href, label, current }: { href: string; label: string; current: boolean }) {
  // The station's centre is 13.5 px above the item's bottom (8 px padding + half of its 11 px box).
  const half = "pointer-events-none absolute bottom-[13px] h-px bg-rule-strong";
  return (
    <li className="relative flex">
      <span aria-hidden="true" data-line="" className={cx(half, "right-1/2 left-0")} />
      <span aria-hidden="true" data-line="" className={cx(half, "right-0 left-1/2")} />
      <Link
        href={href}
        aria-current={current ? "page" : undefined}
        className={cx(
          "group relative grid min-h-11 justify-items-center gap-1 rounded-xs px-2.5 pt-1 pb-2 text-small no-underline sm:px-3",
          current ? "font-semibold text-ink" : "text-ink-2 hover:text-ink",
        )}
      >
        <span>{label}</span>
        <span aria-hidden="true" className="grid size-[11px] place-items-center">
          <span
            data-testid="station"
            data-current={current}
            className={cx(
              "rounded-full bg-ground transition-colors duration-(--duration-hover) ease-out",
              current ? "size-[11px] border-[3px] border-ink" : "size-[9px] border-[1.5px] border-ink-2 group-hover:bg-ink-2",
            )}
          />
        </span>
      </Link>
    </li>
  );
}
