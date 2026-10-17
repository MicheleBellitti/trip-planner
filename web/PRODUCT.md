# Product

<!-- impeccable:product-schema 1 -->

> Written by `impeccable init` without a live interview: every answer below comes from the
> spec (`docs/spec/implementation-doc.it.md`, sections "Obiettivo e perimetro", "Frontend
> Next.js", "Interfaccia e design") and from `CLAUDE.md`. Facts marked *(inferred)* are readings
> of those sources that Michele has not confirmed. The three items the first pass left open (the
> product name, the due-soon window, the cost unit) were decided by Michele on 2026-10-12 and are
> recorded under "Decisions". The visual system lives in `web/DESIGN.md`.
>
> On 2026-10-14 Michele restyled the brand ("Carta notturna", the "A di linee" mark, the tagline,
> dark by default, a public front door): `docs/superpowers/specs/2026-10-14-atlas-brand-design.md`.

## Platform

web

## Stack

Pinned by the spec, not chosen here: Next.js 16 (App Router), TypeScript, Tailwind 4, Zod to
validate every incoming SSE event. Mobile first at 393 px. Deployed on Vercel at
`atlas.bellittim.com`; the API is `atlas.api.bellittim.com`.

## Users

One user: Michele. Access is limited to the emails in `PLANNER_ALLOWED_EMAILS`, through the
TripTracker session cookie. There is no sign-up and no second audience.

He uses it from two places:

- **iPhone (393 px, an iPhone 14 Pro)**: he starts a plan or checks one that is running,
  often in a spare moment, one-handed *(the device is stated by the TripTracker snapshot;
  the one-handed scene is inferred)*.
- **Mac**: he watches a run with the five lanes side by side, reads the finished plan, and
  opens the booking links in new tabs.

The job: **decide a trip and book it**. He describes a trip (origin, destination or "Suggeriscimi
tu" with an idea, fixed dates or a month and a number of nights, adults and children with ages,
a total budget in euro, free-text preferences), watches five agents research it, then books
each piece on the supplier's own site before its deadline and moves the trip into TripTracker.

## Product Purpose

Turn a trip request into a complete, bookable plan in one Managed Agents session: a
coordinator and four subagents (voli, alloggio, attività, spostamenti) search in parallel and
the coordinator assembles the result. The browser shows the work live, lane by lane; the
finished plan imports into TripTracker in one click.

Success means:

- Michele trusts the plan enough to press "Prenota su <sito>" for each booking, and knows by
  when each one must be booked.
- He understood what happened during the run without reading logs: who is working, on what,
  how much it has cost so far, and what failed.
- A complete plan costs under $4 (the monthly API budget is $100, shared with other projects).
- The trip lands in TripTracker without retyping anything.

Out of scope, by the spec's own list: automatic booking or payment (the planner sends him to
the right site, he pays), price tracking over time, editing the plan in chat after the first
generation, history and comparison of past plans, a printable PDF itinerary.

## Positioning

A trip planner that shows its work and hands off cleanly. The run is visible as five agents
with their real tool calls ("Expedia · voli MXP→LIS · 14–18 nov"), their messages to each
other ("coordinatore → voli: incarico") and the cost climbing toward the session budget. The
output is not prose advice but bookings with two separate dates, a price with its source and
retrieval time marked verified or estimated, and pre-filled links to allowlisted supplier
domains. It ends in TripTracker, the app Michele already uses to not miss bookings.

## Operating Context

