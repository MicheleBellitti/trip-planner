# Atlas brand system (step 1 of 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Atlas its brand: the "Carta notturna" palette (dark by default, "Carta di giorno" light on the toggle), paper grain, the "A di linee" mark and lockup, icons and the link preview, the tagline, one app header with the current page drawn as a station, and the No AI Chrome Rule as a test.

**Architecture:** Tokens keep their names and change their values in `web/app/globals.css`. The dark block moves onto `:root`, and light applies only where `data-theme="light"` pins it. The mark is one geometry (`web/lib/brand-mark.ts`) drawn two ways:
- by `<Mark>` with Tailwind token utilities, so it follows the theme;
- by the icon and Open Graph routes with fixed colours.

`AppHeader` replaces `SiteHeader` and `TopBar`. Every link to the plans list reads `ROUTES.plans` (`web/lib/routes.ts`), so step 2 moves the list by changing one constant.

**Tech Stack:** Next.js 16.4 (App Router, `next/og`, metadata file conventions), React 19.3, TypeScript strict, Tailwind 4 (CSS-first `@theme`), Vitest + Testing Library (jsdom).

**Spec:** `docs/superpowers/specs/2026-10-14-atlas-brand-design.md` (sections 1, 3 and 8, step 1). Read it before starting.

## Global Constraints

- Work in `web/` on branch `feat/atlas-brand`. Run every npm command from `web/`.
- Before writing Next-specific code, read the matching guide in `web/node_modules/next/dist/docs/` (`web/AGENTS.md`: this Next has breaking changes).
- No new runtime dependency: `web/package.json` `dependencies` stay `maplibre-gl`, `next`, `react`, `react-dom`, `zod`.
- No backend, TripTracker, auth or plan-contract change.
- Code, comments and identifiers are English. Everything on screen is Italian in sentence case, with no em dash (`—`).
- The product name is spelled only in `BRAND_NAME`, and the tagline only in `BRAND_TAGLINE` (`web/lib/brand.ts`).
- `web/DESIGN.md`'s frontmatter colours and `web/app/globals.css` change together. `components/ui/tokens.test.ts` enforces both and every contrast pair: text ≥ 4.5, non-text ≥ 3.
- Amber is drawn only by `DatePair`, and buttons are never coloured. `components/ui/invariants.test.ts` already enforces both.
- Dark is the default. Light applies only under `data-theme="light"`. `prefers-color-scheme` appears nowhere in `globals.css`.
- **No AI Chrome Rule:**
  - no `drop-shadow`, `blur(`, `radial-gradient`, `conic-gradient`, `bg-clip-text` or `background-clip: text` anywhere
  - `backdrop-blur` / `backdrop-filter` only in `components/live/live-header.tsx`, `components/live/agent-lanes.tsx` and `app/dev/ui/page.tsx`
- Every new animation or transition declares its reduced-motion behaviour. This step adds none beyond colour transitions.
- `/plans/[id]` first-load JS stays ≤ 189.1 KB gzip (`NEXT_DIST_DIR=.next-build npm run build && NEXT_DIST_DIR=.next-build npm run measure:js`).
- Every changed screen is checked in the browser at 393 px and at desktop width, in dark and in light. Before merge, the impeccable critique must reach ≥ 32/40 with no open P0 or P1 (CLAUDE.md, "UI rules").
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Deviations from the spec, decided here:**
- `favicon.ico` is not regenerated: no rasterizer is available without a new dependency. Next's default `app/favicon.ico` is deleted, and `app/icon.svg` plus the generated `apple-icon` replace it.
- The motion rule ("The Motion Tells Something Rule") and its PRODUCT.md principle change in step 4, together with the code they describe. This step's docs change only what this step ships.

## Review Focus

