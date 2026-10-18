---
target: "the waitlist surfaces: the landing closing form, the /login refusal and listed state, /admin/waitlist"
total_score: 99
max_score: 112
na_heuristics: 7,10 (landing only)
p0_count: 0
p1_count: 0
target_identity: "file:/home/user/trip-planner/web/components/waitlist/waitlist-form.tsx"
target_fingerprint: "sha256:de3a705fee1e42f10706f97414a0f22c858e275804a4aa8306c95ce418856275"
target_path: /home/user/trip-planner/web/components/waitlist/waitlist-form.tsx
timestamp: 2026-10-17T19-42-06Z
slug: components-waitlist-waitlist-form-tsx
---
# The waitlist (landing closing, `/login` refusal, `/admin/waitlist`): critique, two rounds (2026-10-17)

Three surfaces in one run. The landing's closing is Persuade (heuristics 7 and 10 n/a, out of
32; the gate is 80 %, i.e. 26/32). The login's refusal and the admin page are Operate (out of 40;
gate 32/40). Combined maximum 112.

## Round 1: 82/112 (73 %; landing 24/32, login 32/40, admin 26/40; P0 0, P1 1, P2 4, P3 4)

Method: dual-agent (A: design review in the browser at 393 and 1440, both themes · B: static
detector, live detector injected on the three pages, focus, targets, overflow and contrast
measurements). B: detector clean (3 pre-existing `nested-cards` in "Come funziona", out of scope);
every target ≥ 44 px at 393; no horizontal scroll 320–1440; lowest text contrast 6.47:1 dark,
5.66:1 light; focus dropped to `<body>` after a server-side field error on the landing form.

Landing closing, 24/32:

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 3 | Join and outcome panel focused; a rejected address leaves focus on `<body>`; the lede still says "Lascia il tuo indirizzo" after the join |
| 2 | Real world | 4 | "Atlas è su invito.", "Mettimi in lista", "Il prossimo viaggio": plain, verb-first |
| 3 | Control | 2 | No "Cambia indirizzo" after "Sei in lista": a typo is final |
| 4 | Consistency | 3 | `check-circle` on "Sei già in lista" (nothing was done); hint "Accedi" → `/plans`, panel "Accedi" → `/login` |
| 5 | Error prevention | 3 | `type=email`, `inputMode`, `maxLength`; a blank submit round-trips to the server |
| 6 | Recognition | 4 | Labels above, the note's hint says why, the consent line says what the address is for |
| 7 | Flexibility | n/a | Persuade |
| 8 | Aesthetic | 3 | A 96 px box for "due righe"; at 1440 a 416 px form under a 1160 px drawing |
| 9 | Recovery | 2 | Focus dropped on both field errors; no exit from a mistyped success |
| 10 | Help | n/a | Persuade |

Login refusal and listed state, 32/40:

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 3 | "Invio…", the listed panel focused; the h1 stays "Accedi" over "Sei in lista" |
| 2 | Real world | 3 | "Cambia indirizzo" under "Sei in lista" reads as editing the listed address |
| 3 | Control | 3 | The way back keeps the address; the Google refusal offers no button |
| 4 | Consistency | 3 | At the refusal the primary is still "Inviami il link", the action that just failed |
| 5 | Error prevention | 4 | Address kept; a second join answers "Sei già in lista"; an invited address gets the link |
| 6 | Recognition | 4 | The error names the next step and the button sits 16 px below it |
| 7 | Flexibility | 3 | Enter sends, desktop autofocus |
| 8 | Aesthetic | 3 | Two full-width stacked pills at 393 |
| 9 | Recovery | 3 | Refused → one tap; the Google refusal dead-ends |
| 10 | Help | 3 | "Quello invitato, o con cui sei già entrato." plus the refusal sentence |

Admin page and header stations, 26/40:

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 2 | Row "Invita": the row vanishes, focus → `<body>`, no sentence; the "email non partita" warning unreachable |
| 2 | Real world | 3 | Heading "Aggiungi un indirizzo" vs button "Invita" + plus glyph, which sends an email at once |
| 3 | Control | 2 | No undo, no way to remove a request (typos live forever) |
| 4 | Consistency | 2 | 16 ink-filled primaries on one view |
| 5 | Error prevention | 2 | The add form clears both fields before the server answers |
| 6 | Recognition | 4 | Who, note, source, date; counts in headings |
| 7 | Flexibility | 3 | Ten invitations = ten taps with the list shifting; acceptable at this scale |
| 8 | Aesthetic | 3 | At 1440 the action is 960 px from the address |
| 9 | Recovery | 2 | Errors are alerts; `signed_out` says "accedi di nuovo" with no link |
| 10 | Help | 3 | Intro says what an invitation does; the note's hint says who sees it |