- **The screens** (spec "Frontend Next.js", plus the brand restyle's front door): `/` the public
  landing (a returning signed-in visitor goes straight to the plans); `/plans` recent plans with
  status and cost and "Nuovo piano"; `/new` the request form, whose button says "Pianifica il viaggio" with the run's
  cost estimate under it ("circa 2–4 $"); `/plans/[id]` the live timeline while running, then the
  finished plan with the timeline collapsible below it.
- **The live screen** carries, at the top: plan status, elapsed time, cumulative cost on a bar
  that reaches the session budget, "Interrompi". Below: one lane per agent (coordinatore, voli,
  alloggio, attività, spostamenti), side by side on desktop, stacked on the phone with the
  active lane open. Each lane shows its state (in attesa, al lavoro, finito, errore), the
  current tool with its main parameters, and its events in time order. Inter-agent messages are
  one row, sender → recipient, that opens to show the text.
- **Run shape** (spec "Il lavoro a ondate"): wave 1 runs voli, alloggio and attività in parallel;
  the coordinator picks flight and lodging; wave 2 sends follow-ups (at most two per subagent)
  and starts spostamenti; the coordinator checks coherence and calls `submit_plan`. A run lasts
  minutes; one still running after 45 minutes is flagged as stuck.
- **Plan states**: `running`, `ready`, `failed`, `budget_paused`, `blocked`, `interrupted`.
- **Session budget**: 100¢ in the development profile, 400¢ in production. At the cap the plan
  pauses and offers "Continua con 2 $ in più".
- **Every state is designed** (spec table): no plan yet is an invitation with a sample request
  already written; session start shows the five lanes waiting, in place, with the clock
  running; a reconnecting stream is one discreet line at the top and missed events arrive by
  themselves; a dead MCP source is a warning on that agent's lane, not a plan error; an agent in
  error says so on its lane while the coordinator continues; budget reached says how much was
  spent; blocked, interrupted and failed say what happened, what was saved and what can be done;
  offline shows the last known state marked as stale; an expired session links to sign in again
  and returns here.
- **The finished plan**: a three-line summary, total estimated cost, warnings (estimated prices,
  sources that did not answer); days as a vertical sequence of stops, as in TripTracker, never a
  grid of cards; bookings with "Prenota entro" and "Quando", price, source and price status;
  "Prenota su <sito>" opens a new tab; discarded alternatives in a closed section per kind;
  "Apri in TripTracker" at the bottom, which goes to `viaggi.bellittim.com/import?plan=<id>`.
- **Neighbouring product**: TripTracker (`viaggi.bellittim.com`), Michele's own trip app. The
  planner shares its sign-in and feeds it trips, but it has its own visual identity.

## Capabilities and Constraints

- The frontend knows nothing about Managed Agents: it talks only to the backend and draws its
  normalized events (`UIEvent`: `seq`, `ts`, `agent`, `kind` = status | tool | message | usage |
  error | plan, a one-line Italian `title`, optional `detail`, cumulative `cost_cents`).
- State lives in a reducer fed by `usePlanEvents()`, which wraps `EventSource`; on reconnect the
  browser resumes from the last `id` and loses nothing.
- Events never carry tool results or page content: tool name, main parameters and duration only.
- An `aria-live="polite"` region announces agent state changes only, never each tool call.
- The timeline is virtualized past 300 events. Initial JS target: 180 KB gzip on first load of
  `/plans/[id]`, to confirm after the first build.
- Booking links open in a new tab with `rel="noopener noreferrer"`. A link outside the
  per-provider allowlist is shown as text, not as a button. Payment always happens on the
  supplier's site.
- Components copied from 21st.dev (Agent Plan, Timeline from Dice UI, bottom sheet, toast) must
  be MIT, copied by hand into `web/components/ui/` with a provenance comment and their tokens
  re-mapped. No whole kits, no borrowed palettes.
- Terminology on screen: piano, corsia (lane), coordinatore, voli, alloggio, attività,
  spostamenti, incarico, "Prenota entro", "Quando", "Prenota su <sito>", "Apri in
  TripTracker", "Interrompi", "Continua con 2 $ in più", "Stream in riconnessione". Code names
  are English (`PlanTimeline`, `AgentLane`, `usePlanEvents`).
- Product name, due-soon window and cost unit: decided, see "Decisions" below.

## Decisions

Taken by Michele on 2026-10-12. They replace the first pass's open questions.

- **Name on screen: "Atlas".** It is the product's name in the header wordmark and in the page
  titles ("I tuoi piani · Atlas"). It lives in one constant, `BRAND_NAME` in `web/lib/brand.ts`;
  nothing else spells it. The repository and the spec keep their names; the domains are `atlas.bellittim.com` and `atlas.api.bellittim.com` (renamed from `pianifica` on 2026-10-13).
- **Due soon means `dueAt` within 72 hours**, TripTracker's own rule (its "In scadenza" group,
  `EXPIRING_WINDOW_HOURS = 72`): a booking whose "Prenota entro" is at most 72 hours from now,
  or already past, is due soon and gets the amber treatment. A booking without a `dueAt` ("Da
  prenotare subito", or no date to derive one from) is not amber, exactly as in TripTracker; its
  urgency is in its words.
- **Costs are dollars with two decimals, Italian formatting**: "1,62 $", "4,00 $", "48,20 $"
  (`formatUsd` in `web/lib/format.ts`). Never cents on screen. Trip prices stay in euro
  ("1.080,00 €").
- **Design direction: 1 "Linee"** (`web/design/directions/1-linee/`), the run drawn as a transit
  line diagram, with the two borrowings the directions README recommended:
  1. From Sala: on desktop the live tool is repeated under each lane's name, so the "you are
     here" plate at the end of a long line is never the only place it shows.
  2. From Partitura: the waves are named stations on the coordinator's line, "Ondata 1",
     "Scelta" and "Ondata 2", so the shape of the run reads without a time grid.

### 2026-10-14: the brand restyle

- **Audience of the restyle: showing Atlas off** (friends, portfolio, a launch video), on top of
  daily use.
- **World: "Carta notturna"**, a printed night transit map: flat ink ground, paper grain, cream
  type, matte line inks. **Dark is the default everywhere**; light ("Carta di giorno") is pinned
  with the toggle.
- **Mark: "A di linee"** (DESIGN.md, Brand). **Tagline: "Ogni viaggio ha il suo atlante."**
- **Front door** (step 2 of the spec): a public landing at `/`, the plans list at `/plans`, and a
  free demo run at `/demo`.
- **Navigation: one app header**, with the current section drawn as a station.
- **Never the "AI site" look**: no glow, no spotlight gradients, no dot grids, no gradient text, no
  glass beyond the sticky bar.
- **2026-10-17: the landing**, approved from a mockup: "Accedi" only in the header and the
  closing, the line map before the legend on the phone, one choreographed moment (the map). Until
  `/demo` exists (step 3) its demo calls to action are off (`DEMO_READY`).

## Brand Commitments

- **Own identity.** From TripTracker the planner keeps only two rules: a booking's two dates
  are always separate and labelled, and one colour is reserved for deadlines. Not its palette,
  not its type, not its aurora.
- **Tone: a printed night map.** Crafted, alive, never neon. Many things move at once on the live
  screen and it must not become noise: no scores, no glowing "AI" chrome (The No AI Chrome Rule,
  DESIGN.md). The motion rule itself is rewritten with the live-run motion (step 4 of the brand
  spec); until then DESIGN.md's "Report, Don't Perform" stands.
- **Two dates, always.** "Prenota entro" (`dueAt`, by when to book) and "Quando"
  (`scheduledFor`, when it happens) are two labelled values everywhere a booking appears,
  including previews and compact strips. Never merged, never one in place of the other.
- **One colour for deadlines.** Amber marks bookings that are due soon and nothing else. It
  never appears on a button, the import button included, and is never decorative.
- **Copy.** All user-facing text is Italian, in sentence case. Buttons start with an action
  verb. An empty state is an invitation. Errors say what happened, what was saved and what to
  do. Proper names and addresses stay as the source writes them.

## Evidence on Hand

- The spec and `CLAUDE.md`; the TripTracker code snapshot in `docs/triptracker/snapshot/`
  (reference only: its identity is not ours).
- The brand assets are the mark "A di linee", the tagline and the paper grain (DESIGN.md, Brand),
  plus free Wikimedia cover photos per destination. No other logo, illustration or stock imagery is
  invented.
- No real plans exist yet. Mockups use synthetic content (a Lisbon trip, 14–18 Nov 2026, two
  adults and two children, a 2400 EUR budget) and must not present invented prices or
  availability as real.

## Product Principles

1. **Report the work, don't perform it.** Motion and colour convey state changes; everything
   else holds still so a run can be followed at a glance.
2. **Urgency has exactly one meaning.** The deadline colour is spent only on bookings due soon,
   so it is never ignored.
3. **Two dates, every time.** By when to book and when it happens are different questions and
   always get two labelled answers.
4. **Provenance is visible.** A price shows where and when it came from and whether it was
   verified; a link shows which site it opens.
5. **Failures stay local.** A dead source or a failing agent is a note on its lane; the plan
   keeps going, and a dropped stream reconnects quietly.

## Accessibility & Inclusion

- WCAG 2.2 AA: text contrast measured on the real background in both light and dark themes.
- Full keyboard use with a visible focus ring.
- `aria-live` only for agent state changes.
- `prefers-reduced-motion` declared for every animation; reduced motion keeps colour and
  opacity feedback and drops movement in space.
- 393 px phone and desktop; state is never carried by colour alone (each lane state has a
  word, each deadline has a label).
