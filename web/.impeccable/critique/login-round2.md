---
target: "/login (sign-in): the form, the sent state, the error and unconfigured states"
slug: login
round: 2
total_score: 29
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
p2_count: 2
p3_count: 7
date: 2026-10-17
---
Method: dual-agent (A: design review sub-agent · B: detector and browser evidence sub-agent)

# Critique, round 2: sign-in `/login`

Surface: the same files as round 1 after its fixes (one lede, address errors on the field, the sent
state as a StatePanel with "Mandane un altro" and "Cambia indirizzo", focus on every transition, the
44 px primary on the phone). Viewed on the local dev server at 393x851 and 1440x900, dark and light,
plus the shape error, the refused address, the expired-link notice (`?error=INVALID_TOKEN`), the
`returnTo` lede, the resend and the loading placeholder (held open through a streaming proxy).

Checks run: `impeccable detect --json app/login components/auth components/ui/field.tsx` returned
`[]` (exit 0); `detect.js` live at both widths: "No anti-patterns found"; the contrast analyzer: no
findings. Measured: input 44 px, primary 44 px at 393 and 40 px at 1440 (own width), the two quiet
actions 44 px tall on the phone, lede and hint 6.47:1 dark and 5.66:1 light, label 13.05:1, focus
ring on every stop. Focus trace at 393: shape error → input (`aria-invalid`, `aria-describedby`
carries hint and error); refused address → input, the error under it; sent → the panel wrapper,
then Tab reaches "Mandane un altro" and "Cambia indirizzo"; "Cambia indirizzo" → input with the
address kept; **resend → `<body>`** (the button disables while busy and the focus effect was keyed
on `phase.kind`, which does not change). The placeholder's two control skeletons measured 12 px
tall instead of 44: `Skeleton` defaults to the line shape and its height won over the classes.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Busy labels and the sent state name the address; a resend is silent for keyboard and screen-reader users. |
| 2 | Match System / Real World | 3 | Plain Italian; "l'invito" is right for a friend and odd for the owner; "di abilitare questo" dangles. |
| 3 | User Control and Freedom | 3 | "Cambia indirizzo" keeps the address and focuses it; the lockup, the only link out, loops back and loses `returnTo`. |
| 4 | Consistency and Standards | 3 | Same h1, lede, Field and pill as `/new`; two verbs for one act (mandare, inviare). |
| 5 | Error Prevention | 3 | Shape check before any request, no browser bubble; `?error=` survives a reload. |
| 6 | Recognition Rather Than Recall | 3 | Address and lifetime stay on screen; the hint still asks the user to recall an invitation. |
| 7 | Flexibility and Efficiency | 2 | Enter and autofill work; the field is three Tabs away on desktop and never pre-focused. |
| 8 | Aesthetic and Minimalist Design | 3 | Three sentences, one field, one button; the expired state prints the validity sentence twice. |
| 9 | Error Recovery | 3 | Refused, expired and 429 each say what happened and what to do; the refused error is a flat red block. |
| 10 | Help and Documentation | 3 | The lede and hint are the help; the sent state says where to look. |
| **Total** | | **29/40** | **Fair** |

## Design Specificity Verdict

**LLM assessment.** Atlas by tokens rather than by vocabulary: the mark, Barlow Semi Condensed,
cream on ink with the grain, the rule-strong field, the ink pill, the plan states' StatePanel reused
for "Controlla la posta". Nothing from the line map itself appears, which is a defensible choice for
a 30-second task page. No amber, no glow, no gradient, no second icon family, every string Italian
in sentence case, every button verb-first.

**Deterministic scan.** 0 findings; live `detect.js` clean at both widths. The detector and the
review agree; the evidence that moved the score is behavioural (the resend's focus, the placeholder's
height), not visual.

## What's Working

- **Focus follows the task**, measured: shape error and refused address → the input with the ring;
  the swap → the panel, then the two actions; the way back → the input with the address kept.
- **The error model is right.** Address problems on the field with `aria-invalid` and a description;
  everything else a `Notice role="alert"` answering the user's own action; the sent state's own
  failures in the panel's footer. The 44 px rule holds everywhere at 393 and drops to 40/32 from
  `sm`, exactly as `/new` does.
