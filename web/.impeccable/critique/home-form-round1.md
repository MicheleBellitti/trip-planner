---
target: home "/" and request form "/new" (web/app/page.tsx, web/app/new/page.tsx, components/home/*, components/request/*)
round: 1
total_score: 29
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 1
p2_count: 7
p3_count: 9
date: 2026-10-12
---

# Critique, round 1: home "/" and request form "/new"

**Method: DEGRADED, single-context.** No sub-agent tool was exposed to this agent, so Assessment A (design review) and Assessment B (detector and browser evidence) ran sequentially in one context. Assessment A was written down before the detector ran. Detector: `impeccable detect --json` on `app/page.tsx`, `app/new/page.tsx`, `components/home`, `components/request` returned `[]` (0 findings). The detector overlay was not injected: no live-server was started, to leave the shared dev stack alone.

How it was inspected: real browser, 393x852 and 1440x900, light and dark, against the running demo stack. Home with 20 real demo plans (running, ready, blocked, failed). The empty state and the list error state were reached by intercepting `GET /plans` in the page after a client-side navigation (no source change). The form was submitted empty (client validation), with a simulated server 422 (`trip_too_long`), 429 and network failure (fetch intercepted), and for real with the example request (POST /plans on the demo backend, redirected to `/plans/<id>` in about 2.5 s). No source file was modified, and no money was spent.

Gate reminder (CLAUDE.md): a screen merges at 32/40 or more with no open P0 or P1. This round is at 29/40 with one P1, so it does not clear the gate yet.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Busy button, skeleton rows, retry, live read-back on desktop are good. A running plan in the list shows a frozen "0,00 $" and its created time, nothing says how long it has been running. |
| 2 | Match System / Real World | 3 | Italian reads naturally. Two slips: "Costo stimato del giro" (what is a "giro"? beside a euro budget it can read as the trip's price) and the budget hint "viaggi, alloggio e attività" (the agents search voli, alloggio, attività, spostamenti). |
| 3 | User Control and Freedom | 3 | Back link, editable example, values kept after every failure. The draft is lost on refresh or when the phone app is evicted. |
| 4 | Consistency and Standards | 3 | The system is coherent. Gaps: the primary button (40 px) is shorter than the inputs above it (44 px), segmented options are 36 px, `enterKeyHint="next"` does not behave like "next". |
| 5 | Error Prevention | 3 | Date `min`, clamped steppers, 9-person cap, month list, forgiving budget parser. But Enter in any text field submits an incomplete form (see P1). |
| 6 | Recognition Rather Than Recall | 3 | Visible labels, hints, example placeholders, desktop read-back summary, strong empty state. 20 near-identical titles in the list force the user to read timestamps to tell plans apart. |
| 7 | Flexibility and Efficiency | 2 | Nothing remembers origin or party size, no way to repeat or start from a past plan, no keyboard accelerators. Fine for a first run, thin for the third trip. |
| 8 | Aesthetic and Minimalist Design | 3 | Calm and quiet, amber and colour discipline is perfect. Small redundancies: the invitation says its request twice, the read-back card shows "da scegliere" placeholders before anything is typed. |
| 9 | Error Recovery | 3 | Specific inline messages, focus moves to the first bad field, server 422 lands on the right field, 429/503/network each have a title and "La richiesta resta qui". Summary stutters and sits out of view on the phone. |
| 10 | Help and Documentation | 3 | A hint under nearly every field, the cost line, the intro. The cost line is the one piece of help that confuses. |
| **Total** | | **29/40** | **Good (28-35)** |

## Design Specificity Verdict

**LLM assessment (written before the detector).** Mixed. The pieces that exist are authored: Barlow Semi Condensed on a cool ink-on-grey ground, ink pill buttons, status as word plus line-form glyph (ring, check, prohibit, cross), the `RouteLine` ring-and-bar "Da Milano, A Lisbona" mark in the invitation and in the desktop read-back card, the "Il tuo viaggio" card that repeats the request before it costs anything. Those could only belong to Atlas. The home list itself, though, is a bordered list of rows with a title, a status and a date, which any planner, task manager or CI dashboard would ship unchanged. Direction 1's strongest idea (the run drawn as a transit line) is absent from the page Michele sees most often; the wordmark is plain 18 px text. The form is a competent, accessible single column; specificity there lives in the copy ("Suggeriscimi tu", "Mese e notti") and the read-back card. Verdict: well-executed and on-system, moderately specific, one missed opportunity on the home list.

**Deterministic scan.** 0 findings on the five source targets. No false positives to flag. Manual checks that agree with it: no amber, no em dash, no coloured button, sentence case everywhere, no `rel` concerns (no external links on these screens), 16 px inputs, `lang="it"`, no horizontal scroll at 393 px (scrollWidth 393), all three Italian error states and the loading state exist.

**Visual overlays.** Not injected (see Method). Fallback signal: the clean detector scan and the manual DOM audit above.

## Overall impression

A calm, careful pair of screens that obey the system almost to the letter: every state exists, errors are specific, the form survives every failure. What holds it back is not craft but three small friction points that all hit the one-handed phone user in the same spot (the keyboard "Avanti" key submits, the primary button and segmented options are under 44 px, the error summary lands where the thumb is not looking), plus a home list that does not yet know which of its plans is the live one. The single biggest opportunity: make "the plan that is running right now" the first thing the home page says, and make the form's keyboard flow match what the keyboard promises.

## What's working

1. **Error handling is the best part of the form.** Empty submit gives one message per field in plain Italian ("Indica dove vuoi andare, oppure scegli «Suggeriscimi tu»."), focus lands on the first bad field with the cursor in it, the field edge turns red with a cross glyph and a sentence (never colour alone), and the server's `trip_too_long` 422 arrives on the date pair with the right wording and focus on "Partenza". The 429 notice says what happened and "La richiesta resta qui, pronta da inviare di nuovo."
2. **The empty state is an invitation, not an apology.** It offers a request already written, shows it as a route line plus three facts, and "Parti da questo esempio" opens the form filled (`/new?esempio=1`), so the first plan is two taps. It is also drawn with the product's own vocabulary (the route line).
3. **Colour and type discipline.** Amber is absent from both screens, ink is the only action colour, status is always glyph plus word (Pronto, In corso, Bloccato, Non riuscito), costs read "0,41 $" in Italian format, tabular figures line up the desktop Costo column, inputs are 16 px so iOS will not zoom. Dark mode holds contrast and hierarchy with no surprises.
4. **Form structure.** Four labelled sections, hints in ink-2 under labels, optional fields marked "(facoltativo)" while required ones carry no mark, native date inputs and native selects (the phone's own pickers), a stepper with a real number input, children's ages appearing as the child count grows. The sticky desktop card that reads the request back next to the button is a good idea.

## Priority issues

### [P1] Enter in a text field submits the whole form, and the keyboard key is labelled "next"

- **Where:** `components/request/request-form.tsx`, origin and destination `TextInput` (`enterKeyHint="next"`, lines about 171 and 224), the budget field, and every single-line input inside the `<form>`.
- **Verified in the browser:** focus the origin field, type "Milano", press Enter. The form submits, four errors appear, the summary opens and focus is thrown to "Dove vuoi andare".
- **Why it matters:** on the phone (the primary device) the soft keyboard's key says "Avanti" (`enterkeyhint="next"`) but acts as submit. The most natural first gesture, "type Milano, tap Avanti", produces a wall of red errors on a form the user has barely started. That is the kind of thing a user would report as broken.
- **Fix:** in one place (a `onKeyDown` on the form, or a small `advanceOnEnter` helper used by `TextInput` fields) intercept Enter on single-line inputs: `preventDefault()` and focus the next focusable control in DOM order (`form.elements`). Let Enter submit only when the focused control is the last one (the budget field, if preferences is skipped, should move to preferences; the textarea keeps Enter as a newline). Keep `enterKeyHint="next"` on the fields that now behave that way and set `enterKeyHint="go"` on the last single-line field.
- **Suggested command:** `/impeccable harden`

### [P2] The primary submit button (40 px) is shorter than the fields above it (44 px), and the segmented options are 36 px

- **Where:** `button.tsx` md size and DESIGN.md `button-primary` (40 px); `field.tsx` `SegmentedControl` labels (`min-h-9`, 36 px inside a 3 px padded 44 px track); measured at 393 px: submit 361x40, each segment 176x36.
- **Why it matters:** the one-handed phone user taps the biggest decision of the page (the thing that starts a paid run) on the smallest control of the form, and the destination and date mode switches are 36 px targets with a 3 px dead ring around them. The 44 px inputs and steppers set the expectation and the primary breaks it.
- **Fix:** below `sm` make the submit `min-h-11` (44 px) and the segmented labels `min-h-10` or drop the track padding so a label fills the 44 px track; keep 40 px from `sm` up. If DESIGN.md's 40 px token is meant to stay absolute, record the phone exception in DESIGN.md (the tokens are the authority) and in `tokens.test.ts`.
- **Suggested command:** `/impeccable adapt`

### [P2] The error summary repeats the inline errors, stutters, and sits below the fold on the phone

- **Where:** `request-form.tsx` summary `Notice`; example on screen: "Da dove parti: Indica da dove parti: una città o un aeroporto." and "Date: Il viaggio può durare al massimo 120 giorni (119 notti)."
- **Why it matters:** every error is now written twice (under the field and in the summary), the summary prefixes a label to a sentence that already names the field, and on the phone the summary is at the bottom while focus is thrown to the top: the user sees one inline error and never the count or the links. It is noise on a screen that is otherwise quiet.
- **Fix:** summary rows are links only, label as link text, no repeated message ("Da dove parti", "Dove vuoi andare", "Partenza"), with the count as the title ("4 campi da sistemare"); or show the summary only when there are 3 or more errors. On the phone place it directly under the intro (above "Il viaggio") and move focus there (it already has `tabIndex={-1}`) when more than one field is wrong; keep focus on the field when exactly one is.
- **Suggested command:** `/impeccable clarify`

### [P2] Copy: "Costo stimato del giro: circa 2–4 $" reads as the trip's price

- **Where:** `COST_ESTIMATE` in `request-form.tsx`, under the primary button, next to a budget typed in euro.
- **Why it matters:** "il giro" is ambiguous in Italian (a tour, a round), the amount is in dollars while everything above is euro, and the sentence does not say whose cost it is. A reader can take it as "this trip costs about 2 to 4 dollars" or be unsure whether it is charged. It is the one line meant to reassure before pressing the paid button.
- **Fix:** "Il planner costa circa 2–4 $ per piano" (or "Costo del planner per questo piano: circa 2–4 $"). The spec keeps the figure; only the noun phrase changes.
- **Suggested command:** `/impeccable clarify`

### [P2] Copy: the budget hint names the wrong things

- **Where:** `request-form.tsx`, "Per tutto il gruppo: viaggi, alloggio e attività."
- **Why it matters:** the user is deciding what the budget has to cover. "Viaggi" is not one of the five agents' areas (voli, alloggio, attività, spostamenti) and omits local transport; it leaves unclear whether flights count.
- **Fix:** "Per tutto il gruppo: voli, alloggio, attività e spostamenti."
- **Suggested command:** `/impeccable clarify`

### [P2] Home does not know which plan is the live one

- **Where:** `components/home/plan-list.tsx`. A running plan shows "In corso", a static "0,00 $" and "12 ott 2026, 16:58", identical in weight to nineteen finished rows; the list never refreshes, so the cost and status freeze at the moment of the fetch.
- **Why it matters:** PRODUCT.md's phone job is "starts a plan or checks one that is running". Coming back from a lock screen, Michele sees a flat list with a stale 0,00 $ for the plan he cares about, has to hunt it, then open it to learn whether it finished.
- **Fix:** (1) for `running` rows show "in corso da 3 min" in place of the created timestamp (computed client-side from `created_at`, `useNow`); (2) while any row is running, refetch `GET /plans` every 15-20 s, quietly, no `aria-live` (rule: live regions are for agent state changes); (3) keep running plans above finished ones only if the backend order already puts them there, otherwise leave the order and just make the row's glyph carry it. Do not colour it: the ring glyph and the word are enough.
- **Suggested command:** `/impeccable layout`

### [P2] Desktop form is one long column; the fold hides two of four sections

- **Where:** `/new` at 1440x900: "Il viaggio" and the top of "Quando" are visible, "Chi viaggia" and "Budget e preferenze" need a scroll while the sticky card (with the button) stays in view. The form column is 38 rem, the card 20 rem, the right third of the viewport is empty. The home list and invitation also stop at 64 rem, leaving about 400 px unused on the right.
- **Why it matters:** the desktop layout is the phone layout plus a side card, not the "second layout" DESIGN.md promises. Origin and destination are naturally a pair, as are the two dates and adults/children, yet each takes a full row.
- **Fix:** from `lg`, lay "Da dove parti" and the destination mode/field in two columns, put "Chi viaggia" (adults, children) and the budget on one row, keep ages and preferences full width. Target: every field above the fold at 1440x900 for a request with no children. On home, leave the 64 rem measure (it keeps the row scannable) but start the right column with something useful or accept the left alignment deliberately.
- **Suggested command:** `/impeccable layout`

### [P2] Nothing is remembered between plans

- **Where:** `emptyRequestForm()` always starts blank; `/new?esempio=1` is the only prefill; rows in the list have no "Ripeti" or "Parti da qui".
- **Why it matters:** the product is for one person who will plan many trips from the same origin with a similar party. Re-typing "Milano", re-stepping adults and children and their ages is the efficiency heuristic's most common failure; here it costs about 12 interactions on a phone.
- **Fix:** persist the last submitted origin, adults and children's ages in `localStorage` (wrapped in try/catch) and use them as `initialValues` when no `?esempio` is present; optionally a quiet "Ripeti" action on a plan row that opens `/new` with that plan's request if the API exposes it. Never persist the budget or preferences by default.
- **Suggested command:** `/impeccable onboard`

### [P3] Draft is lost on refresh or app eviction

- **Why it matters:** the phone user is interrupted mid-form, iOS evicts the tab, the form is empty again.
- **Fix:** mirror `values` to `sessionStorage` on change (try/catch, debounced), restore on mount, clear on successful submit.
- **Suggested command:** `/impeccable harden`

### [P3] The submit failure notice uses `role="alert"`

- **Where:** `request-form.tsx`, `<Notice tone="error" role="alert">` for 429/503/network, with focus also moved to the button.
- **Why it matters:** CLAUDE.md and PRODUCT.md limit live regions to agent state changes. This is arguably the user's own action (as toasts are), but it is an assertive region and focus is already moved, so a screen reader may hear it twice or not in order.
- **Fix:** drop `role="alert"`, give the notice `tabIndex={-1}` and an id like the field summary, and move focus to it (not to the button) so it is read once, then document the exception in DESIGN.md if `role="alert"` is kept.
- **Suggested command:** `/impeccable harden`

### [P3] Small tap targets elsewhere

- **Where:** wordmark link "Atlas" 37x22 px (home link on the phone), "Riprova" in the list error 94x32, "I tuoi piani" back link 81x32.
- **Fix:** pad the wordmark link to 44 px high (negative margin to keep the optical alignment), use `size="md"` for "Riprova" in the full-width error notice, `min-h-11` on the back link at phone width.
- **Suggested command:** `/impeccable adapt`

### [P3] Home list: a wall of near-identical rows

- **Where:** 20 rows, 1634 px tall at 393 px, nearly all titled "Lisbona, 14–18 apr" or "Lisbona in famiglia, 14-18 aprile 2027" (demo data, but a real month of Lisbon variants would look the same). Two title formats coexist ("14–18 apr" with an en dash, "14-18 aprile 2027" with a hyphen): backend fixture or contract, worth aligning.
- **Why it matters:** the only differentiator is a 12 ott 2026 timestamp the same on every row. The year is redundant when all rows are this year.
- **Fix:** timestamps as "Oggi, 17:03", "Ieri, 21:40", then "8 ott" within the year, "8 ott 2025" otherwise (`formatDateTime` already runs in the browser only). Show the first 8 rows and put the rest under a `Disclosure` "Mostra gli altri 12 piani" on the phone. Ask the backend to keep `title` in one format.
- **Suggested command:** `/impeccable distill`

### [P3] The invitation says the same request twice

- **Where:** `empty-invitation.tsx`: the quoted sentence "Lisbona a metà aprile, 2 adulti e 2 bambini, 2.400 €" is followed by Da Milano / A Lisbona / dates / travellers / budget, the same facts.
- **Fix:** keep the route line and facts list, drop the sentence (or keep the sentence and drop the facts). The route line is the part only Atlas has.
- **Suggested command:** `/impeccable distill`

### [P3] The read-back card shows empty placeholders before anything is typed

- **Where:** desktop `RequestSummary`: "Partenza da scegliere", "Meta da scegliere", "Date da scegliere", "1 adulto", "Budget da indicare" on a pristine form, directly beside the same empty fields.
- **Fix:** show the card's facts only once a field has a value; before that show one line in ink-2 ("Qui leggi la richiesta mentre la scrivi.") or only the button and the cost line.
- **Suggested command:** `/impeccable quieter`

### [P3] The home list does not use the product's own vocabulary

- **Why it matters:** Linee's idea (a line with stations) lives only on the live screen and in the invitation's route line. A question rather than a defect: could the list's left edge be a thin ink line with the status glyph as the station for each plan, newest at the top, so that "your plans" is already a line map? (Keep glyph meaning intact: DESIGN.md's rings mean tool calls, so a new glyph or reusing the plan-status glyphs only.)
- **Suggested command:** `/impeccable bolder`

### [P3] Placeholders are close to values

- **Where:** "Per esempio Lisbona" in ink-2 against typed "Lisbona" in ink on the same surface, same size. Readable, but on a quick glance a placeholder looks like a filled value on the phone.
- **Fix:** keep the "Per esempio" prefix (it already marks the sample) and make sure budget "Per esempio 2.400" does the same; lower the placeholder to ink-2 at 80 % only if contrast stays at 4.5:1 (it must, DESIGN.md measures it), otherwise leave it.
- **Suggested command:** `/impeccable polish`

### [P3] Redundant euro statements in the budget field

- **Where:** label "Budget totale in euro", the "€" suffix inside the field, placeholder "Per esempio 2.400".
- **Fix:** label "Budget totale", keep the suffix; the hint carries the scope.
- **Suggested command:** `/impeccable clarify`

## Persona red flags

**Casey (distracted phone user, one thumb).** Type "Milano", tap the keyboard's "Avanti": the form submits and throws four errors (P1). The thumb target for starting the run is 40 px (P2). Cutting the form to answer a text message and coming back loses everything (P3). "Nuovo piano" sits top-right of a 1634 px list (P3). On the plus side: native pickers, 16 px inputs, steppers instead of typing counts.

**Sam (keyboard and screen reader).** Tab order is correct and complete (wordmark, theme toggle, back link, then each field in order, the stepper buttons, the submit button), focus rings are visible (inputs get a 2 px ink ring and ink border, segmented control uses `has-focus-visible`), every field has label, hint and error wired with `aria-describedby`, errors move focus. Flags: the submit failure `role="alert"` (P3), and the summary read after the per-field errors repeats everything a second time.

**Alex (power user, third plan of the week).** Retypes Milano and 2+2 every time (P2, flexibility), no "ripeti questo piano", no way to duplicate; list rows are the only entry point back to a result. No keyboard path to "Nuovo piano" other than tabbing.

**Michele (the product's one user, per PRODUCT.md).** Opens home from the phone to check a running plan: the row is indistinguishable from nineteen finished ones and shows a frozen 0,00 $ (P2). Opens the form to plan the next trip: types the same origin and party as last time (P2). Reads "Costo stimato del giro: circa 2–4 $" and has to decide what it refers to (P2).

## Minor observations

- Home caption "Gli ultimi 20 piani, dal più recente." is honest about the cap; good.
- `Riprova` and the error title "I piani non si sono caricati" are fine; the 401 path keeps skeleton rows while the browser goes to login: correct.
- "Il viaggio" / "Quando" / "Chi viaggia" / "Budget e preferenze": consistent sentence case, no em dash, no amber, no title case. "Date" as a legend under a section called "Quando" is a small redundancy.
- "Cinque agenti" followed by four named areas: the coordinator is the fifth and is never named; harmless, but "cinque agenti" plus a list of four may prompt a second look.
- The `Nuovo piano` button appears twice on an empty home (header primary, plus "Parti da questo esempio" secondary): hierarchy is right, the primary leads.
- On desktop dark the read-back card, rows and inputs hold the same hierarchy as light. No contrast failures seen.
- The Next.js dev indicator overlaps the bottom-left of the phone viewport; dev only.
- The date inputs show the browser's locale mask (dd/mm/yyyy here); nothing to fix.
- DESIGN.md says header "never taller than 72 px": measured 64 px, fine.

## Rule check (CLAUDE.md UI rules)

| Rule | Result |
|---|---|
| Two dates "Prenota entro" / "Quando" | Not applicable on these screens (no bookings). The intro mentions "la data entro cui farla" in prose, correct. |
| Amber only for due-soon bookings | Pass: no amber on either screen. |
| Costs in dollars, two decimals, Italian ("0,41 $") | Pass for the list; the cost estimate line is dollars but reads confusingly (P2). |
| Sentence case, action verbs, no em dash | Pass. Buttons: "Nuovo piano", "Parti da questo esempio", "Pianifica il viaggio", "Riprova". |
| Empty state is an invitation | Pass. |
| `BRAND_NAME` only | Pass (title "I tuoi piani · Atlas"). |
| rel="noopener noreferrer" on booking links | Not applicable (no booking links here). |
| `aria-live` only for agent state changes | Mostly pass; `role="alert"` on the submit failure notice is a P3 to confirm. |
| Reduced motion declared | Not exercised here beyond the busy button and skeleton, which come from primitives that declare it. |
| Keyboard and focus | Pass, one P1 on Enter behaviour. |
| 393 px | No horizontal scroll, readable, one P2 on target sizes. |

## Questions to consider

- What if the home page opened on the one plan that matters (the running one, or the last finished one) and the other nineteen were a quiet list underneath?
- What if the form remembered who you are (origin, party) the way TripTracker remembers a trip, so a repeat plan is three taps?
- Does the submit button need the cost line at all, or is "Il planner costa circa 2–4 $ per piano" better as the button's own caption inside the read-back card?
- Could the empty home use the line vocabulary on the invitation (a three-station line: Richiesta, Ricerca, Prenotazione) to show the whole product in one glance, instead of a sentence?

## Recommended order

1. `/impeccable harden`: Enter-to-next (P1), draft in sessionStorage, role="alert" decision.
2. `/impeccable adapt`: 44 px phone targets (submit, segments, wordmark, Riprova, back link).
3. `/impeccable clarify`: the cost line, the budget hint, the summary's stutter and placement.
4. `/impeccable layout`: desktop form pairs and the fold, running-plan row on the home list.
5. `/impeccable onboard`: remembered origin and party.
6. `/impeccable distill` then `/impeccable polish`: invitation duplication, row timestamps and long list, pristine read-back card, placeholder contrast check.

Re-run `/impeccable critique` after the P1 and the P2s: realistic target 33-34/40, which clears the 32/40 gate.