Fixed after round 1 (commit e5cc36b, verified by the browser check and vitest):

- [P1] Focus and announcements: the refused field takes focus once the server answers (landing
  and admin add form); the news panel takes focus after a join; the admin page has one status
  region, there from the first render, that says what a row action did and takes focus after it
  (in effects, after the commit: the region is `display: none` while empty and the fields are
  disabled while the action runs).
- [P2] Login: while an address stands refused, "Mettimi in lista" is the primary and "Inviami il
  link" steps back; typing another address undoes the swap.
- [P2] Admin add form: fields cleared only on success; "Invita un indirizzo" with an "Invita"
  button, no glyph.
- [P2] The way back: "Cambia indirizzo" on every landing outcome (a new form, address kept and
  selected); "Togli" removes a pending request (`removeRequest`, `removeRequestAction`).
- [P2] One primary per view: the rows' "Invita" secondary, "Togli" quiet; the list capped at
  40rem so the buttons sit beside their row.
- [P3] The listed panel carries "Quando ti scriviamo, torna qui con lo stesso indirizzo."; the
  Google refusal notice says what to do; the note boxes are two rows tall (`TextArea` reads
  `rows`); `info` icon on "Sei già in lista"; the landing's sign-in hint lives inside the form,
  so a panel never shows two "Accedi".
- Deferred: the two-column closing at desktop; the lede above the outcome; the h1 "Accedi" over
  the listed panel.

## Round 2 (confirmation): 99/112 (88 %; landing 28/32, login 37/40, admin 34/40; P0 0, P1 0, P2 2, P3 9)

Method: the same two agents on commit e5cc36b. B: static detector 0 findings on the six files;
live detector 0 on the three surfaces in every state (the landing's 3 `nested-cards` are "Come
funziona", out of scope; the light theme adds a page-level `cream-palette` and a `gray-on-color`
inside "Come funziona", theme-level, out of scope); all 11 focus steps land where expected; every
target ≥ 44 px under a coarse pointer at 393 (the `pointer-coarse:` targets are 40 px under a fine
one); no horizontal scroll at 360, 393 and 1440, but the admin header with three stations overflows
at 320 (scrollWidth 350); row buttons 24 px from their text at 1440 (round 1: ~960); lowest
contrasts: field error 5.75 dark / 5.70 light, ink-2 on ground 6.47 / 5.66, all AA; one primary per
view in every state; emoji local parts pass the shape check and are stored and invitable (reported,
not judged).

Landing closing, 28/32:

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 4 | "Invio…", aria-busy, fields disabled; the panel takes focus, its sentence is role=status |
| 2 | Real world | 3 | The form's "Accedi" went to `/plans`, whose 401 lede says "per tornare dove eri" |
| 3 | Control | 3 | "Cambia indirizzo" on every outcome, address kept and selected; the note was dropped |
| 4 | Consistency | 3 | Two "Accedi" led to different places; the field error stayed while typing |
| 5 | Error prevention | 4 | `noValidate` + server shape check, `type=email`, note capped at 280 |
| 6 | Recognition | 4 | Labels, hint, consent line, the address repeated in bold |
| 7 | Flexibility | n/a | Persuade |
| 8 | Aesthetic | 3 | Desktop still single-column (deferred) |
| 9 | Recovery | 4 | Precise message, typing kept, focus on the field, aria-invalid + describedby |
| 10 | Help | n/a | Persuade |

