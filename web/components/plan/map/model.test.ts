import { describe, expect, it } from "vitest";

import { PlanDetailSchema } from "@/lib/schemas/api";

import happyDetailJson from "../__fixtures__/happy-path.detail.json";
import {
  boundsOf,
  buildMapModel,
  cycleFor,
  dayBounds,
  DAY_HUES,
  distanceKm,
  findStop,
  hueFor,
  isPointBounds,
  isUsablePoint,
  lineFeatures,
  liveLine,
  lodgingRefs,
  mapSummary,
  mixColors,
  modelBounds,
  parseColor,
  stationCaption,
  stopFeatures,
  stopsCount,
  type MapPlan,
} from "./model";

function happyPlan(): NonNullable<ReturnType<typeof PlanDetailSchema.parse>["plan"]> {
  const plan = PlanDetailSchema.parse(structuredClone(happyDetailJson)).plan;
  if (!plan) throw new Error("fixture has no plan");
  return plan;
}

function stop(ref: string, lat: number | null, lon: number | null, extra: Record<string, unknown> = {}) {
  return {
    ref,
    kind: "activity" as const,
    title: `Tappa ${ref}`,
    lat,
    lon,
    address: null,
    duration_min: null,
    location_name: null,
    notes: null,
    start_time: null,
    url: null,
    ...extra,
  };
}

function plan(days: { date: string; stops: ReturnType<typeof stop>[] }[], extra: Partial<MapPlan> = {}): MapPlan {
  return {
    start_date: "2027-04-14",
    bookings: [],
    lodging_name: null,
    days: days.map((day) => ({ ...day, title: null })),
    ...extra,
  };
}

describe("hues", () => {
  it("takes the five hues in a fixed order and starts again", () => {
    expect([0, 1, 2, 3, 4, 5, 6].map(hueFor)).toEqual([...DAY_HUES, "flights", "lodging"]);
    expect(hueFor(-1)).toBe("coordinator");
  });

  it("dashes the lines from the sixth day", () => {
    expect([0, 4, 5, 9, 10].map(cycleFor)).toEqual([0, 0, 1, 1, 2]);
  });
});

describe("coordinates", () => {
  it("accepts a pair in range and refuses everything else", () => {
    expect(isUsablePoint(38.7, -9.1)).toBe(true);
    expect(isUsablePoint(null, -9.1)).toBe(false);
    expect(isUsablePoint(38.7, undefined)).toBe(false);
    expect(isUsablePoint(Number.NaN, 1)).toBe(false);
    expect(isUsablePoint(91, 1)).toBe(false);
    expect(isUsablePoint(1, 181)).toBe(false);
    expect(isUsablePoint(0, 0)).toBe(false);
    expect(isUsablePoint(0, 12)).toBe(true);
  });

  it("boxes some points, and none", () => {
    expect(boundsOf([])).toBeNull();
    expect(
      boundsOf([
        [-9.2, 38.7],
        [-9.1, 38.8],
        [-9.4, 38.6],
      ]),
    ).toEqual([
      [-9.4, 38.6],
      [-9.1, 38.8],
    ]);
  });

  it("knows a box with no extent", () => {
    const one = boundsOf([[1, 2]]);
    expect(one && isPointBounds(one)).toBe(true);
    const two = boundsOf([
      [1, 2],
      [1.1, 2],
    ]);
    expect(two && isPointBounds(two)).toBe(false);
  });
});

