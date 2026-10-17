# Atlas brand step 1 polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the brand restyle's step 1 properly. Fix the eight minors that its final review deferred, apply Michele's three design decisions, and raise the critique of the app's screens (the plans list, the app header, the mark) from 27/40 toward 35/40.

**Architecture:** Small, independent changes in `web/`. Each task ships its own tests:
- page paths come from `ROUTES`;
- the theme toggle swaps the theme without a transition flash;
- the header's station line is local, 2 px from 1080 px, with an equal 24 px overhang;
- the mark has a small geometry used at 28 px and below (the header lockup, the tab icon, a new `/favicon.ico`);
- the link preview breaks the tagline cleanly;
- `/plans` ends on a "Come funziona" help link to the landing.

**Tech Stack:** Next.js 16.4 App Router, React 19.3, Tailwind 4, Vitest + Testing Library, next/og.

**Spec:** `docs/superpowers/specs/2026-10-14-atlas-brand-design.md`. Critique records: `web/.impeccable/critique/brand-step1.md` and `.impeccable/critique/*web-app-page-tsx.md`.

**Michele's decisions (2026-10-17, from `.superpowers/polish/header-mark.html`):**
- Header option **B**: the line stays local to the sections, 2 px, with the same overhang on both sides.
- Mark option **C**: at 28 px and below, a smaller, lighter station ring and thicker lines and crossbar.
- "Valutazioni" becomes **"Collaudi"**.
- Autonomy through the PR.

## Global Constraints

