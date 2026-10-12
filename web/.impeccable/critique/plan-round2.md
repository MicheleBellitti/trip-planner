---
target: "/plans/[id] finished plan (status ready)"
slug: id-ready
round: 2
total_score: 31
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
---

⚠️ DEGRADED: single-context (no sub-agent/Task tool is exposed to this agent, so Assessment A and B ran sequentially in one context; A was written down before `impeccable detect` ran)

# Critique, round 2: finished plan page `/plans/[id]` (ready)

Surface: demo plans `3d27e408-429b-43ee-bc4e-6199c24f09d2` (happy_path, 5 bookings, 2 alternatives, 62 events)
and `33e2c73a-e9c3-43b8-9ea2-e3f59d89c283` (watched from `running` to `ready` to test the arrival). Viewed
at 393x852 and 1440x900, light and dark, with the alternatives and the timeline opened. The amber
due-soon case cannot occur on a happy_path plan (every deadline is 137+ days away on 2026-10-12), so it
was checked on `/dev/plan?scenario=edge` (the same `PlanView` on shifted dates). Judged against
`web/DESIGN.md`, `web/PRODUCT.md`, the spec's "Il piano finito" and states table, and the CLAUDE.md
UI rules. Mode: Operate.

Note on "previous rounds": the harness passed `[]`, but `web/.impeccable/critique/plan-round1.md`
exists on disk (30/40, one P1). This round verifies that file's findings, one by one, below.

## Verification of round 1

| Round 1 finding | Status | Evidence |
| --- | --- | --- |
| **P1** The booking task is buried, no entry point by deadline | **Fixed** | "Da prenotare" strip sits under the facts: its heading is at y=632 on the phone (first viewport, 852 px) and y=416 on desktop. Five 44 px rows sorted by deadline ("entro ven 26 feb" ... "entro mar 13 apr"), each an anchor to its booking. `/dev/plan?scenario=edge` shows "5, 2 in scadenza" in bold ink, "Scadenza passata" and "In scadenza · tra un giorno" in words, no amber in the strip. First "Prenota su" is the 16th tab stop. |
| P2 running cost meter and two "budget" numbers | **Fixed** | Finished header reads "Pronto / Durata 0:37 · Costo del piano 0,41 $", no bar. "budget" now only means the trip's money. |
| P2 "Apri in TripTracker" last and weakest | **Fixed on the phone, partly on desktop** | Now right after the bookings, before alternatives and the timeline; full width on the phone (361x40). On desktop it is 177x40 at the far left of a 1384 px page. |
| P2 no time zone | **Fixed in intent** | "Prenota entro" in Europe/Rome, "Quando" labelled "ora di Lisbona", itinerary lead "Gli orari sono quelli di Lisbona." Residual problem in P2-1 below. |
| P2 summary repeats itself, no cost-vs-budget | **Half fixed** | "710 € sotto il budget di 2.400 €" added, labels raised to 13.5 px. The paragraph's third line, the total fact, the "Date" fact and the subtitle still say the same things (P2-2). |
| P2 three bookings end in a dead-end sentence | **Mostly fixed** | Now "Nessun link di prenotazione. Prenota sul sito di Oceanário de Lisboa: oceanario.pt", host in semibold ink. Still plain text next to a clickable "Fonte oceanario.pt" (P3-2). |
| P3 loading skeleton is the running-plan shape | **Still open** | Cold load of a ready plan: five lane cards (phone) or five columns (desktop), then a full re-layout (P3-1). |
| P3 alternatives print "Prenota entro non disponibile" | **Fixed** | Reads "Prenota entro nessuna scadenza" in ink-2. |
| P3 small targets, heading inconsistency | **Fixed** | Wordmark 53x46; the "5 da fare" link is gone; "Il lavoro degli agenti" and "Corsie degli agenti" are real h2s (the find tool sees the heading); labels "Prenota entro"/"Quando" are 13.5 px. |

