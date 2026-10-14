import { MARK_GEOMETRY as G, MARK_VIEWBOX } from "@/lib/brand-mark";

import { cx } from "./cx";

/**
 * The mark of Atlas, "A di linee" (DESIGN.md, "Brand"), drawn in the theme's own line tokens, so
 * it follows the nearest data-theme with no JavaScript. Decorative: the name beside it, or the
 * link around it, says "Atlas". Size it with `className` (`size-7` in the header).
 */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox={MARK_VIEWBOX} aria-hidden="true" focusable="false" className={cx("shrink-0", className)}>
      <path d={G.flights.d} strokeWidth={G.flights.width} strokeLinecap="round" className="fill-none stroke-line-flights" />
      <path d={G.lodging.d} strokeWidth={G.lodging.width} strokeLinecap="round" className="fill-none stroke-line-lodging" />
      <path
        d={G.coordinator.d}
        strokeWidth={G.coordinator.width}
        strokeLinecap="round"
        className="fill-none stroke-line-coordinator"
      />
      <circle
        cx={G.station.cx}
        cy={G.station.cy}
        r={G.station.r}
        strokeWidth={G.station.width}
        className="fill-ground stroke-ink"
      />
    </svg>
  );
}