- UI copy is Italian, sentence case. Code, comments and identifiers are English.
- No AI chrome: no glow, spotlight gradients, dot grids, gradient text or glass (`components/ui/invariants.test.ts`).
- The tokens in `web/DESIGN.md` are the authority: `components/ui/tokens.test.ts` keeps `globals.css` equal to them.
- Every page path comes from `ROUTES` (`web/lib/routes.ts`), never hand-written.
- Touch targets are 44 px under a coarse pointer (`pointer-coarse:size-11` or `pointer-coarse:min-h-11`).
- `/plans/[id]` first-load JS is 192.4 KB gzip: do not grow it (README's gate decision is pending with Michele).
- A screen merges at ≥ 32/40 in the impeccable critique with no open P0/P1; this plan aims for 35/40.
- Look at every changed screen at 393 px and desktop, in dark and light.

## Review Focus

1. **Quick double toggles of the theme** (two clicks inside one frame, or a toggle while reduced motion is on) never leave the no-transition guard stuck on `<html>`: hover and press feedback keep working afterwards. Test: Task 3.
2. **`/favicon.ico` requested directly** (some browsers, crawlers, bookmarks) returns an image, not the 404 page, and it is static. Test: Task 5.
3. **"Come funziona" from `/plans` while signed in** opens the landing at the section. It does not bounce back to `/plans`: a client navigation runs no skip script, and a full load keeps the landing thanks to the fragment rule. Test: Task 6.
4. **The rename is complete for a reader.** The nav, the page title, the h1, the run page's back link and its neighbour nav, the list's announcements, a run's heading and the trend table all say "Collaudi"/"Collaudo". No "Valutazion…" remains in on-screen copy. Test: Task 4.
5. **The header's station line never eats a click or a focus ring**: it stays `pointer-events-none` behind the links, and the 44 px targets are unchanged. Test: Task 4.

---

### Task 1: Paths from ROUTES, the dead listener, the toggle's classes

**Files:**
- Modify: `web/lib/routes.ts`
- Modify: `components/home/plan-list.tsx`, `components/evals/eval-dashboard.tsx`, `components/evals/eval-run-list.tsx`, `components/evals/eval-run-screen.tsx`, `components/evals/trend-chart.tsx`, `components/states/plan-ended.tsx`, `app/evals/[id]/error.tsx`, `app/dev/ui/page.tsx`
- Modify: `components/plan/map/itinerary-map-gl.tsx`, `components/plan/map/style.ts` (comment)
- Modify: `components/ui/theme-toggle.tsx`, `components/live/live-header.tsx`
- Test: `components/ui/invariants.test.ts`, `lib/routes.test.ts` (new), `components/ui/theme-toggle.test.tsx`

**Interfaces:**
- Produces: `planPath(id: string): string` → `/plans/${id}` and `evalRunPath(id: string): string` → `/evals/${id}`, in `web/lib/routes.ts`.

- [ ] **Step 1: Failing tests.**
  - `lib/routes.test.ts`: `planPath("p1")` is `"/plans/p1"`, `evalRunPath("r1")` is `"/evals/r1"`, and both encode their argument (`planPath("a/b")` is `"/plans/a%2Fb"`).
  - `invariants.test.ts`: a new case "spells no page path by hand" scans every `.tsx`/`.ts` under `app/` and `components/` (tests excluded) for `"/new"`, `"/evals"`, `"/plans"`, `` `/plans/ `` and `` `/evals/ `` inside `href=`, `router.push(` or `href:`. It allows only `lib/routes.ts`.
  - `theme-toggle.test.tsx`: the button's class list contains every class of `iconButtonClasses("md", variant)`.
- [ ] **Step 2: Run them.** `npx vitest run lib/routes.test.ts components/ui/invariants.test.ts components/ui/theme-toggle.test.tsx`. Expected: FAIL (no `planPath`; hand-written paths found; the toggle builds its own classes).
- [ ] **Step 3: Implement.**
  - Add `planPath` and `evalRunPath` (`encodeURIComponent`) to `routes.ts`.
  - Convert every hand-written path listed above to `ROUTES.*`, `planPath` or `evalRunPath`.
  - ThemeToggle: `className={cx(iconButtonClasses("md", variant), className)}`.
  - LiveHeader: `<ThemeToggle variant="bare" className="pointer-coarse:size-11" />`.
  - itinerary-map-gl: drop the `prefers-color-scheme` listener (dark is the default; only `data-theme` decides) and fix the comment in `style.ts` that says the system's scheme comes through.
- [ ] **Step 4: Run** `npm test`, `npm run lint` and `npm run typecheck`. Expected: all pass.
- [ ] **Step 5: Commit** `refactor(web): every page path from ROUTES; the toggle reuses the icon button`.

### Task 2: The token tests catch up with the palette

**Files:**
- Modify: `components/ui/tokens.test.ts`, `components/plan/map/style.test.ts`, `web/DESIGN.md`

- [ ] **Step 1: Failing tests.**
  - `tokens.test.ts`: parse `--selection: rgb(R G B / A)` from both theme blocks. Ink over the selection blended on ground and on surface is ≥ 4.5:1. The values must equal the DESIGN.md row "ink on selection (over ground / surface)", which gets added in Step 3.
  - `style.test.ts`: build the `light`/`dark` `MapPalette` fixtures from `globals.css` (the same parser as `mark.test.tsx`) instead of the old literal hex values. Update the "lines over water" expectation to the figures DESIGN.md states.
- [ ] **Step 2: Run** `npx vitest run components/ui/tokens.test.ts components/plan/map/style.test.ts`. Expected: FAIL (no DESIGN row; the water figures differ: about 3.49 light and 3.98 dark).
- [ ] **Step 3: Implement.**
  - Add the selection row to DESIGN.md's "Measured contrast" table.
  - Update "3.64:1 … 5.4:1" in DESIGN.md ("Map") to the measured figures.
  - The scrim gets no WCAG pair: it is non-text under a sheet, and the cover's gradient sits over photos whose contrast cannot be computed. Say so in a test comment.
- [ ] **Step 4: Run** `npm test`. Expected: pass.
- [ ] **Step 5: Commit** `test(web): the token tests measure the selection and build map fixtures from globals.css`.

### Task 3: The theme swaps without a grey flash

**Files:**
- Modify: `components/ui/theme-toggle.tsx`, `app/globals.css`, `web/DESIGN.md` (Motion)
- Test: `components/ui/theme-toggle.test.tsx`

**Interfaces:**
- Produces: the CSS hook `html[data-theme-swap] *, html[data-theme-swap] *::before, html[data-theme-swap] *::after { transition: none !important; }`.

- [ ] **Step 1: Failing tests (fake `requestAnimationFrame`).**
  - After a click, `<html>` has `data-theme-swap` until two animation frames have run, then loses it.
  - Two clicks within one frame leave it removed after the frames run (Review Focus 1).
- [ ] **Step 2: Run.** Expected: FAIL (no attribute).
- [ ] **Step 3: Implement.**
  - In `toggle()`, set `data-theme-swap` before changing `data-theme`.
  - Remove it after two `requestAnimationFrame`s, the first paint with the new colours. A counter keeps overlapping toggles from removing it early or leaving it on.
  - Add the CSS rule, and a line to DESIGN.md's Motion table ("Theme switch: instant, transitions off for one frame").
- [ ] **Step 4: Run** `npx vitest run components/ui` and look at the swap in the browser: no grey frame.
- [ ] **Step 5: Commit** `fix(web): the theme swaps without a grey flash`.

### Task 4: The header's line (option B) and "Collaudi"

**Files:**
- Modify: `components/nav/app-header-bar.tsx`, `app/evals/page.tsx`, `app/evals/[id]/page.tsx`, `components/evals/eval-run-list.tsx`, `components/evals/eval-run-screen.tsx`, `components/evals/run-header.tsx`, `components/evals/trend-chart.tsx`, `web/DESIGN.md` (Navigation), `web/PRODUCT.md`
- Test: `components/nav/app-header.test.tsx`, the evals tests that assert the copy, and `components/ui/invariants.test.ts`

- [ ] **Step 1: Failing tests.**
  - The first station's outer half-line is the fixed overhang: class `w-6` and `right-1/2`. The last station's outer half is `w-6 left-1/2`. Inner halves span to the item edges.
  - Each half-line is `pointer-events-none`, 1 px below `lg` and 2 px from `lg` (`h-px lg:h-0.5`).
  - The nav item says "Collaudi".
  - `invariants.test.ts` "no Valutazion… in on-screen copy" scans `app/` and `components/` (tests excluded).
  - The evals tests expect "Collaudi"/"Collaudo".
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `Station` takes `edge: "first" | "middle" | "last"`. The outer half is `w-6` toward the centre; the inner half spans the item. Station y centre: `bottom-[13px]` for 1 px, `lg:bottom-[12.5px]` for 2 px.
  - Rename the copy:
    - "Valutazioni" → "Collaudi" (nav, `metadata.title`, h1, back link, `aria-label` "Collaudi vicini");
    - "Valutazione del …" → "Collaudo del …";
    - list announcements "Collaudi da X a Y di Z";
    - the trend table's column "Collaudo";
    - `/evals/[id]` metadata "Collaudo".
  - Update DESIGN.md and PRODUCT.md where they name the section.
- [ ] **Step 4: Run** `npm test` and check the header at 393 and 1280 px, dark and light.
- [ ] **Step 5: Commit** `feat(web): the header's line is local and heavier; Valutazioni becomes Collaudi`.

### Task 5: The small mark (option C) and a favicon

**Files:**
- Modify: `web/lib/brand-mark.ts`, `components/ui/mark.tsx`, `components/ui/wordmark.tsx`, `app/icon.svg`, `web/DESIGN.md` (Brand)
- Create: `app/favicon.ico/route.ts`
- Test: `components/ui/mark.test.tsx`, `app/favicon.ico/route.test.ts`

**Interfaces:**
- Produces:
  - `MARK_GEOMETRY_SMALL` (same keys as `MARK_GEOMETRY`): flights `M8.5 35 L20 7` width 5.4, lodging `M31.5 35 L20 7` width 5.4, coordinator `M12.6 25 H27.4` width 5.6, station `(20, 7.5)` r 3.5 width 2.
  - `markSvg(colors?, geometry?)`.
  - `<Mark small />`.

- [ ] **Step 1: Failing tests.**
  - `<Mark small />` draws the station with `r=3.5` and the crossbar with width 5.6.
  - `<Mark />` keeps r 4.6.
  - The Wordmark's mark is small.
  - `markSvg(NIGHT, MARK_GEOMETRY_SMALL)` contains `r="3.5"`.
  - `GET` of `app/favicon.ico/route.ts` (vitest `node` environment) answers 200 with `image/png` and the PNG signature.
  - The route exports `dynamic = "force-static"`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The small geometry and `markSvg`'s geometry argument.
  - `Mark`'s `small` prop; the Wordmark passes it.
  - `icon.svg` scaled from the small geometry on its 32-unit tile.
  - The favicon route: a 32 × 32 `ImageResponse` with the night tile and the small mark.
  - DESIGN.md "Brand": "at 28 px and below the mark uses the small geometry".
- [ ] **Step 4: Run** `npm test`. Load `/favicon.ico` in the browser, and look at the header lockup at 28 px in both themes.
- [ ] **Step 5: Commit** `feat(web): the small mark reads as an A; /favicon.ico`.

### Task 6: The link preview's tagline and the plans page's ending

**Files:**
- Modify: `app/opengraph-image.tsx`, `app/plans/page.tsx`, `web/DESIGN.md`
- Create: `components/home/plans-footer.tsx`
- Test: `components/home/plans-footer.test.tsx`, `app/plans` page test if present

- [ ] **Step 1: Failing tests.**
  - `PlansFooter` renders a link "Come funziona" to `` `${ROUTES.home}#come-funziona` ``.
  - The plans page renders the footer after the list, so the page ends on it, not on the photo credit.
  - `taglineLines(BRAND_TAGLINE)` returns `["Ogni viaggio ha", "il suo atlante."]`: the split keeps the article with its noun, never "…ha il / suo…".
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `taglineLines` in `lib/brand.ts`, beside the tagline: it breaks before the last word group that starts with an article, "il"/"lo"/"la"/"i"/"gli"/"le"/"un"/"una".
  - The OG image renders the two lines as two block `div`s.
  - `PlansFooter` in `app/plans/page.tsx` after `<main>`.
  - A DESIGN.md line under Navigation/Home.
- [ ] **Step 4: Run** `npm test`. Load `/opengraph-image` and `/plans` in the browser.
- [ ] **Step 5: Commit** `feat(web): the link preview's tagline breaks cleanly; /plans ends on "Come funziona"`.

### Task 7: Verification, critique, review, PR

- [ ] **Step 1:** `npm run gen:schemas -- --check && npm run lint && npm run typecheck && npm test && npm run build` (into `.next-build`), then `npm run measure:js`; `git checkout -- tsconfig.json`. Expected: green, and `/plans/[id]` ≤ 192.4 KB.
- [ ] **Step 2:** Browser: `/plans`, `/new`, `/evals`, a plan page, `/dev/ui`'s mark section, at 393 and 1280 px, dark and light; the theme swap; `/favicon.ico`.
- [ ] **Step 3:** One dual-agent impeccable critique round on the app screens (target `web/app/plans/page.tsx` plus the header on `/new`, `/evals`, a plan page, and the mark). Fix P0/P1, then at most one confirmation round. Record it in `web/.impeccable/critique/brand-step1-polish.md`.
- [ ] **Step 4:** A fresh whole-branch reviewer (opus) with this plan and its Review Focus. Fix Critical/Important with RED→GREEN; ledger the minors.
- [ ] **Step 5:** Push `feat/atlas-brand-polish` and open the PR against `main`. Cover: the decisions, the minors fixed, the critique score, the JS figures, the deferred items.
