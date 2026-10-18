/**
 * The mark's geometry alone (DESIGN.md, "Brand"): what <Mark> draws in the browser. Apart from
 * lib/brand-mark.ts (the fixed colours, the standalone SVG, the converging lines of the images) so
 * the pages that draw the mark do not ship the rest; the bundler keeps every export of a module it
 * loads.
 */

/** A 40-unit square. */
export const MARK_VIEWBOX = "0 0 40 40";

export const MARK_GEOMETRY = {
  flights: { d: "M8.5 35 L20 7", width: 5 },
  lodging: { d: "M31.5 35 L20 7", width: 5 },
  coordinator: { d: "M13.5 25 H26.5", width: 4.5 },
  station: { cx: 20, cy: 7.5, r: 4.6, width: 2.8 },
} as const;

/** The mark at 28 px and below (the header lockup, the tab icon, the favicon): a smaller, lighter
 * station and thicker strokes, so the "A" reads before the ring and the mark is not taken for a
 * drafting compass. Same keys and viewBox as MARK_GEOMETRY. */
export const MARK_GEOMETRY_SMALL = {
  flights: { d: "M8.5 35 L20 7", width: 5.4 },
  lodging: { d: "M31.5 35 L20 7", width: 5.4 },
  coordinator: { d: "M12.6 25 H27.4", width: 5.6 },
  station: { cx: 20, cy: 7.5, r: 3.5, width: 2 },
} as const;

export type MarkGeometry = typeof MARK_GEOMETRY | typeof MARK_GEOMETRY_SMALL;
