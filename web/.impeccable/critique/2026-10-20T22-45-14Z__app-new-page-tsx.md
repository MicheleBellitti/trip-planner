---
target: /new, after the first critique fixes
total_score: 29
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 0
target_identity: "file:/Users/michb/dev/trip-planner/.claude/worktrees/journey-mode-form/web/app/new/page.tsx"
target_fingerprint: "sha256:7674cc65a6771006d72864b19eda733a8247a0b6afd5b8bd2cd2ff684139b33b"
target_path: /Users/michb/dev/trip-planner/.claude/worktrees/journey-mode-form/web/app/new/page.tsx
timestamp: 2026-10-20T22-45-14Z
slug: app-new-page-tsx
---
Method: dual-agent (A: design review · B: detector + browser overlay). B's browser evidence is partial: passes at 1440 after "Traghetto" and in light theme were not run (the permission classifier denied B's browser calls after a shared-tab mix-up), and its 393 px pass landed on A's tab and is discarded.

Target: `/new` (web/app/new/page.tsx) after the first critique's fixes: the mode hint as the group's description, the ferry/car note in a polite live region, mode-neutral copy, the 1.25:1 desktop grid with 16 px between fields, the "Date" legend for screen readers only, the read-back naming every mode. Checked at 393, 1080 and 1440 px, dark and light, keyboard and focus live; submission judged from the code (the classifier refused the click on the paid button).

## Design health score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | The read-back shows unfinished dates as finished ("7 notti" without a month, "Dal 14 giugno 2027" without a return), in ink rather than the missing style |
| 2 | Match system / real world | 3 | "Traghetto" vs "Auto" (car on a ferry) is a real-world trap; the note explains it only after the wrong pick |
| 3 | User control and freedom | 3 | No "let the planner decide" (by spec); a mixed trip (train out, plane back) can only go in Preferenze, and nothing says so |
| 4 | Consistency and standards | 3 | The chosen pill is filled exactly like the primary button |
| 5 | Error prevention | 3 | Enter from "Dove vuoi andare" jumps to "Partenza", so the fast path never meets the mode and Aereo goes out unseen |
| 6 | Recognition rather than recall | 3 | No read-back on the phone before a 2–4 $ commit |
| 7 | Flexibility and efficiency | 2 | The mode is not remembered (by spec: Aereo on every open); a habitual train traveller re-picks Treno every time |
| 8 | Aesthetic and minimalist design | 3 | Three filled pills on the phone's first screen compete for primary weight; ragged 3+2 wraps at 393 and 1080 |
| 9 | Error recovery | 3 | Sound in code (summary from three problems, focus to the problem, per-field wording); not tested live |
| 10 | Help and documentation | 3 | Nothing says local travel stays with the planner, or that the run will pause to ask |
| **Total** | | **29/40** | **Good** |

## Design specificity verdict

**LLM assessment.** Specific, not templated: Barlow headings in cream on the ink ground, hairline sections, no glow; the read-back's route line with station rings is the form's signature. The mode chips are the generic part (the rail-and-flight-site pill), competent and consistent with SegmentedControl, but the mode never touches the line-map language: it is a bullet under the route.

**Deterministic scan.** `impeccable detect --json` over `app/new/page.tsx`, `components/request/`, `components/ui/field.tsx`, `components/ui/icons.ts`, `app/dev/ui/demos.tsx`: 0 findings (exit 0).

**Visual overlays.** In-page detect.js at 1440×900 dark: 1 finding, `line-length ~89 chars` on the page intro (`app/new/page.tsx:32`, `max-w-prose` resolves to 65ch on Barlow's wide "0", about 89 characters); a real measurement on a two-line lede that predates this change, low weight. A follow-up `text-occlusion` hit the detector's own label (false positive). A `cream-palette` hit from the discarded pass is the documented light ground `#F4EFE4` (false positive). No overlay remains visible: B's tab was reset by a navigation.

## What's working

- **ChoiceChips is solid primitive work**: native radios in a fieldset, arrow keys, the hint heard once as the group's description, a persistent polite live region for the note, a 2 px focus ring, 46 px tap areas, the grammar of SegmentedControl.
- **The ferry and car notes are domain care with restraint**: only for the two confusable modes, in plain Italian.
- **The desktop read-back** turns the form into a sentence and names the mode ("In aereo") before money is spent; the sticky card keeps the button in view at every desktop width.

## Priority issues

1. **[P2] The Enter fast path skips "Come viaggi".** `advanceOnEnter` skips the radios of an answered group, so Enter from the destination lands on "Partenza": on the phone, where nothing reads the request back, the default Aereo goes out unseen (a paid flight plan for Milano–Firenze). Fix: make the mode group an Enter stop (Enter from the destination focuses the chosen mode, Enter there goes to the dates). Command: /impeccable harden.
2. **[P3] The read-back shows incomplete dates as complete.** "7 notti" without a month, "Dal 14 giugno 2027" without a return, in ink. Fix: "7 notti, mese da scegliere", "…, ritorno da scegliere", in ink-2 (predates this change). Command: /impeccable clarify.
3. **[P3] The note is announced but not described.** Returning to the group with Traghetto chosen, a screen reader hears the hint but not the note. Fix: add the note's id to the fieldset's `aria-describedby` while it has text. Command: /impeccable harden.
4. **[P3] Chosen pills carry primary-button weight; the rows wrap raggedly.** Fix: chips that grow to fill each row, or a lighter chosen state for choice controls (ink edge on notice-wash, as the map's day picker). Command: /impeccable polish.
5. **[P3] The hint stops short.** Fix: "Per andata e ritorno; gli spostamenti sul posto li sceglie il planner." Command: /impeccable clarify.

## Persona red flags

**Jordan (first-timer).** The preselected Aereo reads as decoration, not a question; picks "Traghetto" for "we bring the car" and is corrected only after the tap.

**Sam (screen reader / keyboard).** The group is well wired ("Come viaggi", group, hint, radio "Aereo", checked, 1 of 5; arrows; visible focus). Enter from the destination skips the group; the note is not part of the group's description on return; in browse mode the hint is read twice.

**Casey (one-handed phone).** The row sits at y ≈ 380–470, a thumb stretch, with Aereo and Auto at the far left; the button is at the bottom of a ~1660 px page with no read-back, so Casey sends without seeing the mode again.

## Minor observations

- The "viaggio" word family appears six times on the screen.
- The read-back could keep the ferry nuance ("In traghetto, a piedi", "In auto, traghetti compresi").
- At 16 px the `train` chip is close to the spostamenti line's `tram`.
- At 1080 px three narrow columns (333 / 266 / 320), the steppers stack, the dates sit below a 900 px fold; at 1440 the two-option tracks stretch to 524 px.

## Questions to consider

- Should the form remember the last mode? The form already remembers the origin; Aereo on every open throws away a habit.
- Should the mode label the route line's segment, as a transit diagram labels a line, instead of a bullet under it?
- Does the phone now need a one-line request summary above the button, now that a silent default decides what gets researched?
