---
target: the choice cards (the live plan page's pause on /plans/[id], phone and desktop; the demo's pause on /demo)
slug: components-choice-choice-panel-tsx
round: 2
total_score: 33
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
---

⚠️ DEGRADED: single-context (the task's brief forbids sub-agents; Assessment A was scored before the detector ran, then Assessment B)

# Impeccable critique, round 2 (confirmation): the choice cards

Same screens as round 1, after the fixes. Seen in the browser again on fresh runs: live at 393 dark (2-minute window: arrival, two picks and "Continua con queste", then the food question left to its deadline, the minute note at 1:00); `/demo` at 1440 light (arrival, keyboard path, a click on a photo, a credit opened, then a passive watch through both pauses) and at 393 dark (a passive watch through both pauses).

## Design health score: 33/40 (Good; no P0, no P1; one above the 32 gate)

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 4 | The whole question arrives on screen (desktop: panel 272 to 852 in a 900 px window; phone without photos: 134 to 776). After "Continua" the coordinator's line says "Hai scelto: Oceanário de Lisboa, Torre di Belém e Mosteiro dos Jerónimos" on the closed phone card; after a deadline "Tempo scaduto: sceglie Atlas". On the phone with photos the clock is under the cards, after them, where the buttons are |
| 2 | Match system / real world | 3 | Unchanged: plain Italian throughout; "Scegli tu" after "Scegli quelle che ti piacciono" is the one ambiguous phrase (the spec's copy) |
| 3 | User control and freedom | 3 | Unchanged; an iPad crossing 1080 px still remounts the panel and loses the picks |
| 4 | Consistency and standards | 4 | Each credit is named after its option; the buttons stay put while the count changes (151/249 px before and after the first pick); one system of rings, chips, ink buttons |
| 5 | Error prevention | 3 | Unchanged, good: primary disabled with no pick, rest at zero, deadline kept across a reload |
| 6 | Recognition rather than recall | 4 | The rule, the clock and the way forward are on screen together on desktop; the eyebrow says whose findings these are |
| 7 | Flexibility and efficiency | 3 | Tab goes card, its credit, next card; Space picks; "Scegli tu" is one tap. No shortcut (none needed) |
| 8 | Aesthetic and minimalist design | 3 | The 64rem grid keeps the panel a compact left-aligned block (cards 332x370 at 1440 instead of 450 px wide); calm and flat. The third card alone on the phone's second row is the spec's grid |
| 9 | Error recovery | 3 | Unchanged (tested paths: failed send keeps the picks, 409 shows the backend's sentence) |
| 10 | Help and documentation | 3 | Unchanged: the rule stated once; what a pick changes is left to guess |
| | **Total** | **33/40** | **Good: the panel now lands whole and leaves a trace; what is left is copy and one rare layout case** |

## Verification of round 1

| Round 1 item | Verdict | Evidence this round |
|---|---|---|
| P2 desktop arrival: clock and buttons below the fold | **Fixed** | `/demo` 1440x900 light: heading focused, `#scelta` top 272, last button bottom 852 (was 530 to 1146); the grid is at most 64rem (`max-w-[64rem]`, the plans list's measure), photos request `21rem` (the 500 px thumbnail is fetched); test `focuses its heading when it appears, and brings its top into view` |
| P2 focus to the page after a passive answer | **Fixed** | Live, the food question's deadline: focus `SPAN#plan-state`; `/demo` both recorded answers: `plan-state` (was `BODY`). A focus moved elsewhere stays (test `hands the focus to the plan's state when the question leaves with it`). "Interrompi" still lands on `#plan-state` as before |
| P2 phone: no trace of the answer | **Fixed** | Live 393: the closed coordinator card reads "Hai scelto: Oceanário de Lisboa, Torre di Belém e Mosteiro dos Jerónimos" until the coordinator's next station; test in `stations.test.ts` |
| P2 credits: one name, before the card in Tab | **Fixed** | Tab: `INPUT a1`, "Crediti della foto: Oceanário de Lisboa", `INPUT a2`, "Crediti della foto: Palácio da Pena a Sintra", ...; a click on a photo picks its card, a click on its credit does not (browser and test) |
| P3 the count moves the buttons | **Fixed** | `sm:min-w-[14ch]`: buttons at 151/249 px with "Nessuna scelta" and with "1 scelta" |
| P3 the minute note stays in the atomic region | **Fixed** | Said at 1:00; it leaves with the region's next words (test with "Alloggio: finito" during the last minute) |
| P3 crossing 1080 px remounts the panel | **Open** | Not touched: the two slots are two places in the tree. Rare (an iPad turning during a 4-minute window) |
| P3 credit strip covers half a phone photo | **Open, accepted** | On demand, closes on the same button |
| P3 "Scegli tu" voice switch | **Open, question** | The spec's and the plan's copy |
| P3 a credit tap does not stop the demo's clock | **Open** | Reading a credit is not taking over; 15 s is short to read one |

## Design specificity verdict

**LLM assessment (before the detector).** Unchanged from round 1: authored, the run asking a question on its own line. The fixes are all placement and hand-off; none adds chrome. The eyebrow above the question is the spec's attribution line (whose findings, with the line's roundel), not a decorative kicker: no caps, no tracking, it carries information.

**Deterministic scan.** `impeccable detect --json` over `components/choice`, `choice-card.tsx`, `countdown.tsx`, `plan-screen-view.tsx`, `stations.ts`: the same single `broken-image` false positive (`choice-card.tsx`, the `<img>` whose `src` is an expression). No overlay re-run: round 1's in-page scan found nothing in the panel and the fixes change no colour or type. Contrast unchanged (no token touched). Horizontal overflow at 393: none.

## What's working

1. **The whole question lands at once** on desktop: eyebrow, question, rule, three photos, clock and buttons in one window.
2. **Every ending leaves a trace and a focus**: the traveller's answer, the deadline, the demo's recording and "Interrompi" all put the focus on the plan's state, and the coordinator's line or station says what was chosen.
3. **The demo's camera still follows the work** after both pauses, on the phone (Alloggio, Coordinatore, Spostamenti) and on desktop (the coordinator's newest station stays in view).

## Priority issues

None at P0, P1 or P2.

### [P3] Left as they are
- **Crossing 1080 px remounts the panel** (picks lost, the heading takes the focus again). Fixing it means one slot for both layouts (a CSS order on the page's main column) or the picks held above the panel; neither is small, and the case is rare.
- **"Scegli tu"** reads as the traveller's own verb right after "Scegli quelle che ti piacciono". A question for Michele: the copy is the spec's.
- **The demo's clock ignores a credit tap.**
- **On the phone with photos the clock sits under the cards**, with the buttons. It is the reading order (pick, then act); a sticky action row would show it all the time, at the cost of a second sticky surface.

## Persona red flags

**Michele on the Mac.** None left: the question, its clock and its buttons arrive together; the answer is the coordinator's newest station.

**Michele on the iPhone.** The panel sits under the bar; after "Continua" the coordinator's closed card says what he chose.

**Sam, keyboard and screen reader.** Tab: card, its named credit, next card, then the buttons; after a deadline the focus is on the plan's state; the minute is said once.

**Riley.** Rotating an iPad across 1080 px during a question loses the picks (P3, open).

## Minor observations

- After the live deadline on the phone the page sits at its top: with every card closed it is shorter than the window, so there is nothing left to scroll.
- `sizes` now says `21rem` from 1080 px: at 1x the 500 px thumbnail is fetched for a 332 px card.

## Questions to consider

- "Scegli tu" or a wording that names Atlas, given the intro just used "Scegli" for the traveller?
- Should a question survive an iPad turning (one slot, moved by CSS), or is the remount acceptable for a 4-minute window?
