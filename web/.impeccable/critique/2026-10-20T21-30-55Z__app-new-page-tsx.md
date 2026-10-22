---
target: /new, the request form with the travel mode row
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 0
target_identity: "file:/Users/michb/dev/trip-planner/.claude/worktrees/journey-mode-form/web/app/new/page.tsx"
target_fingerprint: "sha256:59d19dfd8035d30e2843d8aff3ca3cc0f8d2486f9fe553eec8f08f5d679445c1"
target_path: /Users/michb/dev/trip-planner/.claude/worktrees/journey-mode-form/web/app/new/page.tsx
timestamp: 2026-10-20T21-30-55Z
slug: app-new-page-tsx
---
Method: dual-agent (A: design review · B: detector + browser overlay)

Target: `/new` (web/app/new/page.tsx), focused on the new "Come viaggi" travel-mode row (`ChoiceChips`) and the read-back card. Checked at 320, 393, 1080, 1180, 1280 and 1440 px, light and dark; empty, Treno, Auto, "Suggeriscimi tu" + Traghetto + month and nights + 2 children, and the empty-submit error state.

## Design health score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | The desktop read-back updates live; the phone (primary device) has no read-back before the paid button |
| 2 | Match system / real world | 3 | Copy stays plane-centric after a mode is chosen ("Una città o un aeroporto", "MXP", "voli" in the budget hint and the preferences placeholder) |
| 3 | User control and freedom | 3 | All editable; the contract's "the coordinator decides" (null) is not offered, by spec |
| 4 | Consistency and standards | 3 | Two neighbouring radio groups look different (full-width track vs ragged 3+2 wrap); the read-back names every mode but the plane |
| 5 | Error prevention | 3 | Traghetto (foot passengers) vs Auto (car ferries included) is the likeliest wrong pick and is guarded only by a cryptic hint |
| 6 | Recognition rather than recall | 3 | Icons plus labels, all visible; on the phone, checking the request means scrolling about 1,000 px back up |
| 7 | Flexibility and efficiency | 3 | Example request, remembered party, Enter-advance, arrow keys |
| 8 | Aesthetic and minimalist design | 3 | Calm and on-brand; desktop composition weak: ~240 px hole under the right column, the left column past the fold, 2+2+1 chip break at 1080 |
| 9 | Error recovery | 4 | Summary from 3 problems with links, field-specific messages, 422s mapped back, focus lands on the checked radio |
| 10 | Help and documentation | 3 | Every field has a hint; the mode hint is the weakest on the page |
| **Total** | | **31/40** | **Good** |

## Design specificity verdict

**LLM assessment.** The system is authored; the new component is generic. The road-sign Barlow type, the cream-on-ink pills, the hairline sections, the Italian voice and the read-back's route line drawn with the station glyphs belong to Atlas alone. The "Come viaggi" row is the category-standard transport-pill pattern (Omio, Rome2Rio, Google Maps), drawn faithfully in Atlas tokens: ink when chosen, `rule-strong` edge, Phosphor bold, the same focus ring and tap-area maths as SegmentedControl. It breaks nothing but uses none of the line-map language: the most interchangeable element on the screen.

**Deterministic scan.** `impeccable detect --json` over `app/new/page.tsx`, `components/request/`, `components/ui/field.tsx` and `components/ui/icons.ts`: 0 findings (exit 0). The purple check was skipped on purpose (DESIGN.md declares `line-activities`). Agreement: the detector and the review find nothing mechanical; every issue below is composition, copy or semantics, outside the detector's reach. False positive from the evidence pass: "40 px chips below a 44 px target" measured the pill's box; the `::before` extension makes the tap area 46 px (measured).

**Visual overlays.** detect.js was injected in a "[Human] Nuovo piano · Atlas" tab at 1440×900 and 393×852: "No anti-patterns found." both times, so the overlay has nothing to highlight. The live server was stopped.

## Overall impression

A disciplined, accessible extension of the form that does its job in one glance. Its weak points are around it rather than in it: copy that still assumes a plane, a hint that explains half the Auto/Traghetto fork, and a desktop grid that was balanced for one less row.

## What's working

- **ChoiceChips is a disciplined extension of the system.** Native radios in a fieldset with a legend (Tab lands on the chosen mode, arrows move it), 40 px pills with a 46 px tap area, the 2 px ink focus ring, the chosen-state language of SegmentedControl, Phosphor bold icons with the plane matching the flights line.
- **The error flow is first-rate.** A 422 on the mode lands under the row with the focus on the chosen chip.
- **The read-back card.** The route line uses the map's station glyphs, missing facts read in ink-2, it is sticky with the button, and the mode slots in as its first fact.

