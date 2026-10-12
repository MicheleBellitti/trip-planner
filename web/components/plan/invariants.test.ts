/**
 * DESIGN.md's invariants over the finished plan's own sources (and its dev preview): amber is
 * drawn only by DatePair, no line colour is spent outside the agents' roundels, every new tab
 * carries rel="noopener noreferrer", and no em dash reaches the screen.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const planDir = path.dirname(fileURLToPath(import.meta.url));
const previewDir = path.resolve(planDir, "../../app/dev/plan");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return name === "__fixtures__" ? [] : sources(full);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [full] : [];
  });
}

const files = [...sources(planDir), ...sources(previewDir)];
const read = (file: string) => readFileSync(file, "utf8");

describe("finished plan invariants", () => {
  it("scans the plan's sources", () => {
    expect(files.map((file) => path.basename(file))).toEqual(
      expect.arrayContaining(["PlanView.tsx", "bookings.tsx", "itinerary.tsx", "plan-summary.tsx", "page.tsx"]),
    );
  });

  it("never draws amber itself (DatePair decides it)", () => {
    const amber = /\b(?:bg|text|border|ring|inset-ring|outline|fill|stroke|decoration|shadow)-amber|var\(--amber/;
    expect(files.filter((file) => amber.test(read(file))).map((file) => path.basename(file))).toEqual([]);
  });

  it("spends no line colour (only AgentRoundel draws one)", () => {
    const lineColour = /\b(?:bg|text|border|decoration|fill|stroke)-line(?:-[a-z]+)?\b/;
    expect(files.filter((file) => lineColour.test(read(file))).map((file) => path.basename(file))).toEqual([]);
  });

  it("opens every new tab with rel=noopener noreferrer", () => {
    for (const file of files) {
      const source = read(file);
      const blanks = source.match(/target="_blank"/g)?.length ?? 0;
      const guarded = source.match(/target="_blank"\s+rel="noopener noreferrer"/g)?.length ?? 0;
      expect(guarded, path.basename(file)).toBe(blanks);
    }
  });

  it("puts no em dash on screen", () => {
    expect(files.filter((file) => read(file).includes("—")).map((file) => path.basename(file))).toEqual([]);
  });
});
