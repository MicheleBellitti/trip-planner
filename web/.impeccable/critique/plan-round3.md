---
target: "/plans/[id] finished plan (status ready)"
slug: id-ready
round: 3
total_score: 32
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
---

⚠️ DEGRADED: single-context (no sub-agent/Task tool is exposed to this agent, so Assessment A and B ran sequentially in one context; A was written down before `impeccable detect` ran)

# Critique, round 3: finished plan page `/plans/[id]` (ready)

Surface: demo plans `eaff550e-94ca-4782-83ff-76702e5e1b1f` (happy_path, 5 bookings, 2 alternatives, 62 events,
read cold) and `17bcd050-b09d-4002-b4fa-6bc4f6a2954a` (watched from `running` to `ready`, to test the arrival).
Viewed at 393x852, 1440x900 and 1100x800, light and dark, with the alternatives and the timeline opened. The amber
due-soon case cannot occur on a happy_path plan (deadlines are 137+ days away on 2026-10-12), so it was checked on
`/dev/plan?scenario=edge` (the same `PlanView` on shifted dates), in dark. Judged against `web/DESIGN.md`,
`web/PRODUCT.md`, the spec's "Il piano finito" and states table, and the CLAUDE.md UI rules. Mode: Operate.

Note on "previous rounds": the harness passed `[]`, but `plan-round1.md` (30/40, one P1) and `plan-round2.md`
(31/40, no P0/P1) exist on disk. This round verifies both, one by one.

Checks run: `npm test` 440 passed, `npm run lint` clean, `npm run typecheck` clean, `impeccable detect --json
components/plan components/live components/states app/plans components/ui` returned `[]` (exit 0).

## Verification of the previous findings

### Round 1

| Finding | Status | Evidence now |
| --- | --- | --- |
| **P1** booking task buried, no entry by deadline | **Fixed** | "Da prenotare" heading at y=564 on the phone (inside the first 852 px viewport, rows end at about y=830) and y=167 on desktop. Five rows sorted by deadline, 44 px tall, underlined titles. The first "Prenota su" is the 15th tab stop (was 16th in round 2). Page height 5,024 px (phone), 3,339 px (desktop). |
| P2 running cost meter and two "budget" numbers | Fixed | Header: "Pronto / Durata 0:37 · Costo del piano 0,41 $", no bar. |
| P2 "Apri in TripTracker" last and weakest | Fixed | Phone: right after the bookings, full width (361x40). Desktop: in the right column under the strip, 448x40. |
| P2 time zones | Fixed in intent, residual in P2-1 below | |
| P2 summary repeats itself | Fixed | One total fact with "710 € sotto il budget di 2.400 €" and "3 prezzi stimati"; the "Date" fact is gone (the title states them); the agent's restating line is dropped. |
| P2 dead-end sentences | Fixed | "Nessun link di prenotazione. Prenota sul sito di X: host". |
| P3 skeleton, alternatives "non disponibile", small targets, heading | Fixed except the skeleton (P3-1 below) | |

### Round 2

| Finding | Status | Evidence now |
| --- | --- | --- |
| P2-1 flight on the Lisbon clock | **Fixed, with a residue** | The "Quando" box now carries "09:40 in Italia" under "08:40"; the itinerary says "(parte alle 09:40 in Italia)". The residue is P2-1 below (which clock leads, no label on the first). |
| P2-2 cost said four times, dates twice | **Fixed** | The strip starts at y=564 instead of 632. Cost appears once as a fact plus the comparison line. |
| P2-3 desktop is a 640 px column | **Fixed at the top, not below it** | Two columns from 1080 px: summary and facts left, "Da prenotare" and "Apri in TripTracker" right. Page 393 px shorter. The right column ends with the summary (P2-2 below). |
| P2-4 strip not tappable, other order below | **Fixed** | Titles underlined, "Prenotazioni" uses the same `sortByDeadline`; tapping the third strip row lands on the third booking. |
| P3-1 skeleton is a running plan | **Still open** | Cold load of a ready plan paints five lane cards (phone) or five columns (desktop). Unchanged `plan-skeleton.tsx`. (P3-1 below.) |
| P3-2 host is text, Fonte link a tap | **Still open** | (P3-4 below.) |
| P3-3 past deadline keeps the same primary button | **Still open** | Seen again on the edge scenario in dark: "Scadenza passata" above a light "Prenota su Expedia" with no line of context. (P3-3 below.) |
| P3-4 no way forward | **Still open** | Header holds only the wordmark and the theme toggle. (P3-2 below.) |
| P3-5 skip link, double space | Open, trivial | No skip link (15 controls before the first "Prenota su", strip first). |

