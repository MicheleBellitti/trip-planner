---
target: "/plans/[id] finished plan (status ready)"
slug: id-ready
round: 1
total_score: 30
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 1
---

⚠️ DEGRADED: single-context (no sub-agent/Task tool is exposed to this agent, so Assessment A and B ran sequentially in one context; A was written down before the detector ran)

# Critique, round 1: finished plan page `/plans/[id]` (ready)

Surface: demo plan `6c14b842-a536-4529-a645-4a094d183545` (happy_path, Lisbona 14-18 aprile 2027,
5 bookings, 2 alternatives, 81 events). Viewed at 393x852 and 1440x900, light and dark, plus the
timeline and the alternatives opened. Judged against `web/DESIGN.md`, `web/PRODUCT.md`, the spec's
"Il piano finito" and states table, and the CLAUDE.md UI rules. Mode: Operate (the visitor decides a
trip and books it).

Not verifiable on this plan: the amber due-soon state (every deadline is 137+ days away because the
demo trip is in April 2027 and today is 2026-10-12). It was checked in the `/dev/ui` gallery
("Date di una prenotazione"): amber wash and stroke, the words "In scadenza · tra 2 giorni" and
"Scadenza passata", compact variant, all correct in light.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | "Pronto", verified/estimated chips, "letto il ...", "tra 137 giorni" are all there. Deductions: the running-style cost meter stays at full size on a finished plan; the loading skeleton is shaped like a running plan (five lane cards). |
| 2 | Match system / real world | 3 | Italian, sentence case, no em dash (0 found), two dates labelled exactly as specified. Deductions: two "budget" figures in two currencies in the first viewport; times shown in the trip's time zone with no label while the user lives in Rome. |
| 3 | User control and freedom | 3 | Alternatives and timeline are closed by default and open natively; every external link opens in a new tab. Deduction: no way home except a 37x22 px "Atlas" wordmark. |
| 4 | Consistency and standards | 3 | Same booking row for plan and alternatives, same DatePair everywhere. Deductions: 2 of 5 bookings have a primary button, 3 have a dead-end sentence; the "Il lavoro degli agenti" section title is a span while its siblings are h2; alternatives print "Prenota entro non disponibile". |
| 5 | Error prevention | 3 | Allowlist verdict drives button vs plain text, `rel="noopener noreferrer"` on all 14 external links, amber computed inside DatePair only. Deduction: deadlines and flight times are not labelled with a time zone. |
| 6 | Recognition rather than recall | 3 | Each itinerary stop links to its booking ("Da prenotare: ..."). Deduction: the only jump to bookings is an 18 px "5 da fare" link; nothing says which booking is first. |
| 7 | Flexibility and efficiency | 2 | Bookings start 2,794 px down on the phone; header is not sticky when ready; no jump list, no ordering by deadline; "Apri in TripTracker" is the last element and moves 2,200 px further down once the timeline is opened. |
| 8 | Aesthetic and minimalist design | 3 | Calm, flat, restrained, the line vocabulary carries into the itinerary. Deductions: the top screen repeats itself (dates, travellers, total each appear twice). |
| 9 | Error recovery | 3 | Failed trip read falls back gracefully; no-link bookings name the vendor and phone. Deduction: the no-link sentence ignores the price-source link sitting right above it. |
| 10 | Help and documentation | 4 | Contextual help is the strongest part: the lead under "Prenotazioni", "Da sapere prima di prenotare", and the per-booking reason under the dates ("Le tariffe per metà aprile di solito salgono da marzo."). |
| **Total** | | **30/40** | **Good (75%)** |

The spec's merge gate is 32/40 with no open P0 or P1. This round is **below the gate** (30, one P1).

## Design specificity verdict

**LLM assessment (written before the detector ran).** This is authored, not interchangeable. The
itinerary reuses the transit-line vocabulary (large ink ring per day, small rings per stop, a 3 px
neutral line, times in a gutter) without borrowing agent colours, which keeps The One Hue Per Line
Rule intact. Roundels in line colours on bookings tie the plan back to the agents that found each
piece. The two-date field pair is the most product-specific object on the page and it is
well-made: labelled boxes, equal weight, relative distance ("tra 137 giorni"), reason text below.
Barlow Semi Condensed headings plus tabular figures fit a "calm control room". What reads generic is
the first screen: a plain paragraph, a four-up facts strip at 12.5 px labels, a dashed note. It is
tidy but it has no focal point; nothing says "this is your trip, here is what to do next".

**Deterministic scan.** `impeccable detect --json components/plan components/live components/states
app/plans` returned `[]` (exit 0): no anti-pattern findings. No false positives. Browser overlay
injection was not run (the critique runs in a shared browser pane and mutating injection plus a
live-server would disturb the other agents); fallback signal is the clean CLI scan plus the manual
DOM audit below.

