/**
 * The itinerary map's model: which stops can be drawn, how each day becomes a line, where the
 * map should look. Pure functions, no React and no maplibre, so the geometry is testable without
 * a browser (DESIGN.md, "Map").
 *
 * A stop is drawn only when the plan gave it a coordinate pair (`lat` and `lon`, both finite, in
 * range, and not the (0, 0) of "unknown"). A stop without one stays in the list and is not on the
 * map: the line simply skips it. Days keep the index they have in the itinerary, so a day's
 * colour never changes when a neighbour has no coordinates.
 */

import type { Plan, PlanBooking, PlanDay, PlanStop } from "@/lib/schemas/generated/plan";

import { tripDayNumber } from "../trip-dates";

// --- the five hues ----------------------------------------------------------------------------

/**
 * The line hues, in the fixed order days take them: Giorno 1 blue, 2 green, 3 violet, 4 teal,
 * 5 slate, then again from the first. The coordinator's slate comes last because it is the least
 * distinct from ink, and neighbours differ as much as the five allow. The names are the agents'
 * (`--line-<name>` in globals.css); the map borrows their hues only to tell days apart.
 */
export const DAY_HUES = ["flights", "lodging", "activities", "transport", "coordinator"] as const;
export type DayHue = (typeof DAY_HUES)[number];

/** The hue of the day at a position in the itinerary. */
export function hueFor(dayIndex: number): DayHue {
  return DAY_HUES[((dayIndex % DAY_HUES.length) + DAY_HUES.length) % DAY_HUES.length] ?? "flights";
}

/** How many times the hues have been used up before this day: 0 for the first five days. From the
 * sixth the line is dashed, so two days of one hue can still be told apart. */
export function cycleFor(dayIndex: number): number {
  return Math.max(0, Math.floor(dayIndex / DAY_HUES.length));
}

/** The CSS variable that holds a hue (globals.css). */
export function hueVariable(hue: DayHue): string {
  return `--line-${hue}`;
}

// --- coordinates ------------------------------------------------------------------------------

/** [longitude, latitude], as GeoJSON and maplibre write them. */
export type LngLat = readonly [number, number];
/** [[west, south], [east, north]]. */
export type Bounds = readonly [LngLat, LngLat];

/** A coordinate pair a map may draw: finite, in range, and not (0, 0), which sources use for
 * "unknown" and which no trip in this product visits. */
export function isUsablePoint(lat: number | null | undefined, lon: number | null | undefined): boolean {
  if (typeof lat !== "number" || typeof lon !== "number") return false;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return false;
  return !(lat === 0 && lon === 0);
}

/** The box around some points, or null for none. */
export function boundsOf(points: readonly LngLat[]): Bounds | null {
  if (points.length === 0) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const [lon, lat] of points) {
    if (lon < west) west = lon;
    if (lon > east) east = lon;
    if (lat < south) south = lat;
    if (lat > north) north = lat;
  }
  return [
    [west, south],
    [east, north],
  ];
}

/** Whether a box has no extent (one point, or points on top of each other). */
export function isPointBounds(bounds: Bounds, epsilon = 1e-6): boolean {
  return bounds[1][0] - bounds[0][0] < epsilon && bounds[1][1] - bounds[0][1] < epsilon;
}

// --- the model --------------------------------------------------------------------------------

export interface MapStop {
  /** Unique across the plan: the plan's stop ref, else its position. */
  key: string;
  ref: string;
  title: string;
  /** HH:MM in the trip's zone, as the list shows it. */
  time: string | null;
  /** The place's name when it adds something to the title ("Time Out Market Lisboa"). */
  place: string | null;
  kind: PlanStop["kind"];
  lat: number;
  lon: number;
  /** The trip's base: the stop a lodging booking points to, or a stop at the lodging's name. */
  lodging: boolean;
  /** Position of the day in the itinerary (the list's `li` index). */
  dayIndex: number;
  /** Position in the day's list of stops, counting the stops with no coordinates (0-based): the
   * list's `li` index inside its day, and the number on the map is this plus one. */
  stopIndex: number;
  /** Far from the trip's base (a day trip): outside the view "Tutti i giorni" fits to. */
  far: boolean;
}

/** A day whose stops lie outside the core view: it gets a quiet chip that selects the day. */
export interface MapOutlier {
  /** Itinerary index of the day. */
  dayIndex: number;
  /** "Giorno 3". */
  dayLabel: string;
  /** Where it is: the day's title when it has a short one, else the first far stop's title. */
  name: string;
}