No P0 or P1 is open. Round 3 scores 32/40, which meets the spec's gate (at least 32/40, no open P0 or P1), by one
point and with two P2s still on the page.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | Header says "Pronto", duration and cost; arrival tested (focus on "Sintesi del piano", live region only logged lane states, empty on a plan that is merely opened). Deductions: a ready plan loads as five lane skeletons; arrival scroll clips the header (P3-1, P3-5). |
| 2 | Match system / real world | 3 | Italian, sentence case, 0 em dashes in page text, "Prenota entro" and "Quando" labelled, "tra 137 giorni", "letto il 12 ott 2026, 12:01". Deduction: the clock shown in bold for a departure from Milan is Lisbon's, and the "in Italia" note repeats on rows where it is noise (P2-1). |
| 3 | User control and freedom | 3 | Disclosures native, links in a new tab, wordmark 53x46. Deduction: no "Nuovo piano" or next step after a finished plan (P3-2). |
| 4 | Consistency and standards | 3 | One `BookingRow` for plan and alternatives, strip and list now in one order. Deductions: the compact alternative pair prints a home-clock time with no main time (P3-6); "Da prenotare" strip rows say "entro ven 26 feb" while rows say "ven 26 feb, 21:00" (intended). |
| 5 | Error prevention | 3 | Allowlist verdict drives button vs text; 14 of 14 external anchors `rel="noopener noreferrer"` and announce "(si apre in una nuova scheda)"; amber drawn only inside `DatePair` (0 amber on the happy plan, 0 amber buttons on the edge plan). Deduction: a deadline already past keeps the same inviting primary button (P3-3). |
| 6 | Recognition rather than recall | 4 | Every booking is named three times and linked (strip, itinerary "Da prenotare:", row), roundel plus a category word ("Volo", "Alloggio"), strip titles underlined, urgency in words. Nothing needs remembering. |
| 7 | Flexibility and efficiency | 3 | The strip is the accelerator and lands in the first viewport; anchors are in step. Deductions: no skip link, no way to open the two bookable links in one go, the desktop strip leaves the screen after about 400 px (P2-2). |
| 8 | Aesthetic and minimalist design | 3 | Flat, calm, the line vocabulary reaches the itinerary, 12.5 to 24 px only. Deductions: on desktop 700 px of the right of the itinerary is empty while the page scrolls 2,700 px (P2-2); the TripTracker hand-off on the phone floats with no divider (P3-5). |
| 9 | Error recovery | 3 | No-link bookings say the vendor, the host and the phone; a missing Trip falls back to derived or unknown deadlines. Deduction: nothing tells the reader what to do when a deadline is already past. |
| 10 | Help and documentation | 4 | The lead under "Prenotazioni", "Da sapere prima di prenotare", the reason under every date pair ("Le tariffe per metà aprile di solito salgono da marzo.") and the one-line lead of every section remain the best help in the product. |
| **Total** | | **32/40** | **Good (80 %); +1 on round 2, no P0/P1, at the gate** |

## Design specificity verdict

**LLM assessment (written before the detector ran).** Authored, not interchangeable. The first phone viewport now
does the job the product exists for: title, two summary lines, one total with its comparison against the budget,
and the five things to book in deadline order, each with the roundel of the agent that found it. That strip is the
line map's vocabulary doing real work in a place no other trip planner puts it. The two-box "Prenota entro" and
"Quando" pair is still the most product-specific object, and the amber it can draw (checked on the edge scenario,
dark: amber wash, 1.5 px amber ring, "Scadenza passata" in words) is spent nowhere else. On desktop the page now has
a deliberate composition at the top (summary left, deadlines and hand-off right). What keeps it from a 4 on
aesthetic is that the composition stops after one screen, and that the clock handling is correct but not yet
decided: which clock leads, and where it is named.