**DOM audit (393 and 1440 px).** No horizontal scroll at 393 (scrollWidth 393, no element past the
right edge). One h1, h2 per section, h3 per day and booking; one `aria-live="polite"` region,
empty on ready (agent state changes only). Focus ring is a 2 px ink outline on every control tried
(wordmark, theme toggle). All 14 external links carry `rel="noopener noreferrer"` and a hidden
"(si apre in una nuova scheda)". Closed `<details>` do not take focus. No em dash on screen.
`prefers-reduced-motion` is honoured by 13 `motion-reduce` / media-query rules.

## Overall impression

A competent, calm finished plan with a very good booking row. The weakness is order and emphasis,
not craft: the task is "book each piece before its deadline", yet the first phone screen is spent
on status chrome and a repeated summary, the bookings begin three screens down, and the plan's
destination ("Apri in TripTracker") is the last, quietest object on a 4,700 px page. Biggest
opportunity: add an at-a-glance, deadline-ordered "what to book first" strip to the summary and let
the rest of the page stay as the spec lays it out.

## What's working

- **The two dates.** "Prenota entro" and "Quando" are always two labelled boxes, never merged,
  with distance and reason attached; alternatives keep both labels in the compact form. This is the
  product's promise made visible.
- **Honest price provenance.** Price, a verificato/stimato word chip (never colour alone), the
  source as a quiet link with "letto il 12 ott 2026, 12:01". Trust is built from facts.
- **Itinerary as a line, not cards.** The day ring plus stop rings is readable at 393 px, ties to
  the product's metaphor, uses tabular times, and each stop links to its booking. Dark mode holds
  all of it (contrast, ring fill, button inversion) without a single hard-coded exception.

## Priority issues

### [P1] The booking task is buried and has no entry point ordered by deadline

- **Where**: `components/plan/PlanView.tsx` section order, `components/plan/plan-summary.tsx`
  "Prenotazioni / 5 da fare" fact.
- **What**: on the phone the first booking starts at y=2,794 (3.3 screens); on desktop about two
  screens down. The only shortcut is "5 da fare", an 18 px-high underlined link in a 12.5 px-labelled
  fact. Nothing tells Michele which booking is first or whether any is due soon; the itinerary above
  repeats the same five bookings as "Da prenotare" links, so the top of the page promises
  bookings but delivers days.
- **Why it matters**: PRODUCT.md success criterion one is "knows by when each one must be booked".
  The page currently answers "what is the trip" before "what do I have to do and by when".
