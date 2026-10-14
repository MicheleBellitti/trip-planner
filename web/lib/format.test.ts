import { describe, expect, it } from "vitest";

import { displayTitle, formatCreated, formatDateTime, formatElapsed, formatEur, formatRunningFor, formatUsd, HOME_TIMEZONE, splitDateRange } from "./format";

describe("formatCreated", () => {
  const now = Date.parse("2026-10-12T15:00:00Z");

  it("says today and yesterday on Michele's clock, then the day, and the year only when it is not this one", () => {
    expect(formatCreated("2026-10-12T15:36:00Z", now)).toBe("Oggi, 17:36");
    expect(formatCreated("2026-10-11T19:40:00Z", now)).toBe("Ieri, 21:40");
    expect(formatCreated("2026-10-08T10:00:00Z", now)).toBe("8 ott, 12:00");
    expect(formatCreated("2025-12-31T10:00:00Z", now)).toBe("31 dic 2025, 11:00");
  });

  it("keeps the time on older days, so two plans of one day are told apart", () => {
    expect(formatCreated("2026-10-08T07:05:00Z", now)).not.toBe(formatCreated("2026-10-08T19:40:00Z", now));
  });

  it("counts the day in Rome, not in UTC", () => {
    // 23:30 UTC on the 11th is already 01:30 on the 12th in Rome.
    expect(formatCreated("2026-10-11T23:30:00Z", now)).toBe("Oggi, 01:30");
  });

  it("returns what it cannot read", () => {
    expect(formatCreated("boh", now)).toBe("boh");
  });
});

describe("format", () => {
  it("formats US cents like the backend's format_usd", () => {
    expect(formatUsd(4820)).toBe("48,20 $");
    expect(formatUsd(5)).toBe("0,05 $");
    expect(formatUsd(0)).toBe("0,00 $");
    expect(formatUsd(123456)).toBe("1.234,56 $");
  });

  it("formats euro cents", () => {
    expect(formatEur(150000)).toBe("1.500,00 €");
  });

  it("formats elapsed time", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(65_000)).toBe("1:05");
    expect(formatElapsed(3_725_000)).toBe("1:02:05");
    expect(formatElapsed(-500)).toBe("0:00");
  });

  it("formats instants in the given time zone", () => {
    expect(formatDateTime("2026-10-12T13:00:00Z")).toMatch(/12 ott 2026.*15:00/);
    expect(formatDateTime("2026-11-14T07:05:00+01:00", "Europe/Lisbon")).toMatch(/14 nov 2026.*06:05/);
    expect(formatDateTime("not a date")).toBe("not a date");
  });

  it("says how long a plan has been running, in whole minutes", () => {
    expect(formatRunningFor(-5)).toBe("meno di 1 min");
    expect(formatRunningFor(59_000)).toBe("meno di 1 min");
    expect(formatRunningFor(3 * 60_000 + 59_000)).toBe("3 min");
    expect(formatRunningFor(60 * 60_000)).toBe("1 h");
    expect(formatRunningFor(65 * 60_000)).toBe("1 h 5 min");
  });

  it("writes a range of days with an en dash, wherever the title comes from", () => {
    expect(displayTitle("Lisbona in famiglia, 14-18 aprile 2027")).toBe("Lisbona in famiglia, 14–18 aprile 2027");
    expect(displayTitle("Lisbona, 14–18 apr")).toBe("Lisbona, 14–18 apr");
    expect(displayTitle("Aix-en-Provence, 3-5 mag")).toBe("Aix-en-Provence, 3–5 mag");
  });

  it("reads a booking deadline in Michele's zone", () => {
    expect(HOME_TIMEZONE).toBe("Europe/Rome");
    expect(formatDateTime("2027-02-26T20:00:00Z")).toBe("26 feb 2027, 21:00");
  });
});

describe("splitDateRange", () => {
  const joined = (title: string) => splitDateRange(title).map((part) => part.text).join("");

  it("cuts a title around its date range so the range can stay on one line", () => {
    expect(splitDateRange("Lisbona in famiglia, 14–18 aprile 2027")).toEqual([
      { text: "Lisbona in famiglia, ", nowrap: false },
      { text: "14–18 aprile", nowrap: true },
      { text: " 2027", nowrap: false },
    ]);
    expect(splitDateRange("Lisbona, 14–18 apr")).toEqual([
      { text: "Lisbona, ", nowrap: false },
      { text: "14–18 apr", nowrap: true },
    ]);
  });

  it("takes a range that crosses months whole", () => {
    expect(splitDateRange("Roma, 28 apr–2 mag").find((part) => part.nowrap)?.text).toBe("28 apr–2 mag");
  });

  it("leaves a title with no range alone, and never changes the words", () => {
    expect(splitDateRange("Un titolo solo mio")).toEqual([{ text: "Un titolo solo mio", nowrap: false }]);
    for (const title of ["Lisbona in famiglia, 14–18 aprile 2027", "Roma, 28 apr–2 mag", "Aix-en-Provence, 3–5 mag", "x"]) {
      expect(joined(title)).toBe(title);
    }
  });
});
