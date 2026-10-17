---
target: "/login (sign-in): the form, the sent state, the error and unconfigured states"
slug: login
round: 1
total_score: 25
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 3
p2_count: 2
p3_count: 1
date: 2026-10-17
---
Method: dual-agent (A: design review sub-agent · B: detector and browser evidence sub-agent)

# Critique, round 1: sign-in `/login`

Surface: `web/app/login/page.tsx`, `web/components/auth/login-form.tsx`, `web/components/auth/auth-header.tsx`
(the form, the "Controlla la posta" state, the error alert, the unconfigured state). Viewed on the local dev server
against a local Postgres (Google not configured, so its button was not rendered) at 393x851 and 1440x900, dark and
light. Judged against `web/DESIGN.md`, `web/PRODUCT.md` and the CLAUDE.md UI rules. Mode: Operate (a task screen
reached after a 401 or from an invitation).

Checks run: `impeccable detect --json app/login components/auth` returned `[]` (exit 0). `detect.js` injected live in
both viewports: "No anti-patterns found". Console during load: 0 errors, 0 warnings. Measured: `<html lang="it">`, h1
Barlow Semi Condensed 24/30 px at 13.05:1, hint and note 13.5 px ink-2 at 6.47:1, email input 44 px with 16 px text,
primary button 40 px at both widths, theme toggle 40 px with a mouse and 44 px under a coarse pointer, wordmark link
44 px, focus ring 2 px cream at 3 px offset on every stop, Tab order lockup → toggle → input → button.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Busy label and `aria-busy` are right; nothing says why you landed here after a 401 or that you will go back to the plan. |
| 2 | Match System / Real World | 3 | Plain Italian; "aprilo da questo dispositivo" and "web/.env.example" are the system talking. |
| 3 | User Control and Freedom | 2 | No resend, no exit: the lockup is the only link and it loops `/` → 401 → `/login` until the landing ships. |
| 4 | Consistency and Standards | 2 | Primary is 40 px on the phone against the request form's 44; the browser's validation bubble replaces the house `Field` error; the error Notice has a title and no body. |
| 5 | Error Prevention | 3 | `type=email`, `inputMode`, `autoComplete`, the address echoed in bold in the sent state; validation left to the browser. |
| 6 | Recognition Rather Than Recall | 2 | A first-timer must recall which address was invited; `returnTo` is invisible. |
| 7 | Flexibility and Efficiency | 3 | Enter submits, autocomplete works, the address is kept on the way back; no resend. |
| 8 | Aesthetic and Minimalist Design | 3 | Clean, but three grey prose blocks for one field, and "su invito" twice in the refused state. |
| 9 | Error Recovery | 2 | A refused address is a dead end; the input never gets `aria-invalid`; focus lands on `<body>` after the error and after the sent swap (measured). |
| 10 | Help and Documentation | 2 | No spam or "non è arrivato?" guidance, no one to ask for the uninvited. |
| **Total** | | **25/40** | **Fair** |

## Design Specificity Verdict

**LLM assessment.** Atlas at the edges, generic in the middle. The "A di linee" mark, "Accedi" in Barlow Semi
Condensed, the paper grain, the cream-on-ink pill and the 1.5 px rule-strong field are on token; there is no amber,
no glow, no gradient, no glass (the No AI Chrome Rule holds). But a centred 26 rem column of label, hint, input,
full-width button, divider, Google and fine print is the magic-link form of every SaaS, and nothing from the house
vocabulary of lines and stations appears. The most Atlas-specific moment is the sent card, which borrows the
StatePanel look.

**Deterministic scan.** 0 findings in `app/login` and `components/auth`; `detect.js` live: "No anti-patterns found"
at both viewports. The detector and the review agree on the token discipline; everything below is what a detector
cannot see (orientation, recovery paths, focus).

**Visual overlays.** No overlay nodes were rendered because nothing was detected; the console carried the verdict.

## Overall Impression

A correct, well-wired form that does not yet talk to the person who lands on it. The safety work (open-redirect
guard, 403/429/generic separation, graceful database failure, signed-in redirect) is the strongest part and is
invisible. The single biggest opportunity is to make the page explain itself in one place and to give the wait a
recovery path.

## What's Working

