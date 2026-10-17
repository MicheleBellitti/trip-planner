/**
 * The design tokens keep their promises: web/DESIGN.md (the authority) and app/globals.css (the
 * implementation) agree on every colour, dark is the default and follows no system preference,
 * and every pair DESIGN.md lists under "Measured contrast" still meets WCAG 2.x on its real
 * background.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { THEME_COLORS } from "./theme";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const css = readFileSync(path.join(webDir, "app/globals.css"), "utf8");
const design = readFileSync(path.join(webDir, "DESIGN.md"), "utf8");

type Tokens = Record<string, string>;

/** `--name: #rrggbb;` declarations of the first block that starts with `selector {`. */
function hexTokens(selector: string): Tokens {
  const start = css.indexOf(`${selector} {`);
  expect(start, `block ${selector}`).toBeGreaterThanOrEqual(0);
  const body = css.slice(start, css.indexOf("}", start));
  const tokens: Tokens = {};
  for (const match of body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6});/gi)) {
    tokens[match[1]!] = match[2]!.toLowerCase();
  }
  return tokens;
}

// Dark ("Carta notturna") is the default on :root; light ("Carta di giorno") only where pinned.
const DARK_BLOCK = ':root,\n[data-theme="dark"]';
const LIGHT_BLOCK = '\n[data-theme="light"]';
const dark = hexTokens(DARK_BLOCK);
const light = hexTokens(LIGHT_BLOCK);

/** A `--name: rgb(r g b / a);` declaration of a theme block, as its channels and alpha. */
function alphaToken(selector: string, name: string): { rgb: [number, number, number]; alpha: number } {
  const start = css.indexOf(`${selector} {`);
  const body = css.slice(start, css.indexOf("}", start));
  const match = body.match(new RegExp(`--${name}:\\s*rgb\\((\\d+) (\\d+) (\\d+) / ([\\d.]+)\\);`));
  expect(match, `--${name} in ${selector.trim()}`).toBeTruthy();
  const [, r, g, b, a] = match!;
  return { rgb: [Number(r), Number(g), Number(b)], alpha: Number(a) };
}

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map(channel) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function rgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** `fg` at `alpha` over `bg`, as the browser blends opacity and color-mix in sRGB: on 8-bit
 * channels, so the result is rounded (the unrounded blend overstated the plate's line by 0.02). */
function over(fg: string, bg: string, alpha: number): [number, number, number] {
  const f = rgb(fg);
  const b = rgb(bg);
  return [0, 1, 2].map((i) => Math.round(alpha * f[i]! + (1 - alpha) * b[i]!)) as [number, number, number];
}

function contrast(a: string | [number, number, number], b: string | [number, number, number]): number {
  const la = luminance(typeof a === "string" ? rgb(a) : a);
  const lb = luminance(typeof b === "string" ? rgb(b) : b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const LINES = ["line-coordinator", "line-flights", "line-lodging", "line-activities", "line-transport"];

/** [foreground, background, minimum]: the pairs of DESIGN.md "Measured contrast". */
const TEXT = 4.5;
const NON_TEXT = 3;
const PAIRS: [string, string, number][] = [
  ...["ground", "surface", "notice-wash", "error-wash", "success-wash", "amber-wash"].flatMap(
    (bg): [string, string, number][] => [
      ["ink", bg, TEXT],
      ["ink-2", bg, TEXT],
    ],
  ),
  ["error", "surface", TEXT],
  ["error", "ground", TEXT],
  ["error", "error-wash", TEXT],
  ["success", "surface", TEXT],
  ["success", "ground", TEXT],
  ["success", "success-wash", TEXT],
  ...LINES.flatMap((line): [string, string, number][] => [
    ["on-line", line, TEXT],
    [line, "surface", NON_TEXT],
    [line, "ground", NON_TEXT],
  ]),
  ["amber-ink", "amber-wash", TEXT],
  ["amber-ink", "surface", TEXT],
  ["amber", "surface", NON_TEXT],
  ["amber", "amber-wash", NON_TEXT],
  ["on-action", "action", TEXT],
  ["rule-strong", "ground", NON_TEXT],
  ["rule-strong", "surface", NON_TEXT],
  ["focus", "ground", NON_TEXT],
  ["focus", "surface", NON_TEXT],
];

describe("design tokens", () => {
  it("reads both themes from globals.css", () => {
    expect(Object.keys(light).length).toBeGreaterThanOrEqual(21);
    expect(Object.keys(dark)).toEqual(Object.keys(light));
  });

  it("is dark by default: no block follows the system preference", () => {
    expect(css).not.toMatch(/prefers-color-scheme/);
  });

  it("keeps the browser chrome's colour on each theme's ground", () => {
    expect(THEME_COLORS.dark).toBe(dark.ground);
    expect(THEME_COLORS.light).toBe(light.ground);
  });

  it("matches the colours of DESIGN.md's frontmatter, the authority", () => {
    const frontmatter = design.split("\n---\n")[0]!;
    const documented: Tokens = {};
    for (const match of frontmatter.matchAll(/^ {2}([a-z0-9-]+): "(#[0-9A-Fa-f]{6})"$/gm)) {
      documented[match[1]!] = match[2]!.toLowerCase();
    }
    const implemented: Tokens = {};
    for (const [name, value] of Object.entries(light)) implemented[name] = value;
    for (const [name, value] of Object.entries(dark)) implemented[`${name}-dark`] = value;
    expect(implemented).toEqual(documented);
  });

  for (const [theme, tokens, block] of [
    ["light", light, LIGHT_BLOCK],
    ["dark", dark, DARK_BLOCK],
  ] as const) {
    describe(`${theme} theme contrast`, () => {
      it("keeps selected text readable: ink on the selection over ground and surface", () => {
        // The scrim has no pair: it is non-text under a sheet, and over a cover photo the contrast
        // depends on the photo, which no token can promise.
        const selection = alphaToken(block, "selection");
        for (const bg of ["ground", "surface"]) {
          const back = rgb(tokens[bg]!);
          const blend = [0, 1, 2].map((i) =>
            Math.round(selection.alpha * selection.rgb[i]! + (1 - selection.alpha) * back[i]!),
          ) as [number, number, number];
          expect(contrast(tokens.ink!, blend), `ink on selection over ${bg}`).toBeGreaterThanOrEqual(TEXT);
        }
      });

      it.each(PAIRS)("%s on %s is at least %s:1", (fg, bg, minimum) => {
        expect(tokens[fg], fg).toBeDefined();
        expect(tokens[bg], bg).toBeDefined();
        expect(contrast(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(minimum);
      });

      it("keeps the plate's 92 % time line readable on every line colour", () => {
        for (const line of LINES) {
          expect(contrast(over(tokens["on-line"]!, tokens[line]!, 0.92), tokens[line]!)).toBeGreaterThanOrEqual(TEXT);
        }
      });

      it("keeps the primary button's hover readable", () => {
        const hover = over(tokens.action!, tokens.ground!, 0.86);
        expect(contrast(tokens["on-action"]!, hover)).toBeGreaterThanOrEqual(TEXT);
      });
    });
  }
});
