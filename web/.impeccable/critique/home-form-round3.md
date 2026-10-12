---
target: home "/" and request form "/new" (web/app/page.tsx, web/app/new/page.tsx, components/home/*, components/request/*, lib/remembered-request.ts)
round: 3
total_score: 32
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 1
p2_count: 2
p3_count: 13
date: 2026-10-12
---

# Critique, round 3: home "/" and request form "/new"

**⚠️ DEGRADED: single-context (no sub-agent/Task tool is exposed to this agent).** Assessment A (design review) was written down before Assessment B (detector) ran, in the same context. Detector: `impeccable detect --json app/page.tsx app/new/page.tsx components/home components/request` returned `[]` (0 findings, exit 0). The detector overlay was not injected (no live-server was started, to leave the shared dev stack alone). Also run: `npm run typecheck` (clean), `npm run lint` (clean), `vitest run components/request components/home lib/remembered-request lib/request-form lib/format components/ui` (13 files, 218 tests, all passed).

How it was inspected: real browser, own tab (tab-11), 393x852 and 1440x900, light and dark, against the running demo stack. Home with 20 real demo plans (running, ready, grouped under "In corso" / "Recenti" with "Mostra gli altri 9"). Empty state and list error state reached by stubbing `GET /plans` in the page after a client-side navigation (no source change). Form: pristine (with a remembered Milano, 2 adults, 2 children), empty submit (6 errors), one field error (budget "2400,50"), a control character in the origin, a stubbed server 422 `start_not_in_future`, Enter in a text field, Tab order and focus ring, and a real submit of the example to the demo backend (POST /plans, busy button "Avvio il piano…", redirect to `/plans/<id>` in about 0.1 s in a foreground tab). No source file was modified and no money was spent. Note: "Previous rounds: []" in the task text is stale; `home-form-round1.md` (29/40) and `home-form-round2.md` (32/40, 0 P0, 0 P1, 3 P2, 14 P3) exist and are the baseline.

**Gate (CLAUDE.md / spec): a screen merges at 32/40 or more with no open P0 or P1.** This round scores 32/40 and has **one open P1** (the `Date.now()` render error on "/", below). **Not mergeable until P1-1 is fixed; with it fixed, 32/40 clears the gate at the threshold.** No P0.

## Verification of the previous rounds' P0 and P1

| Finding | Status | Evidence |
|---|---|---|
| Round 1 **P1**: Enter in a text field submits the form | **Fixed, still holds** | Focus in origin, Enter: focus moved to `field-destination`, 0 `aria-invalid`, still on `/new`. Only the budget field (key "Vai") sends. |
| Round 2: no P0, no P1 | n/a | Nothing to verify. |
| Round 2 P2-1 remembered party applied silently, ages go stale | **Fixed (mostly)** | `/new` opens with Milano, Adulti 2, Bambini 2 and both age selects on "Scegli" (`applyRemembered` blanks the ages; its header comment says why). Residue: the restored counts are still not named as remembered (P3-2 below). |
| Round 2 P2-2 desktop with children loses the fold | **Fixed** | 1440x900 with two children: budget field top 639, preferences bottom 837, submit 479 (sticky card), page scrollHeight 908. The whole request is on one screen. |
| Round 2 P2-3 home is twenty equal rows | **Mostly fixed** | Running plans group under "In corso", the rest under "Recenti" (8 rows) with "Mostra gli altri 9"; times are relative ("Oggi, 18:01"); running rows say "in corso da 14 min" and re-read every 15 s. The page went from 20 rows (1634 px) to about 1090 px. The optional "line of runs" idea is still absent (P2-2 below). |
| Round 2 P3s | 5 carried unchanged, see the list | Pre-hydration submit, list error silence, 32 px targets, invitation says it twice, "da scegliere" placeholders, placeholders look like values, `role="alert"` not documented, two right edges at 1440, draft lost on refresh, "cinque agenti". |

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Busy button with `aria-busy`, skeleton rows, running rows alive, retry. A failed list load is still silent to a screen reader, and the dev build shows a render error on every visit to "/" (P1-1). |
| 2 | Match System / Real World | 4 | Copy sounds like Michele talking to himself ("Suggeriscimi tu", "Mese e notti", "Pianifica il viaggio"). Only residue: "cinque agenti" followed by four named areas. |
| 3 | User Control and Freedom | 3 | Back link, editable example, every value kept after every failure. A draft is still lost on refresh. |
| 4 | Consistency and Standards | 3 | One system, applied tightly, no amber, no coloured button, no em dash. Back link (32 px), "Riprova" (32 px) and the error-summary links (31 px) are the only sub-40 targets on the phone. |
| 5 | Error Prevention | 3 | Enter-to-next, date `min`, clamped steppers, forgiving budget parser, control-character check, children's ages now a conscious tap. A native submit before hydration wipes the form. |
| 6 | Recognition Rather Than Recall | 3 | Visible labels and hints, read-back card. Plans of the same trip are told apart only by a timestamp. |
| 7 | Flexibility and Efficiency | 3 | Remembered origin and party, Enter-to-next, example link. No "repeat this plan". |
| 8 | Aesthetic and Minimalist Design | 3 | Calm, flat, restrained. Redundancies persist (invitation sentence plus the same facts, "da scegliere" read-back). Home is still a table, not a line. |
| 9 | Error Recovery | 4 | A sentence per field with a cross, a summary of links at the top of the phone (focus lands there, 6 errors) or beside the button on desktop, focus on the field for 1 or 2 errors, a server 422 mapped onto "Partenza" with "La partenza deve essere da domani in poi.", values never wiped. |
| 10 | Help and Documentation | 3 | A hint under nearly every field; the cost line says whose cost it is. |
| **Total** | | **32/40** | **Good (28-35)**; 0 P0, 1 P1 open: below the gate until P1-1 is fixed |

Trend: 29 -> 32 -> 32 (out of 40, same heuristic set). Round 3 closed two P2s and added a P1 that came with the new list code, so the score is flat.

## Design Specificity Verdict

**LLM assessment (written before the detector).** The form is authored and could only be Atlas: the ring-and-bar route line ("Da Milano / A Lisbona") on the read-back card and in the invitation, "Il tuo viaggio" read back before it costs anything, status as glyph plus word, ink pills, copy in the first person. The home list is the weak point, and it is the page opened most often: grouped and tidier than in round 2, but still a bordered table of title, status, cost, time that any CI dashboard would ship unchanged. Linee's idea (the run drawn as a line of stations) appears on the read-back card and nowhere on home, where it would cost the least. At 1440 the home is the phone list stretched to a 64 rem column, left aligned: the "Nuovo piano" button ends at the list's right edge (x 1052), the theme toggle at the viewport's (x 1412), and about 27 % of the screen to the right of the list is empty.

**Deterministic scan.** 0 findings on the four targets, no false positives. Manual checks that agree: no amber anywhere, no coloured button, no em dash, sentence case, `lang="it"`, 16 px inputs, no horizontal scroll (scrollWidth 393 at 393 px), one `h1` per page, header and main landmarks, no `aria-live` on home, focus ring (2 px, 3 px offset, `:focus-visible` true) on the Tab stops checked, reduced motion declared on the busy spinner and the ring, `rel` n/a on these two pages (no external links). The detector cannot see what the browser console showed: the P1 below.

**Visual overlays.** Not injected (see Method). Fallback signal: the clean scan and the DOM and computed-style audit above.

## Overall impression

Round 2's judgement items were taken seriously: the party no longer arrives with ages the child no longer has, the desktop form fits the screen with children, and the home list reads as groups instead of twenty look-alikes. What went wrong is mechanical, not visual: the new list computes `Date.now()` during render in a Client Component, which this project's `cacheComponents: true` forbids, and the dev server reports it on every visit to "/" (and the overlay badge says "1 Issue" on the home screen the whole time). The single biggest design opportunity is unchanged: let home be Atlas's line map instead of a table.

## What's working

1. **Error handling is complete and consistent.** Empty submit gives "6 campi da sistemare" with the six field names as links at the top of the phone (the sentence under each field says what to do), the same card beside the button on desktop, single problems go straight to the field, a server 422 lands on the same field with Italian copy, and a control character in the origin is named ("Togli i caratteri speciali non stampabili.").
2. **The memory helps without lying.** Origin, adults and number of children come back; each child's age is a conscious tap on "Scegli", so a paid run can never start with last year's ages.
3. **Home states are all designed.** Skeleton rows in the final shape, grouped list with "In corso" first, an invitation with a request already written (route line, dates, party, budget) and one tap to a filled form, and a list error that says what happened and offers "Riprova". Discipline holds in both themes and both sizes: costs as "0,41 $", status always glyph plus word, no amber, ink pills invert in dark.

## Priority issues

### [P1-1] `Date.now()` in the render of `PlanList` raises a prerender error on every load of "/"

- **Where:** `components/home/plan-list.tsx:47`, `const [openedAt] = useState(() => Date.now());` (new since round 2). `next.config.ts` has `cacheComponents: true`.
- **Seen:** the browser console on every visit to "/" (and on every client navigation back to it) logs `Error: Route "/": Next.js encountered the unstable value Date.now() in a Client Component. This value would be evaluated during the prerender, instead of recomputed on each visit.` and the Next dev badge reads "1 Issue" (2 after a second visit), bottom left, over the list. With Cache Components this value is evaluated while the static shell is prerendered, so the message is a build-time error, not a warning: very likely `next build` fails on "/" (not run here: the shared dev server must not be disturbed; confirm with a build when allowed). Even if it builds, the stored "now" would be the build's, and "Oggi" and "Ieri" would be read against it.
- **Why it matters:** the home page cannot ship, and the badge covers the bottom-left of the phone viewport during every review. `lib/use-now.ts` already exists for exactly this and returns `null` on the server.
- **Fix:** do not read the clock in render. Either (a) keep `openedAt` as `number | null`, set it in the fetch effect (`.then((plans) => { setOpenedAt(Date.now()); setState(...) })`) and render created times only when it is non-null (the rows are not shown before the list loads anyway, so nothing changes visually); or (b) use `useNow()` for the "Oggi/Ieri" reference and fall back to the absolute date while it is `null`. Add a test that renders `PlanList` on the server path without touching the clock. Then re-check the console on "/" and `npm run build` once.
- **Suggested command:** `/impeccable harden`

### [P2-1] On desktop the form first paints in the phone layout, then reflows into two columns

- **Where:** `request-form.tsx` branches its markup on `useIsDesktop()` (`desktop ? <two columns> : <stack>`), which is `false` during server rendering and before hydration (`components/live/hooks.ts`).
- **Seen:** a screenshot taken straight after navigation at 1440x900 shows one stacked column on the left with the read-back card on the right; after hydration the sections jump into two columns ("Chi viaggia" and the budget move up and right, the form is about 400 px shorter). It happens on every load of "/new" at 1080 px and wider.
- **Why it matters:** a layout jump on the screen with the most inputs, with the cursor possibly already in the origin field; on a slower Mac or a cold load the user watches the form rearrange itself.
- **Fix:** make the two layouts pure CSS so server and client agree: render the four sections once, in the phone's order, inside a wrapper with `lg:grid lg:grid-cols-2 lg:gap-x-12` and place them with `lg:col-start`/`lg:row-start` (or keep two wrapper divs and use `display: contents` below `lg`). Keep `useIsDesktop` only for the error summary's position, or render the summary twice (`lg:hidden` / `hidden lg:block`) and move focus to the visible one.
- **Suggested command:** `/impeccable layout`

### [P2-2] Home is still a table: the live plan is not first in the eye, and the plans of one trip have one name

- **Where:** `components/home/plan-list.tsx`; with the demo data, five rows read "Lisbona, 14–18 apr" and eight read "Lisbona in famiglia, 14–18 aprile 2027", told apart only by a time ("Oggi, 18:01"). The three "In corso" rows have the same weight as the finished ones: an 11 px ring versus a check glyph in the same 14.5 px meta line; "In corso" and "in corso da 14 min" say the same thing twice.
- **Why it matters:** the phone job is "check the one that is running", and at 393 px the answer is a ring the size of a full stop. It is also where Atlas could show its own idea (a line of runs) and shows a bordered list instead; a month of Lisbon variants will look exactly like this.
- **Fix:** (1) draw the list as a vertical line: a 3 px ink rail down the left of the card, each plan a station on it (the plan-status glyph as the node, the larger ring plate for the running one), "In corso" rows with the title at `text-title` and the elapsed time as the only meta ("da 14 min", dropping the repeated word), finished rows quieter (ink-2 title weight 500 is too weak: keep ink, drop the cost to ink-2); (2) when two titles in the visible list are equal, append the time to the title line instead of the meta ("Lisbona, 14–18 apr · 18:01") or show the party ("2 adulti, 2 bambini") as the second meta item, which is what the user actually varies; (3) at 1440 cap the header to the list's measure (see P3-9). Use plan-status glyphs only: DESIGN.md's rings mean tool calls.
- **Suggested command:** `/impeccable bolder`, then `/impeccable layout`

### [P3-1] A native submit before hydration wipes the form and writes form state into the URL (carried from round 2 P3-1, reproduced)

- **Where:** `request-form.tsx` `<form onSubmit>` has no `method`, `action` or guard; only the radios carry `name` (`useId` values).
- **Seen:** twice in this round, clicking "Pianifica il viaggio" in a tab whose form had not hydrated reloaded to `/new?_R_4klritqlb_=pick&_R_4klritqlbH1_=exact` with an empty form (the example's values gone). In a foreground tab the form hydrates in well under a second, so this needs a slow phone or a background tab; the failure is destructive and exposes internal ids when it happens.
- **Fix:** keep the submit button `disabled` until a `useEffect` flag says the form is hydrated (same for Enter via the existing `onKeyDown`), or give the `<form>` `method="post"` with no action so a native submit is a visible no-op, or set `inert` until hydrated.
- **Suggested command:** `/impeccable harden`

### [P3-2] The restored number of children is still not named as remembered

- **Where:** `lib/remembered-request.ts` `applyRemembered`, shown under "Chi viaggia".
- **Seen:** `/new` opens with "Bambini 2" and two empty age selects, no word saying it came from the last plan. A trip without children means noticing and pressing minus; the read-back card on desktop already says "2 adulti, 2 bambini".
- **Fix:** one ink-2 line under the "Chi viaggia" description, only when something was restored: "Come nell'ultimo piano. Scegli le età." (a `<p>`, no live region). Origin and adults can stay unannounced.
- **Suggested command:** `/impeccable clarify`

### [P3-3] A failed list load is silent to a screen reader, and "Riprova" is 32 px (carried, P3-2 and part of P3-6)

- **Where:** `plan-list.tsx` error branch: `Notice` with no role and no focus move (`document.activeElement` stays `body`), "Riprova" at `size="sm"`, 94x32.
- **Fix:** `tabIndex={-1}` and an id on the notice and focus it when the state flips to `error` after an explicit load (not on the quiet 15 s re-reads); "Riprova" at `size="md"` (40 px) or `min-h-11` on the phone.
- **Suggested command:** `/impeccable harden`

### [P3-4] Three phone targets are under 40 px (carried, plus a new measurement)

- **Where:** back link "I tuoi piani" 81x32 (`min-h-8`); the error summary's links 44 to 105 by 31 px (`py-1.5` on an inline-block); "Riprova" above. Everything else on both pages is 40 to 46.
- **Fix:** back link `min-h-11 sm:min-h-8`; summary links `py-2.5` (about 44 px rows) at phone width; they are the first thing a thumb taps after a failed submit.
- **Suggested command:** `/impeccable adapt`

### [P3-5] The invitation says the request twice (carried since round 1)

- **Where:** `empty-invitation.tsx`: "«Lisbona a metà aprile, 2 adulti e 2 bambini, 2.400 €»" and then Da/A, dates, party, budget: the same facts. Also the facts carry a trailing period only on the preferences line ("Quartieri tranquilli, cucina locale.").
- **Fix:** drop the quoted sentence and keep the route line plus facts (the part only Atlas has); remove the stray period.
- **Suggested command:** `/impeccable distill`

### [P3-6] The read-back card shows "da scegliere" before anything is typed (carried since round 1)

- **Where:** desktop `RequestSummary` on a pristine form: "Meta da scegliere", "Date da scegliere", "Budget da indicare", five lines beside the same empty fields.
- **Fix:** show a fact only once its field has a value; before that one ink-2 line, "Qui leggi la richiesta mentre la scrivi."
- **Suggested command:** `/impeccable quieter`

### [P3-7] Placeholders read as values, and the budget error gives no example (carried, plus one new)

- **Where:** preferences placeholder "Niente voli prima delle 8, quartiere tranquillo, cucina locale" is a full sentence in the hint's ink-2; the origin placeholder "Milano, oppure MXP" has no "Per esempio" where destination and budget do. New: "2400,50" gives "Scrivi un numero intero." without saying what a whole number looks like.
- **Fix:** every placeholder starts with "Per esempio"; the budget error becomes "Scrivi solo euro interi, per esempio 2.400."
- **Suggested command:** `/impeccable clarify`

### [P3-8] `role="alert"` on the submit failure is still not documented (carried, P3-11)

- **Where:** `request-form.tsx` `<Notice tone="error" role="alert">` with focus moved to the button. DESIGN.md's `aria-live` rule (lines about 605 and 731) allows lane state changes only; CLAUDE.md the same.
- **Fix:** add one line to DESIGN.md's rule: "an error that answers the user's own submit is `role="alert"`, once", or move focus to the notice (`tabIndex={-1}`) and drop the role, as the summary does.
- **Suggested command:** `/impeccable document`

### [P3-9] Home at 1440: two right edges and an empty right quarter (carried, P3-7)

- **Where:** `app/page.tsx` `max-w-[64rem]` inside `max-w-page`. The "Nuovo piano" button and the card end at x 1052; the theme toggle at x 1412. The invitation card is a 1024 px strip with a lot of empty ground below and to the right.
- **Fix:** cap the site header's inner width to the same measure on home and `/new`, or let the right column carry something (the example card beside the list).
- **Suggested command:** `/impeccable layout`

### [P3-10] Draft lost on refresh or when iOS evicts the tab (carried, P3-4)

- **Fix:** mirror `values` to `sessionStorage` on change (debounced, try/catch), restore on mount unless `?esempio=1`, clear on a successful submit.
- **Suggested command:** `/impeccable harden`

### [P3-11] "Cinque agenti" followed by four areas, and "planner" in two strings (carried, P3-13 and P3-14)

- **Where:** the `/new` intro and the invitation: "Cinque agenti cercano voli, alloggio, attività e spostamenti" (the coordinator is the fifth and is not named); "Il planner costa circa 2–4 $ per piano", "Non riesco a raggiungere il planner".
- **Fix:** "Un coordinatore e quattro agenti cercano voli, alloggio, attività e spostamenti mentre li guardi lavorare."; "Un piano costa circa 2–4 $ di API." is optional.
- **Suggested command:** `/impeccable clarify`

### [P3-12] The 120-day error is squeezed into half the width (carried, P3-5; not re-tested this round)

- **Fix:** route `trip_too_long` to the `dates` group error under both date fields, keeping a red edge on "Ritorno".
- **Suggested command:** `/impeccable layout`

### [P3-13] Minor

- A running row's "In corso" badge and "in corso da 14 min" repeat the words (covered by P2-2's fix).
- The dev badge sits over the cost line and the end of the list at 393 px (development only; goes with P1-1).
- A restored party plus the example link: `?esempio=1` correctly ignores the memory; the empty form after a pre-hydration reload (P3-1) does not, so the wipe also loses the remembered origin until the next hydration.

## Persona red flags

**Casey (distracted phone user, one thumb).** Taps "Avanti", moves on, no accidental send. Opens `/new` and finds Milano, 2 adults, 2 children already set, ages on "Scegli" (good, but unexplained, P3-2). After a failed submit the summary links are 31 px tall (P3-4). Cut off by a call and back: form empty again (P3-10). On a slow connection a tap on "Pianifica il viaggio" before the form is alive wipes it (P3-1).

**Sam (keyboard and screen reader).** Tab order matches reading order, ring on every stop, `aria-describedby` and `aria-invalid` wired by `Field`, errors say what and how, summary takes focus on 3+ problems. Flags: a failed list load is never announced (P3-3); the submit failure's `role="alert"` is undocumented (P3-8); the running row reads "In corso 0,00 $ in corso da 14 min" (P2-2).

**Alex (power user, third plan of the week).** Enter-to-next works, origin and party remembered. Still no "repeat this plan" on a row, and five rows called "Lisbona, 14–18 apr" cannot be told apart without reading a time (P2-2).

**Michele (the product's one user).** Opens home on the phone to check a run: the ring says it is running, the clock says how long, the list refreshes itself. But the rows are a table, and the dev build tells him "1 Issue" (P1-1). Opens the form: Milano and the party are there, the ages are his to choose, the whole request fits his Mac screen with children. Types a budget with cents and is told to write a whole number, without an example (P3-7).

## Rule check (CLAUDE.md UI rules)

| Rule | Result |
|---|---|
| Two dates always separate and labelled ("Prenota entro" / "Quando") | n/a on these screens (the form's "Partenza" and "Ritorno" are separate and labelled; no booking is shown) |
| Amber only on due-soon bookings, never on buttons | Pass: no amber on either page, buttons are ink |
| Sentence case, action verbs on buttons, no em dash | Pass: "Nuovo piano", "Pianifica il viaggio", "Parti da questo esempio", "Riprova", "Avvio il piano…"; no em dash found |
| `rel="noopener noreferrer"` on booking links | n/a (no external link on these pages) |
| `aria-live` only for agent state changes | Pass on home (no live region); the form has one `role="alert"` for a failed submit, documented nowhere (P3-8) |
| `prefers-reduced-motion` declared for every animation | Pass: only the busy spinner and the working ring animate, both under `motion-safe`/`motion-reduce` |
| Keyboard complete, visible focus | Pass: 2 px ink ring, 3 px offset, `:focus-visible` true on the stops checked, in both themes |
| 393 px | Pass: no horizontal scroll, form fields 44 px, primary 44 px, segments 46 px tap area; three controls at 31 to 32 px (P3-3, P3-4) |
| Costs in dollars, Italian formatting | Pass: "0,41 $", "circa 2–4 $" |
| Empty state is an invitation, not an empty page | Pass |

## Minor observations

- Phone form height: 1691 px, about two screens, with the primary at the end; the button is 44 px and full width, which is right. A sticky bottom bar once the required fields are filled is a question, not a defect.
- The "Mostra gli altri 9" disclosure uses the 18 px title style; it reads as a heading of a closed section. Fine, but it is the heaviest text on the card below the titles.
- `/new` keeps its state when you navigate away and back (Cache Components keeps the previous route alive): the form can show last visit's half-typed values after "I tuoi piani" and back. Worth a deliberate decision with P3-10.

## Questions to Consider

- What if home were the line map: each plan a station, the live one the "you are here" plate, so a month of Lisbon variants reads as a history instead of a list?
- What if the form's primary action stayed in view on the phone (a sticky bar with the cost line) once the required fields are filled, so the first screen is not the only place Michele can start the run?
- Does "Il tuo viaggio" earn its place before anything is typed, or should the card appear with the first value?
