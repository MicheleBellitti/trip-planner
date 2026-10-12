---
target: /plans/[id] (live plan page while running; also budget_paused, failed, blocked, interrupted)
slug: web-components-live
round: 3
total_score: 32
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
---

⚠️ DEGRADED: single-context (no sub-agent tool exposed in this session; Assessment A and B ran sequentially in one context, A first)

# Impeccable critique, round 3: the live plan page

Screen: `web/app/plans/[id]/page.tsx` -> `components/live/*` (+ `components/states/*`). Seen in the browser at 393x852 and 1440x900, light and dark, on fresh demo plans: `happy_path` (x3, watched from 0:00 to ready), `mcp_failure` (x3), `budget_reached`, `three_rejections_failed`, `requires_action_blocked`, `interrupt` (x2: stopped through the real "Interrompi" confirm by keyboard on the phone; confirm panel opened on desktop). Judged against DESIGN.md, PRODUCT.md, the spec's screen description and states table and the CLAUDE.md UI rules. The task said "previous rounds: []", but `live-round1.md` and `live-round2.md` exist in this folder; I verified round 2's list item by item (table below).

Browser notes (harness, not defects of the page): (1) a tab that is not fronted never hydrates (page sat on "Carico il piano..." for 50 s with no request to :8810); `tabs_select` fixes it at once. (2) After `resize_window` the pane sometimes maps clicks and screenshots at the wrong scale (a click at 723,61 landed at clientX 2551); `preset desktop` then the real size, or dividing the coordinate, fixes it. A first "Interrompi" click that seemed to do nothing was this, not the app: with the event log armed, the correctly mapped click opened the panel and put the focus on "Annulla". (3) The Next dev indicator overlaps the bottom-left roundel on the phone; dev only.

## Design health score: 32/40 (Good; no P0, no P1; exactly on the 32 merge gate, no margin)

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | Word + glyph per lane, "in corso da 0:07", the coordinator says what it waits for ("Aspetta alloggio e attività."), subagents say their last step. But the cost meter says "Costo non ancora aggiornato" for 35 of the 37 s of a happy_path run, and the coordinator still says "Ragiona sul prossimo passo." for about 12 s (0:13-0:17 and 0:27-0:35) |
| 2 | Match system / real world | 3 | Plumbing hidden, Italian rows, English only in disclosures. "Budget" still names both the trip's money and the session's ("su un budget di 0,60 $", "nuovo budget di sessione") against DESIGN.md's own reservation of the word |
| 3 | User control and freedom | 3 | Interrupt confirm is exemplary (Annulla focused, Esc returns to the button, focus lands on `#plan-state` "Interrotto"). The phone's auto-follow still swaps the open card under the reader (3 swaps in one 37 s run) |
| 4 | Consistency and standards | 3 | Tokens, glyphs, sentence case, no em dash held in every state. Lane head rules still sit at three heights (449 / 468 / 487 px) in every state where peeks differ; the coordinator of a blocked plan is a red "Errore" while Voli is the calm "Fermato" |
| 5 | Error prevention | 3 | Confirm before interrupt, paused-specific wording, honest budget panel. "Interrompi" and "Continua con 2 $ in più" stay enabled while offline |
| 6 | Recognition rather than recall | 4 | Sticky heads, the live tool repeated under each lane name, a closed phone card now keeps "1 fonte non risponde", "Vai all'ultimo" on phone and desktop, folded history. Everything the reader needs is on screen |
| 7 | Flexibility and efficiency | 3 | Whole card tappable, jump-to-end on both layouts, folded history. No keyboard shortcut, no way to pin a lane (fine for one user) |
| 8 | Aesthetic and minimalist design | 3 | Calm, authored, flat. The sticky region is 192 px (21 % of 900) when a head peek wraps to three lines; the same fact appears twice inside one open card (live line under the head and the plate; "1 fonte non risponde" and the notice 60 px under it) |
| 9 | Error recovery | 4 | what happened / what was saved / what to do on budget, failed, blocked, interrupted; blocked names agent and tool; one primary action and a way back on every panel |
| 10 | Help and documentation | 3 | Self-describing; the meter explains its lag in words. No legend for the lozenge and waves (acceptable for one expert user) |
| | **Total** | **32/40** | **Good: all three round-2 P2 content items fixed; six small layout/state-label items carried over keep it on the gate, not above it** |

## Verification of the previous findings

Round 1 had one P1 (the open phone lane shows the past) and no P0; round 2 had no P0 and no P1. Both remain closed.

