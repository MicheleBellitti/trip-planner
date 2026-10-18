# Demo (`/demo`): critique, two rounds (2026-10-18)

Surface mode: Persuade. Two heuristics were n/a, so totals are out of 32. The project's gate (≥ 32/40) is 80 %, which is 26/32.

## Round 1: 23/32 (72 %, Good; P0 0, P1 3)

Method: dual-agent (A: design review; B: detector + browser). All three P1s and three P2s were fixed in 7b155a2:
- [P1] The phone never showed the subagents working: the open card stayed on the coordinator. Fixed: `AgentLanes follow="show"`, so the open card follows the work, even on screen, until the visitor takes over.
- [P1] The landing promised "il costo che sale", but the cost is reported at the end of a turn. Fixed: the landing says "il costo della corsa".
- [P1] There was no ask where the eye lands at the end. Fixed: the bar shows its ask once the run ends.
- [P2] "Durata 0:45" showed the replay's length, and the relative deadlines rotted with the visitor's calendar. Fixed: the line now gives the recorded run's duration and cost, and the dates read on the recording's day.
- [P2] The "Vai all'ultimo" pill was transparent; this is a live bug too. Fixed.
- [P2] "Ricomincia" dropped the focus. Fixed: the focus moves to the plan's state. The landing's request sample now matches the demo's.

## Round 2 (confirmation): 22/32 (69 %, Acceptable; P0 0, P1 3)

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 2 | The moving part sat off-screen for long stretches |
| 2 | Real world | 3 | Product jargon leaks; TripTracker is never explained |
| 3 | Control | 3 | No pause |
| 4 | Consistency | 3 | The replay clock reaches 0:45, but the recorded duration is 1:17 |
| 5 | Error prevention | 2 | The end ask sent visitors into a form that 401s |
| 6 | Recognition | 3 | No lane legend on `/demo` |
| 7 | Flexibility | 3 | 2× and skip |
| 8 | Aesthetic | 3 | Phone chrome takes 39 % before the first lane |
| 9 | Error recovery | n/a | Bundled replay |
| 10 | Help | n/a | Persuade surface |

The detector found no issues in the code. In the browser it flagged:
- in dark, cramped-padding on the desktop lane heads strip (unconfirmed, and part of the pre-existing live layout);
- in light, the declared cream ground.

The three P1s were fixed after the round in 6b44783, and tests and the browser verify the fixes. They were not re-scored, because one confirmation round is the cap.
- **Camera:** on the phone the open card's newest station stays in view, and on wider layouts the coordinator's newest station does. Scrolling uses `block: "nearest"`; the first scroll, key or toggle hands the page back.
- **The end ask is honest:** "Pianifica il tuo viaggio" for a browser that has signed in before, "Accedi" for anyone else.

Deferred:
- [P2] No ending band after the timeline; the booking buttons stay primary and go off-site.
- [P2] No orientation line for a visitor who arrives by link.
- [P3] The cost meter row stays empty for most of the run.

## Gate

The demo scored 22–23/32, below the 80 % gate, with its P1s fixed after the confirmation round. As for steps 1 and 2, Michele decides whether it merges at this score or waits for a polish pass.
