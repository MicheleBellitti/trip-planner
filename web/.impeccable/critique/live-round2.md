---
target: /plans/[id] (live plan page while running; also budget_paused, failed, blocked, interrupted)
slug: web-components-live
round: 2
total_score: 31
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
---

⚠️ DEGRADED: single-context (no sub-agent tool exposed in this session; Assessment A and B ran sequentially in one context, A first)

# Impeccable critique, round 2: the live plan page

Screen: `web/app/plans/[id]/page.tsx` -> `components/live/*` (+ `components/states/*`). Seen in the browser at 393x852 and 1440x900 (and 1180x820 for the 1080-1279 band), light and dark, on demo plans `happy_path` (x5), `mcp_failure` (x2), `budget_reached`, `three_rejections_failed`, `requires_action_blocked`, `interrupt` (x2: stopped through the real "Interrompi" confirm by keyboard on desktop; confirm panel opened on the phone). Judged against DESIGN.md, PRODUCT.md, the spec's states table and the CLAUDE.md UI rules.

Browser notes (not defects of the page): (1) a tab opened with `tabs_create` is backgrounded and throttled, so the page sat on its skeleton ("Carico il piano...") for 40+ s with no request to :8810; fronting the tab with `tabs_select` loads it at once. This explains the "skeleton for 10-25 s" noticed in round 1 as well. (2) After a resize the pane sometimes captures screenshots at the wrong scale (page in the top-left quarter); `resize_window` preset desktop followed by the real size fixes it. All numbers below come from the DOM, not from those captures.

## Design health score: 31/40 (Good; no P0, no P1, one point under the 32 merge gate)

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | Cost now says "Costo non ancora aggiornato" until the first usage, then "Aggiornato a fine turno"; word + glyph per lane; "in corso da 0:07". But every working lane without a tool says the same "Ragiona sul prossimo passo.", and an interrupted run invents a "Scelta" station |
| 2 | Match system / real world | 3 | Plumbing is gone (one quiet "Consegna l'esito, 1 file"; Italian row titles; English only inside disclosures with `lang="en"`). "Ragiona..." is a claim the data does not back; "budget" names both the trip's money and the session's |
| 3 | User control and freedom | 3 | Interrupt confirm is exemplary (focus on Annulla, Esc, anchored to the bar on the phone, focus lands on the new state). Phone auto-follow swaps the open card under the reader; desktop has no jump-to-live |
| 4 | Consistency and standards | 3 | Tokens, glyphs, copy rules held on every state. Lane head rules step down 449 / 468 / 487 px when the one-line peeks differ in length (blocked, budget) |
| 5 | Error prevention | 3 | Confirm before interrupt with a paused-specific wording; honest budget panel. Interrompi stays enabled offline |
| 6 | Recognition rather than recall | 3 | Sticky lane heads and the repeated live tool fix the round-1 orientation gap. A closed phone card hides the dead-source note of its lane |
| 7 | Flexibility and efficiency | 3 | "Vai all'ultimo" works (tested: scrolls, then disappears), folded history, whole card tappable. Nothing equivalent from 1080 px up, where the coordinator's live end is a screen below |
| 8 | Aesthetic and minimalist design | 3 | Calm and authored; sticky bar + heads take ~170-180 px (about 20 %) of a 900 px window, and the same constant sentence sits under four of five heads |
| 9 | Error recovery | 4 | what happened / what was saved / what to do on budget, failed, blocked, interrupted; blocked now names the agent and the tool; every panel has one primary action and a way back |
| 10 | Help and documentation | 3 | Self-describing; the meter explains its own lag in words. No legend for the lozenge or the waves (acceptable for one expert user) |
| | **Total** | **31/40** | **Good: round-1 P1 and eight of nine P2 are fixed; two truthfulness gaps keep it under the gate** |

## Verification of round 1

