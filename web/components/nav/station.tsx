import Link from "next/link";

import { cx } from "@/components/ui/cx";

/** Where a station sits on the drawn line: the outer ones carry the line's 24 px overhang, and a
 * lone station carries it on both sides. */
export type StationEdge = "first" | "middle" | "last" | "only";

/** The edge of the station at `index` among the `count` stations actually drawn. */
export function stationEdge(index: number, count: number): StationEdge {
  if (count <= 1) return "only";
  if (index === 0) return "first";
  return index === count - 1 ? "last" : "middle";
}

/**
 * One section on the header's line: its label above its station. The line runs through every
 * station and the same 24 px past the outer ones, a route that goes on beyond the edge of the map,
 * so the pair never reads as a two-step progress bar; 1 px on the phone, 2 px from 1080 px, where
 * the header has room for it. The current station is the larger "you are here" ring. The link is
 * stacked above every line (z-1), including the next station's, so no line notches its focus ring.
 */
export function Station({
  href,
  label,
  current,
  edge,
}: {
  href: string;
  label: string;
  current: boolean;
  edge: StationEdge;
}) {
  // The station's centre is 13.5 px above the item's bottom (8 px padding + half of its 11 px box).
  const half = "pointer-events-none absolute bottom-[13px] h-px bg-rule-strong lg:bottom-[12.5px] lg:h-0.5";
  const opens = edge === "first" || edge === "only";
  const closes = edge === "last" || edge === "only";
  return (
    <li className="relative flex">
      <span aria-hidden="true" data-line="" className={cx(half, opens ? "right-1/2 w-6" : "right-1/2 left-0")} />
      <span aria-hidden="true" data-line="" className={cx(half, closes ? "left-1/2 w-6" : "right-0 left-1/2")} />
      <Link
        href={href}
        aria-current={current ? "page" : undefined}
        className={cx(
          "group relative z-[1] grid min-h-11 justify-items-center gap-1 rounded-xs px-2.5 pt-1 pb-2 text-small no-underline sm:px-3",
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