1. **A browser that pinned `atlas-theme = "light"` before this change stays light**, a browser with nothing stored now opens dark, and a pinned `"dark"` stays dark. Test: Task 1, `theme-toggle.test.tsx`.
2. **Storage blocked** (Safari private mode, cookies off): the page renders dark, and the toggle still switches for the session without throwing. Test: Task 1, `theme-toggle.test.tsx`.
3. **The header at 393 px** stays on one line, at most 72 px tall, with no horizontal scroll and every target at least 44 px, on `/`, `/new`, `/evals` and a plan. Test: Task 4, browser measurement step.
4. **A due-soon booking on the cream light theme** still reads as due soon: the amber stroke is visible, "In scadenza" is shown, and the wash alone never carries it. Test: Task 1 pins the amber stroke at ≥ 3:1 on `amber-wash` and on `surface`; Task 6 checks it in the browser on `/dev/ui`.
5. **The mark inside a subtree pinned to the other theme** (the `/dev/ui` gallery's ThemePair, any future light card) takes that subtree's colours, because it uses only token utilities and no hex. Test: Task 2, `mark.test.tsx`; Task 6 checks the gallery.

---

### Task 1: Carta notturna palette, dark by default, paper grain, hero type

**Files:**
- Modify: `web/components/ui/tokens.test.ts`
- Create: `web/components/ui/theme-toggle.test.tsx`
- Modify: `web/components/ui/theme.ts`
- Modify: `web/components/ui/theme-toggle.tsx`
- Modify: `web/app/globals.css`
- Modify: `web/app/layout.tsx`
- Modify: `web/DESIGN.md` (frontmatter `description`, `colors`, `typography`; "Colors"; "Measured contrast"; "Elevation & Depth"; "Typography")

**Interfaces:**
- Produces, in `web/components/ui/theme.ts`:
  - `DEFAULT_THEME: ThemeName` (`"dark"`)
  - `THEME_COLORS: Record<ThemeName, string>` (`{ dark: "#1b2230", light: "#f4efe4" }`)
  - `THEME_STORAGE_KEY`, `ThemeName`, `isThemeName` and `THEME_BOOTSTRAP` unchanged
- Produces these CSS tokens and utilities:
  - `--grain`
  - Tailwind `font-hero`, `text-hero`, `lg:text-hero-lg`, `font-bold`
  - CSS variable `--font-barlow-semi-condensed-bold`

- [ ] **Step 1: Point the token test at the new theme blocks and add the default-theme checks**

In `web/components/ui/tokens.test.ts`:

Add the import after the vitest import:

```ts
import { THEME_COLORS } from "./theme";
```

Replace the three block readers:

```ts
const light = hexTokens(':root,\n[data-theme="light"]');
const systemDark = hexTokens('  :root:not([data-theme="light"])');
const dark = hexTokens('\n[data-theme="dark"]');
```

with:

```ts
// Dark ("Carta notturna") is the default on :root; light ("Carta di giorno") only where pinned.
const dark = hexTokens(':root,\n[data-theme="dark"]');
const light = hexTokens('\n[data-theme="light"]');
```

Replace the test `"keeps the system-dark block identical to the pinned-dark block"` with:

```ts
  it("is dark by default: no block follows the system preference", () => {
    expect(css).not.toMatch(/prefers-color-scheme/);
  });

  it("keeps the browser chrome's colour on each theme's ground", () => {
    expect(THEME_COLORS.dark).toBe(dark.ground);
    expect(THEME_COLORS.light).toBe(light.ground);
  });
```

Update the file's top comment: replace "the system-dark and pinned-dark blocks are identical," with "dark is the default and follows no system preference,".

- [ ] **Step 2: Write the theme toggle tests**

Create `web/components/ui/theme-toggle.test.tsx`:

```tsx
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { THEME_STORAGE_KEY } from "./theme";
import { ThemeToggle } from "./theme-toggle";

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  document.head.querySelector('meta[name="theme-color"]')?.remove();
  try {
    localStorage.clear();
  } catch {
    // A test blocked storage on purpose.
  }
});

function themeColorMeta(content: string): HTMLMetaElement {
  const meta = document.createElement("meta");
  meta.name = "theme-color";
  meta.content = content;
  document.head.append(meta);
  return meta;
}

describe("ThemeToggle", () => {
  it("treats a page with nothing pinned as dark, the default", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Passa al tema chiaro" })).toBeTruthy();
  });

  it("keeps a light theme that was pinned before dark became the default", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(<ThemeToggle />);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(screen.getByRole("button", { name: "Passa al tema scuro" })).toBeTruthy();
  });

  it("keeps a pinned dark theme dark", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Passa al tema chiaro" })).toBeTruthy();
  });

  it("pins light from the default, remembers it and repaints the browser chrome", () => {
    const meta = themeColorMeta("#1b2230");
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Passa al tema chiaro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(meta.content).toBe("#f4efe4");
    expect(screen.getByRole("button", { name: "Passa al tema scuro" })).toBeTruthy();
  });

  it("still switches for the session when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Passa al tema chiaro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
```

- [ ] **Step 3: Run the two test files and watch them fail**

Run: `npx vitest run components/ui/tokens.test.ts components/ui/theme-toggle.test.tsx`

Expected: FAIL.
- `tokens.test.ts`: `block :root,\n[data-theme="dark"]` is not found, and `THEME_COLORS` is undefined.
- `theme-toggle.test.tsx`: `window.matchMedia is not a function`, because today's toggle reads the system preference.

- [ ] **Step 4: Add the default theme and the browser-chrome colours to `theme.ts`**

Replace the top of `web/components/ui/theme.ts`, up to and including `isThemeName`, with:

```ts
/** The pinned theme. Absent means dark, the default ("Carta notturna", DESIGN.md "Colors"): the
 * system preference no longer decides. The toggle pins the other theme and stores it here; the
 * inline script in ./theme-script.tsx applies it before the first paint. */
export const THEME_STORAGE_KEY = "atlas-theme";

export type ThemeName = "light" | "dark";

/** The theme when nothing is pinned. */
export const DEFAULT_THEME: ThemeName = "dark";

/** The browser chrome's colour (<meta name="theme-color">) for each theme: its ground token.
 * tokens.test.ts keeps them equal to globals.css. */
export const THEME_COLORS: Record<ThemeName, string> = { dark: "#1b2230", light: "#f4efe4" };

export function isThemeName(value: unknown): value is ThemeName {
  return value === "light" || value === "dark";
}
```

Leave `THEME_BOOTSTRAP` unchanged.

- [ ] **Step 5: Make the toggle default to dark and repaint the browser chrome**

In `web/components/ui/theme-toggle.tsx`:

Change the import from `./theme` to:

```ts
import { DEFAULT_THEME, isThemeName, THEME_COLORS, THEME_STORAGE_KEY, type ThemeName } from "./theme";
```

Delete `const DARK_QUERY = "(prefers-color-scheme: dark)";`.

Replace `resolvedTheme` and `subscribe` with:

```ts
/** The theme on screen: the pinned one, else the dark default. */
function resolvedTheme(): ThemeName {
  const pinned = document.documentElement.getAttribute("data-theme");
  return isThemeName(pinned) ? pinned : DEFAULT_THEME;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(THEME_EVENT, onChange);
  return () => window.removeEventListener(THEME_EVENT, onChange);
}

/** The browser chrome (iOS status bar, Android toolbar) follows the theme on screen. */
function syncThemeColor(theme: ThemeName) {
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[theme]);
}
```

In the `useLayoutEffect`, add `syncThemeColor(resolvedTheme());` as its last line, after the `if` block.

In `toggle()`, add `syncThemeColor(next);` right after `document.documentElement.setAttribute("data-theme", next);`.

Update the component's doc comment: replace "pins the opposite of the theme on screen" with "pins the other theme (dark is the default)".

- [ ] **Step 6: Rewrite the token blocks of `globals.css`**

In `web/app/globals.css`, replace everything from the file's first line through the end of the `[data-theme] { … }` block with:

```css
/*
 * Atlas design tokens, "Carta notturna" (direction 1 "Linee", restyled on 2026-10-14; web/DESIGN.md
 * is the authority: change a value there and here together). Two layers:
 *
 * 1. Raw tokens (--ground, --ink, --line-flights, ...) per theme. Dark ("Carta notturna") is the
 *    default on :root; light ("Carta di giorno") applies only where data-theme="light" pins it
 *    (the theme toggle on <html>, see components/ui/theme-script.tsx; a subtree in /dev/ui). The
 *    system preference does not decide.
 * 2. `@theme inline` maps them to Tailwind utilities (bg-ground, text-ink-2, border-rule-strong,
 *    bg-line-flights, shadow-plate, ...). `inline` makes each utility read the raw variable on
 *    the element itself, so a [data-theme] subtree (the /dev/ui gallery) themes correctly.
 *
 * Tailwind's default palette, radii, type sizes and breakpoints are reset: only these tokens
 * exist, so an off-system value cannot be typed by accident.
 */
@import "tailwindcss";

/* ---------------------------------------------------------------------------------------------
   Raw tokens: dark by default and wherever data-theme="dark" pins it; light where
   data-theme="light" pins it. Order matters: the light block comes last, so a pinned <html>
   wins over :root.
--------------------------------------------------------------------------------------------- */
:root,
[data-theme="dark"] {
  --ground: #1b2230;
  --surface: #222a39;
  --ink: #efe8d8;
  --ink-2: #aaa596;
  --rule: #313a4a;
  --rule-strong: #6b7384;
  --line-coordinator: #a3abb6;
  --line-flights: #6e8fe0;
  --line-lodging: #4fa77b;
  --line-activities: #9c84d6;
  --line-transport: #4aa8b6;
  --on-line: #1b2230;
  --error: #f2766b;
  --error-wash: #36211f;
  --notice-wash: #283141;
  /* Reserved: only a booking whose dueAt is within 72 hours (DatePair). Never on a button. */
  --amber: #f3a845;
  --amber-ink: #f3a845;
  --amber-wash: #33291a;
  --action: #efe8d8;
  --on-action: #1b2230;
  --focus: #efe8d8;
  --selection: rgb(110 143 224 / 0.3);
  --scrim: rgb(3 6 10 / 0.62);
  --elevation-plate: 0 1px 2px rgb(0 0 0 / 0.4), 0 10px 28px -14px rgb(0 0 0 / 0.7);
  --elevation-pop: 0 1px 2px rgb(0 0 0 / 0.45), 0 18px 36px -16px rgb(0 0 0 / 0.75);
  /* Paper grain (DESIGN.md, "Colors"): one still feTurbulence tile, cream specks at 6 %. */
  --grain: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 .94 0 0 0 0 .91 0 0 0 0 .85 0 0 0 .06 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  /* Inherited switches for theme-dependent glyphs (the theme toggle's moon and sun). */
  --show-in-light: none;
  --show-in-dark: inline-block;
  color-scheme: dark;
}

[data-theme="light"] {
  --ground: #f4efe4;
  --surface: #fbf8f1;
  --ink: #1b2230;
  --ink-2: #5b5e66;
  --rule: #ddd5c5;
  --rule-strong: #8a8473;
  --line-coordinator: #33404f;
  --line-flights: #1f55c4;
  --line-lodging: #0f7348;
  --line-activities: #6d3fc0;
  --line-transport: #08707f;
  --on-line: #fbf8f1;
  --error: #b3261e;
  --error-wash: #f8e3df;
  --notice-wash: #ebe5d8;
  --amber: #a86400;
  --amber-ink: #8a4a00;
  --amber-wash: #f6dca8;
  --action: #1b2230;
  --on-action: #fbf8f1;
  --focus: #1b2230;
  --selection: rgb(31 85 196 / 0.18);
  --scrim: rgb(27 34 48 / 0.4);
  --elevation-plate: 0 1px 2px rgb(27 34 48 / 0.06), 0 10px 28px -14px rgb(27 34 48 / 0.22);
  --elevation-pop: 0 1px 2px rgb(27 34 48 / 0.08), 0 16px 32px -18px rgb(27 34 48 / 0.32);
  /* Ink specks at 5 %. */
  --grain: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 .11 0 0 0 0 .13 0 0 0 0 .19 0 0 0 .05 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  --show-in-light: inline-block;
  --show-in-dark: none;
  color-scheme: light;
}

/* A subtree themed by data-theme repaints its own ground, grain and text. */
[data-theme] {
  background-color: var(--ground);
  background-image: var(--grain);
  color: var(--ink);
}
```

Keep the light block's token order exactly the same as the dark block's: the test compares the two key lists.

- [ ] **Step 7: Make the `dark:` variant follow the dark default**

Replace the whole `@custom-variant dark { … }` block, and the comment above it, with:

```css
/* `dark:` follows the resolved theme of the nearest scope: a pinned data-theme, else the dark
   default. Prefer tokens (they switch by themselves); use dark: only for glyph swaps. */
@custom-variant dark {
  &:where([data-theme="dark"], [data-theme="dark"] *):not(
      :where([data-theme="dark"] [data-theme="light"], [data-theme="dark"] [data-theme="light"] *)
    ) {
    @slot;
  }
  &:where(:root:not([data-theme="light"]), :root:not([data-theme="light"]) *):not(
      :where([data-theme="light"], [data-theme="light"] *)
    ) {
    @slot;
  }
}
```

- [ ] **Step 8: Add the hero face and size, and the grain on the page**

In the `@theme inline` block, after the `--font-cond: …;` line, add:

```css
  --font-hero: var(--font-barlow-semi-condensed-bold), var(--font-barlow-semi-condensed), var(--font-barlow), ui-sans-serif, system-ui, sans-serif;
```

In the `@theme` block, after the `--text-display-xl--line-height: 1.12;` line, add:

```css
  --text-hero: 2.75rem; /* 44px phone, 66px from lg, Semi Condensed 700: landing and demo headings only */
  --text-hero--line-height: 1;
  --text-hero-lg: 4.125rem;
  --text-hero-lg--line-height: 0.98;
```

After `--font-weight-semibold: 600;`, add:

```css
  --font-weight-bold: 700; /* the hero heading only */
```

In `@layer base`, inside `html { … }`, add right after `background-color: var(--ground);`:

```css
    background-image: var(--grain);
```

- [ ] **Step 9: Load the hero face lazily and paint the chrome dark in `layout.tsx`**

In `web/app/layout.tsx`:

Add `THEME_COLORS` and `DEFAULT_THEME` to the imports:

```ts
import { DEFAULT_THEME, THEME_COLORS } from "@/components/ui/theme";
```

After the `barlowSemiCondensed` declaration, add:

```ts
/** Hero face: Barlow Semi Condensed 700, for the landing and demo headings only (`font-hero`). Not
 * preloaded: the file loads only on the pages that use it, so the others pay nothing. */
const barlowSemiCondensedBold = Barlow_Semi_Condensed({
  subsets: ["latin"],
  weight: ["700"],
  display: "swap",
  preload: false,
  variable: "--font-barlow-semi-condensed-bold",
});
```

Replace `viewport` with:

```ts
/** The browser chrome starts on the dark default's ground; ThemeToggle repaints it when light is
 * pinned (components/ui/theme-toggle.tsx). */
export const viewport: Viewport = {
  themeColor: THEME_COLORS[DEFAULT_THEME],
  colorScheme: "dark light",
  viewportFit: "cover",
};
```

Add the new variable to `<html className>`:

```tsx
    <html
      lang="it"
      className={`${barlow.variable} ${barlowSemiCondensed.variable} ${barlowSemiCondensedBold.variable}`}
      suppressHydrationWarning
    >
```

- [ ] **Step 10: Update DESIGN.md's frontmatter**

In `web/DESIGN.md`, set the frontmatter `description:` to:

```yaml
description: A printed night transit map, one line per agent, ink and cream, never neon.
```

Replace the whole `colors:` block with the one below. The plain keys are "Carta di giorno" (light) and the `-dark` keys are "Carta notturna", the default.

```yaml
colors:
  ground: "#F4EFE4"
  surface: "#FBF8F1"
  ink: "#1B2230"
  ink-2: "#5B5E66"
  rule: "#DDD5C5"
  rule-strong: "#8A8473"
  line-coordinator: "#33404F"
  line-flights: "#1F55C4"
  line-lodging: "#0F7348"
  line-activities: "#6D3FC0"
  line-transport: "#08707F"
  on-line: "#FBF8F1"
  error: "#B3261E"
  error-wash: "#F8E3DF"
  notice-wash: "#EBE5D8"
  amber: "#A86400"
  amber-ink: "#8A4A00"
  amber-wash: "#F6DCA8"
  action: "#1B2230"
  on-action: "#FBF8F1"
  focus: "#1B2230"
  ground-dark: "#1B2230"
  surface-dark: "#222A39"
  ink-dark: "#EFE8D8"
  ink-2-dark: "#AAA596"
  rule-dark: "#313A4A"
  rule-strong-dark: "#6B7384"
  line-coordinator-dark: "#A3ABB6"
  line-flights-dark: "#6E8FE0"
  line-lodging-dark: "#4FA77B"
  line-activities-dark: "#9C84D6"
  line-transport-dark: "#4AA8B6"
  on-line-dark: "#1B2230"
  error-dark: "#F2766B"
  error-wash-dark: "#36211F"
  notice-wash-dark: "#283141"
  amber-dark: "#F3A845"
  amber-ink-dark: "#F3A845"
  amber-wash-dark: "#33291A"
  action-dark: "#EFE8D8"
  on-action-dark: "#1B2230"
  focus-dark: "#EFE8D8"
```

Under `typography:`, add this before `headline:`:

```yaml
  hero:
    fontFamily: "Barlow Semi Condensed, Barlow, system-ui, sans-serif"
    fontSize: "44px"
    fontWeight: 700
    lineHeight: 1
```

- [ ] **Step 11: Update DESIGN.md's colour, elevation and typography prose**

**Under "## Colors"**, replace the first paragraph ("A cool neutral ground with ink for text and actions, … pins either one on `<html data-theme>`.") with:

```markdown
"Carta notturna": a flat ink ground with a paper grain, cream text, five matte line inks for the
agents, one red for failures and one amber that belongs to deadlines alone. Values are the
frontmatter's: the plain keys are "Carta di giorno" (light), the `-dark` keys "Carta notturna".
**Dark is the default** everywhere. The system preference does not decide, and the toggle pins
light (or dark again) on `<html data-theme>`.
```

**Under "### Primary"**, replace the sentence "In dark the ink is the near-white `ink-dark` and primary buttons invert to a light pill with dark text." with:

```markdown
In dark, the default, the ink is the cream `ink-dark` and primary buttons are a cream pill with
ink text. In light they are an ink pill with cream text.
```

**Under "### Neutral"**, replace the "**Browser surfaces**" bullet with the two bullets below:

```markdown
- **Browser surfaces**: selection is `rgb(31 85 196 / .18)` light and `rgb(110 143 224 / .3)` dark;
  the scrollbar is `rule-strong` on transparent; the caret is ink; the scrim under a sheet is
  `rgb(27 34 48 / .4)` light and `rgb(3 6 10 / .62)` dark; `<meta name="theme-color">` is each
  theme's ground (`THEME_COLORS`, repainted by the toggle).
- **Paper grain** (`--grain`): one still `feTurbulence` tile on the page ground (`html` and any
  `[data-theme]` subtree), cream specks at 6 % on dark, ink specks at 5 % on light. It is the one
  texture in the product: never animated, never on surfaces, inputs or plates.
```

**Under "### Measured contrast"**, replace the date sentence's "(2026-10-12;" with "(2026-10-14;". Then replace the table, and the "Decorative only" paragraph under it, with:

```markdown
| Pair | Light | Dark | Needs |
| --- | --- | --- | --- |
| ink on ground / surface | 13.89 / 15.02 | 13.05 / 11.80 | 4.5 |
| ink on notice-wash / error-wash / amber-wash | 12.69 / 12.93 / 11.93 | 10.71 / 12.34 / 11.68 | 4.5 |
| ink-2 on ground / surface | 5.66 / 6.12 | 6.47 / 5.85 | 4.5 |
| ink-2 on notice-wash / error-wash / amber-wash | 5.17 / 5.26 / 4.86 | 5.31 / 6.12 / 5.79 | 4.5 |
| error on surface / ground / error-wash | 6.16 / 5.70 / 5.31 | 5.20 / 5.75 / 5.44 | 4.5 |
| on-line on coordinatore / voli / alloggio / attività / spostamenti | 9.96 / 6.28 / 5.55 / 6.34 / 5.45 | 6.87 / 5.06 / 5.42 / 5.07 / 5.74 | 4.5 |
| on-line at 92 % on the plate (worst) | 4.87 (spostamenti) | 4.51 (voli) | 4.5 |
| line strokes on surface (worst) | 5.45 (spostamenti) | 4.57 (voli) | 3 |
| line strokes on ground (worst) | 5.04 (spostamenti) | 5.06 (voli) | 3 |
| amber-ink on amber-wash / surface | 5.14 / 6.47 | 7.13 / 7.20 | 4.5 |
| amber stroke on surface / amber-wash | 4.41 / 3.50 | 7.20 / 7.13 | 3 |
| on-action on action (primary button) / its hover | 15.02 / 10.01 | 13.05 / 9.98 | 4.5 |
| rule-strong on ground / surface (control borders) | 3.25 / 3.52 | 3.35 / 3.02 | 3 |
| focus ring (ink) on ground / surface | 13.89 / 15.02 | 13.05 / 11.80 | 3 |

Decorative only (no minimum, never the sole carrier of meaning): `rule` on surface 1.38 / 1.26,
surface against ground 1.08 / 1.11, the error notice's 55 % edge on error-wash 2.49 / 2.64,
`rule-strong` as the dashed edge of a warning on notice-wash 2.97 / 2.75 (the glyph and the
sentence carry it). On the cream light ground `amber-wash` is only 1.16:1 from `ground`: a due
deadline is carried by the amber stroke (4.41 on surface) and the words "In scadenza", never by the
wash alone.
```

**Under "## Elevation & Depth"**, in the two bullets, replace the light values:
- `0 1px 2px rgb(15 26 42 / .06), 0 10px 28px -14px rgb(15 26 42 / .22)` becomes `0 1px 2px rgb(27 34 48 / .06), 0 10px 28px -14px rgb(27 34 48 / .22)`.
- `0 1px 2px rgb(15 26 42 / .08), 0 16px 32px -18px rgb(15 26 42 / .32)` becomes `0 1px 2px rgb(27 34 48 / .08), 0 16px 32px -18px rgb(27 34 48 / .32)`.

**Under "## Typography"**:
- After the "**Body Font:**" line, add: `**Hero Font:** Barlow Semi Condensed 700, the landing and demo headings only (`font-hero`).`
- In the paragraph that starts "Both are self-hosted", append: `Barlow Semi Condensed 700 is a separate, non-preloaded face: its file loads only on the pages that use `font-hero`.`
- In the "### Hierarchy" table, add this row first:

```markdown
| Hero | `font-hero font-bold text-hero`, `lg:text-hero-lg` | Semi Condensed 700 | 44 / 1.0, 66 / 0.98 from 1080 px | the landing and demo headings only |
```

- [ ] **Step 12: Run the tests**

Run: `npx vitest run components/ui/tokens.test.ts components/ui/theme-toggle.test.tsx`
Expected: PASS, with every contrast pair green in both themes.

Run: `npm test`
Expected: PASS. If a test relied on `matchMedia` through `ThemeToggle`, it already mocks the toggle; nothing else reads the system theme.

- [ ] **Step 13: Look at it**

Start both servers (`.claude/launch.json`): `preview_start {name: "backend-demo"}` and `preview_start {name: "web-dev"}`. Open `http://localhost:3000/` at 1280 × 820 and at 393 × 812.
- The page must be dark with no theme pinned, with the grain faint but present.
- Toggle to light: the cream paper must appear, and the moon and sun glyphs must swap.
- Clear `localStorage` in the tab and reload: the page must be dark again.

Take one screenshot per theme for the record.

- [ ] **Step 14: Commit**

```bash
git add web/app/globals.css web/app/layout.tsx web/components/ui/theme.ts web/components/ui/theme-toggle.tsx web/components/ui/theme-toggle.test.tsx web/components/ui/tokens.test.ts web/DESIGN.md
git commit -m "feat(web): Carta notturna palette, dark by default, paper grain

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The mark and the lockup

**Files:**
- Create: `web/lib/brand-mark.ts`
- Create: `web/components/ui/mark.tsx`
- Create: `web/components/ui/mark.test.tsx`
- Modify: `web/components/ui/wordmark.tsx`
- Modify: `web/app/dev/ui/page.tsx` (the "Testo per screen reader e marchio" section and the "Tipografia" section)

**Interfaces:**
- Consumes: the CSS tokens of Task 1. `Mark` uses the utilities `stroke-line-flights`, `stroke-line-lodging`, `stroke-line-coordinator`, `fill-ground` and `stroke-ink`.
- Produces, in `web/lib/brand-mark.ts`:
  - `MARK_VIEWBOX: "0 0 40 40"`
  - `MARK_GEOMETRY: { flights: { d, width }, lodging: { d, width }, coordinator: { d, width }, station: { cx, cy, r, width } }`
  - `NIGHT: { ground, ink, coordinator, flights, lodging, activities, transport }` (hex strings)
- Produces, in `web/components/ui/mark.tsx`: `Mark({ className?: string })`.
- Changes `Wordmark` to `Wordmark({ href?: string; className?: string; compact?: boolean })`. `compact` hides the name visually below 400 px.

- [ ] **Step 1: Write the tests**

Create `web/components/ui/mark.test.tsx`:

```tsx
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { NIGHT } from "@/lib/brand-mark";

import { Mark } from "./mark";
import { Wordmark } from "./wordmark";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

afterEach(cleanup);

/** The `--name: #rrggbb;` tokens of the dark ("Carta notturna") block of globals.css. */
function nightTokens(): Record<string, string> {
  const css = readFileSync(path.join(webDir, "app/globals.css"), "utf8");
  const start = css.indexOf(':root,\n[data-theme="dark"] {');
  const block = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries([...block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6});/g)].map((m) => [m[1]!, m[2]!]));
}