| Round 1 item | Verdict | Evidence |
|---|---|---|
| P1 open phone lane shows the past | **Fixed** | Open card keeps its live line under the header, folds all but the last 4 stations into "9 passaggi precedenti" (needs 6+ stations), shows the live plate, and "Vai all'ultimo" appears while the end is below the fold; clicking it scrolled the page and the button went away |
| P2 cost stated as fact when unknown | **Fixed** | "Costo non ancora aggiornato" + "limite 0,60 $" from 0:00 to about 0:37 of happy_path, then "0,38 $ spesi / Aggiornato a fine turno"; `role=meter` has words in `aria-valuetext` |
| P2 agent plumbing | **Fixed** | No `mv`, no `.json.tmp`, no `/workspace` paths on screen; "Consegna l'esito / 1 file"; rows "voli -> coordinatore: esito consegnato"; 11 `lang="en"` nodes carry the English text |
| P2 closed card only header tappable | **Fixed** | `elementFromPoint` on the peek line returns the lane button (the `after:inset-0` stretch) |
| P2 interrupted lanes say "Finito" | **Fixed** | After the interrupt: Coordinatore, Voli, Alloggio "Fermato" with stop-circle and "Fermo: il piano è stato interrotto."; untouched lanes "In attesa / Non è partito." |
| P2 desktop 1080-1280 too narrow | **Fixed** | 1180 px: coordinator full-width row (52 rem cap), four subagents in a 4-column row; 1440: five columns |
| P2 lane names scroll away | **Fixed** | Heads strip sticks under the top bar at 1440 and 1180 (translucent ground, no overlap with the bar) |
| P2 the decision hidden | **Fixed** | "Scelta" carries the first sentence of the choice ("Volo TAP diretto con bagaglio (812 €) e Hotel Lisboa Plaza..."), un-clamped |
| P2 running -> ready lands mid-page | **Fixed** | `scrollY` 142 (plan top), `document.activeElement` = `h2#...-sintesi` "Sintesi del piano"; the polite region still says only "Coordinatore: finito" |
| P2 blocked copy vague | **Fixed** | "L'agente Voli aspettava il permesso per usare lastminute.com, che questa app non può dare. Il piano non può continuare."; Voli lane "Fermato", "Aspettava il permesso per usare lastminute.com." |
| P3 "da 1:57" | Fixed | "in corso da 0:07" |
| P3 interrupt copy when paused | Fixed | separate wording, "nulla è in corso" variant in code |
| P3 popover on phone covers the meter | Fixed | spans 16-377 px, hangs under the whole bar |
| P3 focus frame on `#plan-state` | Fixed | `focus:outline-none`, no ring seen after the interrupt |
| P3 wordmark target | Fixed | padded to 44 px |
| P3 phone bar 123 px | Improved | 105 px |
| P3 grid-template-rows vs "no layout animation" | Reconciled | DESIGN.md Motion section names it as the one exception |
| P3 title changes in flight | **Open** | en dash fixed, but the h1 still swaps from "Lisbona, 14-18 apr" to "Lisbona in famiglia, 14-18 aprile 2027" while the plan is still "In corso" |
| P3 mcp_failure note pushes Voli down | **Open** | Voli's first station still starts about 34 px lower than its neighbours; the red station now says something different from the note ("La fonte ha restituito un errore dopo 3,8 s"), so the duplication is acceptable |
| P3 dead code `components/shells/plan-live.tsx` | **Open** | file and `plan-live.test.tsx` still exist and still carry a second `aria-live` region |

## Design specificity verdict

**LLM assessment (before the detector).** Authored, not interchangeable. The line-map vocabulary now carries real information: the folded "N passaggi precedenti" row, the dashed next stop, the wave stations, the plate at the end of a line and the same live tool repeated under each lane name all answer "where is it now" in the product's own shapes. Amber is absent from the whole live screen (correct, no bookings yet), buttons are ink pills in both themes (the dark primary inverts to a light pill), sentence case and no em dash hold on 148 text nodes in the dark desktop view. The remaining weaknesses are about honesty of small sentences, not about taste: a constant "Ragiona sul prossimo passo." under every working lane, an invented "Scelta" after an interrupt, a dead source that disappears when its card closes.

