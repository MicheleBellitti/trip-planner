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
  flights: "#6e8fe0",
  lodging: "#4fa77b",
  activities: "#9c84d6",
  transport: "#4aa8b6",
} as const;
