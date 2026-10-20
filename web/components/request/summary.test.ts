import { describe, expect, it } from "vitest";

import { emptyRequestForm, type RequestFormValues } from "@/lib/request-form";

import {
  budgetSummary,
  datesSummary,
  formatDayRange,
  formatWholeEuros,
  journeySummary,
  monthName,
  nightsBetween,
  travelersSummary,
} from "./summary";

function values(overrides: Partial<RequestFormValues> = {}): RequestFormValues {
  return { ...emptyRequestForm(), ...overrides };
}

describe("dates in words", () => {
  it("writes ranges with an en dash, never an em dash", () => {
    expect(formatDayRange("2027-04-14", "2027-04-18")).toBe("14–18 aprile 2027");
    expect(formatDayRange("2027-04-28", "2027-05-02")).toBe("28 aprile – 2 maggio 2027");
    expect(formatDayRange("2026-12-30", "2027-01-03")).toBe("30 dicembre 2026 – 3 gennaio 2027");
    expect(formatDayRange("2027-04-14", "2027-04-14")).toBe("14 aprile 2027");
    expect(formatDayRange("2027-04-18", "2027-04-14")).toBeNull();
    expect(formatDayRange("2027-02-30", "2027-03-02")).toBeNull();
    expect(formatDayRange("", "")).toBeNull();
  });

  it("counts nights", () => {
    expect(nightsBetween("2027-04-14", "2027-04-18")).toBe(4);
    expect(nightsBetween("2027-03-27", "2027-03-29")).toBe(2);
    expect(nightsBetween("2027-04-18", "2027-04-14")).toBeNull();
    expect(monthName("2027-04-14")).toBe("aprile");
    expect(monthName("nope")).toBe("");
  });

  it("summarises either date mode, or says nothing yet", () => {
    expect(datesSummary(values({ exactStart: "2027-04-14", exactEnd: "2027-04-18" }))).toBe("14–18 aprile 2027, 4 notti");
    expect(datesSummary(values({ exactStart: "2027-04-14", exactEnd: "2027-04-15" }))).toBe("14–15 aprile 2027, 1 notte");
    expect(datesSummary(values({ exactStart: "2027-04-14", exactEnd: "2027-04-14" }))).toBe("14 aprile 2027, in giornata");
    expect(datesSummary(values({ exactStart: "2027-04-14" }))).toBe("Dal 14 aprile 2027");
    expect(datesSummary(values())).toBeNull();
    expect(datesSummary(values({ dateMode: "flexible", month: "2026-11", nights: "7" }))).toBe("Novembre 2026, 7 notti");
    expect(datesSummary(values({ dateMode: "flexible", month: "2026-11" }))).toBe("Novembre 2026");
    expect(datesSummary(values({ dateMode: "flexible", nights: "1" }))).toBe("1 notte");
    expect(datesSummary(values({ dateMode: "flexible", month: "2026-13", nights: "x" }))).toBeNull();
  });
});

describe("the travel mode in words", () => {
  it("names the mode only when it is not the plane", () => {
    expect(journeySummary(values())).toBeNull();
    expect(journeySummary(values({ journeyMode: "train" }))).toBe("In treno");
    expect(journeySummary(values({ journeyMode: "ferry" }))).toBe("In traghetto");
    expect(journeySummary(values({ journeyMode: "car" }))).toBe("In auto");
    expect(journeySummary(values({ journeyMode: "coach" }))).toBe("In pullman");
  });
});

describe("travellers and budget in words", () => {
  it("names adults and children, with the ages once all are chosen", () => {
    expect(travelersSummary(values({ adults: 1 }))).toBe("1 adulto");
    expect(travelersSummary(values({ adults: 2, childAges: ["8", "11"] }))).toBe("2 adulti, 2 bambini di 8 e 11 anni");
    expect(travelersSummary(values({ adults: 2, childAges: ["3", "8", "11"] }))).toBe("2 adulti, 3 bambini di 3, 8 e 11 anni");
    expect(travelersSummary(values({ adults: 2, childAges: ["1"] }))).toBe("2 adulti, 1 bambino di 1 anno");
    expect(travelersSummary(values({ adults: 2, childAges: ["0"] }))).toBe("2 adulti, 1 bambino di meno di un anno");
    expect(travelersSummary(values({ adults: 2, childAges: ["0", "4"] }))).toBe("2 adulti, 2 bambini di meno di 1 e 4 anni");
    expect(travelersSummary(values({ adults: 2, childAges: ["8", ""] }))).toBe("2 adulti, 2 bambini");
  });

  it("shows the budget only when it is a whole positive amount", () => {
    expect(budgetSummary(values({ budgetEur: "2400" }))).toBe("2.400 €");
    expect(budgetSummary(values({ budgetEur: "2.400" }))).toBe("2.400 €");
    expect(budgetSummary(values({ budgetEur: "12000 €" }))).toBe("12.000 €");
    expect(budgetSummary(values({ budgetEur: "2400,50" }))).toBeNull();
    expect(budgetSummary(values({ budgetEur: "0" }))).toBeNull();
    expect(budgetSummary(values())).toBeNull();
    expect(formatWholeEuros(950)).toBe("950 €");
    expect(formatWholeEuros(1250000)).toBe("1.250.000 €");
  });
});
