# Brand step 1 polish: critique, two rounds (2026-10-17)

Target: `/plans`, the app header (on `/plans`, `/new`, `/evals` and a plan page) and the mark. The
surface is Operate, so all ten heuristics are scored, out of 40. The previous record,
`brand-step1.md`, scored 27/40; that run's target was the old home, which is now `/plans`.

Michele's decisions, taken from a mockup before the work:
- header option B (a local line, 2 px, the same overhang on both sides);
- mark option C (at 28 px and below, a lighter station and thicker strokes);
- "Collaudi" for the eval history.

## Round 1: 28/40 (Good; P0 0, P1 0)

Method: dual-agent (A, design review; B, detector plus browser).
- [P2] The `/plans` skeleton had no featured card, so the list jumped about 296 px on the phone.
  Fixed in 645c868: the placeholder takes the card's final shape (measured within 1 px).
- [P2] "Budget raggiunto" named the API cost cap. Fixed: "Limite raggiunto" ("budget" stays with
  the trip's money, as DESIGN.md's CostMeter rule says).
- [P2] "Atlas" was hidden at 393 px. Fixed: the name shows from 360 px.
- Minor: `/favicon.ico` drew a lighter mark than `icon.svg`. Fixed: it rasterises `icon.svg`.

## Round 2 (confirmation): 28/40 (Good; P0 0, P1 0)

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 3 | Featured skeleton within 1 px; the rows' skeleton has no group heading |
| 2 | Real world | 3 | "il planner" in the error copy; Bloccato vs Non riuscito not explained |
| 3 | Control | 3 | The help lands on the public landing; failed runs cannot be hidden |
| 4 | Consistency | 3 | The stations shift ~50 px and the header goes 65 → 56 px on plan pages |
| 5 | Error prevention | 3 | Easy to open the wrong one of several same-titled runs |
| 6 | Recognition | 3 | Identical runs are told apart only by the minute |
| 7 | Flexibility | 2 | No shortcut, filter, search or archive |
| 8 | Aesthetic | 3 | The same photo 8 times on the phone; the cream rail is the brightest mark |
| 9 | Error recovery | 3 | Good; "Riprova più tardi" sits beside an immediate Riprova |
| 10 | Help | 2 | One link at the foot of `/plans`, and it leaves the app |

Detector: the CLI found 0; the browser found 0 in dark, and in light flags only the declared cream
ground. Skeleton against loaded page: 1 px at 393, 0 at 1280.

- [P2] The help's client navigation logged React's script-tag error. Fixed: the link does a full
  load.
- Deferred to Michele:
  - [P2] The stations shift on plan pages. Options: a spacer in the compact bar, or stations
    anchored on the left.
  - [P2] Phone thumbnails squeeze the titles and repeat the same photo.
  - [P2] The landing offers "Accedi" to a signed-in visitor who came for the help.
  - [P3] The rows' skeleton has no group heading.
  - [P3] `aria-current="page"` sits on the section link of detail pages.
  - The full mark still reads as a compass at 40–64 px.

## Gate

28/40 after the confirmation round: up one from 27, below the 32 gate and the 35 aim, with no P0
or P1 open. The rest are design decisions, listed above for Michele: the stations on plan pages,
the list's thumbnails and grouping by trip, contextual help, a shortcut and a filter.
