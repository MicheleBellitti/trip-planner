---
target: /plans/[id] (live plan page, status running; also budget_paused, failed, blocked, interrupted)
slug: web-components-live
round: 1
total_score: 28
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 1
---

⚠️ DEGRADED: single-context (no sub-agent tool exposed in this session; Assessment A and B ran sequentially in one context, A first)

# Impeccable critique, round 1: the live plan page

Screen: `web/app/plans/[id]/page.tsx` -> `components/live/*` (+ `components/states/*`). Seen in the browser at 393x852 and 1440x900, light and dark, on demo plans `happy_path` (twice), `mcp_failure` (twice), `budget_reached`, `three_rejections_failed`, `requires_action_blocked`, `interrupt` (stopped through the real "Interrompi" confirm, by keyboard). Judged against DESIGN.md, PRODUCT.md, the spec's screen description and states table, and the CLAUDE.md UI rules.

Browser notes: the pane's mouse mapping is wrong under phone emulation (clicks land at 1.85x the coordinates), so phone interactions were driven by keyboard and `element.click()`. Skeleton to content took 10 to 25 s on several loads; the cause was the shared browser holding more than six open SSE streams to :8810 (HTTP/1.1 per-host limit) from the other agents' tabs, not a defect of the page (the API answers in 2 ms). Noted as P3 below only because production must be HTTP/2.

## Design health score: 28/40 (Good, one P1 short of the 32 merge gate)

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | Word + glyph per state, live plate, elapsed clock all work. Cost reads "0,00 $ spesi" for most of a run because usage arrives only when the session idles; "da 1:57" on a running tool reads as "since", and lanes of an interrupted plan say "Finito" |
| 2 | Match system / real world | 2 | Timeline shows shell internals ("Comando: mv /workspace/results/flights.json.tmp ..."), "Scrive results/x.json.tmp", "flights.json v1 written: f1 TAP ..." and English prompts as row titles |
| 3 | User control and freedom | 3 | "Interrompi" is a calm inline confirm (Esc, Annulla, focus starts on the safe button). No way to follow or jump to the live end |
| 4 | Consistency and standards | 3 | Tokens and primitives are used faithfully; small drifts: "da 0:14" vs "in corso da 0:14", "14-18" (agent title) vs "14–18" (request title) |
| 5 | Error prevention | 3 | Confirm before interrupt, honest budget copy. Interrupt confirm still says "Gli agenti chiudono il passo in corso" when the plan is budget_paused and nothing runs |
| 6 | Recognition rather than recall | 3 | Names, icons, colours and words carry identity. On desktop the lane names scroll away with the lanes; on phone the open lane hides its "you are here" line |
| 7 | Flexibility and efficiency | 2 | No jump-to-latest, no way to hide agent plumbing, lanes too narrow from 1080 to about 1280 px, closed phone card's second line is not tappable |
| 8 | Aesthetic and minimalist design | 3 | The line-map idea is authored and calm; roughly a quarter of the stations are protocol noise |
| 9 | Error recovery | 3 | what happened / what was saved / what to do panels are excellent; "Gli agenti aspettano una conferma che nessuno darà" (blocked) does not say which confirmation |
| 10 | Help and documentation | 3 | Self-describing in words; no legend for the lozenge or the waves, acceptable for a single expert user |
| | **Total** | **28/40** | **Good: strong system, three honesty/legibility gaps on the live path** |

## Design specificity verdict

**LLM assessment (done before the detector).** This is not category-interchangeable. The transit-line vocabulary is applied with discipline: one hue per agent with its own roundel and icon, stations with distinct glyph forms (ring, bar, lozenge, wave ring, cross), the coordinator's trunk 1.3x wider, "Ondata 1 / Scelta / Ondata 2" as named stations, the live tool as a coloured plate with a halo at the end of its line, repeated under the lane name on desktop. Amber is absent from the whole live screen (correct: no bookings yet), buttons are ink pills, copy is Italian sentence case with no em dashes, state is always word + glyph. The state panels (budget_paused, failed, blocked, interrupted) are the best writing on the screen: three captions ("Cosa è successo / Cosa è stato salvato / Cosa puoi fare") and one primary action. What keeps it from the 32+ band is not taste, it is truthfulness and legibility of the live feed: a cost that sits at zero, a feed that mixes the agents' file plumbing with their work, and a phone layout that shows the past rather than the present.