- **One sentence about the link**, `LINK_VALIDITY`, reused in the lede, the sent state and the
  expired notice; the wording never drifts.

## Priority Issues

- **[P2] The lockup loops and loses the way back.** From `/login?returnTo=%2Fplans%2Fabc`, tapping
  the lockup goes to `/`, the list 401s and bounces to `/login?returnTo=<the list>`: the plan's
  `returnTo` is gone. *Fix (done):* the signed-out header renders the lockup without a link until
  the public landing ships; DESIGN.md's "the lockup links to the plans" is a signed-in rule.
  *Command:* /impeccable harden.
- **[P2] "Mandane un altro" goes silent.** The button disables while busy, focus falls to `<body>`,
  and the text change has no announcer. *Fix (done):* the panel-focus effect is keyed on the
  `phase` object (a new one per send), and the "Cosa è successo" line is `aria-live="polite"`.
  *Command:* /impeccable harden.
- **[P3] The placeholder's rhythm does not match the final shape.** Line skeletons without a line
  box, and the two controls at 12 px (the line shape's height won): a 55 to 87 px jump when the form
  lands. *Fix (done):* each text line takes its real line box; the controls use `shape="block"` and
  `shape="round"`. *Command:* /impeccable polish.
- **[P3] The refused error is a flat red block.** *Fix (done):* the first sentence in semibold, the
  help after it; "di abilitarlo". *Command:* /impeccable clarify.
- **[P3] Two verbs for one act.** *Fix (done):* "inviare" everywhere: "Ti inviamo", "Abbiamo
  inviato", "Inviane un altro", "Invio il link…". *Command:* /impeccable clarify.
- **[P3] The validity sentence twice in the expired state.** *Fix (done):* the notice body says only
  "Chiedine un altro qui sotto." *Command:* /impeccable distill.
- **[P3] Arrival unexplained from the list and the form.** *Fix (done):* with `returnTo` the lede
  opens "Accedi per tornare dove eri: ti inviamo un link, senza password." A `?reason=` from the
  401 handler stays a question for the front-door PR. *Command:* /impeccable clarify.
- **[P3] Small hardening.** *Fix (done):* `?error=` is dropped from the address bar once shown
  (`returnTo` stays); `[overflow-wrap:anywhere]` on the sent line; the unconfigured state shows the
  lede and the reason, no dead form. *Command:* /impeccable harden.
- **[P3] Alignment and arrival focus.** *Fix (done):* the first quiet action pulls back by its own
  padding; on a wide screen with a fine pointer the field takes focus on arrival (never on the
  phone, never over a notice). The hint reads "Quello invitato, o con cui sei già entrato." so it
  fits the owner too. *Command:* /impeccable polish.

## Persona Red Flags

**A first-timer invited by a friend:** the hint and the refused error speak to them; nothing on the
page says what Atlas is (the landing's job); in spam they hunt without a sender or subject (the
sender is the deploy's `AUTH_EMAIL_FROM`; naming it on screen is a front-door item).

**Michele, iPhone, one-handed, mid-plan:** the live screen explains "Sessione scaduta" before sending
him here; field and button are an upper-middle stretch, one tap with autofill; he no longer reads
about an invitation he never got; the lockup can no longer lose his plan.

**Keyboard-only:** every transition now lands focus, the resend included; three Tabs from load to
the field on the phone, none on a desktop.

## Minor Observations

- The h1 "Accedi" stays above "Controlla la posta": a stale but useful anchor.
- The alert is server-rendered on arrival with `?error=`, so most screen readers read it in order
  rather than announcing it; acceptable.
- B's coarse-pointer reading needed a touch context; CDP media emulation did not flip it.

## Questions to Consider

- Is this the one page that should carry none of the line map, or is the sent state a two-station
  line ("Link inviato" → "Di nuovo al piano")?
- Is sign-in an invitation flow or a return flow? Today the copy serves both in one hint; the
  landing and the waitlist will decide the voice.
