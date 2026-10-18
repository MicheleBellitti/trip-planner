/**
 * The map's style: a quiet basemap drawn from the Atlas tokens, and on top of it the plan's own
 * marks. The basemap is OpenFreeMap's vector tiles (OpenStreetMap data, OpenMapTiles schema);
 * only the colours, the few labels and the layer list are ours, so land, water and roads are
 * tones of the page's ground and the line colours belong to the days.
 *
 * Everything here is a pure function of a palette (the tokens, resolved) and some data, so a
 * theme change is `setStyle(buildStyle(...))` and a selection is `setPaintProperty` with the
 * values `selectionPaint` computes (the same ones `buildStyle` starts from).
 */

import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";

import { DAY_HUES, hueVariable, mixColors, type DayHue, type FeatureCollectionOf, type LineFeature, type StopFeature } from "./model";

/** OpenFreeMap's planet tiles: a TileJSON, so the tile path (it carries the data's date) is read
 * from them at run time. */
export const TILE_SOURCE_URL = "https://tiles.openfreemap.org/planet";
export const GLYPHS_URL = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
const LABEL_FONT = ["Noto Sans Regular"];
const LABEL_FONT_ITALIC = ["Noto Sans Italic"];
const LABEL_FONT_BOLD = ["Noto Sans Bold"];

export const BASE_SOURCE = "openmaptiles";
export const LINES_SOURCE = "atlas-lines";
export const STOPS_SOURCE = "atlas-stops";

/** The tokens the map uses, resolved to colours. */
export interface MapPalette {
  scheme: "light" | "dark";
  ground: string;
  surface: string;
  ink: string;
  ink2: string;
  rule: string;
  ruleStrong: string;
  hues: Record<DayHue, string>;
}

const FALLBACK_COLOR = "gray";

/** Reads the palette from the CSS variables in force on an element (the tokens of globals.css: dark
 * by default, light where `data-theme` pins it) and its `color-scheme`. */
export function readPalette(element: Element): MapPalette {
  const computed = getComputedStyle(element);
  const read = (name: string) => computed.getPropertyValue(name).trim() || FALLBACK_COLOR;
  const hues = Object.fromEntries(DAY_HUES.map((hue) => [hue, read(hueVariable(hue))])) as Record<DayHue, string>;
  return {
    scheme: computed.colorScheme.includes("dark") ? "dark" : "light",
    ground: read("--ground"),
    surface: read("--surface"),
    ink: read("--ink"),
    ink2: read("--ink-2"),
    rule: read("--rule"),
    ruleStrong: read("--rule-strong"),
    hues,
  };
}

/** How far light water leans toward the signal blue (`line-flights`): 12 % is a cool step you can
 * tell from land at a glance, still quiet, and the day lines keep 3:1 over it (style.test.ts). */
export const WATER_COOL = 0.12;

/** The basemap's tones, all mixed from the palette: land is the ground, the big roads are one step
 * away from it, and nothing is saturated. Water is the one cool tone: in dark it is simply the
 * darkest step (it already reads against the land), in light a step toward blue, because a grey
 * barely darker than land puts the stations of a riverside quarter in the river. */
export function baseTones(palette: MapPalette) {
  const { ground, surface, rule, ruleStrong } = palette;
  const dark = palette.scheme === "dark";
  return {
    land: ground,
    park: mixColors(ground, rule, dark ? 0.35 : 0.4),
    water: dark ? mixColors(ground, rule, 0.9) : mixColors(mixColors(ground, rule, 0.85), palette.hues.flights, WATER_COOL),
    building: mixColors(ground, rule, dark ? 0.55 : 0.55),
    roadMinor: mixColors(ground, rule, dark ? 0.5 : 0.55),
    roadMajor: mixColors(ground, rule, dark ? 0.95 : 1),
    roadMotorway: mixColors(rule, ruleStrong, 0.35),
    boundary: mixColors(ground, ruleStrong, 0.7),
    label: mixColors(palette.ink2, ground, dark ? 0.1 : 0.05),
    halo: mixColors(ground, surface, 0.4),
  };
}

type PaintMap = Record<string, unknown>;
type LayerBuilder = LayerSpecification;

const NAME: ExpressionSpecification = [
  "coalesce",
  ["get", "name:it"],
  ["get", "name_en"],
  ["get", "name"],
] as unknown as ExpressionSpecification;