describe("buildMapModel", () => {
  it("is null when no stop has coordinates", () => {
    expect(buildMapModel(plan([{ date: "2027-04-14", stops: [stop("a", null, null), stop("b", 0, 0)] }]))).toBeNull();
    expect(buildMapModel(plan([]))).toBeNull();
  });

  it("keeps the located stops, per day, with the day's index in the itinerary", () => {
    const model = buildMapModel(
      plan([
        { date: "2027-04-14", stops: [stop("a", 38.7, -9.1), stop("b", null, null), stop("c", 38.71, -9.12)] },
        { date: "2027-04-15", stops: [stop("d", null, null)] },
        { date: "2027-04-16", stops: [stop("e", 38.8, -9.2)] },
      ]),
    );
    expect(model).not.toBeNull();
    expect(model?.days.map((day) => [day.index, day.label, day.stops.map((s) => s.ref)])).toEqual([
      [0, "Giorno 1", ["a", "c"]],
      [2, "Giorno 3", ["e"]],
    ]);
    // The day with nothing to draw is skipped, and the third day keeps the third hue.
    expect(model?.days.map((day) => day.hue)).toEqual(["flights", "activities"]);
    expect(model?.located).toBe(3);
    expect(model?.total).toBe(5);
  });

  it("numbers the days from the trip's start, not from the first day with stops", () => {
    const model = buildMapModel(plan([{ date: "2027-04-16", stops: [stop("a", 38.7, -9.1)] }]));
    expect(model?.days[0]?.label).toBe("Giorno 3");
    expect(model?.days[0]?.index).toBe(0);
  });

  it("keeps stop keys unique when two stops share a ref", () => {
    const model = buildMapModel(
      plan([
        { date: "2027-04-14", stops: [stop("a", 38.7, -9.1)] },
        { date: "2027-04-15", stops: [stop("a", 38.8, -9.2)] },
      ]),
    );
    const keys = model?.days.flatMap((day) => day.stops.map((s) => s.key)) ?? [];
    expect(new Set(keys).size).toBe(2);
  });

  it("shows the place only when it adds to the title", () => {
    const model = buildMapModel(
      plan([
        {
          date: "2027-04-14",
          stops: [
            stop("a", 38.7, -9.1, { title: "Visita alla Torre di Belém", location_name: "Torre di Belém" }),
            stop("b", 38.7, -9.1, { title: "Cena", location_name: "Time Out Market" }),
          ],
        },
      ]),
    );
    expect(model?.days[0]?.stops.map((s) => s.place)).toEqual([null, "Time Out Market"]);
  });

  it("reads the real plan: five days, the hotel as the base", () => {
    const detail = happyPlan();
    const model = buildMapModel(detail);
    expect(model?.days).toHaveLength(5);
    expect(model?.hasLodging).toBe(true);
    const hotel = model?.days[0]?.stops.find((s) => s.ref === "d1-hotel");
    expect(hotel?.lodging).toBe(true);
    expect(model?.days[0]?.stops.find((s) => s.ref === "d1-baixa")?.lodging).toBe(false);
    // Stops with no coordinates (lunches, the flights) are not on it, only in the list.
    expect(model?.located).toBeLessThan(model?.total ?? 0);
  });
});

describe("lodgingRefs", () => {
  it("follows a lodging booking's stop, and a stop at the lodging's name", () => {
    const base = plan([
      {
        date: "2027-04-14",
        stops: [stop("hotel", 1, 1), stop("also", 1, 1, { location_name: "Hotel Lisboa Plaza" }), stop("other", 1, 1)],
      },
    ]);
    const refs = lodgingRefs({
      ...base,
      lodging_name: "Hotel Lisboa Plaza",
      bookings: [{ kind: "lodging", stop_ref: "hotel" }, { kind: "ticket", stop_ref: "other" }] as MapPlan["bookings"],
    });
    expect([...refs].sort()).toEqual(["also", "hotel"]);
  });

  it("does not match a lodging name that is too short to mean anything", () => {
    const base = plan([{ date: "2027-04-14", stops: [stop("a", 1, 1, { location_name: "Ho" })] }]);
    expect(lodgingRefs({ ...base, lodging_name: "Ho" }).size).toBe(0);
  });
});

