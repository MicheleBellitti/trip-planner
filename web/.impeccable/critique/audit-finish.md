---
target: all screens (/, /new, /plans/[id] running, budget_paused, failed, blocked, ready, not-found)
kind: audit (impeccable audit flow: accessibility, performance, theming, responsive, implementation integrity)
date: 2026-10-12
total_score: 17
max_score: 20
p0_count: 0
p1_count: 0
---

# Technical audit, closing pass

How: `impeccable detect app components lib` (0 findings) and on `/` and `/new` (2 findings on `/`, both
false positives, below); a measuring script injected in the real browser (own tab) at 393 and 1440 px,
light and dark, on the demo stack: contrast of every visible text node against its composited real
background, target sizes, accessible names, ids, headings, landmarks, live regions, horizontal scroll;
Tab order and focus rings by key; focus-not-obscured by scrolling a control under the sticky bar.
Reduced motion verified in code (every animation has a `motion-reduce` branch). No money spent.

## Audit health score

| # | Dimension | Score | Key finding |
|---|---|---|---|
| 1 | Accessibility | 3 | Focus obscured by the sticky bar (fixed), message rows under 24 px (fixed), plan state arrived silently (fixed) |
| 2 | Performance | 3 | `/plans/[id]` 213.0 KB gzip first load, now 189.1 (budget 180 not reached, see README) |
| 3 | Responsive | 4 | No horizontal scroll at 393 or 1440; targets 44 px on touch |
| 4 | Theming | 4 | 0 contrast failures in 12 measured screen/theme/width combinations; tokens test passes |
| 5 | Implementation integrity | 3 | Dead `components/shells/` remains (could not be deleted by this pass) |
| **Total** | | **17/20** | **Good** |

## Findings and what was done

- **[P1, fixed] Focus and in-page jumps went under the sticky bar.** On the phone `LiveHeader` measured a
  `display: contents` element, so `--live-bar-h` was `0px` while the sticky state bar is 125 px: a control
  focused from below ("Continua con 2 $ in più" at y=51 under the bar) and the "Ora: ..." jump both landed
  hidden (WCAG 2.4.11). The header now measures the real sticky element, AgentLanes publishes the heads strip
  height, and `html` carries `scroll-padding-top` from both (and `scroll-padding-bottom` for the "Vai all'ultimo"
  pill). Re-measured: not covered.
- **[P2, fixed] Message rows were 20 px tall** (WCAG 2.5.8 needs 24): 24 px with a mouse, 44 px under a finger
  (`pointer-coarse`), the rhythm kept by a negative margin.
- **[P2, fixed] A plan that stopped (budget reached, failed, blocked, interrupted) arrived silently** to a
  screen reader: the single polite region now also says "Piano: budget raggiunto" (test added).
- **[P2, fixed] "I tuoi piani" back link 32 px, a stop's page link 19 px**: 44 px (negative margin) and 27 px.
- **[P3, fixed] Unmatched addresses showed Next's English 404**: `app/not-found.tsx` in the product's voice (also what
  `/dev/*` answers in production). A root `error.tsx` was tried and dropped: a client component there rides in every
  route's first load (+10 KB), and the plan page already has its own. `not-found.tsx` is server markup only for the
  same reason (a theme toggle or `next/link` in it added 4 KB to the plan page).
- **[P3, open] `components/shells/`** (three unused unstyled shells, one with a second `aria-live`) is dead code;
  nothing imports it. Delete the directory.
- Detector false positives: `clipped-overflow-container` on the home list (the clip is deliberate: it keeps the
  rail and the hover wash inside the rounded corners and nothing positioned escapes), and
  `content-hidden-at-rest` (the rows inside the closed "Mostra gli altri N" disclosure).
- Measuring-script false positives, verified by hand: names empty on links and summaries inside closed
  `<details>` (not focusable, no box to the browser), 1 px radio inputs of the segmented fields (their 40 px label
  is the target).

## Positive findings

0 contrast failures on real backgrounds in light and dark at both widths; one `main`, one `h1`, ordered headings,
no duplicate ids, one live region, no unlabelled field; a visible 2 px ring on every control; `inert` closed
lanes; every motion has a reduced-motion alternative; link targets open in a new tab with `rel="noopener
noreferrer"` and say so for screen readers.