| Earlier item | Verdict | Evidence this round |
|---|---|---|
| R1 P1 open phone lane shows the past | **Still fixed** | Spostamenti at 0:27: live line under the head, "2 passaggi precedenti" folded row, last stations, floating "Vai all'ultimo" at the bottom right. Coordinator at 0:17: "9 passaggi precedenti" + last 4 + Scelta |
| R2 P2 "Scelta" invented after an interrupt | **Fixed** | `interrupt` plan after the real stop: coordinator line is "Interruzione richiesta, Turno concluso"; `document.body.innerText` has no "Scelta"; blocked and failed plans show none either |
| R2 P2 closed phone card hides a dead source | **Fixed** | `mcp_failure` at 0:13: closed Voli card reads "Esito consegnato al coordinatore. / (warning glyph) 1 fonte non risponde" |
| R2 P2 "Ragiona sul prossimo passo." everywhere | **Mostly fixed** | Coordinator: "Aspetta voli, alloggio e attività." then "Aspetta alloggio." then "Aspetta spostamenti."; subagents "Ultimo passo: ..."; the Sala slot at 1440 shows the live tool (Voli "Ricerca web: TAP TP827..." in dark). Left: the coordinator's fallback after all deliveries (see P3 below) |
| R2 P2 no jump-to-end from 1080 px | **Fixed** | "Vai all'ultimo del coordinatore" shows at 1440x900 while the coordinator's end is below the fold |
| R2 P3 lane head rules not aligned | **Open** | DOM at 1440: budget_reached 468 / 468 / 468 / 449 / 449; mcp_failure 173 / 173 / 192 / 154 / 154; blocked visibly three heights. Happy path (all one-line peeks) aligns at 249, which hides it |
| R2 P3 never-started lanes say "In attesa" | **Open** | interrupt, blocked, mcp_failure-ready: Attività and Spostamenti "In attesa" + hourglass, next to "Non è partito." or an empty head |
| R2 P3 auto-follow swaps the card | **Open** | happy_path log: open card Voli (0:05) -> Coordinatore (0:13) -> Spostamenti (0:17) -> Coordinatore (0:27); `scrollY` 0 -> 62 -> 61 while the content under it changes |
| R2 P3 note shifts the lane | **Open** | mcp_failure at 1440: Voli's first station starts 37 px lower than Alloggio's |
| R2 P3 sticky region 170-180 px | **Open, slightly worse** | 192 px (21 %) with a three-line head peek |
| R2 P3 offline line not sticky | **Open** | Simulated offline: line at `top: -122` after a 400 px scroll; "Interrompi" `disabled: false` |
| R2 P3 title swaps mid-run | **Open** | h1 and document title change to "Lisbona in famiglia, 14-18 aprile 2027" at 0:19 (mcp_failure) and 0:35 (happy_path) while the badge still says "In corso" |
| R2 P3 "budget" names two things | **Open** | "La sessione ha speso 0,61 $ su un budget di 0,60 $", "nuovo budget di sessione", "Fermo: budget della sessione esaurito." |
| R2 P3 message rows 20 px tall | **Open** | 201x20 and 229x20 `summary` targets on the phone |
| R2 P3 plan-level state silent | **Open** | Budget/blocked/failed: polite region says only the lane words; no focus move |
| R2 P3 dead code | **Open** | `components/shells/plan-live.tsx` and `plan-live.test.tsx` still exist with a second `aria-live` |

## Design specificity verdict

**LLM assessment (before the detector).** Authored, not interchangeable. The line-map vocabulary is carrying information on every state: the folded row, dashed next stop, the waves "Ondata 1", "Scelta", "Ondata 2" (all three present in happy_path, the decision quoted), the plate at the end of a line and the live tool repeated under each lane name (seen at 1440 light and dark). The state panels are the best thing on the screen: three captions, one primary action, lanes still readable beneath. What is left is no longer taste but bookkeeping: places where two components compute the same thing independently (head rules, the peek and the notice, "Errore" vs "Fermato") and a few labels that describe the lane when the plan is over ("In attesa").