**Deterministic scan.** `impeccable detect --json web/components/live web/components/states web/components/plan web/app/plans` returned `[]` (exit 0): no findings, no false positives to discard. In-page contrast scan (every text node in `main` and `header`, computed colour against nearest opaque background, dark theme, desktop): 0 failures. Horizontal overflow at 393: none (scrollWidth 393). Fonts loaded: Barlow 400/500/600 and Barlow Semi Condensed 600 only. Live regions on the page: exactly one (`aria-live=polite`, sr-only), announcing lane state changes only. External links all carry `rel="noopener noreferrer"`. No amber on any control. No em dash anywhere. Visual overlay was not injected (live-server overlay skipped: critique ran on a dev URL in a shared pane and the detector found nothing to highlight).

## Overall impression

A confident, quiet screen that mostly delivers "calm control room". The single biggest opportunity: make the live view say what is true *now* (cost, current tool, what each lane really ended as) and stop spending a quarter of its rows on the agents' file handling. Fix the phone so the open lane shows its present, not its history, and this clears the gate.

## What's working

1. **The state panels.** budget_paused ("La sessione ha speso 0,61 $ su un budget di 0,60 $", one primary "Continua con 2 $ in più"), failed, interrupted and blocked all follow the spec's table, never lean on colour alone, and keep the lanes readable beneath. Dollar format and sentence case are right throughout.
2. **The phone control bar.** Plan state + elapsed on the left, "Interrompi" and the theme toggle on the right, cost meter across the bottom: sticky, thumb-reachable, 40 px targets, nothing wraps at 393. The open lane follows the work and closed lanes carry a one-line live tool, so five agents fit one screen.
3. **Interrupt interaction.** Inline confirm, focus lands on "Annulla", Esc closes and returns focus, confirm moves focus to `#plan-state` so a screen reader reads "Interrotto" instead of losing focus on a disabled button. Verified by keyboard.
4. **Failure stays local.** In `mcp_failure` the dead source is a dashed note at the head of the Voli lane plus a red ring station with a sentence; the plan continues; the coordinator lane is untouched. Dark theme holds: the line hues keep their identity and all contrast checks pass.

## Priority issues

### [P1] The open lane on the phone shows the past; "you are here" is out of sight
- **What**: On 393 px the open lane (the one auto-opened to follow the work, often the coordinator) lists stations oldest first. By about 0:18 the coordinator lane is ~1,100 px tall; the visible part is "Piano avviato, utente -> coordinatore, Al lavoro ...", and its live tool or ending is below the fold. The one-line live peek that makes closed cards useful is explicitly hidden when the lane is open (`agent-lane.tsx`, `open && !desktop && "hidden"`). Nothing scrolls, jumps or summarises to the live end. The other four lanes (collapsed below the open one) are pushed off screen, so the "5 agents at a glance" promise is lost exactly when the run is busy.
- **Why it matters**: PRODUCT.md success is "who is working, on what, how much it has cost, what failed" glanced from an iPhone in a spare moment. The primary phone scene shows the least useful part of the data.
- **Fix**: (1) Keep the peek line under the header when the lane is open on the phone (remove the `open && !desktop` hide, or render it inside the open body above the line). (2) Collapse older stations in an open phone lane to "12 passaggi precedenti" (a `Disclosure variant="section"`) and show the last 4 stations plus the live plate; "Mostra tutto" expands. (3) Add a small sticky "Vai all'ultimo" button on the lane when its live end is below the fold.
- **Suggested command**: /impeccable layout, then /impeccable adapt

### [P2] Cost is stated as fact when it is unknown
- **What**: `CostMeter` shows "0,00 $ spesi" with an empty bar for about 38 s of a 40 s `happy_path`; the figure jumps to 0,38 $ only when the session idles (`session.usage` is emitted at idle in the recorded fixtures). `mcp_failure` shows the opposite (0,36 $ at 0:26), so the user cannot tell whether zero means "nothing spent" or "nothing reported yet".
- **Why it matters**: the cost is the second thing the live screen promises, and the budget pause ("0,61 $ su 0,60 $") arrives with no approach.
- **Fix**: until the first usage event show "Costo non ancora aggiornato" (or "-- $") in `ink-2` with the budget still labelled; once known, add the hint "aggiornato a fine turno" in the meter's `aria-valuetext` and as a title-less `text-micro` line only on desktop. Keep `0,00 $` only when `cost_cents` is a real 0.
- **Suggested command**: /impeccable clarify

