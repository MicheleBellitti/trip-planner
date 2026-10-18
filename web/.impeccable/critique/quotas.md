---
target: "the economics surfaces: the usage line, the request form refusals, the paused panel at its cap"
total_score: 98
max_score: 120
na_heuristics: 
p0_count: 0
p1_count: 0
target_identity: "file:/home/user/trip-planner/web/components/home/month-usage.tsx"
target_fingerprint: "sha256:5639b5f32f6be2c31fdf7271de97979b59f076bc12019b4809beb5c1cd0cfe30"
target_path: /home/user/trip-planner/web/components/home/month-usage.tsx
timestamp: 2026-10-18T01-36-13Z
slug: components-home-month-usage-tsx
---
# The economics' surfaces (the usage line, the request form's refusals, the paused panel at its cap): critique, two rounds (2026-10-18)

Three Operate surfaces (out of 40 each; gate 32/40, no open P0 or P1), combined maximum 120:
the month's usage line (`components/home/month-usage.tsx`, on `/plans` and under the request
form's button), the request form's refusals (`components/request/request-form.tsx`,
`components/request/failure.ts`: the quota, the ceiling, the planner full, a burst) and the paused
panel at the cap of "Continua" (`components/states/budget-paused.tsx`).

## Round 1: 78/120 (65 %; usage line 26/40, form refusals 27/40, paused panel 25/40; P0 0, P1 4, P2 7, P3 4)

Method: dual-agent against the local servers (backend in DEMO_MODE with 2 plans a month, 3
running, 1 "Continua"). A: design review in the browser at 393 and 1440 (768 and 1024 for the
form), both themes, 90 screenshots, the `/me` requests counted across pages. B: static detector on
the five files (clean), live detector injected on every page, layout shift measured with `/me`
delayed 2.5 s, targets, overflow 320–1440, contrast, focus and announcements, the API's answers.
B: contrast AA or better everywhere (summary ink-2 5.66:1 light); after a refused submit the
focus is on the enabled button with the request kept; the notice is `role=alert`; no overflow in
scope (the `/new` dates grid at 320 is pre-existing); 0 "Continua" buttons when capped, 1 below.

Findings:

- **P1 Stale month.** `lib/me.ts` cached GET /me in a module promise never reset: one request
  across three pages; after creating a plan the line still said "0 piani su 2" until a hard reload.
- **P1 The capped panel named two actions and offered none** ("Puoi interromperlo, o creare un
  nuovo piano." with no button), and promised "gli agenti riprendono da lì" where they cannot.
- **P1 A used-up user was told only after filling the form and pressing**, though GET /me had
  already told the page; the only hint was the line under the button at y≈1650 on the phone.
- **P1 Layout shift when the line lands**: +28 px (one line) to +68 px (three lines, friend at 393)
  on `/plans` 1–2 s after paint; the form's sticky box grew +68/+88 px.
- **P2** "Budget della sessione esaurito" beside a meter at 61 % ("0,61 $ spesi · limite 1,00 $").
- **P2** The reserved budget shown as used ("2,00 $ su 15,00 $" while two plans run), with no noun
  or verb, then the counter goes backwards when they finish.
- **P2** One fact in three wordings; the "used up" sentence switched colour mid-line at 393 (a lone
  "Hai" at the end of line 1) and made a 3-line block under the h1, a 4-line centred ragged paragraph
  in the 278 px card.
- **P2** Error red for things that did not fail (the quota, the planner full, a burst): not
  failures by DESIGN.md's own definition.
- **P2** The card stacked refusal → button → cost pitch → usage line repeating the refusal.
- **P2** "Proroga" vocabulary, new to the user (the button says "2 $ in più"); three names for one
  state ("Budget raggiunto", "Budget della sessione esaurito", "Fermo: budget della sessione esaurito").
- **P2** The form's line was 14.5 px under a 13.5 px estimate: the caller's `text-meta` lost to the
  component's `text-small`.
- **P3** The busy title repeated its body; "Troppe richieste" leans on the user; "Continua con 2 $
  in più" was 40 px tall at 393; after a final refusal the button was described only by the
  estimate; the refusal `Notice` inside the sticky box is flagged `nested-cards` at 1440.

## Fixes (one batch)

- `lib/me.ts`: a small external store. Every page asks again when it mounts, the readers of one
  page share the request in flight, the last answer is drawn at once (`useSyncExternalStore` with a
  null server snapshot, so a chunk that hydrates after the header's request answered still matches
  the server's HTML: the first attempt with a `useState` initialiser produced exactly that
  mismatch on the streamed form), and every mounted reader gets the fresh answer.
- The usage line: "Questo mese: 2 piani su 2 · 2,00 $ impegnati su 15,00 $" (the word the refusal
  and the backend use: the committed figure, reserved budgets included), a calendar glyph like the
  estimate's wallet, the "Il prossimo piano dal 1° novembre." sentence on its own line in ink, a
  `size` prop (`meta` on the form), and one empty line of its size reserved until the answer lands
  (nothing reserved once the tab remembers an admin).
- The form: when GET /me says the month is used up, the same words as the refusal stand above the
  button (phone: at the top of the form, under the lede) as a warning `Notice` with no role, in the
  button's `aria-describedby`; the form stays editable; the estimate and the line make room for it;
  a refusal replaces it (`role=alert`, `aria-describedby` follows). Refusals by rule are
  `tone="warning"`, failures `error` (DESIGN.md, Notice, extended). Titles: "Un momento" for a
  burst; the planner-full body in the form's own words so it does not repeat its title.
- The paused panel: "Budget della sessione raggiunto" (the header's and the lanes' word; the
  backend's station title and its fixture regenerated); "La sessione ha speso 0,61 $: il passo
  successivo non stava nel budget di 1,00 $" (or "il budget di X è finito" once the cost reached
  it); at the cap "Questo piano ha già avuto i suoi 2 $ in più" and a `LinkButton` "Crea un nuovo
  piano", the interrupt pointed to in the header; "riprendono da lì" only when they can; 44 px
  actions at the phone; the quota's and the cap's refusals as warnings. The backend's 409 message
  says "tutti gli aumenti di budget previsti (1 su 1)" instead of "proroghe".

## Confirmation round: 98/120 (82 %; usage line 33/40, form refusals 33/40, paused panel 32/40; P0 0, P1 0)

Browser at 393 and 1440, both themes, plus the end-to-end script (ALL OK, now also failing on
hydration errors): the standing notice before any press, the refusal replacing it, the described-by
chain, the reserved line, the capped panel's action and words; the admin's second load drops the
reserved line on hydration.

Accepted or deferred: the `nested-cards` flag at 1440 (a `Notice` inside the sticky card is its
documented role, as in the panel's footer); the committed figure falls when a plan ends under
budget (said with "impegnati"; a split into spent and reserved is the user's call, PR decision 2);
"Continua" spends 2 $ on one click (the spec's one primary action); the `/new` dates grid at 320
(pre-existing); two `<main>` landmarks for 1–2 s during Next's route change; the API's message says
"il mese prossimo" where the form says the day.