## Priority issues

1. **[P2] The copy ignores the chosen mode.** The origin hint and placeholder ("Una città o un aeroporto", "Milano, oppure MXP"), the budget hint ("voli, alloggio…"), the preferences placeholder ("Niente voli prima delle 8") and the page intro ("cercano voli") contradict a Treno or Auto choice; the placeholder even teaches people to write mode constraints into preferences, the conflict the spec settles with a paid pause. Fix: mode-neutral copy ("Una città, una stazione o un aeroporto", "Per esempio Milano"; "viaggio, alloggio, attività e spostamenti"; "Partenza non prima delle 8, quartiere tranquillo, cucina locale"). Command: /impeccable clarify.
2. **[P2] The mode hint is a riddle and explains half the fork.** "Per andata e ritorno. L'auto è la tua, anche se serve un traghetto." never says Traghetto means on foot, the real fork for Olbia, Elba or the Greek islands; "Per andata e ritorno" can read as "round-trip ticket". Fix: "Vale per andata e ritorno." plus a one-line note under the chips only for the two modes that need it (Traghetto: "Senza auto: se la porti, scegli Auto."; Auto: "La tua auto, anche sui traghetti."). Command: /impeccable clarify.
3. **[P2] Desktop composition after the new row.** At 1440×900 the left column is 748 px and runs about 90 px past the fold (about 140 px with "Suggeriscimi tu" and month and nights) while the right column leaves a ~240 px hole and ~236 px of width sits unused right of the card; between 1080 and 1179 px the chips break 2+2+1 and the month select clips to "Agosto 202". Root cause: the form is capped at 50rem and split 1:1 though the left column is taller. Fix: from `xl`, lift the cap to about 60rem and go asymmetric (about 1.25fr / 1fr) so the chips fit one row; visually hide the redundant "Date" legend; below `xl`, a 3-column chip grid (3+2). Command: /impeccable layout.
4. **[P3] The read-back drops the plane.** The form always sends `flight` now, yet Aereo makes no fact, and switching Treno to Aereo removes a row and moves the sticky button 28 px. Fix: always state the mode, or draw it on the route line. Command: /impeccable polish.
5. **[P3] Screen-reader verbosity.** The hint is each radio's description, so its 67 characters repeat on every arrow press. Fix: describe the fieldset once; keep the error on the radios. Command: /impeccable harden.

## Persona red flags

**Jordan (first-timer).** Driving to Sardinia, picks "Traghetto" and gets foot-passenger research. Reads "Per andata e ritorno" as a round-trip ticket. Sees "aeroporto" and "MXP" above a chosen Treno.

**Sam (screen reader / keyboard).** Group announced, radios named, arrows work, focus visible. The hint repeats on every arrow press. Moving by Enter skips the (already answered) mode group, so a user who only presses Enter travels by plane; Tab does reach it. On the phone there is no read-back before the button.

**Casey (one-handed phone).** The chip row sits at y 670–760 of 852, in thumb reach. The row pushed "Quando" below the first screen; the form is about 2.1 screens with the button at the bottom and no read-back, so checking the mode before paying means scrolling back up. At 320 px the chips take three rows.

## Minor observations

- At 16 px the train and bus glyphs are near-twins; the labels carry them.
- The form's Treno uses `train` while the spostamenti line that researches a train journey uses `tram`.
- The children's age selects clip "Meno di 1 anno" at every desktop width (predates this change).
- "In treno" sits below the hairline, apart from the route it describes.
- The mode is not remembered between requests (defensible: it belongs to the trip; the spec says Aereo on every open).
- At 320 and 393 px nothing scrolls sideways; light-theme contrast holds.

## Questions to consider

- The read-back already draws the trip as a line between two stations, and transit maps tell rail, ferry and road apart by line style. Why is the mode a text fact under a hairline instead of the segment itself (labelled "in treno", dashed for the ferry, the plane included)?
- Ferry bookings have no seller on the allowlist yet (`link: null`). Is Traghetto a first-class choice, or an edge case that ends in a plan with no booking button for the main journey?
- The phone is the primary device; if a summary beside the button earns a card on desktop, why not a one-line ticket above the phone's button?