function baseLayers(palette: MapPalette): LayerBuilder[] {
  const tones = baseTones(palette);
  const road = (id: string, classes: string[], color: string, width: ExpressionSpecification, minzoom: number): LayerBuilder =>
    ({
      id,
      type: "line",
      source: BASE_SOURCE,
      "source-layer": "transportation",
      minzoom,
      filter: ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["match", ["get", "class"], classes, true, false]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": color, "line-width": width },
    }) as LayerBuilder;
  const place = (id: string, classes: string[], minzoom: number, size: number | ExpressionSpecification): LayerBuilder =>
    ({
      id,
      type: "symbol",
      source: BASE_SOURCE,
      "source-layer": "place",
      minzoom,
      filter: ["match", ["get", "class"], classes, true, false],
      layout: {
        "text-field": NAME,
        "text-font": LABEL_FONT,
        "text-size": size,
        "text-max-width": 7,
        "text-padding": 6,
      },
      paint: { "text-color": tones.label, "text-halo-color": tones.halo, "text-halo-width": 1.4 },
    }) as LayerBuilder;

  return [
    { id: "background", type: "background", paint: { "background-color": tones.land } },
    {
      id: "park",
      type: "fill",
      source: BASE_SOURCE,
      "source-layer": "park",
      paint: { "fill-color": tones.park, "fill-opacity": 0.7 },
    },
    {
      id: "landcover",
      type: "fill",
      source: BASE_SOURCE,
      "source-layer": "landcover",
      filter: ["match", ["get", "class"], ["wood", "grass"], true, false],
      paint: { "fill-color": tones.park, "fill-opacity": 0.55 },
    },
    {
      id: "water",
      type: "fill",
      source: BASE_SOURCE,
      "source-layer": "water",
      filter: ["!=", ["get", "brunnel"], "tunnel"],
      paint: { "fill-color": tones.water },
    },
    {
      id: "waterway",
      type: "line",
      source: BASE_SOURCE,
      "source-layer": "waterway",
      minzoom: 9,
      paint: { "line-color": tones.water, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.6, 14, 2] },
    },
    {
      id: "building",
      type: "fill",
      source: BASE_SOURCE,
      "source-layer": "building",
      minzoom: 14,
      paint: { "fill-color": tones.building, "fill-opacity": 0.6 },
    },
    road("road-minor", ["minor", "service", "track"], tones.roadMinor, ["interpolate", ["exponential", 1.55], ["zoom"], 12, 0.6, 14, 1.4, 20, 18], 12),
    road("road-major", ["primary", "secondary", "tertiary", "trunk"], tones.roadMajor, ["interpolate", ["exponential", 1.4], ["zoom"], 8, 0.5, 12, 1.6, 20, 22], 8),
    road("road-motorway", ["motorway"], tones.roadMotorway, ["interpolate", ["exponential", 1.4], ["zoom"], 6, 0.6, 12, 2.2, 20, 24], 6),
    {
      id: "boundary-country",
      type: "line",
      source: BASE_SOURCE,
      "source-layer": "boundary",
      filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
      paint: { "line-color": tones.boundary, "line-width": 1, "line-dasharray": [3, 2] },
    },
    {
      id: "label-water",
      type: "symbol",
      source: BASE_SOURCE,
      "source-layer": "water_name",
      minzoom: 8,
      layout: { "text-field": NAME, "text-font": LABEL_FONT_ITALIC, "text-size": 11, "text-max-width": 6 },
      paint: { "text-color": tones.label, "text-halo-color": tones.halo, "text-halo-width": 1.2, "text-opacity": 0.8 },
    },
    place("label-city", ["city"], 3, ["interpolate", ["linear"], ["zoom"], 4, 12, 11, 16]),
    place("label-town", ["town"], 8, ["interpolate", ["linear"], ["zoom"], 8, 11.5, 13, 14]),
    place("label-district", ["village", "suburb", "quarter"], 11, ["interpolate", ["linear"], ["zoom"], 11, 11, 15, 13]),
    place("label-neighbourhood", ["neighbourhood", "hamlet", "isolated_dwelling"], 14, 11.5),
  ];
}

// --- the plan's own marks ---------------------------------------------------------------------

export const LAYER_IDS = {
  lineCasing: "atlas-line-casing",
  lineSolid: "atlas-line",
  lineDashed: "atlas-line-dashed",
  stopHalo: "atlas-stop-halo",
  stop: "atlas-stop",
  stopNumber: "atlas-stop-number",
  lodging: "atlas-lodging",
  lodgingCore: "atlas-lodging-core",
  lodgingLabel: "atlas-lodging-label",
  picked: "atlas-picked",
} as const;

