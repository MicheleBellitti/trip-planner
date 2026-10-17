/**
 * The mark of Atlas, "A di linee" (DESIGN.md, "Brand"): the flights and lodging lines rise to meet
 * at a station and form an "A"; the coordinator's line is the crossbar. One geometry
 * (lib/mark-geometry.ts), drawn by <Mark> in the theme's tokens and by the icon and link-preview
 * images in the fixed colours below.
 */
import { MARK_GEOMETRY, type MarkGeometry, MARK_VIEWBOX } from "./mark-geometry";

export { MARK_GEOMETRY, MARK_GEOMETRY_SMALL, type MarkGeometry, MARK_VIEWBOX } from "./mark-geometry";

/** "Carta notturna", the dark default, as fixed values: for images that cannot read CSS variables
 * (the icons, the link preview). components/ui/mark.test.tsx keeps them equal to globals.css. */
export const NIGHT = {
  ground: "#1b2230",
  ink: "#efe8d8",
  coordinator: "#a3abb6",
  flights: "#7696e3",
  lodging: "#4fa77b",
  activities: "#a089d9",
  transport: "#4aa8b6",
} as const;

export type MarkColors = Record<"ground" | "ink" | "coordinator" | "flights" | "lodging", string>;

/** The five agent lines entering a destination, 1056 × 150 units with the destination at (990, 75):
 * the landing's closing (`ConvergingLines`) and the link preview draw these paths. Like a transit
 * diagram's hub, each line comes in from its own direction (above, upper left, left, lower left,
 * below), so none is drawn over another. */
export const CONVERGING_VIEWBOX = "0 0 1056 150";
/** The phone's crop: the last 400 units, so the lines keep their weight at 360 px. */
export const CONVERGING_VIEWBOX_NARROW = "656 0 400 150";
export const CONVERGING_DESTINATION = { cx: 990, cy: 75 } as const;
export const CONVERGING_PATHS = {
  coordinator: "M0 75 H990",
  flights: "M0 15 H990 V75",
  lodging: "M0 45 H960 L990 75",
  activities: "M0 105 H960 L990 75",
  transport: "M120 135 H990 V75",
} as const;

/** The mark as a standalone SVG document, for images (the apple icon, the link preview; the small
 * geometry for the favicon). */
export function markSvg(colors: MarkColors = NIGHT, g: MarkGeometry = MARK_GEOMETRY): string {
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${MARK_VIEWBOX}">`,
    `<path d="${g.flights.d}" fill="none" stroke="${colors.flights}" stroke-width="${g.flights.width}" stroke-linecap="round"/>`,
    `<path d="${g.lodging.d}" fill="none" stroke="${colors.lodging}" stroke-width="${g.lodging.width}" stroke-linecap="round"/>`,
    `<path d="${g.coordinator.d}" fill="none" stroke="${colors.coordinator}" stroke-width="${g.coordinator.width}" stroke-linecap="round"/>`,
    `<circle cx="${g.station.cx}" cy="${g.station.cy}" r="${g.station.r}" fill="${colors.ground}" stroke="${colors.ink}" stroke-width="${g.station.width}"/>`,
    "</svg>",
  ].join("");
}

/** markSvg() as a base64 data URI, for <img src> inside next/og images. */
export function markDataUri(colors: MarkColors = NIGHT, geometry: MarkGeometry = MARK_GEOMETRY): string {
  return `data:image/svg+xml;base64,${btoa(markSvg(colors, geometry))}`;
}