No P0 or P1 is open. The spec's gate (at least 32/40, no open P0/P1) is missed by one point only.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | Arrival moves focus to "Sintesi del piano" and scrolls the plan into view (tested: scrolled to the bottom of the running page, plan landed at scrollY 42, `document.activeElement` = the summary h2); the live region logged only lane states ("Coordinatore: finito"), nothing about tool calls. Deduction: the loading skeleton still promises a running plan. |
| 2 | Match system / real world | 3 | Italian, sentence case, 0 em dashes, two labelled dates. Deduction: a flight leaving Milan is shown on the Lisbon clock (08:40 in the gutter and in "Quando", 09:40 on the clock of the airport he leaves from). |
| 3 | User control and freedom | 3 | Disclosures native, links in new tab, wordmark home now 53x46. Deduction: a finished plan offers no "Nuovo piano" or "I tuoi piani"; after "Apri in TripTracker" there is no next step in Atlas. |
| 4 | Consistency and standards | 3 | One BookingRow for plan and alternatives, one DatePair. Deductions: "Da prenotare" is sorted by deadline, "Prenotazioni" below it is in the agent's order (Oceanário before Palácio da Pena), so a tap on the strip jumps down, then up. |
| 5 | Error prevention | 3 | Allowlist verdict drives button vs text; 14 of 14 external anchors `rel="noopener noreferrer"` with a hidden "(si apre in una nuova scheda)"; amber computed in DatePair only (0 amber nodes on the plan; correct on the edge scenario). Deduction: a booking whose deadline is already past keeps the same primary "Prenota su" button (edge scenario). |
| 6 | Recognition rather than recall | 3 | Roundels tie rows to agents; itinerary stops link to bookings. Deduction: the strip rows have no arrow or underline, so on a touch screen nothing says they jump. |
| 7 | Flexibility and efficiency | 3 | The strip is the missing accelerator. Deductions: no deadline order in the list the user acts from, no way to open the two bookable links in one go, no skip link (44 focusable controls). |
| 8 | Aesthetic and minimalist design | 3 | Calm, flat, the line vocabulary holds. Deductions: the cost is stated four times in the first 520 px; the dates twice; on desktop the first screen is a 640 px column and 55 % empty ground. |
| 9 | Error recovery | 3 | Missing Trip falls back to derived/unknown deadlines (checked in code and the `fetch`/`failed` scenarios exist); no-link bookings name the vendor and the host, and the phone when there is one. Deduction: the host is text, not a tap. |
| 10 | Help and documentation | 4 | The lead under "Prenotazioni", the "Da sapere prima di prenotare" notice, the reason under each date pair ("Le tariffe per metà aprile di solito salgono da marzo.") and the one-line lead of each section are the best help in the product. |
| **Total** | | **31/40** | **Good (77.5 %); +1 on round 1, no P0/P1, one point under the gate** |

## Design specificity verdict

**LLM assessment (written before the detector ran).** Authored, not interchangeable. The first screen now
has a job: summary, a plain "710 € sotto il budget" sentence, then a deadline-ordered list of what to book
with the agent roundels in their line colours, which is the product's line-map vocabulary doing real work
(each piece is tied to the agent that found it). The two-box date pair is still the most product-specific
object on the page. What keeps it from a 4 is composition on desktop (a single narrow column in a
1440 px frame, bookings suddenly full width) and a first-screen text stack that says the same number three
times. The page is a very good reading of the brief for a phone; on the Mac it is a phone page with room.

**Deterministic scan.** `impeccable detect --json components/plan components/live components/states
app/plans components/ui` returned `[]` (exit 0): no findings, no false positives. Browser overlay injection
was not run (shared browser pane; injecting a script and starting the live server would disturb the other
agents), so the fallback signal is the clean CLI scan plus the DOM audit.