describe("Mark", () => {
  it("is decorative and drawn only in theme tokens, so it follows the nearest data-theme", () => {
    const { container } = render(<Mark className="size-7" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.outerHTML).not.toMatch(/#[0-9a-f]{3,6}\b/i);
    expect([...svg.querySelectorAll("path, circle")].map((shape) => shape.getAttribute("class"))).toEqual([
      "fill-none stroke-line-flights",
      "fill-none stroke-line-lodging",
      "fill-none stroke-line-coordinator",
      "fill-ground stroke-ink",
    ]);
  });

  it("keeps the fixed night colours (icons, link preview) equal to the dark theme's tokens", () => {
    const tokens = nightTokens();
    expect(NIGHT).toEqual({
      ground: tokens.ground,
      ink: tokens.ink,
      coordinator: tokens["line-coordinator"],
      flights: tokens["line-flights"],
      lodging: tokens["line-lodging"],
      activities: tokens["line-activities"],
      transport: tokens["line-transport"],
    });
  });
});

describe("Wordmark", () => {
  it("is the mark and the name, and the link home is named by the name alone", () => {
    render(<Wordmark href="/somewhere" />);
    const link = screen.getByRole("link", { name: "Atlas" });
    expect(link.getAttribute("href")).toBe("/somewhere");
    expect(link.querySelector("svg[aria-hidden='true']")).toBeTruthy();
  });

  it("keeps the name for screen readers when compact hides it on narrow phones", () => {
    render(<Wordmark href="/somewhere" compact />);
    const name = screen.getByText("Atlas");
    expect(name.className).toContain("max-[25rem]:sr-only");
    expect(screen.getByRole("link", { name: "Atlas" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `npx vitest run components/ui/mark.test.tsx`
Expected: FAIL: `Failed to resolve import "@/lib/brand-mark"`.

- [ ] **Step 3: Write the geometry module**

Create `web/lib/brand-mark.ts`:

```ts
/**
 * The mark of Atlas, "A di linee" (DESIGN.md, "Brand"): the flights and lodging lines rise to meet
 * at a station and form an "A"; the coordinator's line is the crossbar. One geometry, drawn by
 * <Mark> in the theme's tokens and by the icon and link-preview images in the fixed colours below.
 */

/** A 40-unit square. */
export const MARK_VIEWBOX = "0 0 40 40";

export const MARK_GEOMETRY = {
  flights: { d: "M8.5 35 L20 7", width: 5 },
  lodging: { d: "M31.5 35 L20 7", width: 5 },
  coordinator: { d: "M13.5 25 H26.5", width: 4.5 },
  station: { cx: 20, cy: 7.5, r: 4.6, width: 2.8 },
} as const;

/** "Carta notturna", the dark default, as fixed values: for images that cannot read CSS variables
 * (the icons, the link preview). components/ui/mark.test.tsx keeps them equal to globals.css. */
export const NIGHT = {
  ground: "#1b2230",
  ink: "#efe8d8",
  coordinator: "#a3abb6",
  flights: "#6e8fe0",
  lodging: "#4fa77b",
  activities: "#9c84d6",
  transport: "#4aa8b6",
} as const;
```

- [ ] **Step 4: Write the component**

Create `web/components/ui/mark.tsx`:

```tsx
import { MARK_GEOMETRY as G, MARK_VIEWBOX } from "@/lib/brand-mark";

import { cx } from "./cx";

/**
 * The mark of Atlas, "A di linee" (DESIGN.md, "Brand"), drawn in the theme's own line tokens, so
 * it follows the nearest data-theme with no JavaScript. Decorative: the name beside it, or the
 * link around it, says "Atlas". Size it with `className` (`size-7` in the header).
 */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox={MARK_VIEWBOX} aria-hidden="true" focusable="false" className={cx("shrink-0", className)}>
      <path d={G.flights.d} strokeWidth={G.flights.width} strokeLinecap="round" className="fill-none stroke-line-flights" />
      <path d={G.lodging.d} strokeWidth={G.lodging.width} strokeLinecap="round" className="fill-none stroke-line-lodging" />
      <path
        d={G.coordinator.d}
        strokeWidth={G.coordinator.width}
        strokeLinecap="round"
        className="fill-none stroke-line-coordinator"
      />
      <circle
        cx={G.station.cx}
        cy={G.station.cy}
        r={G.station.r}
        strokeWidth={G.station.width}
        className="fill-ground stroke-ink"
      />
    </svg>
  );
}
```

- [ ] **Step 5: Make the wordmark a lockup**

Replace `web/components/ui/wordmark.tsx` with:

```tsx
import Link from "next/link";

import { BRAND_NAME } from "@/lib/brand";

import { cx } from "./cx";
import { Mark } from "./mark";

/**
 * The lockup: the mark ("A di linee") and the name in the display face (Barlow Semi Condensed 600).
 * With `href` it is the header's link home. `compact`: below 400 px a crowded header keeps the mark
 * only, and the name stays the link's accessible name (DESIGN.md, Navigation).
 */
export function Wordmark({ href, className, compact = false }: { href?: string; className?: string; compact?: boolean }) {
  const classes = cx(
    "inline-flex items-center gap-2 font-cond text-title font-semibold tracking-[0.01em] text-ink no-underline",
    className,
  );
  const content = (
    <>
      <Mark className="size-7" />
      <span className={cx(compact && "max-[25rem]:sr-only")}>{BRAND_NAME}</span>
    </>
  );
  if (href) {
    return (
      // Padded to a 44 px target (28 px mark + 2 × 8 px); the negative margin keeps the lockup in place.
      <Link href={href} className={cx(classes, "-mx-2 -my-2 rounded-xs px-2 py-2")}>
        {content}
      </Link>
    );
  }
  return <span className={classes}>{content}</span>;
}
```

- [ ] **Step 6: Run the tests**

Run: `npx vitest run components/ui/mark.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 7: Show the mark in the gallery**

In `web/app/dev/ui/page.tsx`, add `import { Mark } from "@/components/ui/mark";` in alphabetical position.

In the section titled "Testo per screen reader e marchio", replace `<Wordmark />` with:

```tsx
              <div className="flex flex-wrap items-end gap-4">
                <Mark className="size-16" />
                <Mark className="size-10" />
                <Mark className="size-7" />
                <Wordmark />
              </div>
```

- [ ] **Step 8: Look at it**

Open `http://localhost:3000/dev/ui` at desktop width and scroll to "Testo per screen reader e marchio".
- In the "Chiaro" panel the legs must be the light inks and the station ink on cream.
- In the "Scuro" panel they must be the night inks and the station cream.

Check the header lockup at the top of the page.

- [ ] **Step 9: Commit**

```bash
git add web/lib/brand-mark.ts web/components/ui/mark.tsx web/components/ui/mark.test.tsx web/components/ui/wordmark.tsx web/app/dev/ui/page.tsx
git commit -m "feat(web): the A di linee mark and the lockup

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tagline, icons and the link preview

**Files:**
- Modify: `web/lib/brand.ts`
- Modify: `web/lib/brand-mark.ts` (add `markSvg`, `markDataUri`)
- Create: `web/lib/brand-mark.test.ts`
- Create: `web/app/icon.svg`
- Delete: `web/app/favicon.ico`
- Create: `web/app/apple-icon.tsx`
- Create: `web/app/opengraph-image.tsx`
- Create: `web/assets/fonts/BarlowSemiCondensed-Bold.ttf`, `web/assets/fonts/OFL.txt`
- Modify: `web/app/layout.tsx` (metadata)
- Modify: `web/components/home/empty-invitation.tsx`, `web/components/home/plan-list.test.tsx`, `web/app/dev/ui/page.tsx` (hero specimen)

**Interfaces:**
- Consumes: `NIGHT`, `MARK_GEOMETRY` and `MARK_VIEWBOX` (Task 2).
- Produces, in `web/lib/brand.ts`:
  - `BRAND_TAGLINE: "Ogni viaggio ha il suo atlante."`
  - `BRAND_URL: "https://atlas.bellittim.com"`
  - a new `BRAND_DESCRIPTION` text
- Produces, in `web/lib/brand-mark.ts`:
  - `markSvg(colors?: MarkColors): string`
  - `markDataUri(colors?: MarkColors): string`
  - `type MarkColors = { ground: string; ink: string; coordinator: string; flights: string; lodging: string }`

- [ ] **Step 1: Write the tests**

Create `web/lib/brand-mark.test.ts`:

```ts
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
```

In `web/components/home/plan-list.test.tsx`, add `import { BRAND_TAGLINE } from "@/lib/brand";` and change the assertion at line 171 to:

```ts
    expect(screen.getByRole("heading", { name: BRAND_TAGLINE })).toBeTruthy();
```

- [ ] **Step 2: Run them and watch them fail**

Run: `npx vitest run lib/brand-mark.test.ts components/home/plan-list.test.tsx`
Expected: FAIL. `markSvg` is not exported, `app/icon.svg` does not exist (ENOENT), and the heading is still "Il primo viaggio parte da qui".

- [ ] **Step 3: Add the tagline and the site URL**

Replace `web/lib/brand.ts` with:

```ts
/**
 * The brand's words, decided by Michele (web/PRODUCT.md, "Decisions"): the name on 2026-10-12, the
 * tagline on 2026-10-14. Each is spelled here and nowhere else (components/ui/invariants.test.ts):
 * page metadata, the header lockup, the link preview and the landing read them. The repo and the
 * spec keep their own names.
 */
export const BRAND_NAME = "Atlas";

/** The line of the brand: the landing hero, the metadata, the link preview, the empty plans list. */
export const BRAND_TAGLINE = "Ogni viaggio ha il suo atlante.";

/** The page description and the landing's lede (Italian, sentence case). */
export const BRAND_DESCRIPTION =
  "Da Milano a Lisbona in un pomeriggio di lavoro, fatto da altri. Cinque agenti tracciano voli, alloggio, attività e spostamenti, e ti lasciano un piano con le date entro cui prenotare.";

/** The production origin: absolute URLs in metadata (the link preview image) start here. */
export const BRAND_URL = "https://atlas.bellittim.com";
```

- [ ] **Step 4: Add the SVG serialisers to `brand-mark.ts`**

Append to `web/lib/brand-mark.ts`:

```ts
export type MarkColors = Record<"ground" | "ink" | "coordinator" | "flights" | "lodging", string>;

/** The mark as a standalone SVG document, for images (the apple icon, the link preview). */
export function markSvg(colors: MarkColors = NIGHT): string {
  const g = MARK_GEOMETRY;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${MARK_VIEWBOX}">`,
    `<path d="${g.flights.d}" fill="none" stroke="${colors.flights}" stroke-width="${g.flights.width}" stroke-linecap="round"/>`,
    `<path d="${g.lodging.d}" fill="none" stroke="${colors.lodging}" stroke-width="${g.lodging.width}" stroke-linecap="round"/>`,
    `<path d="${g.coordinator.d}" fill="none" stroke="${colors.coordinator}" stroke-width="${g.coordinator.width}" stroke-linecap="round"/>`,
    `<circle cx="${g.station.cx}" cy="${g.station.cy}" r="${g.station.r}" fill="${colors.ground}" stroke="${colors.ink}" stroke-width="${g.station.width}"/>`,
    "</svg>",
  ].join("");
}

/** markSvg() as a base64 data URI, for <img src> inside next/og images. */
export function markDataUri(colors: MarkColors = NIGHT): string {
  return `data:image/svg+xml;base64,${btoa(markSvg(colors))}`;
}
```

- [ ] **Step 5: Draw the tab icon and remove Next's default favicon**

Create `web/app/icon.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <!-- The mark of Atlas for browser tabs (DESIGN.md, "Brand"). The night ground is a tile, so the
       icon reads on light and dark tab bars; strokes are thicker than the 40-unit mark for 16 px. -->
  <rect width="32" height="32" rx="7" fill="#1b2230"/>
  <path d="M8.2 27 L16 7.5" fill="none" stroke="#6e8fe0" stroke-width="4.2" stroke-linecap="round"/>
  <path d="M23.8 27 L16 7.5" fill="none" stroke="#4fa77b" stroke-width="4.2" stroke-linecap="round"/>
  <path d="M11.3 20.5 H20.7" fill="none" stroke="#a3abb6" stroke-width="3.6" stroke-linecap="round"/>
  <circle cx="16" cy="7.6" r="3.3" fill="#1b2230" stroke="#efe8d8" stroke-width="2.2"/>
</svg>
```

Run: `git rm web/app/favicon.ico`

- [ ] **Step 6: Generate the home-screen icon**

First read `web/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/01-metadata/app-icons.md`, section "Generate icons using code". Then create `web/app/apple-icon.tsx`:

```tsx
import { ImageResponse } from "next/og";

import { markDataUri, NIGHT } from "@/lib/brand-mark";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/** The home-screen icon (iOS): the mark on the night ground, rendered once at build time. iOS
 * rounds the corners itself. */
export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: NIGHT.ground,
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- next/og draws a plain <img> */}
        <img src={markDataUri()} width={116} height={116} alt="" />
      </div>
    ),
    size,
  );
}
```

- [ ] **Step 7: Vendor the hero face for the link preview**

`next/og` needs a TTF/OTF/WOFF buffer, and next/font only ships WOFF2. Barlow is SIL OFL 1.1, so the TTF and its licence can live in the repo.

```bash
mkdir -p web/assets/fonts
curl -fsSL -o web/assets/fonts/BarlowSemiCondensed-Bold.ttf https://raw.githubusercontent.com/google/fonts/main/ofl/barlowsemicondensed/BarlowSemiCondensed-Bold.ttf
curl -fsSL -o web/assets/fonts/OFL.txt https://raw.githubusercontent.com/google/fonts/main/ofl/barlowsemicondensed/OFL.txt
file web/assets/fonts/BarlowSemiCondensed-Bold.ttf
```

Expected: `TrueType Font data`, and `OFL.txt` starts with "Copyright".

- [ ] **Step 8: Generate the link preview**

First read `web/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/01-metadata/opengraph-image.md`, the sections on local fonts and local images. Then create `web/app/opengraph-image.tsx`:

```tsx
import { readFile } from "node:fs/promises";
import path from "node:path";

import { ImageResponse } from "next/og";

import { BRAND_NAME, BRAND_TAGLINE } from "@/lib/brand";
import { markDataUri, NIGHT } from "@/lib/brand-mark";

export const alt = `${BRAND_NAME}: ${BRAND_TAGLINE}`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** The five agent lines converging on a destination, as at the end of the landing hero. No text:
 * the inner SVG is rasterised without fonts. 1056 × 150 units. */
const CONVERGING_LINES = [
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1056 150">`,
  `<g fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="7">`,
  `<path d="M0 75 H990" stroke="${NIGHT.coordinator}" stroke-width="9"/>`,
  `<path d="M0 15 H930 L990 75" stroke="${NIGHT.flights}"/>`,
  `<path d="M0 45 H960 L990 75" stroke="${NIGHT.lodging}"/>`,
  `<path d="M0 105 H960 L990 75" stroke="${NIGHT.activities}"/>`,
  `<path d="M120 135 H930 L990 75" stroke="${NIGHT.transport}"/>`,
  `</g>`,
  `<circle cx="990" cy="75" r="26" fill="${NIGHT.ground}" stroke="${NIGHT.ink}" stroke-width="7"/>`,
  `<circle cx="990" cy="75" r="9" fill="${NIGHT.ink}"/>`,
  `</svg>`,
].join("");

/** The link preview of every page (WhatsApp, Slack, iMessage): mark and name, the tagline, the
 * lines converging. Static: rendered once at build time from the vendored hero face. */
export default async function OpengraphImage() {
  const bold = await readFile(path.join(process.cwd(), "assets/fonts/BarlowSemiCondensed-Bold.ttf"));
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "60px 72px 56px",
          background: NIGHT.ground,
          color: NIGHT.ink,
          fontFamily: "Barlow Semi Condensed",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 44 }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- next/og draws a plain <img> */}
          <img src={markDataUri()} width={56} height={56} alt="" />
          {BRAND_NAME}
        </div>
        <div style={{ display: "flex", fontSize: 96, lineHeight: 0.98, maxWidth: 780 }}>{BRAND_TAGLINE}</div>
        {/* eslint-disable-next-line @next/next/no-img-element -- next/og draws a plain <img> */}
        <img
          src={`data:image/svg+xml;base64,${btoa(CONVERGING_LINES)}`}
          width={1056}
          height={150}
          alt=""
        />
      </div>
    ),
    { ...size, fonts: [{ name: "Barlow Semi Condensed", data: bold, weight: 700, style: "normal" }] },
  );
}
```

- [ ] **Step 9: Point the metadata at the site and the tagline**

In `web/app/layout.tsx`, import `BRAND_URL` alongside the other brand imports, and replace `metadata` with:

```ts
export const metadata: Metadata = {
  metadataBase: new URL(BRAND_URL),
  title: { default: BRAND_NAME, template: `%s · ${BRAND_NAME}` },
  description: BRAND_DESCRIPTION,
  applicationName: BRAND_NAME,
  openGraph: { siteName: BRAND_NAME, locale: "it_IT", type: "website" },
};
```

- [ ] **Step 10: Make the tagline the invitation's heading**

In `web/components/home/empty-invitation.tsx`, add `import { BRAND_TAGLINE } from "@/lib/brand";` and replace the heading text `Il primo viaggio parte da qui` with `{BRAND_TAGLINE}`.

In `web/app/dev/ui/page.tsx`, add `import { BRAND_TAGLINE } from "@/lib/brand";` in alphabetical position. In the "Tipografia" section, add this as the first child of the `<div className="grid gap-3">`, so the hero face has a specimen:

```tsx
              <p className="font-hero text-hero font-bold">{BRAND_TAGLINE}</p>