- **Copy discipline.** Italian sentence case everywhere, verbs on every button ("Inviami il link", "Continua con
  Google", "Usa un altro indirizzo"), no passwords, the address echoed in bold so a typo is caught before the wait.
- **Primitive fidelity.** `Field` wires `aria-describedby`; the input is 44 px with 16 px text (no iOS zoom); the
  focus ring is visible on every stop; `Notice role="alert"` answers only the user's own action; the toggle grows to
  44 px under a finger.
- **States and safety.** `safeReturnTo`, `robots: noindex`, the unconfigured state, the busy Google button held until
  the browser leaves.

## Priority Issues

- **[P1] The page does not orient, and its three prose blocks overlap.** The hint "Ti mandiamo un link per entrare,
  senza password." is the real lede; the lede is a tagline; the footer pre-states the error. *Why it matters:* an
  Operate screen reached after an interruption must say what happened and what comes next, in one place. *Fix:* the
  lede says what the link is and how long it lasts, adds "Poi torni dove eri." when `returnTo` is set; the field hint
  names which address to use; the invite sentence moves into the refused error. *Command:* /impeccable clarify.
- **[P1] The sent state has no recovery path.** No spam guidance, no resend, no "non è arrivato?"; the only action is
  a 32 px quiet button whose label hides that it also resends. *Why:* a one-use five-minute link with a slow mail
  server is the most likely failure, and the screen is silent about it. *Fix:* "Non lo vedi? Guarda nella posta
  indesiderata.", a "Mandane un altro" action that re-submits the kept address (and respects the 429 copy), a
  "Cambia indirizzo" action, both 44 px on the phone. *Command:* /impeccable harden.
- **[P1] Focus is dropped on every transition.** After submit the button disables, so focus is gone; the sent panel
  replaces the form and the error Notice appears with `document.activeElement === body` (measured by B at both
  widths); the input is never `aria-invalid` for an address error. *Why:* a keyboard or screen-reader user loses their
  place twice. *Fix:* focus the sent panel (`tabIndex={-1}`), focus the input on an address error and pass address
  errors through `Field error` (red edge, cross, `aria-invalid`), keeping the Notice for non-field errors (429, the
  callback codes). *Command:* /impeccable harden.
- **[P2] The primary is the page's smallest tap on the phone, and validation leaves the design system.** Submit is
  40 px under a 44 px field (DESIGN.md's Buttons exception exists for this and the request form applies it); an
  invalid address gets the browser's English bubble. *Fix:* `min-h-11 sm:min-h-10`; `noValidate` with a trimmed
  shape check surfacing `Field error="Scrivi un indirizzo email completo."`. *Command:* /impeccable polish.
- **[P2] No way out, no one to ask.** The lockup links to `/`, which is the plans list until the landing ships, so it
  bounces back to `/login`; a refused visitor sees "su invito" twice and no contact. *Fix now:* the refused error
  gets a body ("usa l'indirizzo a cui è arrivato l'invito, o chiedi a chi ti ha invitato di abilitare questo").
  *Fix later:* the front-door PR gives `/` to the public landing, which resolves the loop. *Command:* /impeccable
  onboard.
- **[P3] Polish.** `FormPlaceholder` draws a 160 px pill where the real button is full width; the sent card
  re-implements `StatePanel` by class; "Vado su Google…" is chattier than the house voice; "web/.env.example" is
  developer copy on a user screen; the five-minute sentence is phrased two ways. *Command:* /impeccable polish.

## Persona Red Flags

**A first-timer invited by a friend:** the field does not say which address to use; the wrong one lands on a
two-line refusal with no contact; the lockup loops back; "aprilo da questo dispositivo" reads as a restriction if
their mail is on another device; nothing about spam.

**Michele, iPhone, one-handed, mid-plan:** the 40 px button sits under a 44 px field; the lede does not confirm he
will return to the plan; after sending he leaves for Mail with no resend if it is slow; back from the sent state the
32 px quiet button is the only target. The `safeReturnTo` round trip itself is right.

**Keyboard-only:** focus to `<body>` after submit, after the sent swap and after the error (measured); no
`aria-invalid`; Tab order otherwise sound, ring visible, Enter submits.

## Minor Observations

- The error title wraps to two semibold lines on the phone: that is what the Notice title/body split is for.
- `noValidate={false}` is noise. "Email" could be "Indirizzo email".
- Theme toggle is 40 px for mouse users (44 px under a coarse pointer): by design, as on every other screen.
- The Vercel preview build of the branch compiled this route; the sandbox could not fetch Google Fonts.

## Questions to Consider

- Should the 401 handler pass a reason (`?reason=expired`) so the lede can say "La sessione è scaduta" and the
  button "Rientra nel piano"? The page knows `returnTo`; it could know why.
- Atlas draws every process as a line. Would a quiet three-station strip (Indirizzo → Posta → Piano) above the form
  carry the identity better than any ornament, and make the wait legible?
- With Google enabled, is one tap the faster primary for a phone user, and the magic link the secondary?
