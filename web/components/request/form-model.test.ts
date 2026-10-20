import { describe, expect, it } from "vitest";

import { emptyRequestForm, exampleRequestForm, JOURNEY_MODES, validateRequestForm, type RequestFormValues } from "@/lib/request-form";

import {
  ADULTS_ID,
  JOURNEY_MODE_ICONS,
  childAgeOptions,
  DEMO_SCENARIO_PATH,
  errorTargets,
  fieldId,
  MAX_TRAVELERS,
  monthOptions,
  nextDay,
  parseDemoScenarios,
  placeErrors,
  withFieldWording,
} from "./form-model";

const TODAY = "2026-10-12";

describe("the travel mode", () => {
  it("visits the mode right after the destination", () => {
    const targets = errorTargets(emptyRequestForm(), { demo: false });
    expect(targets.map((target) => target.path).slice(0, 3)).toEqual(["origin", "destination", "journey_mode"]);
    expect(targets[2]).toEqual({ path: "journey_mode", controlId: "field-journey_mode", label: "Come viaggi" });
    const suggest = errorTargets({ ...emptyRequestForm(), suggestDestination: true }, { demo: false });
    expect(suggest.map((target) => target.path).slice(0, 3)).toEqual(["origin", "destination_idea", "journey_mode"]);
  });

  it("has an icon for every mode", () => {
    expect(Object.keys(JOURNEY_MODE_ICONS)).toEqual([...JOURNEY_MODES]);
    expect(JOURNEY_MODE_ICONS).toEqual({ flight: "airplane-tilt", train: "train", ferry: "boat", car: "car", coach: "bus" });
  });
});

function values(overrides: Partial<RequestFormValues> = {}): RequestFormValues {
  return { ...emptyRequestForm(), ...overrides };
}

describe("errorTargets", () => {
  it("lists the visible fields in the order the form shows them", () => {
    expect(errorTargets(values({ adults: 2, childAges: ["8", ""] }), { demo: false }).map((target) => target.path)).toEqual([
      "origin",
      "destination",
      "journey_mode",
      "dates",
      "dates.exact_start",
      "dates.exact_end",
      "travelers",
      "travelers.2.age",
      "travelers.3.age",
      "budget_eur",
      "preferences",
    ]);
  });

  it("follows the chosen modes and the demo select", () => {
    const paths = errorTargets(values({ suggestDestination: true, dateMode: "flexible" }), { demo: true }).map(
      (target) => target.path,
    );
    expect(paths).toContain("destination_idea");
    expect(paths).not.toContain("destination");
    expect(paths).toContain("dates.month");
    expect(paths).not.toContain("dates.exact_start");
    expect(paths.at(-1)).toBe(DEMO_SCENARIO_PATH);
  });

  it("points group errors at the group's first control and names each child", () => {
    const targets = errorTargets(values({ adults: 1, childAges: ["", ""] }), { demo: false });
    expect(targets.find((target) => target.path === "travelers")?.controlId).toBe(ADULTS_ID);
    expect(targets.find((target) => target.path === "dates")?.controlId).toBe(fieldId("dates.exact_start"));
    expect(targets.find((target) => target.path === "travelers.2.age")).toMatchObject({
      controlId: "field-travelers-2-age",
      label: "Età del bambino 2",
    });
  });
});

describe("placeErrors", () => {
  it("puts every client-side error next to a visible control", () => {
    const form = values({ adults: 1, childAges: [""] });
    const result = validateRequestForm(form, { today: TODAY });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    const { placed, unplaced } = placeErrors(result.errors, errorTargets(form, { demo: false }));
    expect(unplaced).toEqual([]);
    expect(placed.map((error) => error.path)).toEqual([
      "origin",
      "destination",
      "dates.exact_start",
      "dates.exact_end",
      "travelers.1.age",
      "budget_eur",
    ]);
  });

  it("keeps errors without a control for the summary", () => {
    const targets = errorTargets(values(), { demo: false });
    const { placed, unplaced } = placeErrors(
      { origin: "Campo obbligatorio.", "": "Valore non valido.", [DEMO_SCENARIO_PATH]: "Scelta non valida." },
      targets,
    );
    expect(placed.map((error) => error.path)).toEqual(["origin"]);
    expect(unplaced).toEqual([
      { path: "", message: "Valore non valido." },
      { path: DEMO_SCENARIO_PATH, message: "Scelta non valida." },
    ]);
  });
});

describe("choices", () => {
  it("starts departures tomorrow, across months and years", () => {
    expect(nextDay(TODAY)).toBe("2026-10-13");
    expect(nextDay("2026-10-31")).toBe("2026-11-01");
    expect(nextDay("2026-12-31")).toBe("2027-01-01");
    expect(nextDay("2028-02-28")).toBe("2028-02-29");
  });

  it("offers this month and the next ones, in sentence case", () => {
    const options = monthOptions(TODAY, 4);
    expect(options).toEqual([
      { value: "2026-10", label: "Ottobre 2026" },
      { value: "2026-11", label: "Novembre 2026" },
      { value: "2026-12", label: "Dicembre 2026" },
      { value: "2027-01", label: "Gennaio 2027" },
    ]);
    expect(monthOptions(TODAY).length).toBe(18);
    expect(monthOptions(TODAY, 2, "2028-05").map((option) => option.value)).toEqual(["2026-10", "2026-11", "2028-05"]);
    expect(monthOptions(TODAY, 2, "nope").length).toBe(2);
  });

  it("offers every age the schema allows", () => {
    const ages = childAgeOptions();
    expect(ages[0]).toEqual({ value: "0", label: "Meno di 1 anno" });
    expect(ages[1]).toEqual({ value: "1", label: "1 anno" });
    expect(ages.at(-1)).toEqual({ value: "17", label: "17 anni" });
    expect(ages.length).toBe(18);
    expect(MAX_TRAVELERS).toBe(9);
  });

  it("keeps the example inside the choices", () => {
    const example = exampleRequestForm(TODAY);
    const ages = childAgeOptions().map((option) => option.value);
    for (const age of example.childAges) expect(ages).toContain(age);
  });
});

describe("parseDemoScenarios", () => {
  it("reads a comma list in development, dropping blanks, duplicates and odd names", () => {
    expect(parseDemoScenarios(" happy_path, budget_reached,,happy_path, ../x , MCP ", "development")).toEqual([
      "happy_path",
      "budget_reached",
    ]);
  });

  it("offers nothing when unset or in production", () => {
    expect(parseDemoScenarios(undefined, "development")).toEqual([]);
    expect(parseDemoScenarios("", "development")).toEqual([]);
    expect(parseDemoScenarios("happy_path", "production")).toEqual([]);
    expect(parseDemoScenarios("happy_path", "test")).toEqual(["happy_path"]);
  });
});

describe("withFieldWording", () => {
  it("says what a required field wants instead of 'Campo obbligatorio.'", () => {
    expect(
      withFieldWording({ origin: "Campo obbligatorio.", budget_eur: "Campo obbligatorio.", destination: "Campo obbligatorio." }),
    ).toEqual({
      origin: "Indica da dove parti: una città, una stazione o un aeroporto.",
      budget_eur: "Indica il budget totale, in euro.",
      destination: "Campo obbligatorio.",
    });
    expect(withFieldWording({ budget_eur: "Scrivi un numero intero." })).toEqual({ budget_eur: "Scrivi un numero intero." });
  });
});