```

- [ ] **Step 11: Run the tests**

Run: `npx vitest run lib/brand-mark.test.ts components/home/plan-list.test.tsx components/ui/mark.test.tsx`
Expected: PASS.

- [ ] **Step 12: Look at the images**

With `web-dev` running, open each of these in the browser pane:
- `http://localhost:3000/icon.svg`
- `http://localhost:3000/apple-icon`
- `http://localhost:3000/opengraph-image`

Each must render. Take a screenshot of each image:
- the link preview shows "Atlas", the tagline on two lines, and the converging lines
- the apple icon is the mark centred on the night ground

Then read the page source of `/` (`read_page` or `view-source`). `<link rel="icon" href="/icon.svg…">`, `<link rel="apple-touch-icon" …>` and `<meta property="og:image" content="https://atlas.bellittim.com/opengraph-image…">` must be present, and there must be no `favicon.ico`.

- [ ] **Step 13: Commit**

```bash
git add web/lib/brand.ts web/lib/brand-mark.ts web/lib/brand-mark.test.ts web/app/icon.svg web/app/apple-icon.tsx web/app/opengraph-image.tsx web/assets/fonts web/app/layout.tsx web/components/home/empty-invitation.tsx web/components/home/plan-list.test.tsx web/app/dev/ui/page.tsx
git commit -m "feat(web): tagline, icons and the link preview

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(`git rm` already staged the favicon's deletion.)

---

### Task 4: One app header, the current page as a station

**Files:**
- Create: `web/lib/routes.ts`
- Create: `web/components/nav/app-header.tsx`
- Create: `web/components/nav/app-header.test.tsx`
- Modify: `web/components/ui/icon-button.tsx` (export `iconButtonClasses`)
- Modify: `web/app/page.tsx`, `web/app/new/page.tsx`, `web/app/evals/page.tsx`, `web/app/evals/[id]/error.tsx`, `web/app/plans/[id]/error.tsx`, `web/app/not-found.tsx`, `web/app/dev/ui/page.tsx`
- Modify: `web/components/evals/eval-run-screen.tsx`, `web/components/evals/eval-run-skeleton.tsx`, `web/components/live/plan-screen.tsx`, `web/components/states/plan-skeleton.tsx`, `web/components/states/load-failed.tsx`, `web/components/states/plan-ended.tsx`
- Modify: `web/components/ui/invariants.test.ts` (no hand-written `href="/"`)
- Delete: `web/components/home/site-header.tsx`, `web/components/home/site-header.test.tsx`, `web/components/live/top-bar.tsx`

**Interfaces:**
- Consumes: `Wordmark({ href, compact })` (Task 2).
- Produces, in `web/lib/routes.ts`: `ROUTES: { plans: "/"; newPlan: "/new"; evals: "/evals" }`. Step 2 changes `plans` to `"/plans"`.
- Produces, in `web/components/nav/app-header.tsx`:
  - `type AppSection = "plans" | "evals" | "new"`
  - `AppHeader({ current?: AppSection; compact?: boolean })`
- Produces, in `web/components/ui/icon-button.tsx`: `iconButtonClasses(size?: "md" | "sm", variant?: "outline" | "bare"): string`.

- [ ] **Step 1: Write the header tests and the link invariant**

Create `web/components/nav/app-header.test.tsx`:

```tsx
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ROUTES } from "@/lib/routes";

