# Front door (landing `/`): critique, two rounds (2026-10-17)

Surface mode: Persuade. Heuristics 7 (flexibility) and 10 (help) are n/a, so totals are out of 32;
the project's gate (≥ 32/40) is 80 %, i.e. 26/32.

## Round 1: 23/32 (72 %, Good; P0 0, P1 1)

Method: dual-agent (A: design review · B: detector + browser).

- [P1] Phone: the one choreographed moment ended off-screen ("Lisbona" at 795–858 px of 812). Fixed
  in 691989d: the phone map is short (destination at ~615 px of 852).
- [P2] The inert "Prenota su Expedia" looked like the page's real primary buttons. Fixed: a visible
  "Esempio" tab on every sample frame; the sample button is secondary.
- [P2] The lede did not say the agents are software. Fixed: "Cinque agenti AI".
- [P2] Phone map labels touched the lines. Fixed: new layout, every label clear of every stroke.
- [P3] The live plate contradicted "piano pronto". Fixed: the plate belongs to the run; it retires
  before the destination stamps and is hidden at rest (reduced motion shows the finished plan).
- Also: every line is named at its head (no line is a colour alone); the samples start on one line
  (subgrid); "Lisbona" is on the type ramp (detector's two advisory findings).

## Round 2 (confirmation): 24/32 (75 %, Good; P0 0, P1 1)

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 3 | The anchor jump is an instant ~950 px cut on the phone |
| 2 | Real world | 3 | "Ondata 1"/"Scelta" unexplained; "08:40 a Lisbona" reads as arriving before leaving |
| 3 | Control | 3 | Header "Accedi" leads uninvited visitors to another brand's login |
| 4 | Consistency | 3 | Phone and desktop maps differ in small ways |
| 5 | Error prevention | 3 | No invitation hint before "Accedi" |
| 6 | Recognition | 3 | The legend keys colours, not symbols |
| 7 | Flexibility | n/a | Persuade surface |
| 8 | Aesthetic | 3 | Two lines painted over; thin closing on the phone; ragged frames; map oversized 768–1079 |
| 9 | Error recovery | 3 | The uninvited path ends with no next step |
| 10 | Help | n/a | Persuade surface |

Detector: CLI 0 findings; browser 2 nested-cards (the samples' own plates inside their frames,
false positive). Measured: no horizontal scroll; all text ≥ 4.5:1 and strokes ≥ 3:1 in both
themes; frames inert with 0 focusable; no `/demo` links.

- [P1] Two of the five lines were drawn over (collinear final diagonals) in the map, the closing
  and the link preview. Fixed after the round in 560bd16: each line enters the destination from its
  own direction; `components/landing/line-geometry.test.ts` checks all three drawings. Not
  re-scored: one confirmation round is the cap.
- [P2] Closing drawing thin on the phone: fixed (phone crop). On desktop it outweighs its heading
  and repeats the hero: deferred.
- [P2] Map oversized 768–1079 px: fixed (capped at 40rem).
- [P2] Comprehension (Ondata/Scelta, "08:40 a Lisbona" from `DatePair startsAtHome`, "account
  TripTracker", the lede's first parse): deferred to Michele (copy he chose, a shared component).
- [P3] Frame bottoms ragged: fixed. The ink line has no terminus; the phone caption row lands after
  the legend: deferred.

## Gate

24/32 (75 %) after the confirmation round, below the 80 % gate, with its one P1 fixed and verified
(test and browser) but not re-scored. Michele decides whether the landing merges at this score, as
for step 1, or waits for a polish pass.