**Deterministic scan.** `impeccable detect --json components/live components/states components/plan app/plans` returned `[]` (no findings, nothing to discard). In-page contrast scan (computed text colour against composited ancestor backgrounds, every visible text node): 0 failures below 4.5:1 on the light phone budget_paused view, 0 of 148 on the dark desktop running view. Horizontal overflow at 393: none (`scrollWidth` 393). Fonts loaded: Barlow 400 and Barlow Semi Condensed 600 (500/600 load on demand). One `aria-live="polite"` region on the page, lane state changes only; no `role=status/alert` outside user actions. `<header>` and `<main>` landmarks present. No em dash, no ALL CAPS word, no amber on any control, no external link on the running page (all 20 external links of the finished plan carry `rel="noopener noreferrer"`). Overlay injection skipped (shared pane, detector clean). Not toggled in the browser: `prefers-reduced-motion` (the pane cannot emulate it); checked in code, every `animate-*` in `timeline.tsx`, `agent-lane.tsx`, `interrupt-control.tsx`, `toast.tsx`, `skeleton.tsx` is `motion-safe:` with a `motion-reduce:` fade or none, and the JS scroll uses `behavior: "auto"` under reduced motion.

## Overall impression

The screen now does what the product promises on a phone: five agents on one screen, the open lane telling you the present first, the cost telling you when it does not know. The best of the round-1 fixes are the ones that changed what the interface admits (cost pending, "Fermato", the blocker named). The single biggest remaining opportunity is the same idea applied once more: stop printing sentences the data does not support ("Ragiona sul prossimo passo.", "Scelta" after an interrupt) and surface the one fact the phone hides (a dead source under a closed card).

## What's working

1. **The phone's open card.** Header, live line, folded history, last four stations, plate, then "Vai all'ultimo" while the end is below the fold. The present first, history on request, exactly as DESIGN.md asks. Header and peek are one 44+ px target and keep a visible 2 px inset focus ring.
2. **State panels and the interrupt flow.** Budget, failed, blocked, interrupted: three captions, one primary action, lanes still readable beneath, nothing leaning on colour. Interrupt by keyboard: Interrompi, Enter, focus on "Annulla", Tab, Enter on the confirm, focus lands on `#plan-state` ("Interrotto"), polite region reads "Coordinatore: fermato; Voli: fermato; Alloggio: fermato". The meter keeps "0,14 $ spesi, limite 0,60 $" after the stop.
3. **Desktop orientation.** Sticky heads with the repeated live tool, the trunk 1.3x wider at 1440, the coordinator's full-width row at 1180, the wave stations with the decision quoted. Dark theme holds: line hues keep identity, no contrast failure, halo and plate readable.

## Priority issues

### [P2] An interrupted, failed or blocked run still gets a "Scelta" station
- **What**: in the `interrupt` scenario the coordinator's line reads "Interruzione richiesta (0:27), Scelta: Il coordinatore legge gli esiti e sceglie (0:28), Turno concluso". Nobody chose anything: Voli ended "Non concluso", Alloggio delivered nothing, Attività and Spostamenti never started. Cause: `finishes(event)` in `components/live/stations.ts` (about line 639) counts any "Turno concluso" status as a report, so when the interrupted subagents stop, `waves.outstanding` empties and the choice station is pushed.
- **Why it matters**: the line map is the product's claim of truth about the run; a named station that did not happen is the worst kind of error on it, and it sits right under the plan's "Interrotto" panel.
- **Fix**: let a lane clear `waves.outstanding` only when it delivered (a `subagent -> coordinator` result message or `build.reported`), not on a bare turn end; and skip the choice station when the plan status is `interrupted`, `failed` or `blocked`. Add a test with the `interrupt` fixture: no "Scelta" station.
- **Suggested command**: /impeccable harden