**Deterministic scan.** `impeccable detect --json components/live components/states components/plan app/plans` returned `[]`. In-page contrast scan (computed colour against composited ancestor backgrounds, canvas-parsed so `color-mix` bars are right): 0 failures of 45 text nodes on the dark phone mcp_failure view; the light phone interrupted view produced 7 "failures" that are an artefact of my first parser reading the `color-mix` sticky bar, re-run correctly with 0. Horizontal overflow at 393: none (`scrollWidth` 393). Fonts loaded: Barlow 400/500/600, Barlow Semi Condensed 600. One `aria-live="polite"` region, lane state changes only ("Coordinatore: fermato; Voli: fermato; Alloggio: fermato" after the interrupt). 0 em dashes, 0 all-caps words. Amber: 0 elements on the live page and 0 on the finished plan of a 2027 trip (no booking due within 72 h); all 14 external links on the finished plan carry `noopener noreferrer`, every "Prenota entro" has its "Quando". Reduced motion not toggled (the pane cannot emulate it); in code every `animate-*` in `timeline.tsx`, `agent-lane.tsx`, `interrupt-control.tsx`, `skeleton.tsx` is `motion-safe:` with a `motion-reduce:` fade or none, `cost-meter.tsx` transitions are `motion-reduce:transition-none`, the JS scroll honours the media query. Focus: lane buttons draw a 2 px ink inset ring (`outline 2px solid rgb(15,26,42) offset -2px`); focus lands on "Annulla" when the confirm opens, back on "Interrompi" on Esc, on `#plan-state` after a confirmed interrupt. Overlay injection skipped (shared pane, detector clean).

## Overall impression

The three content fixes asked for in round 2 landed, and the screen reads as true: no invented "Scelta", no hidden dead source, a coordinator that names what it waits for. The remaining weakness is structural polish in the non-happy states, the ones Michele sees when something has gone wrong: the five heads stop lining up, the lanes that never ran say they are waiting, and on the phone the open card still moves on its own. The single biggest opportunity is to make the heads strip one stretched grid row (fixes the rules, the 37 px note shift and gives a place to cap the sticky height in one go).

## What's working

1. **The state panels and the interrupt flow.** Budget, failed, blocked, interrupted: "Cosa è successo / Cosa è stato salvato / Cosa puoi fare", one ink primary, lanes below. The confirm anchors to the bar on the phone and to the button on desktop, focus is managed both ways, and the polite region reads only lane words.
2. **Honest lanes.** A closed card carries its dead source, a lane that waits for others says for whom, a stopped plan has no invented choice station, the coordinator of a blocked plan says the plan stopped and the blocked agent says what it waited for ("Aspettava il permesso per usare lastminute.com.").
3. **Desktop orientation.** Five columns with the trunk 1.3x wider, the sticky heads with the repeated live tool, "Vai all'ultimo del coordinatore", the waves as named stations. Dark theme holds: hues keep identity, the plate and halo read, 0 contrast failures.

## Priority issues

### [P2] Lane heads stop lining up in every state where peeks differ, and a notice shifts its lane
- **What**: the five `border-b` rules of the heads strip are at 468 / 468 / 468 / 449 / 449 px (budget_reached), 173 / 173 / 192 / 154 / 154 (mcp_failure) and three heights in blocked. The rule belongs to an inner div that does not stretch with the grid row. Then each column starts its first station right under its own rule, so the stations start at different heights; in mcp_failure Voli additionally starts 37 px lower than Alloggio because the dashed source note sits between its head and its line. The strip also grows with the longest peek: 192 px (21 % of 900) in mcp_failure.
- **Why it matters**: Linee is a diagram of parallel lines; parallel lines that start at different heights are the opposite of the claim, and it only shows in the states where Michele is already worried (error, block, budget). The happy path (all peeks one line) hides it, which is why it survived two rounds.
- **Fix**: make each head a flex column whose rule div is `flex-1 items-end` (or move `border-b pb-3` to the stretched grid item), `line-clamp-2` the peek in `LaneHead` so the strip is at most two lines, and put a lane's warning note inside the column under its first station (or fold it into the head's peek as the phone's "1 fonte non risponde") so every first station shares one y. Add a test that reads the five rules' bottoms in the mcp_failure fixture.
- **Suggested command**: /impeccable layout

