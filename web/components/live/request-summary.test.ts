import { describe, expect, it } from "vitest";

import { requestSummary, travelersText } from "./request-summary";

describe("requestSummary", () => {
  it("says from where, who and how much in one line", () => {
    expect(
      requestSummary({
        origin: "Milano",
        destination: "Lisbona",
        dates: { exact_start: "2027-04-14", exact_end: "2027-04-18", month: null, nights: null },
        travelers: [{ kind: "adult" }, { kind: "adult" }, { kind: "child", age: 8 }, { kind: "child", age: 11 }],
        budget_eur: 2400,
      }),
    ).toBe("Da Milano, 2 adulti e 2 bambini (8 e 11 anni), budget 2.400 €");
  });

  it("adds the nights of flexible dates (the title only names the month)", () => {
    expect(
      requestSummary({
        origin: "MXP",
        dates: { exact_start: null, exact_end: null, month: "2026-11", nights: 7 },
        travelers: [{ kind: "adult", age: null }],
        budget_eur: 12500,
      }),
    ).toBe("Da MXP, 1 adulto, 7 notti, budget 12.500 €");
  });

  it("never breaks on an odd row", () => {
    expect(requestSummary({})).toBeNull();
    expect(requestSummary(null)).toBeNull();
    expect(requestSummary({ origin: 3, travelers: "x", budget_eur: "2400" })).toBeNull();
  });
});

describe("travelersText", () => {
  it("counts adults and children, with the children's ages", () => {
    expect(travelersText([{ kind: "adult" }])).toBe("1 adulto");
    expect(travelersText([{ kind: "adult" }, { kind: "child", age: 0 }])).toBe("1 adulto e 1 bambino (meno di 1 anno)");
    expect(travelersText([{ kind: "adult" }, { kind: "child", age: 1 }])).toBe("1 adulto e 1 bambino (1 anno)");
    expect(travelersText([{ kind: "child", age: 3 }, { kind: "child", age: 5 }, { kind: "child", age: 9 }])).toBe(
      "3 bambini (3, 5 e 9 anni)",
    );
    expect(travelersText([{ kind: "adult" }, { kind: "child" }])).toBe("1 adulto e 1 bambino");
    expect(travelersText([])).toBeNull();
  });
});
