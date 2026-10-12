/**
 * DESIGN.md's invariants over the eval screens' own sources: no em dash and no middle dot on
 * screen, amber only in DatePair, no colour on a button, and no clock read while rendering.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const evalsDir = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(evalsDir, "../..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return name === "__fixtures__" ? [] : sources(full);
    return /\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [full] : [];
  });
}

const files = [...sources(evalsDir), ...sources(path.join(webDir, "app/evals"))];

describe("the eval screens' invariants", () => {
  it("scans the screens' sources", () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it("puts no em dash and no middle dot on screen", () => {
    // The middle dot is only the backend's title separator and "In scadenza · tra 2 giorni".
    const offenders = files.filter((file) => /[—·]/.test(readFileSync(file, "utf8"))).map((file) => path.basename(file));
    expect(offenders).toEqual([]);
  });

  it("never uses amber (it belongs to a booking due soon, in DatePair)", () => {
    const AMBER = /\b(?:bg|text|border|ring|inset-ring|outline|fill|stroke|decoration|shadow|from|via|to)-amber\b|var\(--amber/;
    expect(files.filter((file) => AMBER.test(readFileSync(file, "utf8")))).toEqual([]);
  });

  it("never colours with a line colour (one hue per agent, nothing else)", () => {
    const LINE = /\b(?:bg|text|border|ring|outline|fill|stroke)-line(?:-(?:coordinator|flights|lodging|activities|transport))?\b/;
    expect(files.filter((file) => LINE.test(readFileSync(file, "utf8")))).toEqual([]);
  });

  it("reads no clock while rendering", () => {
    const IN_RENDER = /use(?:State|Ref|Memo)\(\s*(?:\(\)\s*=>\s*)?(?:Date\.now\(\)|new Date\(\))/;
    expect(files.filter((file) => IN_RENDER.test(readFileSync(file, "utf8")))).toEqual([]);
  });
});
