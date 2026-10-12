import { describe, expect, it } from "vitest";

import { DUE_SOON_HOURS, dueDistance, isDueSoon } from "./due-soon";

const NOW = Date.parse("2026-10-12T10:00:00+02:00");
const HOUR = 3_600_000;

function at(offsetMs: number): string {
  return new Date(NOW + offsetMs).toISOString();
}

describe("isDueSoon (TripTracker's 72-hour rule)", () => {
  it("is 72 hours", () => {
    expect(DUE_SOON_HOURS).toBe(72);
  });

  it("is due soon up to and including 72 hours ahead", () => {
    expect(isDueSoon(at(HOUR), NOW)).toBe(true);
    expect(isDueSoon(at(72 * HOUR), NOW)).toBe(true);
  });

  it("is not due soon a moment after 72 hours", () => {
    expect(isDueSoon(at(72 * HOUR + 1000), NOW)).toBe(false);
    expect(isDueSoon(at(18 * 24 * HOUR), NOW)).toBe(false);
  });

  it("counts a past deadline as due soon, as TripTracker does", () => {
    expect(isDueSoon(at(-HOUR), NOW)).toBe(true);
  });

  it("reads the offset of the instant", () => {
    // 2026-10-14T23:59+02:00 is 61 h 59 min after NOW.
    expect(isDueSoon("2026-10-14T23:59:00+02:00", NOW)).toBe(true);
    expect(isDueSoon("2026-10-30T23:59:00+01:00", NOW)).toBe(false);
  });

  it("never treats an unreadable date as due", () => {
    expect(isDueSoon("not a date", NOW)).toBe(false);
  });
});

describe("dueDistance", () => {
  it.each([
    [-HOUR, "scadenza passata"],
    [30 * 60_000, "tra meno di un'ora"],
    [HOUR, "tra un'ora"],
    [7 * HOUR + 59 * 60_000, "tra 7 ore"],
    [24 * HOUR, "tra un giorno"],
    [61 * HOUR, "tra 2 giorni"],
    [18 * 24 * HOUR, "tra 18 giorni"],
  ])("%s ms ahead -> %s", (offset, text) => {
    expect(dueDistance(at(offset), NOW)).toBe(text);
  });

  it("is null for an unreadable date", () => {
    expect(dueDistance("soon", NOW)).toBeNull();
  });
});