**Deterministic scan.** `impeccable detect --json` over `components/plan`, `components/live`, `components/states`,
`app/plans` and `components/ui` returned `[]` (exit 0). No findings, no false positives. Browser overlay injection was
not run: the browser pane is shared with other agents, and starting the live server and injecting a script would
disturb their tabs. The fallback signal is the clean CLI scan plus the DOM audit below.

**DOM audit.** 393 px: `scrollWidth` 393 (no horizontal scroll); 1440 px: 1440; 1100 px: 1100, strip 448 px wide at
x=624. One h1, h2 per section (Sintesi del piano (sr-only), Da prenotare, Giorno per giorno, Prenotazioni, TripTracker
(sr-only), Alternative scartate, Il lavoro degli agenti, Corsie degli agenti (sr-only)), h3 per day and booking. One
`aria-live="polite"` region: empty on a plan that is opened, and it logged only "Spostamenti: al lavoro",
"Attività: finito", "Coordinatore: finito" and the like during a watched run. Computed font sizes in use on the
page: 12.5, 13.5, 14.5, 15, 18, 20, 24 px (all DESIGN.md steps). 0 em dashes in the page text. 14 of 14
`target="_blank"` anchors carry `rel="noopener noreferrer"`. Focus ring on a strip row: `2px solid rgb(15 26 42)`,
offset 3 px (ink), visible on the 393 px edge. Amber nodes on the happy plan: 0; on the edge plan: only `DatePair`
elements (`bg-amber-wash`, `text-amber-ink`, the clock icon), 0 on buttons. Reduced motion could not be emulated by
the tool (`matchMedia` stays false); by rule, the plan components only animate colour and text-decoration, and the
shared pieces carry `motion-reduce:` utilities. Page height: 5,024 px (phone), 3,339 px (desktop).

## Overall impression

The round 1 P1 and the four round 2 P2s are closed, and the page is now what the brief asked for: a calm,
readable finished plan that answers "what do I book, and by when?" before it says anything else. What is left is one
real content question (the clock) and one layout one (the right column dies too early on desktop), then a tail of
carried P3s that nobody has taken yet. Biggest opportunity: decide the clock rule once, then let the right rail
follow the reader down the itinerary.

## What's working

- **The "Da prenotare" strip.** First viewport on the phone, right column on desktop, sorted by urgency, 44 px
  rows, titles underlined so touch users see they go somewhere, and the same order below in "Prenotazioni". The
  edge scenario shows the words doing the urgency ("da prenotare subito", "Scadenza passata", "In scadenza · tra un
  giorno", "5, 2 in scadenza" in ink) while amber stays inside `DatePair`.
- **Facts and the single comparison.** "1.690,00 € / 710 € sotto il budget di 2.400 € / 3 prezzi stimati" says the
  one thing a total can say, in neutral ink, once.
- **The arrival.** A watched run ends with focus on the summary heading and no scroll below it, the live region
  carried lane states only, and a plan that is merely opened does nothing (no focus move, empty region, scrollY 0).
- **Provenance and the dates.** Price, a "verificato" or "stimato" word chip, a quiet source link, "letto il ...", and
  the two date boxes with relative distance and the agent's reason underneath. Dark mode holds all of it with the
  inverted primary pill and no contrast loss.

## Priority issues

### [P2-1] The bold clock of a departure from Milan is Lisbon's, and the home clock repeats where it does not matter

- **Where**: `components/ui/date-pair.tsx` (`zoneNote`, `homeLabel`), `components/plan/bookings.tsx`, `components/plan/plan-model.ts` (`HOME_CLOCK_LABEL`, `tripZoneName`).
- **What**: the flight row reads "Quando / mer 14 apr, 08:40 / 09:40 in Italia". The bold, 15 px value is the clock
  at the arrival airport; the clock on the departure board in Malpensa is the grey 12.5 px line. Only the second line
  names a zone, so a reader who skips the itinerary's lead ("Gli orari sono quelli di Lisbona.", 14.5 px ink-2, 1,000
  px above the bookings) cannot tell whether 08:40 or 09:40 is Italian. The same "in Italia" line is printed on every
  row where the clocks differ: hotel check-in "15:00 / 16:00 in Italia", Palácio da Pena "10:30 / 11:30", Oceanário
  "10:00 / 11:00", Aerobus "11:50 / 12:50 in Italia", which sits next to "Prenota entro mar 13 apr, 12:50": two
  adjacent boxes both reading 12:50 and meaning different things.