**DOM audit.** 393 px: `scrollWidth` 393, no horizontal scroll. One h1, h2 per section (Sintesi del piano
(sr-only), Da prenotare, Giorno per giorno, Prenotazioni, TripTracker (sr-only), Alternative scartate, Il
lavoro degli agenti, Corsie degli agenti), h3 per day and booking. One `aria-live="polite"` region. 0 em
dashes in the page text. 0 amber nodes on the happy plan. Computed font sizes in use: 12.5, 13.5, 14.5, 15,
18, 20, 24 px (all DESIGN.md steps). Focus ring: `outline: solid 2px rgb(15,26,42)`, offset 3 px (ink), as
specified. 29 `motion-reduce` utilities, nothing animates outside the declared table; reduced motion could
not be emulated by the browser tool (verified by rule count only). Controls under 44 px on the phone: the
theme toggle (40), "Prenota su" and "Apri in TripTracker" (40, DESIGN.md's size), the alternatives' "Vedi su"
(32, `sm`), inline links; all above WCAG 2.2's 24 px. Page height: 5,072 px (phone), 3,732 px (desktop).

## Overall impression

The round 1 P1 is properly fixed and the page now answers the question the user brings ("what do I book,
and by when?") in the first viewport. What is left is polish and one real content hazard: the flight clock.
Biggest opportunity: use the empty right of the desktop frame for the page's job (the deadline list and
the TripTracker hand-off) and cut the repeated cost and date lines so the first phone screen is shorter.

## What's working

- **"Da prenotare" strip.** Sorted by deadline, 44 px rows, roundel + title + "entro ven 26 feb", an ink
  "N in scadenza" count when it applies, urgency in words ("Scadenza passata", "In scadenza · tra un giorno"),
  and amber kept out of it. It lands at y=632 on the phone and y=416 on desktop.
- **The two dates.** "Prenota entro" and "Quando" stay two labelled boxes at 13.5 px with relative distance
  ("tra 137 giorni") and the agent's reason beneath. The amber state on the edge scenario is amber wash +
  stroke + "In scadenza · tra un giorno" or "Scadenza passata": colour never alone.
- **Provenance.** Price, a "verificato"/"stimato" word chip, the source as a quiet link, "letto il 12 ott
  2026, 12:01". Dark mode holds all of it (inverted primary pill, ink-2 contrast) with no exceptions.
- **The arrival.** Focus and scroll go to the summary when a watched run completes; the live region stays
  quiet except for lane states. Exactly what the spec asks.

## Priority issues

### [P2-1] A flight leaving Milan is shown on the Lisbon clock

- **Where**: `components/plan/bookings.tsx` (`timeZone={plan.timezone}` for "Quando"), `components/plan/itinerary.tsx` gutter, `plan-model.ts` `tripZoneName`.
- **What**: the flight row says "Quando mer 14 apr, 08:40 / ora di Lisbona"; the itinerary gutter says 08:40; the agent's note says "Partenza alle 09:40 ora italiana". The label is honest, but the number Michele would act on at the airport in Malpensa is 09:40. The day-1 card shows 08:40 and 09:40 for one departure, and the only reconciling text is a 14.5 px ink-2 lead ("Gli orari sono quelli di Lisbona.") above the whole itinerary, which is easy to miss. The `ora di Lisbona` caption is also printed five times on five identical boxes.
- **Why it matters**: PRODUCT.md: success is "knows by when each one must be booked" and showing up for it. Reading a departure an hour early is a mild failure, an hour late is a missed flight. A label is not a fix for a hazard.
- **Fix**: when the trip's clock differs from `HOME_TIMEZONE` at that instant, show both in the "Quando" box: value "mer 14 apr, 08:40", second line "09:40 in Italia" (ink-2, 12.5 px), instead of the repeated "ora di Lisbona". In the itinerary keep the Lisbon gutter but add "(09:40 in Italia)" to the stop's meta only for stops with `kind` flight/transport that start from home. Drop the page-level lead once each stop says it.
- **Command**: `/impeccable clarify`, then `/impeccable harden`.

### [P2-2] The first 520 px of the phone say the cost four times and the dates twice

- **Where**: `components/plan/plan-summary.tsx`, `components/live/live-header.tsx`.
- **What**: subtitle "budget 2.400 €"; summary line 3 "Costo stimato: circa 1.690 € (voli 812 €, hotel 736 €, ...)"; fact "Costo stimato totale 1.690,00 €"; "710 € sotto il budget di 2.400 €"; "Somma delle 5 prenotazioni, 3 prezzi stimati". The "Date" fact "Dal 14 al 18 aprile 2027 / 5 giorni" repeats the h1 "14–18 aprile 2027" one block above. At 1440 the same facts row repeats the sub-title line again. Round 1 asked to drop the "Date" fact when it equals the title range; it is still there.
- **Fix**: keep the total fact (it carries the comparison); fold "5 giorni" into the "Base" fact or the title subtitle and delete the "Date" fact when `formatTripDates` is contained in the title. Replace "Somma delle 5 prenotazioni, 3 prezzi stimati" with only "3 prezzi stimati" (the count of bookings is already "5" in the strip). Line 3 of the summary is the agent's text: ask the coordinator prompt (`agents/coordinator.md`) not to restate the total, or have the UI hide a line that starts with "Costo stimato:". That brings the strip up by about 110 px, to y ≈ 520.
- **Command**: `/impeccable distill`.

### [P2-3] Desktop: a 640 px column in a 1440 px frame, the destination at the far left

- **Where**: `components/plan/PlanView.tsx` layout (`max-w-prose` summary and strip; bookings 1384 px; `LinkButton` `sm:w-auto`).
- **What**: at 1440x900 the first screen is the title, a 640 px summary and the strip at x=28..~640, with 55 % empty ground to the right; the first "Prenota su" is at y=2,621 (2.9 screens), "Apri in TripTracker" a 177 px outline pill at y=3,347. The bookings then switch to a full-width three-column row. The page reads as two different layouts.
- **Fix**: from `lg` put the summary and facts in the left column and the "Da prenotare" strip plus the TripTracker hand-off in a right column (about 28 rem, `lg:sticky lg:top-6`), with the days and bookings below as they are. No new cards: same hairlines. This puts "what to book by when" and "Apri in TripTracker" beside the summary on the first desktop screen and shortens the page by roughly 250 px. If the right rail is out of scope, at minimum make "Apri in TripTracker" the full 240 px of the action column's width so it aligns with the "Prenota su" buttons above it.
- **Command**: `/impeccable layout`.

### [P2-4] The strip rows do not look tappable, and the list below is in another order

- **Where**: `components/plan/booking-strip.tsx` (`no-underline`, hover wash only), `components/plan/PlanView.tsx` (the `ol` of `BookingRow` uses `plan.bookings` order).
- **What**: on the phone a row of "Da prenotare" is a roundel, a title and a bold date: indistinguishable from a static list. There is no arrow, underline or caret; the only cue is a hover wash that touch devices never see. Tapping the third row ("Ingressi Palácio da Pena", 9 apr) jumps to the fourth booking below; the fourth strip row ("Biglietti Oceanário", 12 apr) jumps back up to the third.
- **Fix**: add a trailing `arrow-down` icon (16 px, ink-2) to each strip row, or underline the title like the quiet links elsewhere; sort the "Prenotazioni" list with the same `sortByDeadline` (the agent order stays in the itinerary), so the strip and the list read top to bottom in step.
- **Command**: `/impeccable clarify`, `/impeccable polish`.

### [P3-1] The loading skeleton is still a running plan

- **Where**: `components/states/plan-skeleton.tsx`, `app/plans/[id]/loading.tsx`, `components/live/plan-screen.tsx` (`if (!hasData) return <PlanSkeleton />`).
- **What**: opening a finished plan paints the title block, a control bar with a cost meter and five lane cards (five columns on desktop) and then replaces them with a different page (5,072 px on the phone). Observed on every cold load at both widths; the layout shift is total. (How long it lasts could not be timed reliably: the tool's tab is hidden, so the page is throttled until a screenshot.)
- **Fix**: first answer unknown, so render a neutral skeleton: title block, three text lines, a facts row and three 44 px rows (the shape of the finished page's first screen), or remember the last status per plan in `sessionStorage` (try/catch) and pick the lane skeleton only for `running`.
- **Command**: `/impeccable harden`.

### [P3-2] "Prenota sul sito: oceanario.pt" is text, the Fonte link two lines above is a tap

- **Where**: `components/plan/bookings.tsx` `ActionSide`, `PriceLine`.
- **What**: for Oceanário, Palácio da Pena and Aerobus the action column names the host in semibold ink as plain text, while "Fonte oceanario.pt ↗" in the price line is a working link to the same site. The rule (no "Prenota su" without an allowed verdict) is respected; the tap target is just in the wrong place. On the two bookable rows the opposite happens: "Fonte Expedia ↗" and "Prenota su Expedia ↗" are adjacent links to the identical URL (checked: same href).
- **Fix**: say it: "Nessun link di prenotazione. Per prenotare apri il sito dalla fonte qui sopra: oceanario.pt" (no new link, no rule broken), or render the host as the same `QuietExternalLink` and keep "Prenota su" for allowed verdicts only. On bookable rows show "Fonte Expedia" as text when it equals the booking link.
- **Command**: `/impeccable clarify`.

### [P3-3] A booking whose deadline has passed keeps the same primary button

- **Where**: `components/plan/bookings.tsx` `ActionSide` (variant is by `alternative` only); visible on `/dev/plan?scenario=edge` ("Scadenza passata" above a black "Prenota su Expedia").
- **What**: a past deadline is amber, but the row's action is as inviting as any other. The contract sends such a `book_by` back to the agent, so it is rare, but it is exactly the case where a calm, honest line helps.
- **Fix**: keep the button (the user may still book) and add one line under the dates when `deadline.kind === "date"` and in the past: "La scadenza è passata: controlla che sia ancora disponibile." in ink-2, no colour.
- **Command**: `/impeccable harden`.

### [P3-4] No way forward from a finished plan

- **Where**: the page header (wordmark only) and the end of the page.
- **What**: after "Apri in TripTracker", or after reading, the only route is the 53 px "Atlas" link. Round 1 flagged it; unchanged. The timeline disclosure is the last element.
- **Fix**: a quiet "Nuovo piano" link (quiet button, 40 px) in the header's right group next to the theme toggle, at 1080 px and up, and at the foot of the page on the phone.
- **Command**: `/impeccable layout`.

### [P3-5] Smaller things

- "Il lavoro degli agenti" is an h2 inside a `<summary>`: the accessibility tree here keeps it as a heading, but summary children are presentational in some engines. Keep the visible title in the `summary` and move the heading role to the `details` label only if VoiceOver on Safari flattens it (test on the iPhone).
- No skip link; 44 focusable controls, 15 before the first "Prenota su". Acceptable since the strip comes first, but a "Vai alle prenotazioni" skip is one line.
- "Prenota entro  nessuna scadenza" (two spaces) in the compact alternative pair.
- The "Quando" captions repeat "ora di Lisbona" five times (see P2-1).

## Persona red flags

**Casey (Michele on the iPhone, between two things).** Opens the plan: title, one status line, three summary lines
that include the cost, two fact blocks, and "Da prenotare" starting at y=632 with three of five rows visible.
Good: the deadline order is the first thing after the facts, and the primary buttons are full width and in the
thumb zone once he gets there. Flags: tapping a strip row gives no hint it will jump (P2-4); the rows below are in
a different order (P2-4); "Apri in TripTracker" is at y=4,630 of 5,072, five screens down (acceptable only
because it follows the bookings, as DESIGN.md says).

**Sam (keyboard / screen reader).** Heading outline clean (no skipped levels), one polite region that stays empty
at rest, focus ring 2 px ink with a 3 px offset on every control tried, closed `<details>` take no focus, 14 of 14
external anchors announce "(si apre in una nuova scheda)". Flags: the strip's link names read "title, entro
date" with no hint they go to a booking; focus does not move when a strip row is activated (the browser
scrolls, the sequential focus start follows, which is fine, but a screen-reader user hears nothing); the h2
inside `<summary>` (P3-5).

**Alex (the owner at the Mac, daily).** The strip now answers "what first" at 416 px. Flags: the actions are 2,200
px below it; bookings are not in deadline order; no "open both bookable links"; the right 55 % of the screen is
empty while the page scrolls for 3,700 px (P2-3).

**Riley (stress, edge).** On `/dev/plan?scenario=edge`: a very long hotel title wraps cleanly in the strip and the
row; a past deadline sorts above the due-soon one; "Da prenotare subito" sorts first; a link outside the
allowlist is text with "Link non verificato". Flag: a past deadline keeps a primary button (P3-3).

## Minor observations

- The theme toggle sits in the status row on the phone and in the top bar on desktop: both fine.
- Alternatives: "Vedi su Booking.com" for a Martinhal listing whose source is martinhal.com is correct but may
  surprise; the label names the host, which is the right call.
- The page title "Lisbona in famiglia, 14–18 aprile 2027 · Atlas" is good; the running page's title ("Lisbona, 14–18 apr")
  differs from the finished one: the two names for one trip are deliberate but visible in tab history.
- The caret of an opened disclosure is mid-turn when the screenshot is taken within 220 ms: motion works.
- Dark mode at both widths: surfaces, hairlines, the notice's dashed edge and the inverted primary pill all hold.

## Questions to consider

- If the right rail existed on desktop, would the page still need "Da prenotare" in the left column at all?
- Is "Costo stimato: circa 1.690 €" the agent's sentence or the product's number? One of the two should go.
- Should a booking row end with its action, and the deadline order be the only order the page has?

## Checks against the rules asked

| Rule | Result |
| --- | --- |
| Two dates separate and labelled | Pass: plan rows (fields) and alternatives (compact, "nessuna scadenza"); strip shows only "entro" and says it is the deadline. |
| Amber reserved | Pass: 0 amber nodes on the happy plan; on the edge scenario amber appears only inside DatePair (wash + stroke + words), never in the strip, buttons, chips or headings. |
| Sentence case, no em dash, verbs on buttons | Pass: 0 em dashes in page text; "Prenota su", "Vedi su", "Apri in TripTracker". |
| `rel="noopener noreferrer"`, new tab, only when the verdict allows | Pass: 14 of 14 external anchors; no-link bookings are text. |
| aria-live only for agent state | Pass: one region, only "Coordinatore: finito"-style entries during the watched run, empty at rest. |
| Reduced motion | Pass by rule (29 `motion-reduce`, fade-in fallbacks); not exercised at runtime. |
| Keyboard and focus | Pass: visible 2 px ink ring, logical order, first "Prenota su" is stop 16; no skip link (P3-5). |
| 393 px | Pass: scrollWidth 393, no overflow. |
| Costs in dollars with two decimals | Pass: "0,41 $" (and "limite 0,60 $" while running); trip prices in euro. |

## Fix list in order

1. P2-1 flight clock (show the Italian clock where it matters).
2. P2-2 remove the repeated cost and date lines.
3. P2-4 strip affordance and same order in the list.
4. P2-3 desktop right rail.
5. P3-1 neutral skeleton, P3-2 host link, P3-3 past deadline line, P3-4 "Nuovo piano".

Reaching 33 to 34 needs P2-1, P2-2 and P2-4 only; they move heuristics 2, 4, 6 and 8 by one point each.

Trend: round 1 30/40 (1 P1) then round 2 31/40 (0 P0, 0 P1), same max, like for like.