import { AppHeader } from "./app-header";

vi.mock("@/components/ui/theme-toggle", () => ({ ThemeToggle: () => <button type="button">Tema</button> }));

afterEach(cleanup);

describe("AppHeader", () => {
  it("links the lockup to the plans and draws both sections as stations, the current one filled", () => {
    render(<AppHeader current="plans" />);
    expect(screen.getByRole("link", { name: "Atlas" }).getAttribute("href")).toBe(ROUTES.plans);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    const plans = within(nav).getByRole("link", { name: "Piani" });
    const evals = within(nav).getByRole("link", { name: "Valutazioni" });
    expect(plans.getAttribute("href")).toBe(ROUTES.plans);
    expect(plans.getAttribute("aria-current")).toBe("page");
    expect(evals.getAttribute("href")).toBe(ROUTES.evals);
    expect(evals.getAttribute("aria-current")).toBeNull();
  });

  it("marks the eval history as the current section on the eval pages", () => {
    render(<AppHeader current="evals" />);
    const nav = screen.getByRole("navigation", { name: "Sezioni" });
    expect(within(nav).getByRole("link", { name: "Valutazioni" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "Piani" }).getAttribute("aria-current")).toBeNull();
  });

  it("always offers a new plan as a secondary action, named on the phone's icon too", () => {
    render(<AppHeader current="plans" />);
    const links = screen.getAllByRole("link", { name: "Nuovo piano" });
    expect(links).toHaveLength(2); // the labelled button from 640 px, the icon below
    for (const link of links) {
      expect(link.getAttribute("href")).toBe(ROUTES.newPlan);
      expect(link.className).not.toMatch(/\bbg-action\b/);
    }
  });

  it("drops the new-plan action on the form itself", () => {
    render(<AppHeader current="new" />);
    expect(screen.queryByRole("link", { name: "Nuovo piano" })).toBeNull();
  });

  it("leaves the theme toggle to the live screen's bar when compact", () => {
    const { unmount } = render(<AppHeader current="plans" />);
    expect(screen.getByRole("button", { name: "Tema" })).toBeTruthy();
    unmount();
    render(<AppHeader current="plans" compact />);
    expect(screen.queryByRole("button", { name: "Tema" })).toBeNull();
  });
});
```

In `web/components/ui/invariants.test.ts`, add inside `describe("design invariants")`:

```ts
  it("links to the plans list through ROUTES, never a hand-written \"/\"", () => {
    // Step 2 of the brand spec gives "/" to the landing: every link to the list must move with ROUTES.
    const LITERAL_ROOT = /href=(?:"\/"|\{"\/"\})/;
    const offenders = [...sources(path.join(webDir, "components")), ...sources(path.join(webDir, "app"))]
      .filter((file) => LITERAL_ROOT.test(readFileSync(file, "utf8")))
      .map((file) => path.relative(webDir, file));
    expect(offenders).toEqual([]);
  });