describe("geometry", () => {
  const model = buildMapModel(
    plan([
      { date: "2027-04-14", stops: [stop("a", 38.7, -9.1), stop("b", 38.8, -9.2), stop("c", null, null)] },
      { date: "2027-04-15", stops: [stop("d", 38.9, -9.3)] },
    ]),
  );
  if (!model) throw new Error("no model");

  it("draws one line per day with two stops or more, skipping unlocated stops", () => {
    const lines = lineFeatures(model);
    expect(lines.features).toHaveLength(1);
    expect(lines.features[0]?.geometry.coordinates).toEqual([
      [-9.1, 38.7],
      [-9.2, 38.8],
    ]);
    expect(lines.features[0]?.properties).toEqual({ day: 0, slot: 0, cycle: 0 });
  });

  it("draws one point per located stop, in [lon, lat]", () => {
    const stops = stopFeatures(model);
    expect(stops.features.map((feature) => feature.geometry.coordinates)).toEqual([
      [-9.1, 38.7],
      [-9.2, 38.8],
      [-9.3, 38.9],
    ]);
    expect(stops.features[2]?.properties).toMatchObject({ day: 1, slot: 1, lodging: false });
  });

  it("fits every stop, or one day", () => {
    expect(modelBounds(model)).toEqual([
      [-9.3, 38.7],
      [-9.1, 38.9],
    ]);
    expect(dayBounds(model, 0)).toEqual([
      [-9.2, 38.7],
      [-9.1, 38.8],
    ]);
    expect(dayBounds(model, 7)).toBeNull();
  });

  it("finds a stop and its day by key", () => {
    expect(findStop(model, "d")?.day.label).toBe("Giorno 2");
    expect(findStop(model, "zzz")).toBeNull();
    expect(findStop(model, null)).toBeNull();
  });
});

describe("words", () => {
  it("counts stops", () => {
    expect(stopsCount(1)).toBe("1 tappa");
    expect(stopsCount(5)).toBe("5 tappe");
  });

  it("summarises the map for a screen reader", () => {
    const model = buildMapModel(
      plan([
        { date: "2027-04-14", stops: [stop("a", 38.7, -9.1), stop("b", 38.8, -9.2), stop("c", null, null)] },
        { date: "2027-04-15", stops: [stop("d", 38.9, -9.3)] },
      ]),
    );
    if (!model) throw new Error("no model");
    expect(mapSummary(model)).toBe(
      "Mappa di 3 tappe su 4, in 2 giorni. Una tappa non ha una posizione e resta solo nell'elenco. " +
        "Giorno 1: 2 tappe, da Tappa a a Tappa b. Giorno 2: Tappa d.",
    );
  });

  it("captions a station with its day and time", () => {
    expect(stationCaption({ label: "Giorno 2" }, { time: "10:00", stopIndex: 2 })).toBe("Giorno 2, tappa 3, 10:00");
    expect(stationCaption({ label: "Giorno 2" }, { time: null, stopIndex: 0 })).toBe("Giorno 2, tappa 1");
  });
});

describe("colours", () => {
  it("reads hex and rgb()", () => {
    expect(parseColor("#fff")).toEqual([255, 255, 255]);
    expect(parseColor("#0f1a2a")).toEqual([15, 26, 42]);
    expect(parseColor("rgb(1 2 3)")).toEqual([1, 2, 3]);
    expect(parseColor("rgb(1, 2, 3)")).toEqual([1, 2, 3]);
    expect(parseColor("gray")).toBeNull();
  });

  it("mixes two colours and clamps the amount", () => {
    expect(mixColors("#000000", "#ffffff", 0.5)).toBe("rgb(128, 128, 128)");
    expect(mixColors("#000000", "#ffffff", 0)).toBe("rgb(0, 0, 0)");
    expect(mixColors("#000000", "#ffffff", 3)).toBe("rgb(255, 255, 255)");
    expect(mixColors("gray", "#ffffff", 0.5)).toBe("gray");
  });
});

