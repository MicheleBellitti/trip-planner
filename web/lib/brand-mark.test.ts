import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { MARK_GEOMETRY, markDataUri, markSvg, NIGHT } from "./brand-mark";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

describe("markSvg", () => {
  it("draws the one geometry in the night colours by default", () => {
    const svg = markSvg();
    expect(svg).toContain(`d="${MARK_GEOMETRY.flights.d}"`);
    expect(svg).toContain(`stroke="${NIGHT.flights}"`);
    expect(svg).toContain(`stroke="${NIGHT.lodging}"`);
    expect(svg).toContain(`stroke="${NIGHT.coordinator}"`);
    expect(svg).toContain(`fill="${NIGHT.ground}" stroke="${NIGHT.ink}"`);
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true);
  });

  it("encodes it as a base64 data URI for next/og images", () => {
    const uri = markDataUri();
    expect(uri.startsWith("data:image/svg+xml;base64,")).toBe(true);
    expect(atob(uri.slice("data:image/svg+xml;base64,".length))).toBe(markSvg());
  });
});

describe("app/icon.svg", () => {
  it("uses only the night colours, so the tab icon matches the mark", () => {
    const icon = readFileSync(path.join(webDir, "app/icon.svg"), "utf8");
    const colours = new Set([...icon.matchAll(/#[0-9a-f]{6}/gi)].map((m) => m[0].toLowerCase()));
    const night = new Set<string>(Object.values(NIGHT));
    expect([...colours].filter((colour) => !night.has(colour))).toEqual([]);
  });
});