```

- [ ] **Step 2: Run them and watch them fail**

Run: `npx vitest run components/nav/app-header.test.tsx components/ui/invariants.test.ts`
Expected: FAIL. The header test can't resolve `@/lib/routes` or `./app-header`. The invariant lists `app/new/page.tsx`, `app/not-found.tsx`, `app/plans/[id]/error.tsx`, `app/dev/ui/page.tsx`, `components/home/site-header.tsx`, `components/live/top-bar.tsx`, `components/states/load-failed.tsx` and `components/states/plan-ended.tsx`.

- [ ] **Step 3: Add the routes**

Create `web/lib/routes.ts`:

```ts
/**
 * Where the app's pages live, so no link spells a path by hand (components/ui/invariants.test.ts).
 * Step 2 of the brand spec (docs/superpowers/specs/2026-10-14-atlas-brand-design.md) moves the
 * plans list from "/" to "/plans" and gives "/" to the public landing: that move is this file.
 */
export const ROUTES = {
  plans: "/",
  newPlan: "/new",
  evals: "/evals",
} as const;
```

- [ ] **Step 4: Export the icon button's classes**

In `web/components/ui/icon-button.tsx`, add above `interface IconButtonProps`:

```ts
/** Class string of an icon button, for a link that must look like one (the header's "Nuovo piano"
 * on the phone). */
export function iconButtonClasses(size: keyof typeof SIZES = "md", variant: "outline" | "bare" = "outline"): string {
  return cx(
    "inline-grid shrink-0 place-items-center rounded-full border-[1.5px] bg-transparent text-ink",
    variant === "outline" ? "border-rule-strong" : "border-transparent",
    "transition-[background-color,scale] duration-(--duration-hover) ease-out not-disabled:hover:bg-notice-wash",
    "active:scale-[0.96] active:duration-(--duration-press) motion-reduce:active:scale-100",
    "disabled:cursor-not-allowed disabled:opacity-55",
    SIZES[size].box,
  );
}
```

In `IconButton`, replace the `className={cx( … )}` argument with `className={cx(iconButtonClasses(size, variant), className)}`.

- [ ] **Step 5: Write the header**

Create `web/components/nav/app-header.tsx`:

```tsx
import Link from "next/link";

import { LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { iconButtonClasses } from "@/components/ui/icon-button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/** The app's sections. "new" is the request form: it has no nav item, and no "Nuovo piano" there. */
export type AppSection = "plans" | "evals" | "new";

const SECTIONS = [
  { section: "plans", href: ROUTES.plans, label: "Piani" },
  { section: "evals", href: ROUTES.evals, label: "Valutazioni" },
] as const;

/**
 * The header of every signed-in page (DESIGN.md, Navigation): the lockup as the link to the plans,
 * the sections drawn as stations on one line (the current one filled), "Nuovo piano" always at hand
 * as a secondary action (each view keeps its single primary), the theme toggle. One line, at most
 * 72 px, no menu drawer at 393 px. `compact` is the live screen's slim top row: its sticky control
 * bar carries the toggle.
 */
export function AppHeader({ current, compact = false }: { current?: AppSection; compact?: boolean }) {
  return (
    <header className={cx(!compact && "border-b border-rule")}>
      <div
        className={cx(
          "mx-auto flex max-w-page items-center justify-between gap-2 px-4 lg:px-7",
          compact ? "min-h-14" : "min-h-16",
        )}
      >
        <Wordmark href={ROUTES.plans} compact />
        <div className="flex items-center gap-1 sm:gap-2">
          <nav aria-label="Sezioni">
            <ul className="flex">
              {SECTIONS.map((item, index) => (
                <Station
                  key={item.section}
                  href={item.href}
                  label={item.label}
                  current={current === item.section}
                  first={index === 0}
                  last={index === SECTIONS.length - 1}
                />
              ))}
            </ul>
          </nav>
          {current === "new" ? null : (
            <>
              <LinkButton href={ROUTES.newPlan} variant="secondary" icon="plus" className="max-sm:hidden">
                Nuovo piano
              </LinkButton>
              <Link
                href={ROUTES.newPlan}
                aria-label="Nuovo piano"
                title="Nuovo piano"
                className={cx(iconButtonClasses(), "sm:hidden")}
              >
                <Icon name="plus" size={18} />
              </Link>
            </>
          )}
          {compact ? null : <ThemeToggle />}
        </div>
      </div>
    </header>
  );
}

/**
 * One section on the header's line: its label above its station. The line runs from the first
 * station to the last, behind them (each item draws the halves that face its neighbours). The
 * link is positioned, so it paints above the line drawn before it.
 */
function Station({
  href,
  label,
  current,
  first,
  last,
}: {
  href: string;
  label: string;
  current: boolean;
  first: boolean;
  last: boolean;
}) {
  // The station's centre is 11.5 px above the item's bottom (8 px padding + half of 7 px).
  const half = "pointer-events-none absolute bottom-[11px] h-px bg-rule-strong";
  return (
    <li className="relative flex">
      {first ? null : <span aria-hidden="true" className={cx(half, "right-1/2 left-0")} />}
      {last ? null : <span aria-hidden="true" className={cx(half, "right-0 left-1/2")} />}
      <Link
        href={href}
        aria-current={current ? "page" : undefined}
        className={cx(
          "group relative grid min-h-11 justify-items-center gap-1 rounded-xs px-2.5 pt-1 pb-2 text-small no-underline sm:px-3",
          current ? "font-semibold text-ink" : "text-ink-2 hover:text-ink",
        )}
      >
        <span>{label}</span>
        <span
          aria-hidden="true"
          className={cx(
            "size-[7px] rounded-full border-[1.5px] transition-colors duration-(--duration-hover) ease-out",
            current ? "border-ink bg-ink" : "border-ink-2 bg-ground group-hover:bg-ink-2",
          )}
        />
      </Link>
    </li>
  );
}
```

- [ ] **Step 6: Put the header on every signed-in page, and route list links through `ROUTES`**

Make each of these replacements:

- **`web/app/page.tsx`**:
  - Replace `import { SiteHeader } from "@/components/home/site-header";` with `import { AppHeader } from "@/components/nav/app-header";` and delete the `LinkButton` import.
  - Replace `<SiteHeader />` with `<AppHeader current="plans" />`.
  - Replace the `<div className="flex max-w-[64rem] …">…</div>` title row with just its `<h1 …>I tuoi piani</h1>`. "Nuovo piano" now lives in the header, as the secondary action.
  - Update the page's doc comment: replace `and "Nuovo piano" as the one primary action` with `; "Nuovo piano" is in the header`.
- **`web/app/new/page.tsx`**: `SiteHeader` becomes `<AppHeader current="new" />`, imported from `@/components/nav/app-header`. The back link's `href="/"` becomes `href={ROUTES.plans}`; add `import { ROUTES } from "@/lib/routes";`.
- **`web/app/evals/page.tsx`**, **`web/app/evals/[id]/error.tsx`**, **`web/components/evals/eval-run-skeleton.tsx`**, **`web/components/evals/eval-run-screen.tsx`** (all three uses): `<SiteHeader current="evals" />` becomes `<AppHeader current="evals" />`, with the import swapped.
- **`web/components/live/plan-screen.tsx`** (three uses), **`web/components/states/plan-skeleton.tsx`**, **`web/app/plans/[id]/error.tsx`**: `<TopBar />` becomes `<AppHeader current="plans" compact />`. Replace `import { TopBar } from "./top-bar";` (or `"@/components/live/top-bar"`) with `import { AppHeader } from "@/components/nav/app-header";`.
- **`web/app/plans/[id]/error.tsx`**, **`web/components/states/load-failed.tsx`** (both), **`web/components/states/plan-ended.tsx`**: `<LinkButton href="/"` becomes `<LinkButton href={ROUTES.plans}`, plus the `ROUTES` import.
- **`web/app/not-found.tsx`**: `<a href="/"` becomes `<a href={ROUTES.plans}`, plus the `ROUTES` import. `ROUTES` is a constant, so the page stays server markup only.
- **`web/app/dev/ui/page.tsx`**: `<Wordmark href="/" />` becomes `<Wordmark href={ROUTES.plans} />`, plus the import.

Then delete the old headers:

```bash
git rm web/components/home/site-header.tsx web/components/home/site-header.test.tsx web/components/live/top-bar.tsx
```

- [ ] **Step 7: Run the tests, the types and the linter**

Run: `npx vitest run components/nav/app-header.test.tsx components/ui/invariants.test.ts`
Expected: PASS.

Run: `npm test && npm run typecheck && npm run lint`
Expected: all PASS. If `eval-run-screen.test.tsx` or `plan-screen.test.tsx` queried the old header, adjust only the query (for example, the home link is now named "Atlas" with `href` `ROUTES.plans`), never the behaviour under test.

- [ ] **Step 8: Measure the header at 393 px (Review Focus 3)**

With both servers running, set the browser pane to 393 × 812 and open each of:
- `http://localhost:3000/`
- `/new`
- `/evals`
- a plan from the list

On each page, run this in the page with `javascript_tool`:

```js
(() => {
  const header = document.querySelector("header");
  const targets = [...header.querySelectorAll("a, button")].filter((el) => el.getClientRects().length > 0);
  return {
    headerHeight: Math.round(header.getBoundingClientRect().height),
    horizontalScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    smallTargets: targets.filter((el) => el.getBoundingClientRect().height < 44).map((el) => el.textContent.trim() || el.getAttribute("aria-label")),
    oneLine: new Set(targets.map((el) => Math.round(el.getBoundingClientRect().top / 8))).size <= 2,
  };
})()
```

Expected on each page:
- `headerHeight` ≤ 72
- `horizontalScroll: false`
- `smallTargets: []`
- `oneLine: true`

On the plan page, measure the compact header (the first `header`). Take one screenshot at 393 px and one at 1280 px of `/`, in dark and in light.

- [ ] **Step 9: Commit**

```bash
git add web/lib/routes.ts web/components/nav web/components/ui/icon-button.tsx web/components/ui/invariants.test.ts web/app web/components/evals web/components/live/plan-screen.tsx web/components/states
git commit -m "feat(web): one app header with the current page as a station

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The No AI Chrome Rule as a test, and the docs

**Files:**
- Modify: `web/components/ui/invariants.test.ts`
- Modify: `web/DESIGN.md` (intro, "Where things live", Overview, new "## Brand", Components, Navigation, Do's and Don'ts)
- Modify: `web/PRODUCT.md` (header note, Decisions, Brand Commitments, Evidence on Hand)
- Modify: `web/design/directions/README.md` (first paragraph)
- Modify: `CLAUDE.md` ("UI rules (web/)")

**Interfaces:**
- Consumes: `BRAND_TAGLINE` (Task 3), `Mark` / `AppHeader` (Tasks 2 and 4).
- Produces: nothing new in code; the rules later steps follow.

- [ ] **Step 1: Write the invariants**

In `web/components/ui/invariants.test.ts`, add inside `describe("design invariants")`:

```ts
  it("keeps the No AI Chrome Rule: no glow, spotlight or gradient text, and glass only on the sticky live bar", () => {
    const all = [...sources(path.join(webDir, "components")), ...sources(path.join(webDir, "app"))];
    const relative = (file: string) => path.relative(webDir, file);
    const CHROME = /drop-shadow|blur\(|radial-gradient|conic-gradient|bg-clip-text|background-clip:\s*text/;
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
```

Update the file's top comment: append "the No AI Chrome Rule holds, the tagline is spelled once, and no link spells the list's path by hand" to the list of checks.

- [ ] **Step 2: Run them**

Run: `npx vitest run components/ui/invariants.test.ts`

Expected: PASS. Tasks 1–4 introduced none of the banned effects. If `sources()` does not walk `lib/` because `lib/` holds generated files, check that the tagline test still lists only `lib/brand.ts`. A failure here means a real violation: fix the source, not the test.

- [ ] **Step 3: Rewrite the brand parts of DESIGN.md**

In `web/DESIGN.md`:

**1. Intro.** Under "# Design System: Atlas", replace the first sentence ("Direction 1 "Linee", chosen by Michele on 2026-10-12 … README).") with:

```markdown
Direction 1 "Linee", chosen by Michele on 2026-10-12 from the three studies in
`web/design/directions/` (the study is `1-linee/index.html`, the comparison and trade-offs are in
that folder's README), restyled as **"Carta notturna"** on 2026-10-14
(`docs/superpowers/specs/2026-10-14-atlas-brand-design.md`).
```

**2. "Where things live".** Replace the row `| Product name ("Atlas") | ... |` with these rows:

```markdown
| Product name ("Atlas"), tagline, description, site URL | `web/lib/brand.ts` (`BRAND_NAME`, `BRAND_TAGLINE`, `BRAND_DESCRIPTION`, `BRAND_URL`), nowhere else |
| The mark's geometry and its fixed night colours | `web/lib/brand-mark.ts`; drawn by `components/ui/mark.tsx` |
| Tab icon, home-screen icon, link preview | `web/app/icon.svg`, `web/app/apple-icon.tsx`, `web/app/opengraph-image.tsx` (font: `web/assets/fonts/`, OFL) |
| Links between pages | `web/lib/routes.ts` (`ROUTES`), never a hand-written path |
| The app header | `web/components/nav/app-header.tsx` |
```

and add `, the No AI Chrome Rule, the tagline spelled once, no hand-written list path` to the end of the Invariants row's description.

**3. Overview.** Keep "Creative North Star: "The Line Map"" and its first paragraph. Replace the second paragraph ("The tone is a calm control room. …") with:

```markdown
The line map is printed at night: **"Carta notturna"**. A flat ink ground with a paper grain, cream
type, five matte line inks, the way a transit map looks on good paper under a street lamp. It is
crafted and alive, and never neon: colour is spent on identity (one hue per agent), on failure (one
red) and on deadlines (one amber). Everything else is cream or ink on the ground. Density is medium:
stations are spaced like a printed line map (about 40 px a row), with tabular figures so times and
costs line up.
```

In "**Key Characteristics:**", add as the last bullet:

```markdown
- Dark by default; paper grain on the ground; never glow, spotlight, gradient text or glass
  (The No AI Chrome Rule).
```

**4. New section.** Insert a new section right before "## Colors":

```markdown
## Brand

**The mark: "A di linee".** The flights and lodging lines rise to meet at a station and form an
"A"; the coordinator's line is the crossbar. It reads as a letter and as a piece of the map. It is
a 40-unit square (`web/lib/brand-mark.ts`, `MARK_GEOMETRY`):

- left leg: `M8.5 35 L20 7` in `line-flights`, 5 wide, round caps
- right leg: `M31.5 35 L20 7` in `line-lodging`
- crossbar: `M13.5 25 H26.5` in `line-coordinator`, 4.5 wide
- the station: r 4.6 at (20, 7.5), `ground` fill and `ink` stroke at 2.8

`<Mark>` draws it in token utilities, so it follows the nearest `data-theme`. Images that cannot
read CSS variables use `NIGHT`, the night values, which a test keeps equal to `globals.css`.

- **Lockup** (`Wordmark`): the mark (28 px) and "Atlas" in Semi Condensed 600. `compact` hides the
  name below 400 px (the header on a phone); the name stays the link's accessible name.
- **Tab icon** (`app/icon.svg`): the mark on a night tile, with thicker strokes for 16 px.
  **Home-screen icon** (`app/apple-icon.tsx`): the mark on the night ground, 180 px. There is no
  `favicon.ico`.
- **Link preview** (`app/opengraph-image.tsx`): mark and name, the tagline, the five lines
  converging on a destination; 1200 × 630, rendered at build time with the vendored Semi
  Condensed 700.
- **Tagline**: "Ogni viaggio ha il suo atlante." (`BRAND_TAGLINE`): the landing hero, the
  metadata, the link preview, the empty plans list's invitation.
- **Rule:** this is the only mark. It is never redrawn in another form, and it moves only where it
  draws itself on the landing hero.

**The No AI Chrome Rule.** Nothing on screen may look like a template made by AI. Banned:

- glow (`drop-shadow`, `blur()` used as light, coloured halos)
- radial or conic spotlight gradients
- dot or grid backgrounds
- gradient text (`background-clip: text`)
- glass beyond the sticky live bar (`backdrop-filter` lives only in `live-header.tsx`,
  `agent-lanes.tsx` and the dev gallery's header)
- floating blurred shapes
- sparkle iconography

`components/ui/invariants.test.ts` enforces the mechanical part. The texture of the product is the
paper grain, and nothing else.
```

**5. Components table.**
- Replace the `Wordmark` row with:

```markdown
| `Mark` | `mark.tsx` | "A di linee" in the theme's line tokens (Brand) | any size via `className` |
| `Wordmark` | `wordmark.tsx` | The lockup: mark and "Atlas", optionally the link home | `compact` (name hidden below 400 px) |
```

- After the `IconButton` row, add:

```markdown
| `iconButtonClasses` | `icon-button.tsx` | An icon button's classes, for a link that must look like one | md, sm; outline, bare |
```

- Under the table, add:

```markdown
`AppHeader` (`web/components/nav/app-header.tsx`) is app chrome, not a primitive: see Navigation.
```

**6. Navigation.** Replace the "### Navigation" body with:

```markdown
- **One header on every signed-in page** (`AppHeader`):
  - the lockup, the link to the plans (`ROUTES.plans`)
  - the sections "Piani" and "Valutazioni" as **stations on one line**: the current one has a
    filled ink node and `aria-current="page"`, the others a hollow node that fills on hover
  - "Nuovo piano", always the *secondary* button so each view keeps its single primary. On the
    phone it is a 40 px "+" icon link named "Nuovo piano". It is hidden on the form itself.
  - the theme toggle
- At most 72 px tall, one line, no menu drawer at 393 px, 44 px targets.
- On the live screen the header is `compact`: the slim top row (56 px) above the sticky control
  bar, which keeps the theme toggle and stays the only sticky, translucent surface.
- Links between pages read `ROUTES` (`web/lib/routes.ts`), never a hand-written path.
```

**7. Do's and Don'ts.**
- Replace the last Don't ("**Don't** invent a logo: Atlas is its wordmark.") with:

```markdown
- **Don't** draw another mark or redraw "A di linee": `<Mark>` and `lib/brand-mark.ts` are the only
  sources.
- **Don't** add glow, spotlight gradients, dot grids, gradient text, glass or blurred shapes (The No
  AI Chrome Rule).
```

- Add to the Do's:

```markdown
- **Do** read the tagline from `BRAND_TAGLINE` and every page path from `ROUTES`.
```

- [ ] **Step 4: Rewrite the brand parts of PRODUCT.md**

In `web/PRODUCT.md`:

**1. Header note.** At the end of the blockquote under "# Product", append this sentence:

```markdown
> On 2026-10-14 Michele restyled the brand ("Carta notturna", the "A di linee" mark, the tagline,
> dark by default, a public front door): `docs/superpowers/specs/2026-10-14-atlas-brand-design.md`.
```

**2. "## Decisions".** Add a subsection at the end:

```markdown
### 2026-10-14: the brand restyle

- **Audience of the restyle: showing Atlas off** (friends, portfolio, a launch video), on top of
  daily use.
- **World: "Carta notturna"**, a printed night transit map: flat ink ground, paper grain, cream
  type, matte line inks. **Dark is the default everywhere**; light ("Carta di giorno") is pinned
  with the toggle.
- **Mark: "A di linee"** (DESIGN.md, Brand). **Tagline: "Ogni viaggio ha il suo atlante."**
- **Front door** (step 2 of the spec): a public landing at `/`, the plans list at `/plans`, and a
  free demo run at `/demo`.
- **Navigation: one app header**, with the current section drawn as a station.
- **Never the "AI site" look**: no glow, no spotlight gradients, no dot grids, no gradient text, no
  glass beyond the sticky bar.
```

**3. "## Brand Commitments".** Replace the "**Tone: a calm control room, not a videogame.**" bullet with:

```markdown
- **Tone: a printed night map.** Crafted, alive, never neon. Many things move at once on the live
  screen and it must not become noise: no scores, no glowing "AI" chrome (The No AI Chrome Rule,
  DESIGN.md). The motion rule itself is rewritten with the live-run motion (step 4 of the brand
  spec); until then DESIGN.md's "Report, Don't Perform" stands.
```

**4. "## Evidence on Hand".** Replace "- No logo, no photography, no illustrations, no brand assets exist. Do not invent them." with:

```markdown
- The brand assets are the mark "A di linee", the tagline and the paper grain (DESIGN.md, Brand),
  plus free Wikimedia cover photos per destination. No other logo, illustration or stock imagery is
  invented.
```

- [ ] **Step 5: Note the restyle in the directions README and CLAUDE.md**

In `web/design/directions/README.md`, add this paragraph after the first paragraph:

```markdown
**2026-10-14:** Michele chose direction 1, "Linee", and it has since been restyled as "Carta
notturna" (dark by default, the "A di linee" mark): `docs/superpowers/specs/2026-10-14-atlas-brand-design.md`.
These studies stay as they were drawn.
```

In `CLAUDE.md`, section "## UI rules (web/)":
- Replace `- Design: direction 1 "Linee" (the run drawn as a transit line diagram, PRODUCT.md
  "Decisions").` with:

```markdown
- Design: direction 1 "Linee" (the run drawn as a transit line diagram, PRODUCT.md
  "Decisions"), restyled as "Carta notturna" on 2026-10-14: dark by default, the "A di linee"
  mark, no glow or "AI" chrome (`docs/superpowers/specs/2026-10-14-atlas-brand-design.md`).
```

- Replace `The product name is spelled only in `BRAND_NAME` (`web/lib/brand.ts`).` with:

```markdown
The product name and the tagline are spelled only in `BRAND_NAME` and `BRAND_TAGLINE`
(`web/lib/brand.ts`); page paths come from `ROUTES` (`web/lib/routes.ts`).
```

- [ ] **Step 6: Run the whole suite**

Run: `npm test`
Expected: PASS. The token test also re-checks that the frontmatter and globals.css still agree after the DESIGN.md edits.

- [ ] **Step 7: Commit**

```bash
git add web/components/ui/invariants.test.ts web/DESIGN.md web/PRODUCT.md web/design/directions/README.md CLAUDE.md
git commit -m "docs(web): the Carta notturna brand, the No AI Chrome Rule as a test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Full verification and the design gate

**Files:**
- Modify: whatever this task's findings require. Fix in the component, and re-run the owning task's tests.

**Interfaces:** none.

- [ ] **Step 1: Run every web check CI runs**

Run from `web/`:

```bash
npm run gen:schemas -- --check && npm run lint && npm run typecheck && npm test && npm run build
```

Expected: every command exits 0. In the build output, the routes `/icon.svg`, `/apple-icon` and `/opengraph-image` must be listed as static (○ or ●), and there must be no `metadataBase` warning.

- [ ] **Step 2: Check the JS budget**

```bash
NEXT_DIST_DIR=.next-build npm run build && NEXT_DIST_DIR=.next-build npm run measure:js
```

Expected: `/plans/[id]` ≤ 189.1 KB gzip. Record the figures for `/`, `/new` and `/plans/[id]` in `web/README.md`'s "JS budget" paragraph ("Measured on …"), with today's date.

- [ ] **Step 3: Look at every screen**

Start `backend-demo` and `web-dev`. Start one demo plan from `/new?esempio=1` ("Pianifica il viaggio"; offline, free) and let it finish.

Check each screen at 393 × 812 and at 1280 × 820, in dark (nothing pinned) and in light (pinned with the toggle):
- `/`
- `/new`
- the plan while running
- the same plan finished, scrolled to the map and the bookings
- `/evals`
- `/dev/ui`

On each one, look for:
- text contrast that looks off
- the grain missing or too strong
- the map basemap clashing with the new ground (it reads the tokens at runtime)
- a cover photo whose credit is unreadable
- **in light on `/dev/ui`, the due-soon `DatePair`**: amber stroke visible, "In scadenza" present (Review Focus 4)
- **the mark in both ThemePair panels** (Review Focus 5)

Take the screenshots as the record: 6 screens × 2 widths × 2 themes. Fix what is wrong in the component that causes it, with a test where the defect is testable.

- [ ] **Step 4: Run the design gate**

Invoke the `impeccable` skill with a critique of `/`, the header (all pages) and `/dev/ui`'s "Marchio" section, in both themes.

Expected: ≥ 32/40, with no open P0 or P1 (CLAUDE.md, "UI rules"). Fix P0 and P1 findings, re-run the critique, and save it as `web/.impeccable/critique/brand-step1.md` like the existing rounds.

- [ ] **Step 5: Commit the fixes and the record**

```bash
git add web
git commit -m "fix(web): brand step 1 findings from the browser pass and the critique

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If there was nothing to fix, commit only the critique and the README figures with the message `docs(web): brand step 1 critique and JS figures`.