### [P2] A closed phone card hides its lane's dead source
- **What**: in `mcp_failure` the dashed note "Fonte Kiwi.com non raggiungibile: il piano prosegue con le altre fonti" lives inside the open body of Voli. When Voli finishes and the follow moves on, its card reads "Finito / Esito consegnato al coordinatore." and nothing says a source failed. The same holds for an agent in error: the peek is only the summary.
- **Why it matters**: Principle 5 ("failures stay local") means local, not invisible. Michele checking on the phone sees five green "Finito" lines and only learns on the finished plan.
- **Fix**: add a second, quiet part to `Peek` when `view.notices.length > 0`: the warning glyph and "1 fonte non risponde" (`text-meta`, ink, dashed-edge style not needed), or a small warning glyph beside the state badge in the header; keep the full note in the open body.
- **Suggested command**: /impeccable clarify

### [P2] "Ragiona sul prossimo passo." is a stock sentence, and the coordinator's real state is unsaid
- **What**: `summaryFor` returns the same sentence for every `working` lane without a live tool. On desktop it sits under four of five lane heads in the Sala-borrowed slot that exists to show the present; the coordinator spends the longest stretches (0:14-0:37 of happy_path) waiting for Spostamenti or for submit_plan, still "Ragiona sul prossimo passo.". At 1440 its "you are here" end is also a screen below the fold, and nothing on desktop scrolls or jumps to it.
- **Why it matters**: the slot is the screen's best answer to "what is each agent doing right now", and it is filled with a sentence that is true of every agent at every moment. It also makes five lanes look equally busy.
- **Fix**: derive it from data you already have: coordinator "Aspetta Spostamenti" (from `waves.outstanding`), "Verifica il piano" after `submit_plan`; subagents "Ultimo passo: Consegna l'esito" (the last station's title and time) or hide the line. And add the phone's "Vai all'ultimo" to `lg:` (sticky bottom-right, same observer) pointing at the longest open end.
- **Suggested command**: /impeccable clarify, then /impeccable adapt

### [P3] Lane head rules do not line up when the peeks differ
- **What**: DOM measure on `requires_action_blocked` at 1440: the five `border-b` rules sit at y = 468 (Coordinatore), 487 (Voli), 449 (the other three), because each head's rule belongs to an inner div that does not stretch with the grid row. First stations then start at three different heights. In happy_path (peeks all one line) they align, so the flaw appears exactly in the states where the heads say the most.
- **Fix**: make each head a flex column with the rule div `flex-1 items-end` (or move `border-b` and `pb-3` to the stretched grid item); also reserve two lines for the peek in `lg:` when any lane's peek wraps.
- **Suggested command**: /impeccable layout

### [P3] Smaller items
- **Ended plans: lanes that never started say "In attesa" with an hourglass** (Attività, Spostamenti after an interrupt, failure or block), next to the sentence "Non è partito.". Use a distinct badge word ("Non partita") with the dashed-ring glyph so the badge and the sentence agree.
- **Phone auto-follow swaps the open card under the reader**: Spostamenti (open at 0:21) closed and Coordinatore opened by 0:34 with the page scrolled; the viewport then started mid-coordinator under the bar. Stop auto-follow once the user has scrolled inside the open card, or keep the previous card open until they act; at least do not close a card that is in view.
- **Failure note shifts the lane**: the dashed note makes Voli's first station about 34 px lower than Alloggio's and Attività's. Put the note after the head (inside the head's peek) or after the first station.
- **Sticky region on desktop is about 170-180 px** (bar 91 px + heads strip), 20 % of a 900 px window and a quarter of a 720 px one. Drop the summary line from the sticky state, or collapse the heads' peek under 800 px of height.
- **Offline and reconnect line is not sticky**: "Non aggiornato: sei offline, ultimo stato alle 17:43" sits below the bar and scrolls away; a reader deep in the coordinator's line sees frozen lanes and no warning. Put it inside the sticky bar (it is one line).
- **Title swaps mid-run**: the h1 changes to the agent's title while the plan is still "In corso" (document title too), reflowing the sticky bar. Keep the request title until `ready`.
- **"Budget" names two things**: the header says "budget 2.400 €" (the trip), the panel says "La sessione ha speso 0,61 $ su un budget di 0,60 $" and the meter says "limite 0,60 $". DESIGN.md reserves "budget" for the trip's money; the spec's "Budget raggiunto" can stay as the plan status, but the panel body should say "limite di spesa della sessione".
- **Message disclosure rows are 20 px tall** on the phone (`summary` of "coordinatore -> voli: incarico", 229 x 20). Spacing satisfies WCAG 2.2 target size, but a thumb gets one chance; give the row `py-2.5` (44 px).
- **Plan-level state arrives silently**: when a running plan turns budget_paused, failed or blocked, the polite region speaks only the lane words ("fermato"), and focus does not move to the panel (it does for ready and for the user's own interrupt). Consider `tabIndex={-1}` on the panel heading and focus it only if the user was watching, as for the finished plan.
- **Dead code**: delete `components/shells/plan-live.tsx` and `plan-live.test.tsx` (second `aria-live`, unstyled, imported by nothing but its own test).
- **Demo only, not a UI bug**: scripted coordinator messages say "9 e 6 anni, budget 2.800 €" while the header (from the request) says "8 e 11 anni, 2.400 €".

## Persona red flags

**Michele on the iPhone, one-handed, in a spare moment (primary).** Opens the plan at 0:25: sees the plan state, "Costo non ancora aggiornato", five cards, one open with its present at the bottom, and a thumb-sized "Vai all'ultimo". Good. Red flags left: reads "Finito" on Voli with no sign that Kiwi failed; the open card he was reading closes by itself when its lane finishes; after an interrupt he reads a "Scelta" station that never happened.

**Michele on the Mac, watching five lanes for minutes (primary).** At 1440 the five heads, the repeated live tool and the cost meter are all on screen; scrolling the coordinator's long column keeps every column named. Red flags left: the coordinator's head says "Ragiona sul prossimo passo." for half the run and its live end is below the fold with nothing to jump there; in blocked and budget states the head rules step down by 19 px per column.

**Sam, keyboard and screen reader (accessibility).** Linear tab order (home link, Interrompi, theme, lane buttons), 2 px ink ring on lane buttons (inset) and on the home link, `aria-expanded`, `inert` closed bodies, `role=meter` with words, one polite region with lane states only, focus moved to the plan after a watched run and to `#plan-state` after an interrupt, 0 contrast failures. Gaps: plan-level panels arrive silently; message summaries are 20 px tall on the phone.

## Minor observations

- Reduced motion verified in code only (see scan above); the one JS animation (smooth scroll) honours it.
- Dark theme: coordinator trunk `#A9B6C7`, plates and red ring read; the confirm button inverts to a light pill; no contrast failure measured.
- Phone skeleton and desktop skeleton match the final layouts (five card shells, five head shells); no layout shift seen beyond the title swap.
- Cost units: "0,14 $ spesi", "limite 0,60 $", "Costo del piano 0,41 $" all `formatUsd`; no cents on screen.
- The page spends nothing on external links while running; the booking links are the finished-plan screen's concern (all carry `rel="noopener noreferrer"`).
- Interrompi remains enabled while offline; the call would fail with the generic error. Disable it with a title or let the error name the connection.

## Questions to consider

- If a lane's head could only say one thing that is true right now, what would it say for the coordinator at 0:25: that it waits for Spostamenti?
- Is "Finito" the right word for a lane that finished with a dead source, or does the card need a half-state ("Finito, con avviso")?
- Should the open card on the phone ever change without the reader's hand? What does "follow the work" mean for someone who is reading one lane on purpose?

## Fix list in priority order (for the next round)

1. P2 No "Scelta" (or "Ondata 2") station unless a subagent delivered; none after interrupted, failed or blocked.
2. P2 Closed phone card shows a one-line warning when its lane has a dead source or an error.
3. P2 Replace "Ragiona sul prossimo passo." with the last real step or what the coordinator waits for; add "Vai all'ultimo" from 1080 px.
4. P3 Align the head rules (flex column heads); distinct "Non partita" badge on ended plans; keep request title until ready; sticky offline line; delete dead shell.

Expected score after items 1 to 3: 33/40.