/** The layers a click can land on. */
export const CLICKABLE_LAYERS: string[] = [LAYER_IDS.stop, LAYER_IDS.lodging, LAYER_IDS.lodgingCore];

const dayColor = (palette: MapPalette): ExpressionSpecification =>
  [
    "match",
    ["get", "slot"],
    ...DAY_HUES.flatMap((hue, slot) => [slot, palette.hues[hue]]),
    palette.ink2,
  ] as unknown as ExpressionSpecification;

const isSelected = (selected: number): ExpressionSpecification =>
  ["==", ["get", "day"], selected] as unknown as ExpressionSpecification;

/** How much of a layer shows: all of it with no day selected, else the selected day's marks at
 * full strength and the others faded back. */
function opacityFor(selected: number | null, faded: number): number | ExpressionSpecification {
  return selected === null
    ? 1
    : (["case", isSelected(selected), 1, faded] as unknown as ExpressionSpecification);
}

/** A line's width: the selected day's is wider. */
function widthFor(selected: number | null, normal: number, wide: number): number | ExpressionSpecification {
  return selected === null
    ? normal
    : (["case", isSelected(selected), wide, Math.max(2, normal - 1)] as unknown as ExpressionSpecification);
}

/** The paint properties that depend on the selected day (and the picked station), per layer. */
export function selectionPaint(selected: number | null, picked: string | null): Record<string, PaintMap> {
  const lineFade = 0.22;
  const stopFade = 0.3;
  return {
    [LAYER_IDS.lineCasing]: {
      "line-opacity": opacityFor(selected, 0.15),
      "line-width": widthFor(selected, 7, 9),
    },
    [LAYER_IDS.lineSolid]: {
      "line-opacity": opacityFor(selected, lineFade),
      "line-width": widthFor(selected, 4, 6),
    },
    [LAYER_IDS.lineDashed]: {
      "line-opacity": opacityFor(selected, lineFade),
      "line-width": widthFor(selected, 4, 6),
    },
    [LAYER_IDS.stopHalo]: { "circle-opacity": opacityFor(selected, stopFade) },
    [LAYER_IDS.stop]: {
      "circle-opacity": opacityFor(selected, stopFade),
      "circle-stroke-opacity": opacityFor(selected, stopFade),
    },
    [LAYER_IDS.lodging]: {
      "circle-opacity": opacityFor(selected, 0.5),
      "circle-stroke-opacity": opacityFor(selected, 0.5),
    },
    [LAYER_IDS.stopNumber]: { "text-opacity": opacityFor(selected, stopFade) },
    [LAYER_IDS.lodgingCore]: { "circle-opacity": opacityFor(selected, 0.5) },
    [LAYER_IDS.lodgingLabel]: { "text-opacity": opacityFor(selected, 0.6) },
    [LAYER_IDS.picked]: { "circle-stroke-opacity": picked === null ? 0 : 1 },
  };
}

/** The layer filter that keeps only the picked station's ring. */
export function pickedFilter(picked: string | null): ExpressionSpecification {
  return ["==", ["get", "key"], picked ?? ""] as unknown as ExpressionSpecification;
}

