/**
 * Mechanical checks of DESIGN.md's invariants over the design system's own sources:
 * amber is drawn only by DatePair, buttons have no colour prop, no em dash reaches the screen, no
 * component reads the clock while rendering (Cache Components prerenders the routes), and a lane
 * that never started is not told "in attesa".
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { LANE_BADGE_LABELS, LANE_STATE_LABELS } from "@/lib/plan-events/labels";

const uiDir = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(uiDir, "../..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sources(full);
    return /\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [full] : [];
  });
}

const files = [...sources(uiDir), ...sources(path.join(webDir, "app/dev"))];
const componentFiles = sources(path.join(webDir, "components"));

/** A use of the amber tokens: a utility (bg-amber-wash, inset-ring-amber, text-amber-ink, ...) or
 * the variable itself. Comments that name the rule ("never amber") do not match. */
const AMBER_USE = /\b(?:bg|text|border|ring|inset-ring|outline|fill|stroke|decoration|shadow|from|via|to)-amber\b|var\(--amber/;

describe("design invariants", () => {
  it("scans the design system's sources", () => {
    expect(files.length).toBeGreaterThan(15);
  });

  it("draws amber only in DatePair (bookings due within 72 hours)", () => {
    const users = files.filter((file) => AMBER_USE.test(readFileSync(file, "utf8"))).map((file) => path.basename(file));
    expect(users).toEqual(["date-pair.tsx"]);
  });

  it("offers no way to colour a button", () => {
    const button = readFileSync(path.join(uiDir, "button.tsx"), "utf8");
    expect(button).toMatch(/export type ButtonVariant = "primary" \| "secondary" \| "quiet";/);
    expect(button).not.toMatch(AMBER_USE);
    expect(button).not.toMatch(/\bline-(?:coordinator|flights|lodging|activities|transport)\b/);
  });

  it("puts no em dash on screen", () => {
    const offenders = files.filter((file) => readFileSync(file, "utf8").includes("—")).map((file) => path.basename(file));
    expect(offenders).toEqual([]);
  });

  it("reads no clock while rendering: no Date.now() as an initial state, ref or memo", () => {
    // `useState(() => Date.now())` in a Client Component is a prerender error under Cache Components
    // (and would freeze the build's time into the shell). Read the clock in an effect or a callback,
    // or through lib/use-now.
    const IN_RENDER = /use(?:State|Ref|Memo)\(\s*(?:\(\)\s*=>\s*)?(?:Date\.now\(\)|new Date\(\))/;
    const offenders = componentFiles
      .filter((file) => IN_RENDER.test(readFileSync(file, "utf8")))
      .map((file) => path.relative(webDir, file));
    expect(offenders).toEqual([]);
  });

  it("links to the plans list through ROUTES, never a hand-written \"/\"", () => {
    // Step 2 of the brand spec gives "/" to the landing: every link to the list must move with ROUTES.
    const LITERAL_ROOT = /href=(?:"\/"|\{"\/"\})/;
    const offenders = [...sources(path.join(webDir, "components")), ...sources(path.join(webDir, "app"))]
      .filter((file) => LITERAL_ROOT.test(readFileSync(file, "utf8")))
      .map((file) => path.relative(webDir, file));
    expect(offenders).toEqual([]);
  });

  it("tells a lane that never started apart from one that waits", () => {
    expect(Object.keys(LANE_BADGE_LABELS).sort()).toEqual([...Object.keys(LANE_STATE_LABELS), "not_started"].sort());
    expect(LANE_BADGE_LABELS.not_started).not.toBe(LANE_BADGE_LABELS.waiting);
    const badge = readFileSync(path.join(uiDir, "status-badge.tsx"), "utf8");
    // The hourglass belongs to "in attesa" alone.
    expect(badge).toMatch(/waiting: "hourglass-medium"/);
    expect(badge).not.toMatch(/not_started: "hourglass/);
  });
});
