# Brand step 1: critique, two rounds (2026-10-14)

Round 1 (dual-agent): 27/40, P1 1 (desktop list titles truncated), P2 3, P3 1. All P1/P2 of this step fixed in ff87683.

## Round 2

Method: dual-agent (A: design review · B: detector + browser), confirmation round after the round-1 fixes.

## Design Health Score: 27/40 (Acceptable; P0 0, P1 0)
| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 3 | /new had no visible "you are here" (fixed after this round: 3 px ink edge) |
| 2 | Real world | 3 | "Valutazioni" is developer language in the main nav |
| 3 | Control | 3 | Clear ways back, reversible theme |
| 4 | Consistency | 2 | Toggle bare in the header, ringed in the live bar (fixed after this round) |
| 5 | Error prevention | 3 | Little to get wrong |
| 6 | Recognition | 3 | Labelled stations; icon controls are named |
| 7 | Flexibility | 2 | No shortcuts, search or filter |
| 8 | Aesthetic | 3 | Calm; desktop header's middle empty; identical rows |
| 9 | Error recovery | 3 | Notice with "Riprova" |
| 10 | Help | 2 | Little explanation beyond /new's lede |

Detector: CLI 0 findings; browser clean on /, /new, /evals, the plan page at 393/1280/1440; light theme flags the declared cream ground (intentional). Its /dev/ui plate contrast came from stale dev CSS; re-measured after a restart: all dark plate lines ≥ 4.77:1.
Measurements: header 65 px, no horizontal scroll, every target ≥ 44 px on touch, "Nuovo piano" last and current on /new; 0 clipped titles at 393/1280/1440.

## Priority issues
- [P2] Desktop header undersells the brand: 1 px line pinned right, uneven overhang. (/impeccable bolder) Deferred to Michele.
- [P2] /new "you are here" invisible (wash 1.1:1). Fixed: 3 px ink edge.
- [P2] Theme toggle bare in the header, ringed in the live control bar. Fixed: bare in both.
- [P3] The mark reads as a drafting compass at 28 px (bright station ring). Deferred.
- [P3] Theme switch flashes grey for 160 ms (transitions). Deferred to step 5 (theme View Transition).