### [P2] Agent plumbing fills the timeline
- **What**: rows such as "Comando: mv /workspace/results/flights.json.tmp /workspace/results/flights.json", "Scrive results/activities.json.tmp", "voli -> coordinatore: flights.json v1 written: f1 TAP TP827/TP826 direct ..." and English prompt openers ("coordinatore -> voli: Find round-trip flights Milan (MXP/LIN/BGY) to...") are about a quarter of all stations in `happy_path`. In 250 px lanes the `/workspace/results/...` paths break mid-word ("lodgin g.json").
- **Why it matters**: DESIGN.md "calm control room", PRODUCT.md "understood without reading logs", and the Language rule (Italian for what the user reads). Shell commands are the opposite of reassuring.
- **Fix**: in `stations.ts`, map file-handling tool calls (`mv`, `*.json.tmp`, "Scrive results/...") and the "<file>.json vN written" hand-off messages to nothing, or merge them into one quiet station "Consegna l'esito" (`TimelineMeta`: "1 file"); keep them in the data. For messages whose text is English, show an Italian row title ("coordinatore -> voli: incarico", exactly the spec's example) and keep the English text only inside the disclosure with `lang="en"`. Add `overflow-wrap: anywhere` to station titles as a safety net.
- **Suggested command**: /impeccable distill, /impeccable clarify

### [P2] Phone card: only the header row opens the lane; the second line looks tappable and is not
- **What**: a collapsed lane is one card, header plus a line with the live tool or ending. The `<button>` covers only the header (`agent-lane.tsx`: the peek `div` is a sibling of `h3`), so tapping "Expedia · voli MXP->LIS · 14-18 apr  da 0:00" does nothing.
- **Why it matters**: a one-handed user taps the line with the information; a dead tap reads as a frozen page.
- **Fix**: make the whole card header (button + peek) one click target: either move the peek inside the button (keep `aria-expanded`, the peek text then joins the accessible name, add `aria-describedby`), or add a transparent `::after` on the button that stretches over the peek (`after:absolute after:inset-0`, card `relative`).
- **Suggested command**: /impeccable adapt

### [P2] Interrupted lanes say "Finito"
- **What**: after "Interrompi il piano" the plan is "Interrotto" but Coordinatore, Voli and Alloggio show a check and "Finito" ("Turno concluso."), because the interrupted session emits a status "Turno concluso" before the plan status flips; the reducer only turns `working` lanes into `stopped`. The coordinator, which never delivered a plan, reads as done.
- **Why it matters**: a state a user may rely on (what finished?) is wrong; the design already has the right word and glyph ("Fermato", stop-circle).
- **Fix**: in `overlay()` (`reducer.ts`), when plan status is `interrupted`, `failed` or `blocked`, map `done` lanes with no delivered result (`reported` false, coordinator without `planAccepted`) to `stopped` with summary "Fermo: il piano è stato interrotto."; keep `done` only for subagents that reported.
- **Suggested command**: /impeccable harden

### [P2] Desktop lanes are too narrow from 1080 to about 1280 px
- **What**: at 1440 a subagent lane is 251 px and its text 171 px (about 24 characters per line, 14.5 px). The gutter (2.6 rem) and track (1.5 rem) take a third of the lane. At the 1080 breakpoint the text column is about 100 px (14 characters), so every tool title breaks into 5 or 6 lines and file paths split mid-word.
- **Why it matters**: the desktop is "the second layout, not a stretched phone"; the 13" MacBook scaled modes sit exactly in this band.
- **Fix**: raise the five-column breakpoint to 1280 (`xl`) and, between 1080 and 1279, put the coordinator on its own full-width row with the four subagents in a 4-column grid below (or drop the time gutter to `text-micro` above the title). Update DESIGN.md Layout accordingly.
- **Suggested command**: /impeccable layout, /impeccable adapt

### [P2] On desktop the lane names scroll out of view
- **What**: only the title and control bar are sticky. After about 400 px of scroll the five columns have no header, so a column's identity relies on colour alone (a long Coordinatore column next to four unnamed lines).
- **Why it matters**: "The Word Beside The Colour Rule" and orientation while watching a long run.
- **Fix**: make the lane header row (`roundel, name, state`, plus the repeated live tool) sticky under the top bar at `lg:` with `top` equal to the bar height and the same translucent ground; the subgrid rows already align the headers.
- **Suggested command**: /impeccable layout

### [P2] The decision is hidden behind a truncated disclosure
- **What**: the "Scelta" station carries only "Il coordinatore legge gli esiti e sceglie"; the actual choice ("Scelta: volo TAP diretto con bagaglio (812 €)...") is a 2-line truncated "coordinatore -> utente" message that opens on tap.
- **Why it matters**: it is the most valuable moment of the run for the person who will book.
- **Fix**: give the wave station a `TimelineMeta` with the first sentence of the coordinator message that follows it (up to 90 characters, Italian), un-clamped, and keep the disclosure for the rest.
- **Suggested command**: /impeccable clarify

### [P2] Running to ready swaps the whole page without orienting the user
- **What**: when the plan turns `ready` the lanes are replaced by the finished plan under the same scroll offset; observed after scrolling a running desktop page by 10 ticks: the viewer lands in the middle of "Giorno per giorno", past the summary and the warnings. Only the lane announcement ("Spostamenti: finito") is spoken; the plan appearing is not.
- **Why it matters**: the end of the run is the peak-end moment of the journey; the warnings ("Da sapere prima di prenotare") are skipped.
- **Fix**: on the transition to `ready`, scroll to the top of `main` (`scrollIntoView({block:"start"})`) unless the user scrolled up on purpose, and move focus to the plan summary heading (`tabIndex={-1}`) so assistive tech reads it; keep the existing `aria-live` untouched (still lane states only).
- **Suggested command**: /impeccable harden

### [P2] Blocked copy does not say what was blocked
- **What**: "Gli agenti aspettano una conferma che nessuno darà." Meanwhile the evidence is on the Voli lane ("lastminute.com · voli MXP->LIS (attende conferma) / Non concluso") and the lane that is red is the Coordinatore, not the lane that waits (Voli shows "In attesa").
- **Why it matters**: spec: "cosa è successo, cosa è stato salvato, cosa si può fare"; the first answer is vague and a little cryptic.
- **Fix**: "Voli aspettava il tuo permesso per usare lastminute.com, che questa app non può dare. Il piano non può continuare." (name the agent and tool from the pending event) and show the Voli lane in `error`/`stopped`, not `waiting`.
- **Suggested command**: /impeccable clarify

### [P3] Smaller items
- **"da 1:57" on the inline tool chip** (`chip.tsx` line 61) reads as "since 1:57"; the plate says "in corso da". Use "in corso da 1:57" or "1:57" with a clock glyph.
- **Interrupt confirm in `budget_paused`** says "Gli agenti chiudono il passo in corso"; nothing is running. Use a paused variant: "Interrompere il piano? Il lavoro fatto resta qui; il piano non viene consegnato."
- **The confirm popover** on 393 px covers the cost meter and the head of the first lane (it is anchored `-right-12`); acceptable as a transient, but it hides the numbers the user might be deciding on. Anchor it to the full-width bar (`left-4 right-4` on the phone).
- **Focus ring on `#plan-state`** after interrupting is a large ink frame around a word, which looks like a button; use a softer `outline-offset` or `focus:outline-none` plus `aria-live` text since it is not interactive.
- **Title changes in flight**: "Lisbona, 14-18 apr" (from the request) becomes the agent's title "Lisbona in famiglia, 14-18 aprile 2027" with a hyphen, and at 393 px the h1 gets within 22 px of the edge. Keep the request title until the plan is ready, or normalise hyphens in ranges to en dashes.
- **mcp_failure duplication**: the Voli lane tells the dead source twice (dashed note and the red station) and the note pushes Voli's first station lower than its neighbours. Keep the note, drop the red station's sentence, or put the note after the head station.
- **Phone sticky bar is ~123 px (14% of 852)**; consider collapsing the meter row to a 2 px line under the status row once scrolled.
- **Wordmark link** is 37x22 px on the phone (below 24 px height for WCAG 2.2 target size without the spacing exception); add `py-2`.
- **Dead code**: `components/shells/plan-live.tsx` and `plan-live.test.tsx` (the unstyled shell) are no longer imported by any route; they still carry a second `aria-live` region. Delete them.
- **Production**: the page holds one SSE stream per open plan; with HTTP/1.1 (browsers allow 6 per host) a 7th tab stalls its first fetch. Confirm the API answers over HTTP/2 on Railway.
- **Lane open/close animates `grid-template-rows`** (a layout property) while DESIGN.md says "Don't animate layout properties" and lists it in its own motion table; reconcile one of the two.

## Persona red flags

**Michele on the iPhone, one-handed, in a spare moment (primary).** Opens the plan at 0:18 and sees the coordinator's first ten rows ("Piano avviato", "utente -> coordinatore ...") and no sign of the present; taps the "Expedia · voli MXP->LIS" line on the Voli card and nothing happens; reads "0,00 $ spesi" and concludes the run is free so far; interrupts, and the lanes say "Finito". Each of these costs a second look.

**Michele on the Mac, watching five lanes for minutes (primary).** At 1440 the lanes are tidy, the live tool repeats in each header (good), but after scrolling the coordinator's long column he no longer sees which column is which; every hand-off is a `.json.tmp` write; at a 13" scaled 1280 window the text column is 147 px wide. When the run ends he lands mid-itinerary.

**Screen-reader and keyboard user (accessibility).** Mostly well served: single polite region for lane state, `aria-expanded` on lane buttons, inert collapsed bodies, `aria-current="step"` on the live station, focus moved to the plan state after an interrupt, 2 px ink focus ring everywhere checked. Gaps: the finished plan is not announced or focused when it replaces the lanes; blocked state names no agent; the focus frame on a non-interactive label.

## Minor observations

- Reduced motion: every animation in `globals.css` has a declared equivalent (`motion-safe:` on halo/draw/arrive, `motion-reduce:transition-none` on lane, meter, caret, buttons). Checked in code, not toggled in the browser.
- Dark theme: coordinator `#A9B6C7` trunk, plate colours and the red ring all read; no contrast failure measured; the `Nuova scheda` and wordmark are fine.
- Demo-only mismatch worth knowing, not a UI bug: the scripted coordinator messages say "9 e 6 anni, budget 2.800 €" while the header (from the request) says "8 e 11 anni, budget 2.400 €".
- Time gutter counts from session start ("0:12"), so a stopped plan's last gutter and the header duration agree ("Durata 0:37"): consistent.
- Sentence case, no em dash, no amber, `rel="noopener noreferrer"` on all 12 external links of the finished plan, no title case found.

## Questions to consider

- What would the phone look like if the *present* were the heading of each lane (live tool or last result) and the history a drawer? The line map is lovely, but a metro map you stand in front of is "you are here" first.
- Is the agents' file handling part of the product or its engine room? If a station does not help Michele decide or book, why does it have a glyph?
- Should the cost meter promise a live number the backend cannot yet give, or promise a checkpoint ("aggiornato a ogni turno")?
- The five-column desktop is the signature: is it worth keeping below 1280 px, or does the coordinator deserve a full-width trunk there?

## Fix list in priority order (for the next round)

1. P1 Phone open lane: peek line stays, older stations collapse, "Vai all'ultimo".
2. P2 Cost unknown vs zero.
3. P2 Hide or merge file-plumbing stations; Italian row titles for English messages.
4. P2 Whole collapsed card tappable.
5. P2 Interrupted/failed/blocked lanes use "Fermato", not "Finito".
6. P2 Desktop breakpoint 1280 (or coordinator row on top between 1080 and 1279).
7. P2 Sticky lane headers on desktop.
8. P2 Show the "Scelta" decision in the station.
9. P2 Scroll/focus to the plan on ready.
10. P2 Blocked copy names agent and tool.
11. P3 list above.

Expected score after items 1 to 5: about 32/40 (gate), after all P2: 34/40.
