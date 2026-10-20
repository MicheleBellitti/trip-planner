import { describe, expect, it } from "vitest";

import {
  DEFAULT_JOURNEY_MODE,
  JOURNEY_MODE_LABELS,
  JOURNEY_MODE_NOTES,
  JOURNEY_MODE_PHRASES,
  journeyModePhrase,
} from "./journey-mode";

describe("the modes in words", () => {
  it("has a phrase for every mode, the plane included (the form's read-back names them all)", () => {
    expect(Object.keys(JOURNEY_MODE_PHRASES)).toEqual(Object.keys(JOURNEY_MODE_LABELS));
    expect(JOURNEY_MODE_PHRASES.flight).toBe("in aereo");
    expect(JOURNEY_MODE_PHRASES.coach).toBe("in pullman");
  });

  it("explains only the two modes that are easy to confuse: on foot or with the car", () => {
    expect(JOURNEY_MODE_NOTES).toEqual({
      ferry: "A bordo a piedi: se porti l'auto, scegli Auto.",
      car: "Con la tua auto, anche sui traghetti se servono.",
    });
  });
});

describe("journeyModePhrase", () => {
  it("says the mode in words, except the plane and anything unknown", () => {
    expect(journeyModePhrase("train")).toBe("in treno");
    expect(journeyModePhrase("ferry")).toBe("in traghetto");
    expect(journeyModePhrase("car")).toBe("in auto");
    expect(journeyModePhrase("coach")).toBe("in pullman");
    for (const odd of ["flight", null, undefined, "plane", 3, "Train", "__proto__", "toString"]) {
      expect(journeyModePhrase(odd)).toBeNull();
    }
  });

  it("defaults to the plane", () => {
    expect(DEFAULT_JOURNEY_MODE).toBe("flight");
  });
});