Login refusal and listed state, 37/40:

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 4 | "Invio il link…" / "Invio…"; the listed panel takes focus |
| 2 | Real world | 4 | The error names both ways in |
| 3 | Control | 4 | Typing another address undoes the swap; the way back keeps, selects and focuses the address |
| 4 | Consistency | 3 | The primary "Mettimi in lista" had no arrow and came second in reading and tab order |
| 5 | Error prevention | 4 | Client shape check first; the field's hint |
| 6 | Recognition | 3 | The panel sits under the h1 "Accedi" (left as is); the hint softens it |
| 7 | Flexibility | 3 | Enter after a refusal re-sent the refused link request |
| 8 | Aesthetic | 4 | One field, one lede, one error; 44 px on the phone, side by side from 640 px |
| 9 | Recovery | 4 | Refusal as a field error with focus and the way in as the filled button |
| 10 | Help | 4 | The lede says what the link is; every notice names the next step |

Admin page, 34/40:

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 3 | Every row action focused a status line at the top: the viewport jumped (393: 1697 → 117) |
| 2 | Real world | 4 | "In attesa"/"Invitati", the sources, "invitato il … da … · email inviata · ha un account" |
| 3 | Control | 3 | "Togli" removed at once, no undo |
| 4 | Consistency | 3 | Two status regions (add form, page) could show at once, one stale |
| 5 | Error prevention | 3 | "Togli" with no confirmation, 8 px from "Invita" on the phone |
| 6 | Recognition | 4 | Note, source, date; counts; every button named with its address |
| 7 | Flexibility | 3 | Scrolling back after each action; no filter as the list grows |
| 8 | Aesthetic | 4 | List capped at 640 px, buttons 24 px from their text; note box two rows |
| 9 | Recovery | 3 | A failed "Togli" would have said "invitare" (shared wording) |
| 10 | Help | 4 | One-line description, the note's hint, empty states as invitations |

Fixed after the round (commit 98a4fa8; verified by vitest and the browser check, not re-scored:
one confirmation round is the cap):

- [P2] The admin's focus stays on the list: after a row action it moves to the next pending row's
  button (once the transition ends, since the buttons are disabled until then) and to the status
  region only when no request is left or the action failed; the region is sticky at the top of the
  viewport and `aria-live` reads it; it is the one region for the whole view, the add form's
  answers included (P3: no stale second line).
- [P2] "Togli" asks once, inline ("Togliere la richiesta?", "Sì, togli", "Annulla"), the question
  takes focus and "Annulla" gives it back.
- [P3] A failed removal has its own wording; Enter on a refused address joins the list, as the
  primary says; the primary comes first with its arrow; the landing's hint goes to the login (which
  forwards a live session to the plans); "Cambia indirizzo" carries the note back; a field's error
  clears as soon as the field is edited; the panels and the status region show a focus ring to
  keyboard users.
- [B] At 320 px the stations strip scrolls sideways instead of widening the page, and the current
  station is brought into view, again once the admin stations arrive.
- Deferred: prefill the login after "Hai già un invito" (the address would travel in storage or a
  query string); the desktop two-column closing; the h1 "Accedi" over the listed panel; whether
  the shape check should refuse non-ASCII local parts (the admin can remove such rows).

## Gate

99/112 (88 %) at the confirmation round: landing 28/32 (88 %), login 37/40 (93 %), admin 34/40
(85 %), each above the 80 % gate (26/32, 32/40), with no P0 or P1. The two P2s and the small P3s
the round found were fixed after it and verified, not re-scored.

## Questions for Michele

- ~~The landing's "Hai già un account" tells anyone whether an address has an Atlas account (the
  login's refusal already does, one step later). Keep it, or fold it into "Hai già un invito" so
  the form never distinguishes an account from an invitation?~~ **Decided 2026-10-18: "uguale per
  tutti".** No answer distinguishes an address any more. The join always answers "Ricevuto: Se
  … è già abilitato puoi accedere subito; altrimenti ti scriviamo lì quando c'è posto." The
  magic-link request answers as sent for every address (no email for one that may not sign in),
  and the sent state says "Se … è abilitato, ti arriva un link." with "Non arriva niente? Mettiti
  in lista" and the join beside it. The field's invite refusal is gone; Google's refusal (after
  OAuth, the account is the caller's own) keeps its notice. Timing too (2026-10-18): the email
  leaves after the response (`after()`), so both answers take the same time.
- The note could seed the first request ("Il prossimo viaggio"): keep it for triage only, or
  prefill the request form from it after sign-up?
- One invitation email for everyone: a person who asked ("ti avevamo in lista") and a cold invite
  ("Michele ti ha invitato") read the same text today.