- **Fix** (keeps the spec's order: summary, days, bookings): replace the "Prenotazioni" fact with a
  full-width strip under the facts, "Da prenotare" with the bookings sorted by `deadline`, one line
  each: `Volo TAP Milano Malpensa ⇄ Lisbona · entro ven 26 feb` as anchor links to `bookingAnchor(i)`
  (min 44 px tall rows on the phone). When one or more is due soon say it in words in ink, never
  amber: "2 in scadenza" (amber stays inside DatePair). Alternatively propose an amendment to
  DESIGN.md Layout to put "Prenotazioni" before "Giorno per giorno" on the phone only.
- **Command**: `/impeccable layout`, then `/impeccable clarify`.

### [P2] The finished page still shows the running cost meter and two competing "budget" numbers

- **Where**: `components/live/live-header.tsx` (ready state), `components/ui/cost-meter.tsx`.
- **What**: in the first 400 px of the phone there is "budget 2.400 €" (trip, subtitle) and, 130 px
  below, "0,41 $ spesi ... budget 0,60 $" with a 68 % full ink bar and a thumb. Different currency,
  same word, a bar that looks like a trip-budget gauge. The visible label never says it is the
  session's API cost (only the `aria-label` "Costo della sessione" does). The header block eats about
  170 px of the first viewport for information that no longer changes.
- **Fix**: when `status === "ready"` drop the meter and show one quiet line, "Costo del piano 0,41 $"
  (no bar), or move it into the "Il lavoro degli agenti" disclosure meta ("81 eventi, 0,41 $"). If the
  meter stays, relabel the right end "limite 0,60 $" and keep "budget" for the trip only.
- **Command**: `/impeccable distill`.

### [P2] "Apri in TripTracker" is the product's destination but is the last and weakest object

- **Where**: `components/plan/PlanView.tsx` (the `timeline` slot is before the TripTracker section).
- **What**: the outline pill is left-aligned, 177 px wide, at y=4,626 of 4,714 on the phone. Opening
  "Il lavoro degli agenti" grows the page to 6,903 px and pushes the button 2,200 px further away.
  PRODUCT.md: "The trip lands in TripTracker without retyping anything" is a success criterion.
- **Fix**: render the TripTracker section directly after the bookings (above "Alternative scartate"
  and the timeline); on the phone make the button `w-full` (like "Prenota su"), keep `secondary`
  (the amber and one-primary rules stay intact). This departs from the spec's "in fondo": record it
  in DESIGN.md Layout if accepted. Minimal alternative: keep it last but full width on the phone and
  put the timeline's `RunSection` after it.
- **Command**: `/impeccable layout`.

### [P2] Dates have no time zone; deadlines are shown in the trip's clock, not Michele's

- **Where**: `components/plan/bookings.tsx` (`timeZone={plan.timezone}` for both fields),
  `components/ui/date-pair.tsx`.
- **What**: "Prenota entro ven 26 feb, 20:00" is 20:00 in Lisbon in February, which is 21:00 for
  Michele in Rome. "Quando mer 14 apr, 08:40" for the flight from Milan is Lisbon time; the notes
  say "Partenza alle 09:40 ora italiana" so the same card shows 08:40 and 09:40 for one departure.
  Nothing on the page says which clock applies.
- **Fix**: render "Prenota entro" in Europe/Rome (the user's clock, `HOME_TIMEZONE`) and add a short
  clock hint to "Quando" only when it differs: "mer 14 apr, 08:40 (ora di Lisbona)". Same hint on
  the itinerary gutter once per day or in the "Date" fact ("ora di Lisbona"). Needs a decision on
  which side owns the rule; the contract already stores offsets.
- **Command**: `/impeccable clarify`, `/impeccable harden`.

### [P2] Summary repeats itself and misses the one comparison that matters (cost vs budget)

- **Where**: `components/plan/plan-summary.tsx`.
- **What**: the third summary line ("Costo stimato: circa 1.690 € (voli 812 €, ...)") and the fact
  "Costo stimato totale 1.690,00 €" say the same thing 60 px apart; the "Date" fact repeats the h1
  (14-18 aprile 2027) and "4 viaggiatori" repeats the subtitle. The facts' labels are 12.5 px.
  Meanwhile the number a decider wants, 1.690 € against a 2.400 € budget, is not shown.
- **Fix**: change the first fact to "Costo stimato totale 1.690,00 €" with the note "710 € sotto il
  budget di 2.400 €" (or "sopra" in ink with the existing neutral warning style, never amber/red);
  drop the "Date" fact when it equals the title's range, or fold it into "Base"; raise fact labels to
  `text-meta` (13.5 px). The agent's third line is content from the backend, leave it.
- **Command**: `/impeccable distill`, `/impeccable typeset`.

### [P2] Three of five bookings end in a dead-end sentence

- **Where**: `components/plan/bookings.tsx` `ActionSide`.
- **What**: Oceanário, Palácio da Pena and Aerobus show "Nessun link: prenota direttamente con
  Oceanário de Lisboa." while their price source (oceanario.pt, parquesdesintra.pt, aerobus.pt) is a
  working quiet link two lines above. The row's action column is empty text, so the page looks like
  two real actions and three loose ends; on desktop the sentence is left-aligned in the 240 px
  column while the buttons are right-aligned.
- **Fix** (copy only, rules kept: no "Prenota su" without an allowed verdict): "Nessun link di
  prenotazione. Prenota sul sito di Oceanário: oceanario.pt" where the host is the price source link,
  or a secondary `size="sm"` "Apri oceanario.pt" button (verb, not "Prenota"). Align the text column
  with the button's left edge (`lg:justify-start` for text, `lg:justify-end` for buttons is the
  current mismatch).
- **Command**: `/impeccable clarify`.

### [P3] Loading state is the running-plan skeleton

- **Where**: `components/states/plan-skeleton.tsx`, `app/plans/[id]/loading.tsx`.
- **What**: the page is client-rendered (server HTML is the skeleton, no h1). A finished plan opens
  on five lane-card placeholders, then jumps to a summary and a 4,700 px page. Layout shift is
  total. In dev it stayed visible for more than 2 s on cold loads.
- **Fix**: before the first answer render a neutral skeleton (title block plus three text lines and
  a block), or remember the last known status per plan in `sessionStorage` (try/catch) and choose
  the skeleton shape from it.
- **Command**: `/impeccable harden`.

### [P3] Alternatives print "Prenota entro non disponibile"

- **Where**: `components/plan/plan-model.ts` `alternativeDeadline` (returns `unknown` when it has a
  `scheduled_for` but no `book_by`), `components/ui/date-pair.tsx`.
- **What**: a discarded option with no deadline reads as an error value next to a label that must
  stay. The label rule is right; the value is noise.
- **Fix**: return `{ kind: "none" }` for alternatives without `book_by` so it reads "nessuna
  scadenza", quiet ink-2.
- **Command**: `/impeccable clarify`.

### [P3] Small targets and one heading inconsistency

- "Atlas" wordmark 37x22 px, "5 da fare" 57x18 px: under the 24 px WCAG 2.2 minimum when they are
  standalone targets (inline "Da prenotare" and "Fonte" links are exempt as in-sentence). Give both
  `min-h-6` with padding or `py-1.5` (44 px on the phone for the wordmark's bar).
- "Il lavoro degli agenti" (`run-section.tsx`) is a bold span; "Alternative scartate" and
  "Prenotazioni" are h2. A screen-reader heading list jumps from "Alternative scartate" to a
  sr-only "Corsie degli agenti" with no visible counterpart. Make the summary text a heading (the
  summary's inner span becomes an `h2` with `role` kept native).
- "Fonte Expedia" and "Prenota su Expedia" link to the same URL on the flight row (two adjacent
  external links, same target); fine by the rules, but consider showing "Fonte" as text when it
  equals the booking link.
- The labels "Prenota entro" and "Quando" (the mandated pair) are the smallest text in the row at
  12.5 px (`text-micro`); raising them to 13.5 px costs nothing.

## Persona red flags

**Casey (distracted mobile user, Michele on the iPhone).** Opens the plan between two things: the
first screen is title, a meter, a paragraph and four facts; no booking, no action. To reach the first
"Prenota su Expedia" he scrolls 3.3 screens past five days of itinerary. The cost bar and "budget
0,60 $" look like a trip gauge. The primary actions (full-width pills) are in the thumb zone once he
gets there, which is good; "Apri in TripTracker" is not full width.

**Sam (keyboard / screen reader).** Heading outline is clean and the live region is empty on ready,
as intended; focus ring is visible. Gaps: "Il lavoro degli agenti" is not a heading; "5 da fare" and
the wordmark are small targets; the tab order to the first booking button passes through every
itinerary link (20+ stops) with no skip target other than "5 da fare".

**Alex (the owner at the Mac, repeats this daily).** Wants to open all bookings in tabs in order.
No ordering by deadline, no "apri tutti"; each of the 2 button rows is 900 px apart on desktop. The
itinerary is limited to 44 rem of a 1,384 px column, leaving the right 440 px empty while bookings
run full-width.

## Minor observations

- Desktop: itinerary and prose are left-heavy (13 rem + 44 rem columns in a 1,384 px page); the
  empty right third reads as unfinished next to the full-width booking rows. A right-hand sticky
  "Da prenotare" list (the P1 strip) would use that space without adding a card grid.
- Summary paragraph is plain 15 px body with three equal lines; the second fact's value "Dal 14 al 18
  aprile 2027" is the same weight as the total. Consider the total at `text-heading` size.
- The finished header has no sticky bar (correct, nothing is running) but also no "Nuovo piano" or
  "I tuoi piani" link; home is only the wordmark.
- Booking rows put the CTA last (after notes, dates, reason): on the phone each row is about 600 px;
  five rows are 2,900 px. A tighter row (price, source and notes in one `meta` line) would save a
  screen.
- Closed timeline holds 81 events in the DOM while closed (all lanes mounted); harmless to focus
  (closed details), a small render cost on a long run. Mount lanes on first open.
- Timeline opened: all five lanes say "Finito", the coordinator's long list is the open lane; fine.

## Questions to consider

- If Michele could do only one thing on this page, would he expect to see "book the flight by 26
  feb" at the top, or the summary paragraph?
- Does the finished plan need the session meter at all, or only the number?
- What would the page look like if the TripTracker import were the confident primary end of the
  flow and "Prenota su" a per-row step toward it?

## Checks against the rules asked

| Rule | Result |
| --- | --- |
| Two dates separate and labelled | Pass in plan rows and in alternatives (compact). Alternative value "non disponibile" is noisy. |
| Amber reserved | Pass: no amber anywhere on this plan (nothing due within 72 h); gallery confirms DatePair draws it with words; no amber on buttons. |
| Sentence case, no em dash | Pass: 0 em dashes on screen; headings and buttons in sentence case, verbs on buttons. |
| `rel="noopener noreferrer"`, new tab, only when allowed | Pass: 14 of 14 external anchors; no-link bookings are text. |
| aria-live only for agent state | Pass: single polite region, empty on ready. |
| Reduced motion | Pass by rule count (13 `motion-reduce` rules; chevron and fade-in covered). Not exercised at runtime. |
| Keyboard and focus | Pass: ring visible, order logical; small targets noted. |
| 393 px | Pass: no horizontal scroll, no overflow element, h1 fits at 24 px. |
| Costs in dollars | Pass: "0,41 $", "0,60 $"; trip prices in euro. |

Trend: first run for this target, no trend yet.
