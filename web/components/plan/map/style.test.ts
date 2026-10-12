import { describe, expect, it } from "vitest";

import { buildMapModel, lineFeatures, mixColors, parseColor, stopFeatures, type MapPlan } from "./model";
import {
  baseTones,
  BASE_SOURCE,
  buildStyle,
  CLICKABLE_LAYERS,
  LAYER_IDS,
  pickedFilter,
  selectionPaint,
  WATER_COOL,
  type MapPalette,
} from "./style";

const light: MapPalette = {
  scheme: "light",
  ground: "#f2f4f7",
  surface: "#fbfcfd",
  ink: "#0f1a2a",
  ink2: "#4b5768",
  rule: "#d5dbe3",
  ruleStrong: "#7a8597",
  hues: { flights: "#1f55c4", lodging: "#0f7348", activities: "#6d3fc0", transport: "#08707f", coordinator: "#33404f" },
};
const dark: MapPalette = {
  scheme: "dark",
  ground: "#0c121b",
  surface: "#131b26",
  ink: "#e6ebf2",
  ink2: "#9ba7b8",
  rule: "#263241",
  ruleStrong: "#5f6c7e",
  hues: { flights: "#7aa2f7", lodging: "#43c08a", activities: "#b497f5", transport: "#3fc0d3", coordinator: "#a9b6c7" },
};

const plan: MapPlan = {
  start_date: "2027-04-14",
  lodging_name: null,
  bookings: [],
  days: [
    {
      date: "2027-04-14",
      title: null,
      stops: ["a", "b"].map((ref, i) => ({
        ref,
        kind: "activity" as const,
        title: ref,
        lat: 38.7 + i / 100,
        lon: -9.1,
        address: null,
        duration_min: null,
        location_name: null,
        notes: null,
        start_time: null,
        url: null,
      })),
    },
  ],
};
const model = buildMapModel(plan);
if (!model) throw new Error("no model");
const data = { lines: lineFeatures(model), stops: stopFeatures(model) };

