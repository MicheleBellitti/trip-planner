/**
 * Mechanical checks of DESIGN.md's invariants over the design system's own sources:
 * amber is drawn only by DatePair, the green only by the eval history, buttons have no colour prop, no em dash reaches the screen, no
 * component reads the clock while rendering (Cache Components prerenders the routes), and a lane
 * that never started is not told "in attesa", the No AI Chrome Rule holds, the tagline is spelled once,
 * and no link spells the list's path by hand.
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

/** A use of the eval green (DESIGN.md, "The Green Means Passed Rule"): a utility or the variable. */
const SUCCESS_USE =
  /\b(?:bg|text|border|ring|inset-ring|outline|fill|stroke|decoration|shadow|from|via|to)-success(?:-wash)?\b|var\(--success/;

/** AI chrome (DESIGN.md, "The No AI Chrome Rule"): glow, spotlight gradients and gradient text, spelled
 * as raw CSS or as Tailwind utilities. The sticky bar's `backdrop-blur` is glass, checked apart. */
const CHROME =
  /drop-shadow|text-shadow|(?<!backdrop-)\bblur-|blur\(|\bbg-radial|\bbg-conic|radial-gradient|conic-gradient|bg-clip-text|background-clip:\s*text/;

describe("design invariants", () => {
  it("scans the design system's sources", () => {
    expect(files.length).toBeGreaterThan(15);
  });

  it("draws amber only in DatePair (bookings due within 72 hours)", () => {
    const users = files.filter((file) => AMBER_USE.test(readFileSync(file, "utf8"))).map((file) => path.basename(file));
    expect(users).toEqual(["date-pair.tsx"]);
  });

  it("draws the green only in the eval history (a passed run, check or score)", () => {
    expect(SUCCESS_USE.test('className="text-success"')).toBe(true);
    expect(SUCCESS_USE.test("bg-success-wash")).toBe(true);
    expect(SUCCESS_USE.test("// a success message")).toBe(false);
    const users = [...componentFiles, ...sources(path.join(webDir, "app"))]
      .filter((file) => !file.endsWith("globals.css") && SUCCESS_USE.test(readFileSync(file, "utf8")))
      .map((file) => path.relative(webDir, file));
    expect(users.length).toBeGreaterThan(0);
    expect(users.filter((file) => !file.startsWith("components/evals/"))).toEqual([]);
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

  it("spells no page path by hand: every link and navigation goes through lib/routes.ts", () => {
    const HAND_PATH = /(?:href=\{?|href:\s*|push\()\s*["'`]\/(?:new|evals|plans|demo)\b/;
    const offenders = [...sources(path.join(webDir, "components")), ...sources(path.join(webDir, "app"))]
      .filter((file) => HAND_PATH.test(readFileSync(file, "utf8")))
      .map((file) => path.relative(webDir, file));
    expect(offenders).toEqual([]);
  });

  it("recognises AI chrome in raw CSS and in Tailwind's own utilities, but not the sticky bar's glass", () => {
    for (const glow of [
      "filter: drop-shadow(0 0 4px red)",
      "filter: blur(8px)",
      "background: radial-gradient(circle, #fff, transparent)",
      "background: conic-gradient(red, blue)",
      "background-clip: text",
      'className="bg-clip-text"',
      'className="drop-shadow-lg"',
      'className="bg-radial from-ink"',
      'className="bg-conic/oklch"',
      'className="blur-2xl"',
      'className="text-shadow-lg"',
    ]) {
      expect(CHROME.test(glow), glow).toBe(true);
    }
    for (const allowed of ['className="backdrop-blur-[8px]"', 'className="lg:backdrop-blur-none"', "box-shadow: var(--elevation-pop)"]) {
      expect(CHROME.test(allowed), allowed).toBe(false);
    }
  });

  it("keeps the No AI Chrome Rule: no glow, spotlight or gradient text, and glass only on the sticky live bar", () => {
    const all = [...sources(path.join(webDir, "components")), ...sources(path.join(webDir, "app"))];
    const relative = (file: string) => path.relative(webDir, file);
    expect(all.filter((file) => CHROME.test(readFileSync(file, "utf8"))).map(relative)).toEqual([]);
    const GLASS = /backdrop-blur|backdrop-filter/;
    expect(all.filter((file) => GLASS.test(readFileSync(file, "utf8"))).map(relative).sort()).toEqual([
      "app/dev/ui/page.tsx",
      "components/live/agent-lanes.tsx",
      "components/live/live-header.tsx",
    ]);
  });

  it("spells the tagline only in lib/brand.ts", () => {
    const all = [
      ...sources(path.join(webDir, "components")),
      ...sources(path.join(webDir, "app")),
      ...sources(path.join(webDir, "lib")),
    ];
    const spellers = all
      .filter((file) => readFileSync(file, "utf8").includes("Ogni viaggio ha il suo atlante"))
      .map((file) => path.relative(webDir, file));
    expect(spellers).toEqual(["lib/brand.ts"]);
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
