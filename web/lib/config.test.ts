import { describe, expect, it } from "vitest";

import { parseAuthMode } from "./config";

describe("parseAuthMode", () => {
  it("reads the two modes and trims them", () => {
    expect(parseAuthMode("atlas", "production")).toBe("atlas");
    expect(parseAuthMode(" triptracker ", "production")).toBe("triptracker");
  });

  it("falls back to atlas under next dev and to TripTracker elsewhere", () => {
    expect(parseAuthMode(undefined, "development")).toBe("atlas");
    expect(parseAuthMode("", "development")).toBe("atlas");
    expect(parseAuthMode(undefined, "production")).toBe("triptracker");
    expect(parseAuthMode(undefined, "test")).toBe("triptracker");
  });

  it("refuses any other value instead of guessing", () => {
    expect(() => parseAuthMode("local", "production")).toThrow(/NEXT_PUBLIC_AUTH_MODE/);
    expect(() => parseAuthMode("Atlas", "production")).toThrow(/NEXT_PUBLIC_AUTH_MODE/);
  });
});