/** Stations grow with the zoom so a number fits inside the ring from zoom 12. */
const NUMBER_MIN_ZOOM = 12;
const STOP_STROKE = 2.5;
const STOP_RADIUS: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["zoom"],
  11,
  5.5,
  12,
  7.5,
] as unknown as ExpressionSpecification;
function planLayers(palette: MapPalette, selected: number | null, picked: string | null): LayerBuilder[] {
  const paint = selectionPaint(selected, picked);
  const color = dayColor(palette);
  const solid: ExpressionSpecification = ["==", ["get", "cycle"], 0] as unknown as ExpressionSpecification;
  const dashed: ExpressionSpecification = [">", ["get", "cycle"], 0] as unknown as ExpressionSpecification;
  const round = { "line-cap": "round", "line-join": "round" } as const;
  const notLodging: ExpressionSpecification = ["!", ["get", "lodging"]] as unknown as ExpressionSpecification;
  const isLodging: ExpressionSpecification = ["get", "lodging"] as unknown as ExpressionSpecification;
  return [
    {
      id: LAYER_IDS.lineCasing,
      type: "line",
      source: LINES_SOURCE,
      layout: round,
      paint: { "line-color": palette.surface, ...paint[LAYER_IDS.lineCasing] },
    },
    {
      id: LAYER_IDS.lineSolid,
      type: "line",
      source: LINES_SOURCE,
      filter: solid,
      layout: round,
      paint: { "line-color": color, ...paint[LAYER_IDS.lineSolid] },
    },
    {
      id: LAYER_IDS.lineDashed,
      type: "line",
      source: LINES_SOURCE,
      filter: dashed,
      layout: { "line-join": "round" },
      paint: { "line-color": color, "line-dasharray": [2, 1.4], ...paint[LAYER_IDS.lineDashed] },
    },
    {
      id: LAYER_IDS.stopHalo,
      type: "circle",
      source: STOPS_SOURCE,
      paint: {
        "circle-color": palette.surface,
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["zoom"],
          11,
          ["case", isLodging, 14, 8.5],
          12,
          ["case", isLodging, 14, 10.5],
        ],
        ...paint[LAYER_IDS.stopHalo],
      },
    },
    {
      id: LAYER_IDS.stop,
      type: "circle",
      source: STOPS_SOURCE,
      filter: notLodging,
      paint: {
        "circle-color": palette.surface,
        "circle-radius": STOP_RADIUS,
        "circle-stroke-color": color,
        "circle-stroke-width": STOP_STROKE,
        ...paint[LAYER_IDS.stop],
      },
    },
    {
      // The stop's place in its day's list, inside the ring: the same number the list shows.
      id: LAYER_IDS.stopNumber,
      type: "symbol",
      source: STOPS_SOURCE,
      filter: notLodging,
      minzoom: NUMBER_MIN_ZOOM,
      layout: {
        "text-field": ["get", "number"],
        "text-font": LABEL_FONT_BOLD,
        "text-size": 10.5,
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: { "text-color": palette.ink, ...paint[LAYER_IDS.stopNumber] },
    },
    {
      id: LAYER_IDS.lodging,
      type: "circle",
      source: STOPS_SOURCE,
      filter: isLodging,
      paint: {
        "circle-color": palette.surface,
        "circle-radius": 9,
        "circle-stroke-color": palette.ink,
        "circle-stroke-width": 3.5,
        ...paint[LAYER_IDS.lodging],
      },
    },
    {
      id: LAYER_IDS.lodgingCore,
      type: "circle",
      source: STOPS_SOURCE,
      filter: isLodging,
      paint: { "circle-color": palette.ink, "circle-radius": 3.5, ...paint[LAYER_IDS.lodgingCore] },
    },
    {
      // "Hotel" under the large ring, so the base is told by a word as well as by its size.
      id: LAYER_IDS.lodgingLabel,
      type: "symbol",
      source: STOPS_SOURCE,
      filter: isLodging,
      layout: {
        "text-field": "Hotel",
        "text-font": LABEL_FONT_BOLD,
        "text-size": 11.5,
        "text-anchor": "top",
        "text-offset": [0, 1.7],
        "text-padding": 2,
      },
      paint: {
        "text-color": palette.ink,
        "text-halo-color": palette.surface,
        "text-halo-width": 1.6,
        ...paint[LAYER_IDS.lodgingLabel],
      },
    },
    {
      id: LAYER_IDS.picked,
      type: "circle",
      source: STOPS_SOURCE,
      filter: pickedFilter(picked),
      paint: {
        "circle-color": palette.surface,
        "circle-opacity": 0,
        "circle-radius": 16,
        "circle-stroke-color": palette.ink,
        "circle-stroke-width": 2,
        ...paint[LAYER_IDS.picked],
      },
    },
  ] as LayerBuilder[];
}

export interface MapData {
  lines: FeatureCollectionOf<LineFeature>;
  stops: FeatureCollectionOf<StopFeature>;
}

export interface MapView {
  /** Itinerary index of the highlighted day, or null for all of them. */
  selected: number | null;
  /** Key of the station whose card is open. */
  picked: string | null;
}

/** The whole style: basemap, then the lines, then the stations. */
export function buildStyle(palette: MapPalette, data: MapData, view: MapView): StyleSpecification {
  return {
    version: 8,
    glyphs: GLYPHS_URL,
    sources: {
      [BASE_SOURCE]: { type: "vector", url: TILE_SOURCE_URL },
      [LINES_SOURCE]: { type: "geojson", data: data.lines },
      [STOPS_SOURCE]: { type: "geojson", data: data.stops },
    },
    layers: [...baseLayers(palette), ...planLayers(palette, view.selected, view.picked)],
  } as StyleSpecification;
}