describe("the core view", () => {
  it("leaves a day trip out of 'Tutti i giorni', keeps its day, and names it", () => {
    const model = buildMapModel(happyPlan());
    if (!model) throw new Error("no model");
    expect(model.outliers).toEqual([{ dayIndex: 2, dayLabel: "Giorno 3", name: "Sintra" }]);
    const far = model.days.flatMap((day) => day.stops).filter((candidate) => candidate.far);
    expect(far.map((candidate) => candidate.ref)).toEqual(["d3-pena"]);
    // The first view is Lisbon: Pena's longitude (-9.39) is outside it, the day's own box has it.
    const core = modelBounds(model);
    expect(core?.[0][0]).toBeGreaterThan(-9.3);
    expect(dayBounds(model, 2)?.[0][0]).toBeLessThan(-9.3);
  });

  it("calls the outlier by its stop when the day has no short title", () => {
    const base = happyPlan();
    const named = { ...base, days: base.days.map((day) => ({ ...day, title: day.date === "2027-04-16" ? null : day.title })) };
    const model = buildMapModel(named);
    expect(model?.outliers[0]?.name).toBe("Palácio da Pena");
  });

  it("marks nothing far in a plan of only a few stops", () => {
    const model = buildMapModel(
      plan([{ date: "2027-04-14", stops: [stop("a", 38.7, -9.1), stop("b", 38.7, -9.1), stop("c", 41.9, 12.5)] }]),
    );
    expect(model?.outliers).toEqual([]);
  });

  it("marks nothing far when the stops are spread over several centres", () => {
    // Lisbon, Madrid and Rome in equal parts: no centre, so no day trip.
    const centres: [number, number][] = [
      [38.72, -9.14],
      [40.41, -3.7],
      [41.9, 12.5],
    ];
    const model = buildMapModel(
      plan(
        centres.map(([lat, lon], day) => ({
          date: `2027-04-${14 + day}`,
          stops: [0, 1, 2].map((at) => stop(`s${day}${at}`, lat + at / 1000, lon)),
        })),
      ),
    );
    expect(model?.outliers).toEqual([]);
    expect(modelBounds(model!)?.[0][0]).toBeCloseTo(-9.14);
  });

  it("measures distance in km", () => {
    expect(distanceKm([-9.14, 38.72], [-9.14, 38.72])).toBe(0);
    expect(distanceKm([-9.1455, 38.7196], [-9.3906, 38.7876])).toBeGreaterThan(20);
    expect(distanceKm([-9.1455, 38.7196], [-9.3906, 38.7876])).toBeLessThan(25);
  });
});

describe("numbers", () => {
  it("numbers a stop by its place in the day's list, counting stops with no coordinates", () => {
    const model = buildMapModel(
      plan([{ date: "2027-04-14", stops: [stop("a", 38.7, -9.1), stop("b", null, null), stop("c", 38.8, -9.2)] }]),
    );
    if (!model) throw new Error("no model");
    expect(model.days[0]?.stops.map((candidate) => candidate.stopIndex)).toEqual([0, 2]);
    expect(stopFeatures(model).features.map((feature) => feature.properties.number)).toEqual(["1", "3"]);
  });
});

describe("the live line", () => {
  const model = buildMapModel(happyPlan());
  if (!model) throw new Error("no model");

  it("says how much of the plan is on the map", () => {
    expect(liveLine(model, null)).toBe(`${stopsCount(model.located)} su 19 sono sulla mappa, le altre solo nell'elenco.`);
  });

  it("says what a day has on the map and what stays in the list", () => {
    expect(liveLine(model, 2)).toBe("Giorno 3: 2 tappe sulla mappa, altre 2 solo nell'elenco.");
    expect(liveLine(model, 0)).toBe("Giorno 1: 4 tappe sulla mappa, un'altra solo nell'elenco.");
  });

  it("says all of it when nothing is missing", () => {
    const whole = buildMapModel(plan([{ date: "2027-04-14", stops: [stop("a", 38.7, -9.1), stop("b", 38.8, -9.2)] }]));
    expect(liveLine(whole!, null)).toBe("Tutte le 2 tappe sono sulla mappa.");
    expect(liveLine(whole!, 0)).toBe("Giorno 1: 2 tappe sulla mappa.");
  });

  it("is part of the summary a screen reader gets, with the day trip", () => {
    expect(mapSummary(model)).toContain("Fuori dalla vista iniziale: Sintra (Giorno 3).");
  });
});
