import { describe, expect, it } from "vitest";

import { parseJoinInput, WAITLIST_NOTE_MAX, WAITLIST_SOURCES } from "./waitlist-policy";

describe("parseJoinInput", () => {
  it("normalizes the address, trims the note and keeps the source", () => {
    const result = parseJoinInput({ email: "  Friend@Example.COM ", note: "  Lisbona ad aprile\r\ncon i bambini  ", source: "landing" });
    expect(result).toEqual({ ok: true, value: { email: "friend@example.com", note: "Lisbona ad aprile\ncon i bambini", source: "landing" } });
  });

  it("refuses anything that is not an address", () => {
    for (const email of ["", "   ", "friend", "friend@", "@example.com", "a b@example.com", `${"x".repeat(250)}@e.it`, 12, null, undefined]) {
      expect(parseJoinInput({ email, source: "landing" })).toEqual({ ok: false, error: "invalid_email" });
    }
  });

  it("caps the note and strips control characters, keeping line breaks", () => {
    expect(parseJoinInput({ email: "a@b.co", note: "x".repeat(WAITLIST_NOTE_MAX + 1), source: "login" })).toEqual({ ok: false, error: "note_too_long" });
    const result = parseJoinInput({ email: "a@b.co", note: "riga\u0000 uno\u001b\nriga due\u007f", source: "login" });
    expect(result).toEqual({ ok: true, value: { email: "a@b.co", note: "riga uno\nriga due", source: "login" } });
    expect(parseJoinInput({ email: "a@b.co", note: 42, source: "admin" })).toMatchObject({ ok: true, value: { note: "" } });
  });

  it("knows only its three sources", () => {
    expect(WAITLIST_SOURCES).toEqual(["landing", "login", "admin"]);
    expect(parseJoinInput({ email: "a@b.co", source: "api" })).toEqual({ ok: false, error: "invalid_source" });
    expect(parseJoinInput({ email: "a@b.co" })).toEqual({ ok: false, error: "invalid_source" });
  });
});