### [P2] Lanes that never started, on an ended plan, say "In attesa" with an hourglass
- **What**: after an interrupt, a block, or a short run, Attività and Spostamenti show the badge "In attesa" and the hourglass, beside the sentence "Non è partito." (or an empty head on desktop, or on a finished plan's closed timeline). `summaryFor` is already right ("Non è partito."); the badge is not told the plan is over.
- **Why it matters**: "In attesa" is a promise that work will come; on an interrupted, blocked or finished plan nothing will. It contradicts the sentence next to it and breaks the screen's rule that a state is a word and a glyph that agree.
- **Fix**: when the plan is not `running`/`budget_paused` and the lane has no events, `StatusBadge` gets a new state "Non partita" with the dashed-ring glyph from the glyph table (not the hourglass); keep "In attesa" for lanes that will still run. Add it to `/dev/ui` and `tokens`/invariants tests.
- **Suggested command**: /impeccable clarify

### [P2] On the phone the open card still changes under the reader
- **What**: in one happy_path run the open card went Voli (0:05) -> Coordinatore (0:13) -> Spostamenti (0:17) -> Coordinatore (0:27), while the page scrolled 62 px; a card being read closes the instant its lane finishes (`followed` resets as soon as `views[followed].state !== "working"`). This is the "follow the work" rule applied to a reader who may be reading a lane on purpose.
- **Why it matters**: Michele checks the plan one-handed in a spare moment; a card closing under his thumb loses his place, and the 3 swaps in 37 s make the page feel restless in the one place the design promises calm.
- **Fix**: follow only while the viewer has not interacted since load AND the open card is out of view (or has no live tool); never close a card that intersects the viewport; when the followed lane changes, leave the old card open and show the new one as a quiet one-line "Ora: Spostamenti" row on the bar, tap to open. At minimum stop following after the first scroll gesture.
- **Suggested command**: /impeccable harden

### [P3] Smaller items
- **Coordinator of a blocked plan is a red "Errore"** (blocked, 1440 light): "Errore" in `error` red with "Il piano si è fermato." while the header says "Bloccato" and Voli is the neutral "Fermato". No agent errored; the plan waits for a permission nobody can give. Show the coordinator as "Fermato" when `status === "blocked"`, keep red for `failed`.
- **"Ragiona sul prossimo passo." survives for the coordinator** between the last delivery and `submit_plan` (0:13-0:17 and 0:27-0:35 of happy_path, a third of the run). Say what is true: after wave 1 "Sceglie volo e alloggio.", after wave 2 "Compone il piano.". `Present` already knows the phase (`waves.phase`).
- **Title swaps mid-run**: h1 and `document.title` change from "Lisbona, 14-18 apr" to the agent's "Lisbona in famiglia, 14-18 aprile 2027" at 0:19 / 0:35 while the badge says "In corso". Keep the request title until the plan is `ready`.
- **"Budget" names two things** in the budget panel, the failed/blocked/interrupted panels ("nuovo budget di sessione") and lane peeks ("Fermo: budget della sessione esaurito."). DESIGN.md reserves the word for the trip's money. Say "limite di spesa della sessione"; "Budget raggiunto" can stay as the status badge.
- **Offline line is not sticky and "Interrompi" stays enabled offline** (simulated: line at `top: -122` after scrolling 400 px). Put `StreamStatus` inside the sticky bar (it is one line) and disable "Interrompi"/"Continua con 2 $ in più" with a title while `!online`.
- **Sticky region is 192 px at 1440x900 with a wrapping peek** (bar 91 + heads 101); cap the peek at two lines (see the P2 fix) and add `scroll-padding-top: calc(var(--live-bar-h) + <heads height>)` so a keyboard user tabbing up never has a message row or button under the bars (WCAG 2.2 Focus Not Obscured; Chrome centres the target, Safari scrolls it to the edge).
- **The same fact twice in one open card**: the live line under the head and the plate 60 px below ("Expedia · voli MXP→LIS · 14-18 apr in corso da 0:00" twice at 0:05), and "1 fonte non risponde" directly above the notice that says the same. DESIGN.md asks for the live line under an open head, so keep it but drop the source line from `Peek` when the card is open (`withNotices={!open}`), and render the head's live line without the elapsed time when the plate is visible.
- **"In attesa di una risposta" after "Piano accettato"** (coordinator line, 0:35): a status station that reads as the coordinator waiting after the plan was already accepted. Suppress the "waiting" status after `planAccepted`.
- **Message `summary` rows are 20 px tall** on the phone (201x20, 229x20). Spacing satisfies WCAG 2.5.8, but give them `py-2.5` (44 px) so a thumb gets one shot.
- **Plan-level state arrives silently**: when a watched plan turns budget_paused, failed or blocked, the polite region says only "Coordinatore: fermato; ..." and focus stays; it moves for ready and for the user's own interrupt. Add `tabIndex={-1}` to the panel's heading and focus it only if the viewer was watching, as for the finished plan; add the plan state to the announcement ("Budget raggiunto").
- **The cost meter is "non ancora aggiornato" for 94 % of a short run**: 35 of 37 s of happy_path (first usage at the end of a turn). It is honest, but the header's promise ("the cost climbing toward the session budget") is invisible on a one-minute run. If the backend can report usage per subagent turn, the meter will move; if not, the "Aggiornato a fine turno" hint should show from 0:00, not only after the first value.
- **Desktop skeleton is five equal heads** while the real layout is `1.3fr` + four columns and a taller sticky strip; match the grid and reserve the strip height to avoid a shift when data arrives.
- **Confirm button is not in the thumb zone on the phone**: "Interrompi il piano" sits at the top of the screen (the panel hangs from the bar). Acceptable (the bar is sticky, the action is rare), listed for Casey's pass.
- **Dead code**: delete `components/shells/plan-live.tsx` and `plan-live.test.tsx` (still carries a second `aria-live`).
- **Demo only, not a UI bug**: the scripted coordinator messages say "9 e 6 anni, budget 2.800 €" while the header (from the request) says "8 e 11 anni, 2.400 €".

## Persona red flags

**Michele on the iPhone, one-handed (primary).** Opens a running plan: state, "Costo non ancora aggiornato", five cards, the active one open with the present at its bottom, a thumb-sized "Vai all'ultimo". Good. Red flags: the card he is reading closes by itself when its lane finishes (3 swaps in one run); in a blocked plan the coordinator shouts "Errore" in red while the fault is a permission nobody can give; in an interrupted plan two lanes still say "In attesa"; the title changes under him at the end.

**Michele on the Mac, watching five lanes for minutes (primary).** Five columns, sticky heads, repeated live tool, "Vai all'ultimo del coordinatore". Red flags: in every state with an error or a wrapping peek the heads' rules and first stations step by 19-37 px, and the sticky region eats 21 % of the window; the coordinator's head says "Ragiona sul prossimo passo." for a third of the run.

**Sam, keyboard and screen reader (accessibility).** Linear tab order (home link, Interrompi, theme, lane buttons), visible 2 px ring, `aria-expanded`, `inert` closed bodies, `role=meter` with words, one polite region with lane states only, 0 contrast failures, `lang="en"` on the agents' text. Gaps: no `scroll-padding` under two sticky bars; plan-level panels arrive silently; the stopped plan's polite message is lane words only.

**Riley, edge cases.** Offline: line scrolls away, the two mutating buttons stay live. Interrupt on a paused plan: right wording. Stuck plan (the `interrupt` scenario sat running at 1:41 with "Costo non ancora aggiornato"): the screen is calm but nothing says "nothing has happened for a minute"; the 45-minute stuck flag from PRODUCT.md is not visible here (backend job), a quiet "Nessun evento da 1 min" in the head peek would help.

## Minor observations

- Dark theme: coordinator trunk `#A9B6C7`, plate and halo read, interrupt confirm inverts to a light pill, no contrast failure measured.
- The Next dev indicator overlaps the bottom roundel on the phone; dev only.
- A closed card with a live tool wraps "14-18 apr" with an orphaned "apr" before "in corso da 1:08"; set the elapsed time on its own line or `whitespace-nowrap` on the date.
- In a 2027 trip no booking is due within 72 h, so amber could not be exercised on the finished plan; the live page has none (correct).
- Reduced motion verified in code only.

## Questions to consider

- If the heads strip were one grid row with a hard two-line peek, would the rules, the shifted first stations and the 21 % sticky region all disappear together?
- Should the phone ever move the open card for the reader, or only offer "Ora: Spostamenti" and let the reader decide?
- Is "Errore" a state of a lane, or of an agent that errored? A blocked coordinator is neither.

## Fix list in priority order (for the next round)

1. P2 Heads strip as one stretched row: aligned rules, peek capped at two lines, lane notes below the first station, sticky height capped.
2. P2 "Non partita" badge (dashed ring) for lanes with no events on an ended plan.
3. P2 Phone auto-follow: never close a card in view; stop after the first scroll; offer "Ora: ..." instead.
4. P3 batch: blocked coordinator "Fermato"; coordinator fallback line by wave phase; keep request title until `ready`; "limite di spesa" wording; sticky offline line and disabled mutators offline; `scroll-padding-top`; `withNotices={!open}`; suppress "In attesa di una risposta" after acceptance; 44 px message rows; focus the plan panel on plan-level change; delete the dead shell.

Expected score after items 1 to 3: 34/40; after the P3 batch: 35/40.