export interface MapDay {
  /** Position in the itinerary: the list's `li` index and the hue's source. */
  index: number;
  /** 1-based day of the trip, else the position. */
  number: number;
  /** "Giorno 3". */
  label: string;
  date: string;
  title: string | null;
  hue: DayHue;
  cycle: number;
  /** Only the stops that have coordinates, in the order they happen. */
  stops: MapStop[];
  /** All the day's stops, with or without coordinates. */
  totalStops: number;
}

export interface MapModel {
  /** The days that have at least one located stop. */
  days: MapDay[];
  /** Located stops, and all stops, over the whole plan. */
  located: number;
  total: number;
  /** A located stop is the trip's base. */
  hasLodging: boolean;
  /** The days with stops outside the core view, for the "Fuori mappa" chips. */
  outliers: MapOutlier[];
}

export type MapPlan = Pick<Plan, "days" | "start_date" | "bookings" | "lodging_name">;

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLocaleLowerCase("it")
    .replace(/\s+/g, " ")
    .trim();
}

/** Refs of the stops that are the trip's base: the target of a lodging booking, or a stop whose
 * place is named like the plan's lodging. */
export function lodgingRefs(plan: Pick<MapPlan, "days" | "bookings" | "lodging_name">): Set<string> {
  const refs = new Set<string>();
  for (const booking of plan.bookings as readonly PlanBooking[]) {
    if (booking.kind === "lodging" && booking.stop_ref) refs.add(booking.stop_ref);
  }
  const name = plan.lodging_name ? normalize(plan.lodging_name) : "";
  if (name.length >= 3) {
    for (const day of plan.days) {
      for (const stop of day.stops) {
        const place = stop.location_name ? normalize(stop.location_name) : "";
        if (place && (place === name || place.includes(name) || name.includes(place))) refs.add(stop.ref);
      }
    }
  }
  return refs;
}

function stopPlaceName(stop: Pick<PlanStop, "title" | "location_name">): string | null {
  const name = stop.location_name?.trim();
  if (!name) return null;
  return normalize(stop.title).includes(normalize(name)) ? null : name;
}

function dayLabel(day: PlanDay, index: number, startDate: string): { number: number; label: string } {
  const counted = tripDayNumber(day.date, startDate);
  const number = counted !== null && counted >= 1 ? counted : index + 1;
  return { number, label: `Giorno ${number}` };
}

/** What the map draws for a plan, or null when no stop has coordinates (then there is no map). */
export function buildMapModel(plan: MapPlan): MapModel | null {
  const lodging = lodgingRefs(plan);
  const seen = new Set<string>();
  const days: MapDay[] = [];
  let located = 0;
  let total = 0;
  let hasLodging = false;

  plan.days.forEach((day, index) => {
    total += day.stops.length;
    const stops: MapStop[] = [];
    day.stops.forEach((stop, stopIndex) => {
      if (!isUsablePoint(stop.lat, stop.lon)) return;
      let key = stop.ref || `d${index}-s${stopIndex}`;
      if (seen.has(key)) key = `${key}#${index}-${stopIndex}`;
      seen.add(key);
      const isLodging = lodging.has(stop.ref);
      if (isLodging) hasLodging = true;
      stops.push({
        key,
        ref: stop.ref,
        title: stop.title,
        time: stop.start_time ?? null,
        place: stopPlaceName(stop),
        kind: stop.kind,
        lat: stop.lat as number,
        lon: stop.lon as number,
        lodging: isLodging,
        dayIndex: index,
        stopIndex,
        far: false,
      });
    });
    located += stops.length;
    if (stops.length === 0) return;
    days.push({
      index,
      ...dayLabel(day, index, plan.start_date),
      date: day.date,
      title: day.title ?? null,
      hue: hueFor(index),
      cycle: cycleFor(index),
      stops,
      totalStops: day.stops.length,
    });
  });

  if (days.length === 0) return null;
  const outliers = markFarStops(days);
  return { days, located, total, hasLodging, outliers };
}

// --- the core view ----------------------------------------------------------------------------

/** Great-circle distance in km between two points. */
export function distanceKm(a: LngLat, b: LngLat): number {
  const rad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * rad;
  const dLon = (b[0] - a[0]) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(h)));
}

const median = (values: number[]): number => {
  const sorted = [...values].sort((x, y) => x - y);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? (sorted[mid] ?? 0) : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2;
};

/** Fewer located stops than this and there is no telling a day trip from the trip. */
const MIN_STOPS_FOR_CORE = 5;
/** The core view is at least this wide (km) around the base, however tight the stops are. */
const CORE_FLOOR_KM = 10;

/**
 * Stops far from the trip's base are marked `far` and left out of the view "Tutti i giorni" fits
 * (a day trip to Sintra would otherwise squeeze Lisbon into a sixth of the frame). The base is the
 * lodging (else the median point); "far" is beyond 10 km or twice the distance that three quarters
 * of the stops are within. A trip whose stops are spread over several centres has no outlier: when
 * more than a third would be far, nothing is. Returns one entry per day with far stops.
 */