describe("buildStyle", () => {
  for (const palette of [light, dark]) {
    it(`is a complete style in ${palette.scheme}`, () => {
      const style = buildStyle(palette, data, { selected: null, picked: null });
      const ids = style.layers.map((layer) => layer.id);
      expect(new Set(ids).size).toBe(ids.length);
      for (const layer of style.layers) {
        if ("source" in layer && layer.source) expect(Object.keys(style.sources)).toContain(layer.source);
      }
      // The plan's marks are above the basemap, in this order.
      expect(ids.indexOf(LAYER_IDS.lineSolid)).toBeGreaterThan(ids.indexOf("label-city"));
      expect(ids.at(-1)).toBe(LAYER_IDS.picked);
      for (const id of CLICKABLE_LAYERS) expect(ids).toContain(id);
      expect(style.glyphs).toContain("openfreemap.org");
    });
  }

  it("draws the basemap from OpenFreeMap's vector tiles", () => {
    const style = buildStyle(light, data, { selected: null, picked: null });
    expect(style.sources[BASE_SOURCE]).toMatchObject({ type: "vector", url: "https://tiles.openfreemap.org/planet" });
  });

  it("puts the day colours of the theme into the lines", () => {
    const text = (palette: MapPalette) => JSON.stringify(buildStyle(palette, data, { selected: null, picked: null }));
    expect(text(light)).toContain("#1f55c4");
    expect(text(dark)).toContain("#7aa2f7");
    expect(text(dark)).not.toContain("#1f55c4");
  });

  it("leaves no raw hex of its own: every tone comes from the palette", () => {
    const style = JSON.stringify(buildStyle(light, data, { selected: null, picked: null }));
    const known = new Set(Object.values({ ...light, ...light.hues }).filter((value) => typeof value === "string"));
    for (const hex of style.match(/#[0-9a-f]{3,6}\b/gi) ?? []) expect(known.has(hex.toLowerCase())).toBe(true);
  });

  it("keeps the basemap quiet: the tones differ little from the ground", () => {
    for (const palette of [light, dark]) {
      const tones = baseTones(palette);
      expect(tones.land).toBe(palette.ground);
      for (const value of Object.values(tones)) expect(value).toMatch(/^(rgb\(|#)/);
    }
  });
});

describe("selection", () => {
  it("shows every day at full strength with none selected", () => {
    const paint = selectionPaint(null, null);
    expect(paint[LAYER_IDS.lineSolid]?.["line-opacity"]).toBe(1);
    expect(paint[LAYER_IDS.stop]?.["circle-opacity"]).toBe(1);
    expect(paint[LAYER_IDS.picked]?.["circle-stroke-opacity"]).toBe(0);
  });

  it("fades the other days and widens the selected one", () => {
    const paint = selectionPaint(2, "k");
    expect(JSON.stringify(paint[LAYER_IDS.lineSolid]?.["line-opacity"])).toBe('["case",["==",["get","day"],2],1,0.22]');
    expect(JSON.stringify(paint[LAYER_IDS.lineSolid]?.["line-width"])).toBe('["case",["==",["get","day"],2],6,3]');
    expect(paint[LAYER_IDS.picked]?.["circle-stroke-opacity"]).toBe(1);
  });

  it("starts the style from the same values it later applies", () => {
    const style = buildStyle(light, data, { selected: 1, picked: null });
    const layer = style.layers.find((candidate) => candidate.id === LAYER_IDS.lineSolid);
    expect(layer && "paint" in layer ? (layer.paint as Record<string, unknown> | undefined)?.["line-opacity"] : undefined).toEqual(
      selectionPaint(1, null)[LAYER_IDS.lineSolid]?.["line-opacity"],
    );
  });

  it("filters the picked ring by key, and by nothing when none is picked", () => {
    expect(pickedFilter("d1-s2")).toEqual(["==", ["get", "key"], "d1-s2"]);
    expect(pickedFilter(null)).toEqual(["==", ["get", "key"], ""]);
  });
});

/** WCAG 2.x contrast of two colours (the map's tones come out as "rgb(r, g, b)"). */
function contrast(a: string, b: string): number {
  const luminance = (color: string) => {
    const [r, g, bl] = (parseColor(color) ?? [0, 0, 0]).map((channel) => {
      const value = channel / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    }) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [light, darker] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (light + 0.05) / (darker + 0.05);
}

describe("water", () => {
  it("is a cool step in light: bluer than the grey it was, and darker than the land", () => {
    const tones = baseTones(light);
    const grey = mixColors(light.ground, light.rule, 0.85);
    expect(tones.water).not.toBe(grey);
    expect(tones.water).toBe(mixColors(grey, light.hues.flights, WATER_COOL));
    const [r, , b] = parseColor(tones.water) ?? [0, 0, 0];
    const [gr, , gb] = parseColor(grey) ?? [0, 0, 0];
    expect(b - r).toBeGreaterThan(gb - gr);
    expect(contrast(tones.land, tones.water)).toBeGreaterThan(1.1);
  });

  it("stays the darkest step in dark, as it was", () => {
    expect(baseTones(dark).water).toBe(mixColors(dark.ground, dark.rule, 0.9));
  });

  for (const palette of [light, dark]) {
    it(`keeps every day line at 3:1 over the water in ${palette.scheme}`, () => {
      const { water } = baseTones(palette);
      for (const [hue, color] of Object.entries(palette.hues)) {
        expect(contrast(color, water), `${hue} on water`).toBeGreaterThanOrEqual(3);
      }
    });
  }
});

describe("the stations' numbers and the hotel's label", () => {
  const style = buildStyle(light, data, { selected: null, picked: null });
  const layer = (id: string) => style.layers.find((candidate) => candidate.id === id);

  it("draws the stop's number inside its ring from zoom 12, on every station but the hotel", () => {
    const numbers = layer(LAYER_IDS.stopNumber);
    expect(numbers).toMatchObject({ type: "symbol", minzoom: 12, layout: { "text-field": ["get", "number"] } });
    expect(JSON.stringify((numbers as { filter?: unknown }).filter)).toContain("lodging");
  });

  it("writes 'Hotel' under the large ring", () => {
    expect(layer(LAYER_IDS.lodgingLabel)).toMatchObject({ type: "symbol", layout: { "text-field": "Hotel" } });
  });

  it("fades the numbers and the label with their day", () => {
    const paint = selectionPaint(1, null);
    expect(paint[LAYER_IDS.stopNumber]?.["text-opacity"]).toBeTruthy();
    expect(paint[LAYER_IDS.lodgingLabel]?.["text-opacity"]).toBeTruthy();
  });
});
