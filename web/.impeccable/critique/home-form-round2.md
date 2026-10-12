---
target: home "/" and request form "/new" (web/app/page.tsx, web/app/new/page.tsx, components/home/*, components/request/*, lib/remembered-request.ts)
round: 2
total_score: 32
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
p2_count: 3
p3_count: 14
date: 2026-10-12
---

# Critique, round 2: home "/" and request form "/new"

**Method: DEGRADED, single-context.** No sub-agent tool was exposed to this agent, so Assessment A (design review) and Assessment B (detector and browser evidence) ran sequentially in one context; the design review was written down before the detector ran. Detector: `impeccable detect --json app/page.tsx app/new/page.tsx components/home components/request` returned `[]` (0 findings). The detector overlay was not injected (no live-server was started, to leave the shared dev stack alone). Also run: `npm run typecheck` (clean) and `vitest run components/request components/home lib/remembered-request lib/request-form` (7 files, 80 tests, all passed).

How it was inspected: real browser, own tab, 393x852 and 1440x900, light and dark, against the running demo stack. Home with 20 real demo plans (running, ready, blocked, failed, interrupted, budget reached). Empty state and list error state reached by stubbing `GET /plans` in the page after a client-side navigation (no source change). Form: pristine, empty submit (client validation), Enter in a text field, Tab order and focus ring, "Suggeriscimi tu" and "Mese e notti" modes, a 157-night trip (client rule), a stubbed 429 `monthly_limit_reached` and a stubbed 422, and a real submit of the example to the demo backend (POST /plans, redirect to `/plans/<id>` in about 3.6 s, last request stored). No source file was modified and no money was spent. Note: "Previous rounds: []" in the task text is stale; `home-form-round1.md` exists (29/40, 1 P1, 7 P2) and is the baseline here.

Gate (CLAUDE.md): a screen merges at 32/40 or more with no open P0 or P1. This round is 32/40, 0 P0, 0 P1: **it clears the gate, at the threshold.** The three P2s below are what keep it from 34.

## Verification of round 1's P0 and P1

| Round 1 finding | Status | Evidence |
|---|---|---|
| **P1** Enter in a text field submits the form (keyboard key labelled "Avanti") | **Fixed** | Typed "Milano" in origin, pressed Enter: focus moved to `field-destination`, 0 `aria-invalid`, no summary. `advance-on-enter.ts` moves to the next input/select/textarea, skips radios not focused, and lets only the last single-line field (budget, `enterKeyHint="go"`) send. 80 unit tests pass, including the helper. |
| P2 submit 40 px / segments 36 px | Fixed | Submit 361x44; segment labels 40 px plus a 3 px `before:-inset` so the tap area is 46 px (below 640 px). |
| P2 error summary repeats and sits out of view | Fixed | 5 errors: title "5 campi da sistemare", rows are field names only (links), summary is first in the form on the phone (top 247 px) and takes focus; from 1080 px it sits in the card beside the button. With 1 or 2 errors it does not show and focus goes to the field. |
| P2 cost line "Costo stimato del giro" | Fixed | "Il planner costa circa 2–4 $ per piano". |
| P2 budget hint "viaggi" | Fixed | "Per tutto il gruppo: voli, alloggio, attività e spostamenti." |
| P2 running plan not alive | Fixed | Running rows read "in corso da meno di 1 min"; list re-reads every 15 s while a plan runs, quietly (no `aria-live`; statuses changed between my visits without a reload); tests cover it. |
| P2 desktop form one long column | Mostly fixed | Two columns of sections at 1440x900; pristine form fits above the fold. With two children (the example, or a remembered party) "Budget e preferenze" starts at y 776 and the textarea is cut. See P3-5. |
| P2 nothing remembered | Fixed, with a new hazard | Origin, adults and children's ages are restored. See P2-1. |
| P3 draft lost on refresh | Not fixed | No sessionStorage mirror. |
| P3 `role="alert"` on submit failure | Unchanged | Still there (Notice's own doc allows it for the user's own action) but DESIGN.md does not record the exception. |
| P3 small targets | Partly fixed | Wordmark now 53x46. "Riprova" still 94x32 and the back link "I tuoi piani" 81x32. |
| P3 near-identical rows, timestamps | Partly fixed | `displayTitle` unifies the en dash. Still 20 rows, 1634 px tall at 393 px, "12 ott 2026, 17:36" on every row. |
| P3 invitation says the request twice | Not fixed | Sentence and facts both still show. |
| P3 read-back placeholders before typing | Not fixed | "Partenza da scegliere", "Meta da scegliere", "Date da scegliere", "Budget da indicare". |
| P3 placeholders look like values | Not fixed | Preferences placeholder is a full sentence in the same ink-2 as the hint. |
| P3 redundant euro statements | Fixed | Label "Budget totale", `€` suffix kept. |

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Busy button ("Avvio il piano…", `aria-busy`), skeleton rows, running rows alive, retry. The list's load failure is silent to a screen reader; nothing says when the form is not yet interactive (P3-2). |
| 2 | Match System / Real World | 4 | The two copy slips are gone. Reads as Michele talks. Only residue: "cinque agenti" followed by four named areas. |
| 3 | User Control and Freedom | 3 | Back link, editable example, values kept after every failure. Draft still lost on refresh; a restored party is applied without saying so (P2-1). |
| 4 | Consistency and Standards | 3 | One system, applied tightly. Two controls still under 44 px on the phone ("Riprova", back link) where everything else on the form is 44+. |
| 5 | Error Prevention | 3 | Enter, date `min`, clamped steppers, forgiving budget parser, 120-day rule on the client. A remembered set of children's ages goes stale and is preset into a paid run (P2-1). |
| 6 | Recognition Rather Than Recall | 3 | Visible labels, hints, read-back card. 20 titles that differ only by a timestamp (P2-3). |
| 7 | Flexibility and Efficiency | 3 | Remembered origin and party, Enter-to-next, example link. No "repeat this plan", no shortcut. |
| 8 | Aesthetic and Minimalist Design | 3 | Calm, flat, no amber, no colour on buttons. Redundancies persist: the invitation's sentence plus facts, the read-back card's placeholders. |
| 9 | Error Recovery | 4 | Specific sentence per field, summary of links at the top of the phone, focus where the problem is, 429/network each with a title and what was kept, nothing wiped. |
| 10 | Help and Documentation | 3 | A hint under nearly every field; the cost line now says whose cost it is. |
| **Total** | | **32/40** | **Good (28-35)**; clears the 32 gate with 0 P0, 0 P1 |

Trend: 29 -> 32.

## Design Specificity Verdict

**LLM assessment (written before the detector).** Better than round 1, still moderate. The form is authored: the ring-and-bar route line ("Da Milano / A Lisbona") on the read-back card and in the invitation, the "Il tuo viaggio" card that reads the request back before it costs anything, status as glyph plus word, ink pills, and copy that sounds like one person talking to himself ("Suggeriscimi tu", "Mese e notti"). Those could only be Atlas. The home list, the page Michele opens most often, is still a bordered table of near-identical rows (title, status, cost, timestamp) that any planner or CI dashboard would ship unchanged: Linee's idea (the run drawn as a line of stations) is absent exactly where it would cost the least to show. At 1440 the home is the phone list stretched to 64 rem and left aligned, with the primary action at the list's right edge and the theme toggle at the viewport's.

**Deterministic scan.** 0 findings on the four targets, no false positives. Manual checks that agree: no amber anywhere, no coloured button, no em dash, sentence case, `lang="it"`, 16 px inputs, no horizontal scroll (scrollWidth 393 at 393 px, 1440 at 1440 px), one `h1` per page, header and main landmarks, reduced motion declared (`motion-safe:animate-breathe`, `motion-safe:animate-turn`, `motion-reduce:active:scale-100`), focus ring visible on every one of 17 tab stops in the form (2 px ink, 3 px offset, `:focus-visible` true), tab order matches reading order.

**Visual overlays.** Not injected (see Method). Fallback signal: the clean scan and the DOM and computed-style audit above.

## Overall impression

Round 1's complaints were about friction at the thumb; they are gone. Enter now behaves like the key says, the primary is a full 44 px, errors are said once and read first. What remains is no longer craft but judgement: the form now helps by remembering, and the help can hurt (silently preset children's ages), and the home list still does not look like Atlas. The single biggest opportunity: make home read as a line of runs, newest and live first, instead of 20 equal rows.

## What's working

1. **Error handling is now complete.** Empty submit gives a count and links at the top of the phone (focus lands there, "5 campi da sistemare" with the five field names), each field has its own sentence and a cross, and a single problem puts focus on the field instead of the summary. A stubbed 429 says "Limite di spesa del mese raggiunto" with the backend's own message and keeps every value; the retry notice sits right above the button where the thumb is.
2. **Enter and the keyboard.** The flow Alex and Casey both expect works: Enter walks origin, destination, dates, steppers, budget, and only the budget (key reads "Vai") sends. The 17 tab stops are in order and every one shows the focus ring.
3. **A running plan reads as running.** "in corso da meno di 1 min" replaces a frozen timestamp, the list refreshes itself every 15 s only while something runs, and it does so without a live region, as the aria-live rule requires. I saw the three running rows turn into finished rows with real costs between two visits.
4. **Discipline holds in both themes and both sizes.** No amber, no colour on buttons, costs as "0,41 $", status always glyph plus word, dark mode keeps hierarchy (ink pill inverts, error wash legible). The empty state is an invitation with a request already written, two taps to a first plan.

## Priority issues

### [P2-1] A remembered party is applied silently, and children's ages go stale

- **Where:** `lib/remembered-request.ts` (`applyRemembered`), applied in `request-form.tsx` after hydration (`useEffect`).
- **Seen:** after one real submit (Milano, 2 adults, children 8 and 11), every later `/new` opens with origin "Milano", Adulti 2, Bambini 2 and both ages chosen, no sign that any of it came from memory. The read-back card on desktop already says "2 adulti, 2 bambini di 8 e 11 anni".
- **Why it matters:** the efficiency gain is real (about 12 interactions), but the thing being preset is the input that changes the price of flights and rooms and is the one that is wrong a year later (the children are 9 and 12). Michele has to notice something he did not type. A wrong party starts a paid run that cannot be corrected.
- **Fix:** restore origin and adults only; restore the number of children but leave each age on "Scegli" so every age is a conscious tap (the count is the time-saver, the ages are the stale part); or keep ages and add one line in ink-2 under the "Chi viaggia" heading, "Come nell'ultimo piano. Controlla le età." (a `<p>`, no live region). A remembered origin is safe and stays.
- **Suggested command:** `/impeccable harden`

### [P2-2] Desktop with children: the form loses its "everything above the fold" promise

- **Where:** `request-form.tsx` layout at 1440x900. Pristine: budget visible, preferences cut at y 900. With two children (the example, or a remembered party): "Chi viaggia" grows 263 px, "Budget e preferenze" starts at y 776 and the budget field is at the fold; the "Il viaggio" column ends about 100 px above the end of the right column, leaving a hole under "Dove vuoi andare".
- **Why it matters:** DESIGN.md promises that "a request with no children fits at 1440 by 900"; with children, which is Michele's usual request, the last required field is below the fold while the sticky card (and its button) sits at the top. He can press "Pianifica il viaggio" without ever having seen the budget field, and gets the budget error instead.
- **Fix:** move "Budget e preferenze" into the left column under "Il viaggio" (the shorter column) from `lg`, so it fills the hole: left column "Il viaggio" + "Budget", right column "Quando" + "Chi viaggia". Heights then balance at about 560 and 490 px and the whole request fits at 900 with children. Keep the textarea `lg:min-h-20`.
- **Suggested command:** `/impeccable layout`

### [P2-3] Home list: twenty equal rows, and the live one is not first in the eye

- **Where:** `components/home/plan-list.tsx`. Every row has the same weight (18 px semibold title, same meta); a typical month of Lisbon variants gives 20 rows whose only difference is the timestamp ("12 ott 2026, 17:36", the year repeated on every row); 1634 px tall at 393 px.
- **Why it matters:** the phone job is "check the one that is running". Running rows are now correct but visually identical to finished ones, so the page still has to be read, not seen. It is also where Atlas could show its own idea (a line, stations) and shows a table.
- **Fix:** (1) timestamps relative then short: "Oggi, 17:36", "Ieri, 21:40", "8 ott", "8 ott 2025" (the year only when different); (2) group: running plans first under "In corso" with the ring glyph, then "Recenti"; show 8 rows and put the rest in a `Disclosure` "Mostra gli altri 12"; (3) optional, bolder: a 3 px ink line down the row's left edge with the plan status glyph as the station, newest at the top, so "I tuoi piani" is already a line map (use the plan-status glyphs only: DESIGN.md's rings mean tool calls).
- **Suggested command:** `/impeccable layout`, then `/impeccable bolder`

### [P3-1] Pre-hydration submit reloads the page with junk in the URL

- **Where:** `request-form.tsx` `<form onSubmit>`; no `method`/`action`; only the radios have `name` (`useId` values).
- **Seen:** while the form's Suspense boundary had not hydrated (it streams late: `searchParams` + `connection()`; in my tab it stayed unhydrated for 30 s while the tab was in the background), clicking the submit button did a native GET: the URL became `/new?_R_4klritqlb_=pick&_R_4klritqlbH1_=exact` and the form was wiped. On a slow phone the window between paint and hydration is real, and Enter in a field does the same.
- **Why it matters:** rare, but destructive and ugly (it also shows form state in the URL). Verified as a background-tab artefact only in the sense that a foreground tab hydrates in under a second.
- **Fix:** keep the submit button `disabled` (and `aria-disabled`) until a `useEffect` flag says the form is hydrated, and add `onKeyDown` for Enter as it already does; or render the form `inert` until hydrated. No change needed after hydration.
- **Suggested command:** `/impeccable harden`

### [P3-2] A failed list load is silent to a screen reader

- **Where:** `plan-list.tsx` error branch: the skeleton (`aria-busy`) is replaced by a `Notice` with no role and no focus move; roles in the page after the error: only the `group`.
- **Fix:** give the notice `tabIndex={-1}` and an id and focus it when the state flips to `error` after an explicit load (not on the quiet 15 s re-reads, which already keep what is shown). That keeps `aria-live` off the page and still lets Sam hear it. Make "Riprova" `size="md"` (40 px) in this full-width notice.
- **Suggested command:** `/impeccable harden`

### [P3-3] The restored values pop in after hydration (a layout jump)

- **Where:** `useEffect(... applyRemembered ...)` in `request-form.tsx`.
- **Seen:** the server HTML has an empty form with "Chi viaggia" one row tall; after hydration origin fills and the two age selects appear, pushing "Budget e preferenze" down about 90 px at 1440 and 80 px at 393.
- **Fix:** if P2-1 stops restoring ages the jump mostly disappears (only the origin text changes). Otherwise reserve the height or run the restore in `useLayoutEffect`.
- **Suggested command:** `/impeccable polish`

### [P3-4] Draft is still lost on refresh or when iOS evicts the tab

- **Fix (unchanged from round 1):** mirror `values` to `sessionStorage` on change (debounced, try/catch), restore on mount unless `?esempio=1`, clear on a successful submit. Pair it with the remembered party so the two do not fight (`applyRemembered` already only fires on an untouched form).
- **Suggested command:** `/impeccable harden`

### [P3-5] The trip-length error is squeezed into half the width

- **Where:** at 393 px the 120-day message sits under "Ritorno" (175 px wide) and wraps to three lines: "Il viaggio può durare / al massimo 120 giorni / (119 notti)."
- **Fix:** route `trip_too_long` (client and server) to the `dates` group error (`GroupError`, full width under both date fields) and keep a red edge on "Ritorno".
- **Suggested command:** `/impeccable layout`

### [P3-6] Two tap targets on the phone are still 32 px

- **Where:** back link "I tuoi piani" (81x32, `min-h-8`), "Riprova" (94x32). Everything else on these two pages is 40 px or more.
- **Fix:** `min-h-11` on the back link at phone width (`sm:min-h-8`); "Riprova" at `size="md"`.
- **Suggested command:** `/impeccable adapt`

### [P3-7] Home at 1440: the content is a 1024 px column with two right edges

- **Where:** `app/page.tsx` `max-w-[64rem]` inside `max-w-page`. The "Nuovo piano" button ends at the list's right edge (x about 1050); the theme toggle at the viewport's (x 1412); about 35 % of the screen is empty on the right on both the list and the invitation.
- **Fix:** either cap the header's inner width to the same measure as the content (so both edges agree), or use the empty column: from `lg` put a quiet panel to the right of the list (a "Cos'è in corso" count, or the example card) instead of leaving it blank. The first is a one-line change.
- **Suggested command:** `/impeccable layout`

### [P3-8] The invitation says the request twice

- **Where:** `empty-invitation.tsx`: "«Lisbona a metà aprile, 2 adulti e 2 bambini, 2.400 €»" and then Da/A/dates/travellers/budget, the same facts. Not fixed since round 1.
- **Fix:** drop the quoted sentence and keep the route line plus facts (the part only Atlas has), or keep the sentence as the figure's caption and drop the facts list.
- **Suggested command:** `/impeccable distill`

### [P3-9] The read-back card shows "da scegliere" before anything is typed

- **Where:** desktop `RequestSummary` on a pristine form: five placeholder lines beside the same empty fields. Not fixed since round 1.
- **Fix:** show the facts only once a field has a value; before that one ink-2 line ("Qui leggi la richiesta mentre la scrivi.") above the button.
- **Suggested command:** `/impeccable quieter`

### [P3-10] Placeholders read as values

- **Where:** preferences placeholder "Niente voli prima delle 8, quartiere tranquillo, cucina locale" is a full sentence in the same ink-2 as the hint above it; the origin placeholder "Milano, oppure MXP" has no "Per esempio" while destination does.
- **Fix:** start every placeholder with "Per esempio" (origin: "Per esempio Milano o MXP"; preferences: "Per esempio niente voli prima delle 8, quartiere tranquillo").
- **Suggested command:** `/impeccable clarify`

### [P3-11] The submit failure still uses `role="alert"` and DESIGN.md does not say why

- **Where:** `request-form.tsx`, `<Notice tone="error" role="alert">` plus focus moved to the button. `Notice`'s own comment allows it for the user's own action; CLAUDE.md and DESIGN.md only allow lane state changes and toasts.
- **Fix:** add one line to DESIGN.md's `aria-live` rule ("an error that answers the user's own submit is `role="alert"`, once") or move focus to the notice with `tabIndex={-1}` and drop the role, as the summary does.
- **Suggested command:** `/impeccable document`

### [P3-12] Minor mobile ergonomics

- The phone form is 1606 px tall (two and a half screens); the primary is only at the bottom. It is 44 px and full width, which is right, but consider repeating the cost line and button in a sticky bottom bar only once the required fields are filled. A question more than a defect.
- Tab stops: a stepper is three stops (minus, number, plus); the form has 17 in total. Fine; no skip link on the pages (two stops before the content, so not needed).
- The dev indicator overlaps the cost line at the bottom-left of the phone viewport (development only).

### [P3-13] "Cinque agenti" followed by four areas

- **Where:** intro of `/new` and the invitation: "Cinque agenti cercano voli, alloggio, attività e spostamenti". The coordinator is the fifth and is not named; a careful reader counts four.
- **Fix:** "Cinque agenti, un coordinatore e quattro specialisti, cercano voli, alloggio, attività e spostamenti" is too long; prefer "Un coordinatore e quattro agenti cercano voli, alloggio, attività e spostamenti mentre li guardi lavorare".
- **Suggested command:** `/impeccable clarify`

### [P3-14] Provenance of the cost line

- "Il planner costa circa 2–4 $ per piano" uses the word "planner" where every other string says the product's name or "il piano". It reads fine, and it is the right figure; consider "Un piano costa circa 2–4 $ di API" if "planner" is not an everyday word for Michele. Optional.

## Persona red flags

**Casey (distracted phone user, one thumb).** Type "Milano", tap "Avanti": moves to the destination, no errors (was the P1). Submit is 44 px, segments 46 px tap area, steppers 44. Opens `/new` and finds the last party already set (good, but silently, P2-1). Cut off mid-form by a call and back: form empty again (P3-4). The button is two and a half screens down.

**Sam (keyboard and screen reader).** 17 tab stops in reading order, focus ring on all, `aria-describedby` and `aria-invalid` wired by `Field`, errors say what and how to fix, the summary takes focus on 3+ problems. Flags: the summary and the list error carry no role, so the first is read from its text (acceptable) and the second not at all (P3-2); `role="alert"` on the submit failure is undocumented (P3-11); a pre-hydration submit reloads the page (P3-1).

**Alex (power user, third plan of the week).** Enter-to-next works, origin and party remembered. Still no "repeat this plan" on a row and no key to start a new plan; the list gives no way to tell twenty Lisbon rows apart without reading seconds (P2-3).

**Michele (the product's one user).** Opens home from the phone to check a run: running rows now say "in corso da 3 min" and refresh. But they sit among nineteen look-alikes (P2-3). Opens the form: Milano, 2 adults and two children are already there; one year from now the ages will be wrong and nothing will say so (P2-1). Types a budget and presses the button at the bottom, never scrolling past "Chi viaggia" on a Mac with children set (P2-2).

## Rule check (CLAUDE.md UI rules)

| Rule | Result |
|---|---|
| Two dates "Prenota entro" / "Quando" | Not applicable here (no bookings). The intro says "la data entro cui farla" in prose, correct. |
| Amber only on due-soon bookings | Pass: no amber on either screen, in either theme. |
| Costs in dollars, two decimals, Italian ("0,41 $") | Pass: list "0,00 $", "0,41 $"; estimate "2–4 $" (a range, as the spec). |
| Sentence case, action verbs, no em dash | Pass. Buttons "Nuovo piano", "Parti da questo esempio", "Pianifica il viaggio", "Riprova"; "Avvio il piano…" while busy. |
| `BRAND_NAME` only | Pass (title "I tuoi piani · Atlas", "Nuovo piano · Atlas"). |
| `rel="noopener noreferrer"` on booking links | Not applicable (no booking links, no external links). |
| `aria-live` only for agent state changes | Pass for live regions (0 on both pages, the 15 s poll is silent). One `role="alert"` on the submit failure: allowed by Notice's doc, not by DESIGN.md (P3-11). |
| Reduced motion | Pass: skeleton, busy arrows and press scale all have `motion-safe` / `motion-reduce` equivalents. |
| Keyboard and focus | Pass: complete tab order, visible ring, Enter moves on. |
| 393 px | Pass: no horizontal scroll, 16 px inputs, targets 44 px except two 32 px links (P3-6). |
| Empty state is an invitation | Pass. |
| Every state designed | Pass: loading, empty, error, retry, validation, 429/503/network, busy, example prefill. |

## Questions to consider

- What if home opened with the running plan as a single wide row ("Lisbona, 14–18 apr, in corso da 3 min, 0,36 $") and the rest as a quiet list under "Recenti"?
- Should the form remember the party at all, or only the origin? The party is the input that goes stale.
- Does the desktop need the page header's right edge and the list's right edge to be the same line?

## Recommended order

1. `/impeccable harden`: restore children's ages as "Scegli" or flag them (P2-1), disabled-until-hydrated submit (P3-1), focus the list error notice (P3-2), draft in sessionStorage (P3-4).
2. `/impeccable layout`: move "Budget e preferenze" under "Il viaggio" (P2-2), full-width trip-length error (P3-5), one right edge on desktop home (P3-7), running-first and relative-date list (P2-3).
3. `/impeccable adapt`: 44 px back link and "Riprova" (P3-6).
4. `/impeccable distill` and `/impeccable quieter`: invitation duplicate, pristine read-back card (P3-8, P3-9).
5. `/impeccable clarify` then `/impeccable polish`: placeholders, "cinque agenti" line, DESIGN.md note on `role="alert"` (P3-10, P3-11, P3-13).

Re-run `/impeccable critique` after P2-1, P2-2 and P2-3: realistic target 34-35/40.