function markFarStops(days: MapDay[]): MapOutlier[] {
  const stops = days.flatMap((day) => day.stops);
  if (stops.length < MIN_STOPS_FOR_CORE) return [];
  const points = stops.map((stop): LngLat => [stop.lon, stop.lat]);
  const base = stops.filter((stop) => stop.lodging);
  const anchor: LngLat = base.length
    ? [base.reduce((sum, stop) => sum + stop.lon, 0) / base.length, base.reduce((sum, stop) => sum + stop.lat, 0) / base.length]
    : [median(stops.map((stop) => stop.lon)), median(stops.map((stop) => stop.lat))];
  const distances = points.map((point) => distanceKm(anchor, point));
  const sorted = [...distances].sort((x, y) => x - y);
  const p75 = sorted[Math.ceil(sorted.length * 0.75) - 1] ?? 0;
  const radius = Math.max(CORE_FLOOR_KM, 2 * p75);
  const far = stops.filter((_, at) => (distances[at] ?? 0) > radius);
  if (far.length === 0 || far.length > stops.length / 3) return [];
  const outliers: MapOutlier[] = [];
  for (const day of days) {
    const here = day.stops.filter((stop) => far.includes(stop));
    if (here.length === 0) continue;
    for (const stop of here) stop.far = true;
    const title = day.title?.trim();
    const first = here[0];
    outliers.push({
      dayIndex: day.index,
      dayLabel: day.label,
      name: title && title.length <= 28 ? title : (first?.title ?? day.label),
    });
  }
  return outliers;
}

/** Every located stop, in the order of the plan. */
export function modelStops(model: MapModel): MapStop[] {
  return model.days.flatMap((day) => day.stops);
}

const pointOf = (stop: Pick<MapStop, "lat" | "lon">): LngLat => [stop.lon, stop.lat];

/** The box around the stops "Tutti i giorni" fits: all of them, minus the far ones (day trips,
 * which have their chip and their day). */
export function modelBounds(model: MapModel): Bounds | null {
  const stops = modelStops(model);
  const core = stops.filter((stop) => !stop.far);
  return boundsOf((core.length > 0 ? core : stops).map(pointOf));
}

/** The box around one day's stops, by its itinerary index. */
export function dayBounds(model: MapModel, dayIndex: number): Bounds | null {
  const day = model.days.find((candidate) => candidate.index === dayIndex);
  return day ? boundsOf(day.stops.map(pointOf)) : null;
}

/** The day at an itinerary index, if it has stops on the map. */
export function dayAt(model: MapModel, dayIndex: number | null): MapDay | null {
  return dayIndex === null ? null : (model.days.find((day) => day.index === dayIndex) ?? null);
}

// --- GeoJSON ----------------------------------------------------------------------------------

export interface LineProps {
  day: number;
  slot: number;
  cycle: number;
}

export interface StopProps {
  key: string;
  /** The number drawn on the station: its place in the day's list. */
  number: string;
  day: number;
  slot: number;
  cycle: number;
  lodging: boolean;
  title: string;
  time: string | null;
}

export type LineFeature = {
  type: "Feature";
  properties: LineProps;
  geometry: { type: "LineString"; coordinates: [number, number][] };
};
export type StopFeature = {
  type: "Feature";
  properties: StopProps;
  geometry: { type: "Point"; coordinates: [number, number] };
};
export type FeatureCollectionOf<F> = { type: "FeatureCollection"; features: F[] };

/** Position of a hue in DAY_HUES: the number the style's colour expression matches on. */
export function slotOf(hue: DayHue): number {
  return DAY_HUES.indexOf(hue);
}

/** One line per day with at least two located stops: its stops in order, one segment between
 * each pair (a stop with no coordinates is skipped, not bridged by a guess). */
export function lineFeatures(model: MapModel): FeatureCollectionOf<LineFeature> {
  return {
    type: "FeatureCollection",
    features: model.days
      .filter((day) => day.stops.length >= 2)
      .map((day) => ({
        type: "Feature" as const,
        properties: { day: day.index, slot: slotOf(day.hue), cycle: day.cycle },
        geometry: {
          type: "LineString" as const,
          coordinates: day.stops.map((stop): [number, number] => [stop.lon, stop.lat]),
        },
      })),
  };
}

/** One point per located stop. */
export function stopFeatures(model: MapModel): FeatureCollectionOf<StopFeature> {
  return {
    type: "FeatureCollection",
    features: model.days.flatMap((day) =>
      day.stops.map((stop) => ({
        type: "Feature" as const,
        properties: {
          key: stop.key,
          number: String(stop.stopIndex + 1),
          day: day.index,
          slot: slotOf(day.hue),
          cycle: day.cycle,
          lodging: stop.lodging,
          title: stop.title,
          time: stop.time,
        },
        geometry: { type: "Point" as const, coordinates: [stop.lon, stop.lat] as [number, number] },
      })),
    ),
  };
}