- **Why it matters**: PRODUCT.md success is arriving at the right place at the right time; a one-hour error on a
  flight leaving the country is the one clock mistake in this product that costs a trip. A label on one of two
  numbers is half a rule.
- **Fix**: pick the clock per booking, not per page. For the booking that starts from home (flight, `kind` transfer
  that leaves home, the same predicate the itinerary already uses for "parte alle 09:40 in Italia"), lead with the
  home clock in bold and put the trip clock second: "mer 14 apr, 09:40" / "08:40 a Lisbona". For everything that
  happens at the destination (lodging, tickets, local transport) show the local time only and drop the home line.
  Name the zone on whichever line is the second one ("a Lisbona" or "in Italia"), so each box carries one label.
- **Command**: `/impeccable clarify`, then `/impeccable harden`.

### [P2-2] Desktop: the right column ends with the summary, so the strip and the hand-off leave the screen after about 400 px

- **Where**: `components/plan/plan-summary.tsx` (the grid and `lg:sticky lg:top-6` live inside the summary `section`), `components/plan/PlanView.tsx`.
- **What**: at 1440x900 the right column holds "Da prenotare" and "Apri in TripTracker" next to the summary, and then
  nothing: the itinerary below it is a 13 rem + 44 rem block at the left, so for 2,100 px of itinerary the right 700
  px are empty ground, and the strip that could sit beside the stops scrolls away (its sticky container is only as
  tall as the summary, about 500 px). Then the bookings go full width in three columns. Measured: page 3,339 px
  tall; at scroll 1,100 the right half of the viewport is blank.
- **Why it matters**: the page's job is "book these before their dates, then open TripTracker". The desktop reader
  loses both while reading the days, and the composition reads as a page of two halves that do not meet.
- **Fix**: lift the two-column grid one level up: wrap `PlanSummary`'s left content and the "Giorno per giorno"
  section in one `lg:grid lg:grid-cols-[minmax(0,1fr)_28rem]`, with the strip and the hand-off in a single right
  cell `lg:row-span-2 lg:sticky lg:top-6 lg:self-start`. The strip is about 250 px plus the hand-off 130 px, well
  inside a 900 px viewport, and it stays beside the stops until the bookings section begins. No new card, same
  hairlines. The itinerary's day column (13 rem) and stops (44 rem) already fit in the left cell (about 940 px).
- **Command**: `/impeccable layout`.

### [P3-1] A ready plan opens on a running plan's skeleton

