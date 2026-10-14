/**
 * The mark of Atlas, "A di linee" (DESIGN.md, "Brand"): the flights and lodging lines rise to meet
 * at a station and form an "A"; the coordinator's line is the crossbar. One geometry, drawn by
 * <Mark> in the theme's tokens and by the icon and link-preview images in the fixed colours below.
 */

/** A 40-unit square. */
export const MARK_VIEWBOX = "0 0 40 40";

export const MARK_GEOMETRY = {
  flights: { d: "M8.5 35 L20 7", width: 5 },
  lodging: { d: "M31.5 35 L20 7", width: 5 },
  coordinator: { d: "M13.5 25 H26.5", width: 4.5 },
  station: { cx: 20, cy: 7.5, r: 4.6, width: 2.8 },
} as const;

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

/** The mark as a standalone SVG document, for images (the apple icon, the link preview). */
export function markSvg(colors: MarkColors = NIGHT): string {
  const g = MARK_GEOMETRY;
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
export function markDataUri(colors: MarkColors = NIGHT): string {
  return `data:image/svg+xml;base64,${btoa(markSvg(colors))}`;
}