/** A located stop by key, with the day it belongs to. */
export function findStop(model: MapModel, key: string | null): { stop: MapStop; day: MapDay } | null {
  if (key === null) return null;
  for (const day of model.days) {
    const stop = day.stops.find((candidate) => candidate.key === key);
    if (stop) return { stop, day };
  }
  return null;
}

// --- words ------------------------------------------------------------------------------------

/** "1 tappa", "5 tappe". */
export function stopsCount(count: number): string {
  return count === 1 ? "1 tappa" : `${count} tappe`;
}

/**
 * The map in words, for people who do not see it: how much of the plan is on it, then each day's
 * first and last place. The itinerary list stays the primary content; this says what the map adds.
 */
export function mapSummary(model: MapModel): string {
  const parts: string[] = [];
  const missing = model.total - model.located;
  parts.push(
    `Mappa di ${stopsCount(model.located)} su ${model.total}, in ${model.days.length === 1 ? "1 giorno" : `${model.days.length} giorni`}.`,
  );
  if (missing > 0) {
    parts.push(
      missing === 1
        ? "Una tappa non ha una posizione e resta solo nell'elenco."
        : `${missing} tappe non hanno una posizione e restano solo nell'elenco.`,
    );
  }
  if (model.outliers.length > 0) {
    parts.push(
      `Fuori dalla vista iniziale: ${model.outliers.map((outlier) => `${outlier.name} (${outlier.dayLabel})`).join(", ")}.`,
    );
  }
  for (const day of model.days) {
    const first = day.stops[0];
    const last = day.stops[day.stops.length - 1];
    if (!first || !last) continue;
    parts.push(
      day.stops.length === 1
        ? `${day.label}: ${first.title}.`
        : `${day.label}: ${stopsCount(day.stops.length)}, da ${first.title} a ${last.title}.`,
    );
  }
  return parts.join(" ");
}

/** The words on a station's card: "Giorno 2, tappa 3, 10:00". */
export function stationCaption(day: Pick<MapDay, "label">, stop: Pick<MapStop, "time" | "stopIndex">): string {
  const base = `${day.label}, tappa ${stop.stopIndex + 1}`;
  return stop.time ? `${base}, ${stop.time}` : base;
}

/** What the map says under its legend, as the person picks a day: how much of the plan is on it.
 * It is a polite live region, so a pick on the phone (where the list is not in view) is heard. */
export function liveLine(model: MapModel, selectedDay: number | null): string {
  const day = dayAt(model, selectedDay);
  if (day) {
    const rest = day.totalStops - day.stops.length;
    const tail = rest > 0 ? `, ${rest === 1 ? "un'altra" : `altre ${rest}`} solo nell'elenco` : "";
    return `${day.label}: ${stopsCount(day.stops.length)} sulla mappa${tail}.`;
  }
  if (model.located === model.total) {
    return model.total === 1 ? "La tappa è sulla mappa." : `Tutte le ${model.total} tappe sono sulla mappa.`;
  }
  const are = model.located === 1 ? "è" : "sono";
  return `${stopsCount(model.located)} su ${model.total} ${are} sulla mappa, le altre solo nell'elenco.`;
}

// --- colours ----------------------------------------------------------------------------------

/** "#rgb", "#rrggbb" or "rgb(r g b)" / "rgb(r, g, b)" as [r, g, b], else null. */
export function parseColor(value: string): [number, number, number] | null {
  const text = value.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text);
  if (hex?.[1]) {
    const digits = hex[1].length === 3 ? [...hex[1]].map((char) => char + char).join("") : hex[1];
    return [0, 2, 4].map((at) => Number.parseInt(digits.slice(at, at + 2), 16)) as [number, number, number];
  }
  const rgb = /^rgba?\(\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)/i.exec(text);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  return null;
}

/** `amount` of `b` mixed into `a` (0 gives a, 1 gives b), as "rgb(r, g, b)". maplibre does not
 * read `color-mix()`, so the map's muted tones are computed from the tokens here. A colour that
 * cannot be read comes back unchanged. */
export function mixColors(a: string, b: string, amount: number): string {
  const from = parseColor(a);
  const to = parseColor(b);
  if (!from || !to) return a;
  const t = Math.min(1, Math.max(0, amount));
  const [r, g, bl] = from.map((channel, at) => Math.round(channel + ((to[at] ?? channel) - channel) * t));
  return `rgb(${r}, ${g}, ${bl})`;
}