- **Where**: `components/states/plan-skeleton.tsx`, `app/plans/[id]/loading.tsx`, `components/live/plan-screen.tsx` (`!hasData`).
- **What**: opening a finished plan cold paints the title block, a control bar with a cost meter and five lane cards
  (five columns at 1440), then replaces them with a page of another shape. Seen on every cold load at both widths
  (and again on the arrival test). The tab title also steps through "Piano · Atlas", then "Lisbona, 14–18 apr · Atlas"
  (the running page's title), then "Lisbona in famiglia, 14–18 aprile 2027 · Atlas". Carried from round 2, unchanged.
- **Fix**: render a status-neutral skeleton (title block, three text lines, a facts row, five 44 px rows: the
  finished page's first screen) when the status is unknown; keep the lane shape only when the last known status of
  this plan is `running` (a `sessionStorage` hint in a try/catch). Keep `Piano · Atlas` as the title until the status
  is known.
- **Command**: `/impeccable harden`.

### [P3-2] No way forward from a finished plan

- **Where**: `components/live/top-bar.tsx` / the page header.
- **What**: after "Apri in TripTracker" or after reading, the only route out is the 53 px "Atlas" link. Reported in
  rounds 1 and 2, unchanged. The last element on the page is a closed "Il lavoro degli agenti".
- **Fix**: a quiet "Nuovo piano" link (quiet button, 40 px) in the header's right group next to the theme toggle from
  1080 px, and under the timeline on the phone.
- **Command**: `/impeccable layout`.

### [P3-3] A booking whose deadline has passed keeps the same primary button, with no line of help

- **Where**: `components/plan/bookings.tsx` `ActionSide` (the variant depends on `alternative` only).
- **What**: on `/dev/plan?scenario=edge` (dark) the hotel box says "Prenota entro lun 12 ott, 15:05, Scadenza passata" in
  amber, and directly below it sits the same light "Prenota su Expedia" pill as any other row. The contract sends a
  past `book_by` back to the agent, so it is rare, which is the reason it needs one calm sentence.
- **Fix**: keep the button; when `deadline.kind === "date"` and in the past, add under the dates, in ink-2 with no
  colour: "La scadenza è passata: controlla che sia ancora disponibile." Carried from round 2.
- **Command**: `/impeccable harden`.

### [P3-4] No-link rows put the host in text while the same site is a tap two lines above; bookable rows print two links to one URL

- **Where**: `components/plan/bookings.tsx` `ActionSide`, `PriceLine`.
- **What**: for Palácio da Pena, Oceanário and Aerobus the action column says "Nessun link di prenotazione. Prenota
  sul sito di Oceanário de Lisboa: **oceanario.pt**" in plain text, while "Fonte oceanario.pt ↗" two lines above is a
  working link to that site. On the Expedia rows "Fonte Expedia ↗" and "Prenota su Expedia ↗" are adjacent links
  to one URL. Rules respected, tap target in the wrong place. Carried from round 2.
- **Fix**: for no-link rows, say it where the tap is: "Nessun link di prenotazione. Per prenotare apri il sito dalla
  fonte qui sopra: oceanario.pt" (no new link, no rule broken). On bookable rows render the source as plain text when
  it equals the booking link.
- **Command**: `/impeccable clarify`.

### [P3-5] The TripTracker hand-off floats on the phone, and arrival lands mid-header

- **Where**: `components/plan/PlanView.tsx` (`handoff`: `desktop ? "mt-6 ... border-t ..." : "min-w-0"`) and the `arrival` effect.
- **What**: on the phone the hand-off is a paragraph and a 40 px outline pill 80 px under the last booking with no
  divider (every booking row above has a `border-t`), so it reads as the tail of the Aerobus row. It is also the
  quietest control in a stretch where two primary ink pills sit above it, although it is what the page is for.
  Separately, a watched run's arrival sets `scrollY` to 143.5: the sr-only "Sintesi del piano" heading is at 24 px
  from the top, which cuts the "Pronto" status row in half and leaves the title off screen.
- **Fix**: give the phone hand-off the desktop treatment (`border-t border-rule pt-4`) and a 24 px gap instead of
  40. For arrival, scroll to the page header (or to 0, the finished header is only about 200 px) instead of the
  heading's own offset, and keep the focus on the heading with `preventScroll`.
- **Command**: `/impeccable polish`.

### [P3-6] The compact pair on alternatives prints a bare home-clock time

- **Where**: `components/ui/date-pair.tsx` compact branch (`formatBookingInstant(..., !compact)` drops the time, `zoneNote` keeps it).
- **What**: an alternative flight reads "Quando mer 14 apr (10:25 in Italia)": a date, then a time in another zone
  in parentheses, and no time for the trip's clock. Also "Prenota entro  nessuna scadenza" looks double spaced
  (`gap-1.5` after the label).
- **Fix**: in compact, show the time with the date ("mer 14 apr, 09:25") and the home note only where P2-1 would
  show it, or drop the note; use a single `gap-1` after the label.
- **Command**: `/impeccable clarify`.

## Persona red flags

**Casey (Michele on the iPhone, between two things).** The first screen is title, two summary lines, a total with its
comparison, a base, then "Da prenotare" with five rows, all with a visible deadline: this is good. Flags: the
hand-off is 4,580 px down with no divider before it (P3-5); a cold open shows five lane skeletons first (P3-1); on a
flight he reads the bold 08:40 and may leave at the wrong time (P2-1).

**Sam (keyboard / screen reader).** Heading outline clean, one polite region that stays empty at rest, focus ring 2 px
ink with 3 px offset on every control tried, closed `<details>` take no focus, 14 of 14 external anchors announce
"(si apre in una nuova scheda)". Flags: no skip link (15 controls before the first "Prenota su"); the strip's link
names read "title, entro date" with no hint they go to a booking; the h2 inside the timeline's `<summary>` needs a
VoiceOver check on Safari; the 08:40 and "09:40 in Italia" read in that order with no zone on the first (P2-1).

**Alex (the owner at the Mac, daily).** The two-column top answers "what first" at y=167 and keeps the hand-off in
view: good. Flags: after about 400 px both leave the screen and 700 px of the right side stay empty (P2-2); no way to
open both bookable links at once; no "Nuovo piano" shortcut on the page (P3-2).

**Riley (stress, edge).** Edge scenario: a long hotel title wraps in the strip and the row; a past deadline sorts above
a due-soon one and "Da prenotare subito" sorts first; a link outside the allowlist is text with "Link non
verificato"; a booking with no scheduled time says "da definire". Flags: a past deadline keeps a primary button
(P3-3); the compact alternative's lone "(10:25 in Italia)" (P3-6).

## Minor observations

- "Prenotazioni" is now in deadline order while the itinerary keeps the agent's order: the lead could say "In ordine di
  scadenza." so the change is not a surprise to a reader who saw the itinerary first.
- The Next.js dev indicator sits over the bottom-left of the phone viewport in development only; ignore.
- The summary's second sentence ("Voli TAP diretti da Malpensa, Oceanário, Sintra e Belém con ritmi adatti ai
  bambini.") is the agent's text and reads as one run-on thought; it belongs to the coordinator prompt, not the UI.
- At 1440 the opened timeline is a clear five-column picture with waves ("Ondata 1", "Scelta") as named stations and
  every lane "Finito": the arrival of its lines mid-animation looks empty for a frame, then fills, as designed.
- The strip, the itinerary's "Da prenotare:" and the row all name each booking: three mentions, three jobs; fine.
- Total "1.690,00 €" keeps ",00": consistent with `formatEur` and the booking prices, but a total reads calmer as
  "1.690 €" if DESIGN.md's euro rule ever gets a whole-euro variant.

## Questions to consider

- If the right rail follows the reader down the itinerary, does the strip still need to be the first thing on the
  phone, or could the hand-off ("Apri in TripTracker") be the page's confident first action and the strip its
  explanation?
- Which clock does Michele act on for a flight he is about to book from his sofa in Milan: the one at the airport he
  leaves, or the one he lands on? What would the "Quando" box show if the answer were always "the clock where I am
  when it starts"?
- Should a plan that is merely opened ever look like a run in progress, even for 200 ms?

## Checks against the rules asked

| Rule | Result |
| --- | --- |
| Two dates separate and labelled | Pass: "Prenota entro" and "Quando" in every plan row (two boxes) and every alternative (compact line). Residue: the compact pair's lone home-clock time (P3-6). |
| Amber reserved | Pass: 0 amber nodes on the happy plan; on the edge plan amber is only `DatePair` (wash, ring, ink, clock icon) with "Scadenza passata" or "In scadenza · tra un giorno" in words; 0 amber buttons, none in the strip. |
| Sentence case, no em dash, verbs on buttons | Pass: 0 em dashes in page text; "Prenota su Expedia", "Apri in TripTracker", "Vedi su Booking.com". |
| `rel="noopener noreferrer"`, new tab, only when allowed | Pass: 14 of 14 external anchors; no-link and unverified bookings are text. |
| aria-live only for agent state | Pass: one polite region, empty on a plan that is opened, lane states only during a run. |
| Reduced motion | Pass by rule: nothing on the page animates outside the shared `motion-reduce:` pieces. Not exercised at runtime (the tool cannot emulate it). |
| Keyboard and focus | Pass: visible 2 px ink ring on every control tried, logical order, strip first (15th stop to the first "Prenota su"). No skip link. |
| 393 px | Pass: no horizontal scroll, h1 fits at 24 px, targets 40 to 46 px, inline links 16 to 20 px (in-sentence). |
| Costs in dollars, trip prices in euro | Pass: "0,41 $", "limite 0,60 $" (live), prices in euro with two decimals. |
| Dark mode | Pass at both widths and on the edge scenario (amber states, inverted primary, ink-2 contrast). |

Trend for `id-ready` (last 3 runs): 30 → 31 → 32 (out of 40, same heuristic set).
