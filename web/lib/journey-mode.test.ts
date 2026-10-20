import { describe, expect, it } from "vitest";

import { DEFAULT_JOURNEY_MODE, journeyModePhrase } from "./journey-mode";

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
