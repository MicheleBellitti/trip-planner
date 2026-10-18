---
target: "/login (sign-in): the form, the sent state, the error and unconfigured states"
slug: login
round: 3
total_score: 32
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
p2_count: 2
p3_count: 4
date: 2026-10-17
---
Method: dual-agent (A: design review sub-agent · B: detector and browser evidence sub-agent)

# Critique, round 3: sign-in `/login`

Surface: the same files after round 2's fixes (the lockup no longer a link, the resend focused and
announced, one verb, the lede with the reason, the refused error structured, `?error=` scrubbed, the
placeholder's shapes). Viewed on the local dev server at 393x851 (touch context, dark and light) and
1440x900, every state, with 429 and 500 produced by intercepting the sign-in request, and the
loading placeholder held open through a streaming proxy.

Checks run: `impeccable detect --json app/login components/auth components/ui/field.tsx` returned
`[]` (exit 0); `detect.js` live: "No anti-patterns found" at both widths; a sweep of every state in
both themes found zero amber, zero box-shadow, zero filter, zero gradient. Measured: input 44 px,
primary 44 px at 393 and 40 x 148 at 1440 (the placeholder's 9.25 rem), toggle 44 px under a coarse
pointer, lede and hint 6.47:1, label 13.05:1; the placeholder's rows land within 0.2 px of the
final rows at both widths. Focus trace at 393 (measured): shape error → input with `aria-invalid`
and a description that includes the error; refused → input, the first sentence in `<strong>`; sent
→ the panel (contains the heading), Tab → "Inviane un altro" → "Cambia indirizzo", both 44 px, the
first's icon on the text column; resend → the panel again, the `aria-live` line says "un altro
link"; "Cambia indirizzo" → the input with the address kept; **a failed resend → `<body>`**. The
desktop arrival focuses the field with a fine pointer; the phone and any page with a notice do not.
`?error=INVALID_TOKEN` shows the notice and leaves the address bar; `returnTo` survives.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Busy label, turning glyph, the address named, "un altro link" on a resend; the focused panel shows no ring (a region, by design). |
| 2 | Match System / Real World | 3 | Plain Italian throughout; "Quello invitato" is elliptical for a first-timer. |
| 3 | User Control and Freedom | 3 | "Cambia indirizzo" keeps the address, `?error=` cannot resurrect; an expired link landed without `returnTo` (fixed below). |
| 4 | Consistency and Standards | 3 | Same primitives and header as `/new`, one verb; `check-circle` meant "finito" on a half-done step (fixed below). |
| 5 | Error Prevention | 4 | Shape check, no browser bubble, email keyboard and autofill, controls locked in flight, the address echoed, the open redirect closed. |
| 6 | Recognition Rather Than Recall | 3 | Address and lifetime stay on screen; after an expired link the lede forgot the way back (fixed below). |
| 7 | Flexibility and Efficiency | 3 | Desktop autofocus, Enter sends, Google when configured; nothing remembers the last address on the 401 path. |
| 8 | Aesthetic and Minimalist Design | 4 | Two sentences, one field, one button, a flat panel; the lede's orphaned last line (fixed below). |
| 9 | Error Recovery | 3 | Refused, 429 and expired each say what happened and what to do; a failed resend dropped focus (fixed below). |
| 10 | Help and Documentation | 3 | The hint and the refusal route to the inviter; nothing says what Atlas is (the landing's job). |
| **Total** | | **32/40** | **Good** |

## Design Specificity Verdict

**LLM assessment.** Identifiably Atlas, by subtraction: the mark alone in a hairline header,
"Accedi" in Semi Condensed, one rule-strong field, one cream (ink in light) pill, paper grain on a
flat ground, Phosphor bold glyphs, no card, no shadow, no illustration, no divider unless Google is
configured. Not the stock centred-card login. The only borrowed convention was the sent panel's
check glyph, now the sign-in glyph the session-expired state already uses.

**Deterministic scan.** 0 findings; live `detect.js` clean; the manual sweep found nothing the
No AI Chrome Rule or the Amber rule forbids.

## What's Working

- **The refused error's structure**: what happened in semibold, then what to do, on the field with
  the red edge, the cross, `aria-invalid` and a described-by chain that includes the hint; focus
  lands in the field with the value kept.
- **Target discipline at 393**: toggle 44, field 44, primary 44 (40 x 148 from 640, the
  placeholder's width), both quiet actions 44 tall with the first icon on the text column.
- **The `?error=` lifecycle**: shown once, scrubbed with `replaceState`, gone on reload, `returnTo`
  preserved; and the field is deliberately not focused over a notice.

## Priority Issues

- **[P2] An expired link lost the way back.** `errorCallbackURL` was the bare login path, so a
  spent link landed without `returnTo`: the lede turned generic and the next link went to the plans
  list. *Fix (done):* the error callback is `/login?returnTo=<the laundered path>` whenever one is
  known; Better Auth adds `error` with `searchParams.set`, so the query survives. *Command:*
  /impeccable harden.
- **[P2] Focus lost after a failed resend.** A 429 from the sent state left `document.activeElement`
  on `<body>`: the busy button disables and nothing refocused. *Fix (done):* a notice in the sent
  state refocuses the panel, where the alert is. *Command:* /impeccable harden.
- **[P3] The placeholder was drawn for the two-line lede.** With `returnTo` the lede ran to three
  lines at 393 and the form jumped 20 px on the main path. *Fix (done):* the `returnTo` lede is
  "Accedi per tornare dove eri: ti inviamo un link." plus the validity sentence, two lines at
  361 px; `text-pretty` keeps the last line from orphaning. *Command:* /impeccable polish.
- **[P3] The generic failure misnamed the action.** *Fix (done):* "Non è stato possibile inviare il
  link. Riprova." on the magic-link path; the access wording stays for Google. *Command:*
  /impeccable clarify.
- **[P3] `check-circle` on "Controlla la posta".** *Fix (done):* the `sign-in` glyph, as on the
  session-expired state. *Command:* /impeccable clarify.
- **[P3] "Cambia indirizzo" put the caret at the end.** *Fix (done):* the kept address is selected,
  so typing replaces it. *Command:* /impeccable polish.

## Persona Red Flags

**A first-timer invited by a friend:** the hint assumes they know the invitation is tied to an
address; the refusal routes them correctly; nothing says what Atlas is (the landing's job).

**Michele, iPhone, one-handed, after a 401:** field and button are one thumb motion; the keyboard
does not cover the lede because nothing autofocuses on the phone; the real flag is the stale tab
when Mail opens the link in a new one (see the questions).

**Keyboard-only (measured):** desktop arrival on the field; after submitting, the panel, then the
two actions; after an error, the field; after "Cambia indirizzo", the field with the address kept
and now selected; after a resend, the panel; after a failed resend, now the panel too.

## Minor Observations

- The server-rendered alert on arrival with `?error=` is read in order rather than announced; h1 →
  lede → notice is a fine order.
- The light capture showed the toggle's hover wash persisting under touch emulation; worth a glance
  on a real iPhone.
- "Questo indirizzo non è abilitato" confirms to a stranger which addresses are on the allowlist: a
  fair trade for an invite-only door, to revisit when the landing and `/demo` invite strangers.

## Questions to Consider

- When the link opens in another tab or Mail, this tab says "Controlla la posta" forever. Should the
  sent panel notice the session (a `getSession` check on `visibilitychange`) and go to `returnTo` on
  its own, so the 401 heals in the tab where it happened?
- Should the 401 handler pass why (`?reason=expired`), and should the field remember the last
  address on the 401 path? Both belong with the front door.
