---
name: Atlas
description: A printed night transit map, one line per agent, ink and cream, never neon.
colors:
  ground: "#F4EFE4"
  surface: "#FBF8F1"
  ink: "#1B2230"
  ink-2: "#5B5E66"
  rule: "#DDD5C5"
  rule-strong: "#8A8473"
  line-coordinator: "#33404F"
  line-flights: "#1F55C4"
  line-lodging: "#0F7348"
  line-activities: "#6D3FC0"
  line-transport: "#08707F"
  on-line: "#FBF8F1"
  error: "#B3261E"
  error-wash: "#F8E3DF"
  success: "#4B7300"
  success-wash: "#EAF0DB"
  notice-wash: "#EBE5D8"
  amber: "#A86400"
  amber-ink: "#8A4A00"
  amber-wash: "#F6DCA8"
  action: "#1B2230"
  on-action: "#FBF8F1"
  focus: "#1B2230"
  ground-dark: "#1B2230"
  surface-dark: "#222A39"
  ink-dark: "#EFE8D8"
  ink-2-dark: "#AAA596"
  rule-dark: "#313A4A"
  rule-strong-dark: "#6B7384"
  line-coordinator-dark: "#A3ABB6"
  line-flights-dark: "#7696E3"
  line-lodging-dark: "#4FA77B"
  line-activities-dark: "#A089D9"
  line-transport-dark: "#4AA8B6"
  on-line-dark: "#1B2230"
  error-dark: "#F2766B"
  error-wash-dark: "#36211F"
  success-dark: "#9CCC65"
  success-wash-dark: "#26301F"
  notice-wash-dark: "#283141"
  amber-dark: "#F3A845"
  amber-ink-dark: "#F3A845"
  amber-wash-dark: "#33291A"
  action-dark: "#EFE8D8"
  on-action-dark: "#1B2230"
  focus-dark: "#EFE8D8"
typography:
  hero:
    fontFamily: "Barlow Semi Condensed, Barlow, system-ui, sans-serif"
    fontSize: "44px"
    fontWeight: 700
    lineHeight: 1
  display:
    fontFamily: "Barlow Semi Condensed, Barlow, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.15
  headline:
    fontFamily: "Barlow Semi Condensed, Barlow, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.2
  title:
    fontFamily: "Barlow Semi Condensed, Barlow, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.2
  body:
    fontFamily: "Barlow, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tnum"
  small:
    fontFamily: "Barlow, system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 400
    lineHeight: 1.38
    fontFeature: "tnum"
  meta:
    fontFamily: "Barlow, system-ui, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.4
    fontFeature: "tnum"
  label:
    fontFamily: "Barlow, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.35
    fontFeature: "tnum"
  input:
    fontFamily: "Barlow, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.35
    fontFeature: "tnum"
rounded:
  xs: "4px"
  sm: "10px"
  md: "16px"
  full: "9999px"
spacing:
  hair: "2px"
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  2xl: "32px"
  3xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.on-action}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    padding: "0 16px"
    height: "40px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    padding: "0 16px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.notice-wash}"
    textColor: "{colors.ink}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.full}"
    padding: "0 16px"
    height: "40px"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.full}"
    size: "40px"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: "0 8px"
  tool-plate:
    backgroundColor: "{colors.line-flights}"
    textColor: "{colors.on-line}"
    typography: "{typography.small}"
    rounded: "{rounded.sm}"
    padding: "7px 10px 8px"
  lane-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "12px 14px"
  notice-warning:
    backgroundColor: "{colors.notice-wash}"
    textColor: "{colors.ink}"
    typography: "{typography.meta}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
  notice-error:
    backgroundColor: "{colors.error-wash}"
    textColor: "{colors.ink}"
    typography: "{typography.meta}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
  date-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
  date-field-due-soon:
    backgroundColor: "{colors.amber-wash}"
    textColor: "{colors.amber-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "44px"
  sheet:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "16px"
  toast:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.md}"
    padding: "10px 8px 10px 14px"
---

# Design System: Atlas

Direction 1 "Linee", chosen by Michele on 2026-10-12 from the three studies in
`web/design/directions/` (the study is `1-linee/index.html`, the comparison and trade-offs are in
that folder's README), restyled as **"Carta notturna"** on 2026-10-14
(`docs/superpowers/specs/2026-10-14-atlas-brand-design.md`). This file was written with `impeccable document` from that study and from
the code that implements it. **From now on the tokens here are the authority**: the study is a
reference, `web/app/globals.css` is the implementation, and the two change together.

Where things live:

| What | Where |
| --- | --- |
| Tokens (both themes), Tailwind theme, base styles, keyframes | `web/app/globals.css` |
| Fonts, theme bootstrap, metadata, icon sprite | `web/app/layout.tsx` |
| Product name ("Atlas"), tagline, description, site URL | `web/lib/brand.ts` (`BRAND_NAME`, `BRAND_TAGLINE`, `BRAND_DESCRIPTION`, `BRAND_URL`), nowhere else |
| The mark's geometry and its fixed night colours | `web/lib/brand-mark.ts`; drawn by `components/ui/mark.tsx` |
| Tab icon, home-screen icon, link preview | `web/app/icon.svg`, `web/app/apple-icon.tsx`, `web/app/opengraph-image.tsx` (font: `web/assets/fonts/`, OFL) |
| Links between pages | `web/lib/routes.ts` (`ROUTES`, and `DEMO_READY` until step 3 builds /demo), never a hand-written path |
| The landing (`/`, public) | `web/app/page.tsx`, `web/components/landing/` |
| Returning visitors skip the landing | `web/lib/returning.ts` (the mark, the decision, the inline script) |
| The app header | `web/components/nav/app-header.tsx` |
| Primitives | `web/components/ui/` (inventory under Components) |
| Every primitive in every state, both themes | `/dev/ui` (development only, `notFound()` in production) |
| Measured contrast | the table under Colors, enforced by `components/ui/tokens.test.ts` |
| Invariants (amber only in `DatePair`, no colour on buttons, no em dash, the No AI Chrome Rule, the tagline spelled once, no hand-written list path) | `components/ui/invariants.test.ts` |

## Overview

**Creative North Star: "The Line Map"**

You read a metro line without thinking: where it started, which stops are behind, where you are
now. Atlas draws a plan's run the same way. Every agent is a line in its own colour, every event a
station on it, every message between agents an interchange that shows on both lines, and the tool
running now is the "you are here" plate at the end of its line. The five lines together are the
run. The finished plan keeps the vocabulary: each booking carries the roundel of the line that
found it.

The line map is printed at night: **"Carta notturna"**. A flat ink ground with a paper grain, cream
type, five matte line inks, the way a transit map looks on good paper under a street lamp. It is
crafted and alive, and never neon: colour is spent on identity (one hue per agent), on failure (one
red), on deadlines (one amber) and, in the eval history only, on a passed check (one green).
Everything else is cream or ink on the ground. Motion reports a
change and stops: a new station draws its segment down, the live node sends a slow halo, nothing
loops for decoration. Density is medium: stations are spaced like a printed line map (about 40 px a
row), with tabular figures so times and costs line up.

The lettering comes from road signs. Barlow Semi Condensed carries names and titles; Barlow
carries everything else. Both are drawn for reading in motion, which is what watching a run is.

**Key Characteristics:**

- One line colour per agent, chosen to stay clear of orange and yellow so amber keeps one meaning.
- Ink is the only action colour: buttons are ink pills, never coloured.
- State is a word plus a glyph, and the glyph is a line form (ring, bar, lozenge, cross, dashed
  stub), never colour alone.
- Flat surfaces separated by tone and hairlines; shadows only for the live plate and floating
  layers.
- Soft corners (10 and 16 px) for containers, pills for every control, circles for every node.
- Two dates on every booking, "Prenota entro" and "Quando", always labelled.
- Dark by default; paper grain on the ground; never glow, spotlight, gradient text or glass
  (The No AI Chrome Rule).

## Brand

**The mark: "A di linee".** The flights and lodging lines rise to meet at a station and form an
"A"; the coordinator's line is the crossbar. It reads as a letter and as a piece of the map. It is
a 40-unit square (`web/lib/brand-mark.ts`, `MARK_GEOMETRY`):

- left leg: `M8.5 35 L20 7` in `line-flights`, 5 wide, round caps
- right leg: `M31.5 35 L20 7` in `line-lodging`
- crossbar: `M13.5 25 H26.5` in `line-coordinator`, 4.5 wide
- the station: r 4.6 at (20, 7.5), `ground` fill and `ink` stroke at 2.8

`<Mark>` draws it in token utilities, so it follows the nearest `data-theme`. Images that cannot
read CSS variables use `NIGHT`, the night values, which a test keeps equal to `globals.css`.

- **Lockup** (`Wordmark`): the mark (28 px) and "Atlas" in Semi Condensed 600. `compact` hides the
  name below 400 px (the header on a phone); the name stays the link's accessible name.
- **Tab icon** (`app/icon.svg`): the mark on a night tile, with thicker strokes for 16 px.
  **Home-screen icon** (`app/apple-icon.tsx`): the mark on the night ground, 180 px. There is no
  `favicon.ico`.
- **Link preview** (`app/opengraph-image.tsx`): mark and name, the tagline, the five lines
  converging on a destination; 1200 × 630, rendered at build time with the vendored Semi
  Condensed 700.
- **Tagline**: "Ogni viaggio ha il suo atlante." (`BRAND_TAGLINE`): the landing hero, the
  metadata, the link preview, the empty plans list's invitation.
- **Rule:** this is the only mark. It is never redrawn in another form, and it moves only where it
  draws itself on the landing hero.

**The No AI Chrome Rule.** Nothing on screen may look like a template made by AI. Banned:

- glow (`drop-shadow`, `blur()` used as light, coloured halos)
- radial or conic spotlight gradients
- dot or grid backgrounds
- gradient text (`background-clip: text`)
- glass beyond the sticky live bar (`backdrop-filter` lives only in `live-header.tsx`,
  `agent-lanes.tsx` and the dev gallery's header)
- floating blurred shapes
- sparkle iconography

`components/ui/invariants.test.ts` enforces the mechanical part, in raw CSS and in Tailwind's own
utilities (`bg-radial`, `bg-conic`, `blur-*`, `drop-shadow-*`, `text-shadow-*`, `bg-clip-text`). The
texture of the product is the paper grain, and nothing else.

## Colors

"Carta notturna": a flat ink ground with a paper grain, cream text, five matte line inks for the
agents, one red for failures, one amber that belongs to deadlines alone and one green that belongs
to a passed eval. Values are the
frontmatter's: the plain keys are "Carta di giorno" (light), the `-dark` keys "Carta notturna".
**Dark is the default** everywhere. The system preference does not decide, and the toggle pins
light (or dark again) on `<html data-theme>`.

### Primary

- **Ink** (`ink`, `action`, `focus`): text, primary buttons (ink pill with `on-action` text), the
  focus ring, the cost meter, the interchange lozenge and the wave stations. In dark, the default,
  the ink is the cream `ink-dark` and primary buttons are a cream pill with ink text. In light they
  are an ink pill with cream text.

### Secondary: the five lines

One hue per agent, used for its line, its roundel, its working ring and its live plate. Nothing
else is drawn in a line colour.

- **Coordinatore** (`line-coordinator`): slate, the trunk line, 1.3 times wider on desktop.
- **Voli** (`line-flights`): signal blue.
- **Alloggio** (`line-lodging`): deep green.
- **Attività** (`line-activities`): violet.
- **Spostamenti** (`line-transport`): teal.
- **On line** (`on-line`): text and icons on a line colour (plates, roundels).

### Tertiary: failure, success and deadline

- **Error** (`error`, `error-wash`): a failed tool's ring, an agent in error, error notices, form
  errors. Always with a cross or a warning glyph and a sentence.
- **Success** (`success`, `success-wash`): **reserved for the eval history** (`/evals`). A passed run
  or check, a judge score of 4 or 5, a figure that improved since the previous run. Always with a
  check glyph or a sign and a word. A leaf green, yellower and lighter than the lodging line, so the
  two never read as one; the eval screens draw no line colour.
- **Amber** (`amber` stroke, `amber-ink` text, `amber-wash` fill): **reserved**. Only the "Prenota
  entro" side of a booking whose `dueAt` is within 72 hours (or past), drawn by `DatePair`.

### Neutral

- **Ground** (`ground`): the page.
- **Surface** (`surface`): lane cards on the phone, date fields, inputs, sheets, toasts.
- **Ink 2** (`ink-2`): secondary text, times, hints, field captions.
- **Rule** (`rule`): decorative hairlines (card edges, dividers). Not a control boundary.
- **Rule strong** (`rule-strong`): control borders (icon buttons, chips, inputs, steppers), the
  dashed edge of a source warning, the cost meter's track. At least 3:1 on ground and surface.
- **Notice wash** (`notice-wash`): note backgrounds and the hover wash of quiet controls.
- **Browser surfaces**: selection is `rgb(31 85 196 / .18)` light and `rgb(118 150 227 / .3)` dark;
  the scrollbar is `rule-strong` on transparent; the caret is ink; the scrim under a sheet is
  `rgb(27 34 48 / .4)` light and `rgb(3 6 10 / .62)` dark; `<meta name="theme-color">` is each
  theme's ground (`THEME_COLORS`), set before paint by the theme bootstrap for a pinned theme and
  repainted by the toggle.
- **Paper grain** (`--grain`): one still `feTurbulence` tile on the page ground (`html` and any
  `[data-theme]` subtree), cream specks at 6 % on dark, ink specks at 5 % on light. It is the one
  texture in the product: never animated, never on surfaces, inputs or plates.

### Measured contrast

WCAG 2.x ratios, measured on the background each element actually sits on (2026-10-14; text needs
4.5:1, large text and non-text 3:1). `components/ui/tokens.test.ts` recomputes every pair from
`globals.css` on each `npm test`, and fails if the frontmatter above and `globals.css` disagree.

| Pair | Light | Dark | Needs |
| --- | --- | --- | --- |
| ink on ground / surface | 13.89 / 15.02 | 13.05 / 11.80 | 4.5 |
| ink on notice-wash / error-wash / amber-wash | 12.69 / 12.93 / 11.93 | 10.71 / 12.34 / 11.68 | 4.5 |
| ink-2 on ground / surface | 5.66 / 6.12 | 6.47 / 5.85 | 4.5 |
| ink-2 on notice-wash / error-wash / amber-wash | 5.17 / 5.26 / 4.86 | 5.31 / 6.12 / 5.79 | 4.5 |
| error on surface / ground / error-wash | 6.16 / 5.70 / 5.31 | 5.20 / 5.75 / 5.44 | 4.5 |
| success on surface / ground / success-wash | 5.28 / 4.88 / 4.79 | 7.71 / 8.53 / 7.37 | 4.5 |
| ink / ink-2 on success-wash | 13.65 / 5.55 | 11.28 / 5.59 | 4.5 |
| on-line on coordinatore / voli / alloggio / attività / spostamenti | 9.96 / 6.28 / 5.55 / 6.34 / 5.45 | 6.87 / 5.49 / 5.42 / 5.37 / 5.74 | 4.5 |
| on-line at 92 % on the plate, blended on 8-bit channels (worst) | 4.87 (spostamenti) | 4.77 (attività) | 4.5 |
| line strokes on surface (worst) | 5.45 (spostamenti) | 4.85 (attività) | 3 |
| line strokes on ground (worst) | 5.04 (spostamenti) | 5.37 (attività) | 3 |
| amber-ink on amber-wash / surface | 5.14 / 6.47 | 7.13 / 7.20 | 4.5 |
| amber stroke on surface / amber-wash | 4.41 / 3.50 | 7.20 / 7.13 | 3 |
| on-action on action (primary button) / its hover | 15.02 / 9.99 | 13.05 / 9.95 | 4.5 |
| rule-strong on ground / surface (control borders) | 3.25 / 3.52 | 3.35 / 3.02 | 3 |
| focus ring (ink) on ground / surface | 13.89 / 15.02 | 13.05 / 11.80 | 3 |

Decorative only (no minimum, never the sole carrier of meaning): `rule` on surface 1.38 / 1.26,
surface against ground 1.08 / 1.11, the error notice's 55 % edge on error-wash 2.50 / 2.64,
`rule-strong` as the dashed edge of a warning on notice-wash 2.97 / 2.75 (the glyph and the
sentence carry it), `success-wash` against ground 1.02 / 1.16 (the glyph and the word carry a
passed state). On the cream light ground `amber-wash` is only 1.16:1 from `ground`: a due
deadline is carried by the amber stroke (4.41 on surface) and the words "In scadenza", never by the
wash alone.

### Named Rules

**The Amber Is Spoken For Rule.** Amber means one thing: this booking must be booked within 72
hours (TripTracker's rule, `dueAt <= now + 72 h`, past deadlines included). It never appears on a
button (the import button included), a chip, a heading, a chart, an icon or a decoration. A
booking without `dueAt` ("Da prenotare subito", "nessuna scadenza") is not amber, as in
TripTracker; its words carry the urgency. `DatePair` is the only component that may draw it, and
it decides by itself (the caller cannot force it).

**The One Hue Per Line Rule.** A line colour identifies its agent and nothing else: no line
colour for status, success, links or emphasis. The five hues avoid orange and yellow so they can
never be mistaken for the deadline. One exception, named: on a finished plan's itinerary (the map
and the day list) the five hues tell days apart, always beside the day's number (Map).

**The Green Means Passed Rule.** Green says one thing, only in the eval history: this passed, or
this got better. A passed run's verdict and its station, a passed check, a judge score of 4 or 5, a
delta that moved the right way. Never on a button, a link, a heading, a plan or a booking, and never
a line colour: the lodging line's green is the agent's, this green is the verdict's.

**The Word Beside The Colour Rule.** No state is carried by colour alone. Lane states are a word
and a glyph, errors have a cross and a sentence, a due deadline says "In scadenza", the live tool
says "in corso da".

## Typography

**Display Font:** Barlow Semi Condensed 600 (with Barlow, system-ui)
**Body Font:** Barlow 400, 500, 600 (with system-ui)
**Hero Font:** Barlow Semi Condensed 700, the landing and demo headings only (`font-hero`).

**Character:** both families come from highway-sign lettering: open, slightly condensed, made to
be read at a glance while things move. The condensed cut names things (plan titles, lane names,
wave stations, the wordmark); the regular cut says things.

Both are self-hosted by `next/font/google` (`display: swap` with size-adjusted fallbacks, so there
is no layout shift and no request to Google from the browser). Only the latin subset is preloaded,
four files of about 16 KB: Barlow 400, 500, 600 and Barlow Semi Condensed 600. Latin covers Italian
and the Portuguese, Spanish and French names a trip meets; the latin-ext files load by
`unicode-range` only when a name needs them. Barlow Semi Condensed 700 is a separate, non-preloaded
face: its file loads only on the pages that use `font-hero`. There is no other bold and no italic.

### Hierarchy

| Role | Token | Face | Size / line height | Where |
| --- | --- | --- | --- | --- |
| Hero | `font-hero font-bold text-hero`, `lg:text-hero-lg` | Semi Condensed 700 | 44 / 1.0, 66 / 0.98 from 1080 px | the landing and demo headings only |
| Display | `text-display`, `lg:text-display-lg`, `xl:text-display-xl` | Semi Condensed 600 | 24 / 1.15, 30 from 1080 px, 32 from 1280 px | the page title ("Lisbona, 14–18 nov") |
| Headline | `text-heading` | Semi Condensed 600 | 20 / 1.2 | section headings, sheet titles |
| Title | `text-title` | Semi Condensed 600 | 18 / 1.2 | lane names, plan state in the header, closed sections, wordmark |
| Body | `text-body` | Barlow 400 | 15 / 1.45 | running text, date values (600) |
| Small | `text-small` | Barlow 400–600 | 14.5 / 1.38 | station titles, buttons (600), notices, secondary prose |
| Meta | `text-meta` | Barlow 400–600 | 13.5 / 1.4 | meta lines, lane state, the stream line, message text, labels of fields (600) |
| Label | `text-micro` | Barlow 400–600 | 12.5 / 1.35 | the time gutter, hints, chips (600), date captions |
| Lede | `text-lede` | Barlow 400 | 16.5 / 1.5 | the landing's lede and closing paragraph |
| Input | `text-input` | Barlow 400–600 | 16 / 1.35 | form controls only: at 16 px iOS Safari does not zoom when they take focus |

Tailwind's default sizes are switched off in `globals.css`; use only these.

### Named Rules

**The Tabular Figures Rule.** `font-variant-numeric: tabular-nums` is set on the root: times,
durations, costs and dates line up in every list. Never turn it off.

**The Sentence Case Rule.** Every string on screen is Italian in sentence case: "Prenota su
Expedia", "Alternative scartate", "In scadenza". No title case, no all caps, no letter-spaced
eyebrows. Buttons start with a verb.

**The No Em Dash Rule.** No em dash anywhere on screen. The en dash appears only inside ranges as
the backend writes them ("14–18 nov"); the middle dot only as the backend's title separator
("Expedia · voli MXP→LIS · 14–18 nov") and once in "In scadenza · tra 2 giorni".

## Layout

**The reference is the 393 px phone** (iPhone 14 Pro), designed first; desktop is the second
layout, not a stretched phone.

- **Gutters**: 16 px at the sides on the phone, 28 px from 1080 px. Page content is capped at
  1480 px (`max-w-page`), centred. Prose is capped at 40 rem (`max-w-prose`).
- **Breakpoints** (Tailwind's are replaced): `sm` 640 px, `md` 768 px (the sheet becomes a
  centred dialog), **`lg` 1080 px (the lanes leave their cards: every lane is open and the coordinator
  and the subagents sit in rows)**, **`xl` 1280 px (the five lanes are columns)**.
- **Spacing**: a 4 px base (Tailwind's `--spacing: 0.25rem`). The steps in use are 2, 4, 6, 8,
  10, 12, 14, 16, 24, 28, 32, 40 px. Tight inside a group (4 to 8), 10 to 14 between rows of a
  list, 16 to 24 between groups, 28 to 40 between sections; more space above a heading than below.
- **The live screen on the phone**: a title block, then a sticky control bar (plan state and
  elapsed time on the left, "Interrompi" and the theme toggle on the right, the cost meter across
  the bottom), then the one-line stream status, then the five lanes as stacked cards (16 px
  radius, surface, `rule` edge, 10 px apart). The active lane is open; the others are one line
  with their live tool (`ToolChip` inline) or how they ended. **The present comes first**: the
  live-tool line stays under the header of an open lane too; an open lane keeps its last 4 stations
  and the live plate and folds the older ones into one row, "N passaggi precedenti", that unfolds
  them (a lane with fewer than 6 stations does not fold); and while the end of the open lane's line
  is below the fold a floating "Vai all'ultimo" button (secondary, `shadow-pop`, 44 px, bottom
  right) scrolls to it. The header and the line under it are one tap target (the button stretches
  over both). A closed card keeps a dead source visible: a quiet second line under its ending,
  warning glyph and "1 fonte non risponde", while the full note lives in the open body. A working
  lane with no tool running says what is true now (the coordinator "Aspetta alloggio.", a
  subagent "Ultimo passo: ..."), never the same "thinking" line on every lane. The "Scelta"
  station is drawn only after a subagent delivered: an interrupted or failed wave has none.
  **The open card never moves under a reader.** While the history replays (and until the open
  card has caught up with it) the open lane follows the work; after that it follows only while the
  viewer has not scrolled, pressed a key or opened a lane **and** the open card is out of view, and
  a card that touches the screen is never closed. A quiet row above the cards says where the work
  is ("Ora: Spostamenti", the lane's roundel, 44 px, no frame; "Si è fermato qui: Voli" once the
  plan stopped and that lane is closed) and opens that lane and brings it into view on a tap. The
  lane stays the focus while it works, so the row changes a few times per run, not every second.
- **The live screen from 1080 px**: the title and the control bar share one sticky top bar. Lanes
  lose their card and become bare columns under a header (roundel, name, state, and the live
  tool or the ending) with a `rule` line below it. **From 1280 px** the five lanes are columns in
  the spec's order, `grid-template-columns: minmax(0, 1.3fr) repeat(4, minmax(0, 1fr))` with 14 px
  gaps: the coordinator's trunk line is 1.3 times wider, and the five heads share one row. **From
  1080 to 1279 px** (a subagent column would leave about 100 px of text) the coordinator has a
  full-width row of its own, its text capped at 52 rem, and the four subagents share a
  four-column row under it. In both layouts the row of heads **sticks under the top bar** (the bar
  publishes its height as `--live-bar-h`; translucent ground at 92 % with the same 8 px blur), so
  a column's name is never out of sight however long the coordinator's line grows.
- **Level heads**: each head is a flex column whose `rule` row grows to the height of the row the
  heads share, so the five rules sit at one height however long each peek is, and the first
  stations below them start level. The peek is two lines at most (`line-clamp-2`, the live tool's
  title included), so the sticky row of heads stays under about 125 px. A lane's dead source is a
  quiet last line of its head ("1 fonte non risponde", warning glyph; the sentence "il piano
  prosegue con le altre fonti" is for screen readers), never a dashed note above the line: on
  desktop the note would push that lane's first station below its neighbours'. The phone's open
  body keeps the full note.
- **Jump to the end, desktop too**: from 1080 px the same floating button, "Vai all'ultimo del
  coordinatore", appears while the coordinator's line ends below the fold and scrolls to its end.
- **Borrowing 1 (from Sala)**: on desktop each lane header repeats the live tool under the lane
  name (`ToolChip variant="inline"`), so the "you are here" plate at the bottom of a long line is
  never the only place it shows.
- **Borrowing 2 (from Partitura)**: the waves are named stations on the coordinator's line,
  "Ondata 1", "Scelta", "Ondata 2" (`TimelineItem kind="wave"`), so the shape of the run reads
  without a time grid.
- **The station row** (`components/ui/timeline.tsx`): a three-column grid, 2.6 rem time gutter,
  1.5 rem track, the content; 0.45 rem column gap. The line is 5 px wide and centred in the track;
  each glyph sits 0.78 rem from the row's top, level with the first line of text. Oldest station
  at the top, the live plate at the bottom.
- **The finished plan**: the agent's summary (its line restating the total is left out: the
  total has its own fact); a strip of facts (the estimated total set against the request's budget,
  "710 € sotto il budget di 2.400 €", in neutral ink whether under or over, with one quiet line,
  "3 prezzi stimati"; the base; the dates only when the title does not state them, else the length
  goes in the header's subtitle and the budget leaves it); **"Da prenotare"**, the bookings sorted
  by deadline, one 44 px row each (roundel, underlined title, "entro ven 26 feb"), each a link to
  its row below, with "N in scadenza" in ink when some are due within 72 hours (amber stays
  inside `DatePair`); the warnings; then days as a vertical sequence of stops (never a grid of
  cards), **drawn as the trip's line map** (`itinerary.tsx`): each day is its own 5 px line (the
  lanes' width) in the hue the map gives that day, dashed from the sixth day as on the map; its
  head is a day badge, a disc in that hue with the day's number in `on-line` (28 px on the phone,
  32 px from 1280 px, a 3 px `ground` ring so it sits on the line), beside the caption ("Giorno 1,
  mer 14 apr") and the day's name at headline size; its stops are 13 px rings, 3 px in the day's
  hue on `ground`. On the phone the days join into one line that changes hue at each badge, like a
  line changing at an interchange, and so it stays up to 1279 px; from 1280 px each day is a
  timetable row with its own line (from 1080 px the right cell leaves the list about 600 px, too
  narrow for a day column beside the stops). The
  number on the badge is also in the caption, so the hue never carries the day alone; then bookings as rows **in the same urgency order as the strip** (`roundel | title,
  price, source | DatePair | "Prenota su"`; on desktop `1.3fr 1.4fr 240px`, the action column
  left-aligned with full-width buttons; the itinerary keeps the agent's order); discarded
  alternatives in a closed section per kind; the run's timeline closed at the very end. **From
  1080 px the page is two columns down to the bookings**: the summary, the facts, the warnings and
  "Giorno per giorno" on the left, "Da prenotare", **"Apri in TripTracker"** and the itinerary map
  (Map, below) in one right cell of 28 rem (`lg:sticky lg:top-6`) that spans from the summary
  through the last day, so it stays beside the stops instead of scrolling away after the first
  400 px (when it is taller than the window, `max-h` 100 dvh minus 3 rem and it scrolls inside
  itself); "Prenotazioni" then goes full width. Same hairlines, no cards. **On the phone "Da
  prenotare" is the first thing under the cover band**, before the summary's prose and facts (drawn
  first with `order`, the markup keeps the summary first): the first screen at 393 x 852 shows its
  heading and all five rows, which is the booking entry point (round 1 P1). **On the phone
  "Apri in TripTracker" sits right after the bookings**
  (full width: the trip landing in TripTracker is what the page is for, so it is not the last
  thing after a closed timeline). This departs from the spec's "in fondo" on purpose.
  A booking with no link says "Nessun link di prenotazione. Prenota sul sito di X: host", the host
  as plain text. The page header of a finished plan keeps only a quiet line, "Costo del piano
  0,41 $", where a running plan shows the cost meter.
- **Clocks**: "Prenota entro" is read in Michele's zone (Europe/Rome, `HOME_TIMEZONE`), because it is
  when he has to act. "Quando" and the itinerary's times are in the trip's zone ("Gli orari sono
  quelli di Lisbona" under "Giorno per giorno"), **except for a booking that starts from home**
  (the one that belongs to the trip's first stop, the transfer that leaves home: the same predicate
  as the itinerary's "(parte alle 09:40 in Italia)", `leavesHome`): its "Quando" leads with the
  clock at home in bold ("mer 14 apr, 09:40") and the trip's clock is the ink-2 second line, naming
  its zone ("08:40 a Lisbona", `startsAtHome` and `tripLabel`). A booking at the destination shows
  the trip's clock alone: no second clock, no zone words. He reads the plan from home: a flight is
  not read on the wrong clock.
- **When the plan arrives** under someone watching the run, the page scrolls to the plan's top
  (never down) and the focus goes to its summary heading (`tabIndex -1`); a plan that is merely
  opened does neither. The one live region stays for lane states only.
- **The request form**: one markup for every width (the server's HTML is already the right
  layout, so nothing reflows after hydration): on the phone one column; from 1080 px two balanced
  columns of sections in the phone's order ("Il viaggio" over "Quando" on the left, "Chi viaggia" over "Budget e
  preferenze" on the right, about 600 px each), so a request fits at 1440 by 900 with children
  too, and the read-back card beside it. The form remembers the origin, the adults and the number
  of children, never the children's ages (they go stale and set the price): each age is a tap on
  "Scegli". Enter in a single-line field
  moves to the next field; only the budget, the last one, sends the form. The error summary
  appears from three problems (or one with no field of its own), lists the fields by name as
  links, and takes the focus; with one or two problems the focus goes to the field.
- **The home list is a line** ("Plan rail"): a 3 px ink rail down the left of the card, clipped by
  its corners, and each plan a station on it, the plan's status glyph as its node (`PlanStatusGlyph`,
  20 px on a surface disc that hides the rail; the running plan's is the large ink ring, 18 px with
  a 4 px edge; ink for ready and running, ink-2 for budget reached and interrupted, error red for
  the two failures). Plan-status glyphs only: the rings that mean tool calls stay on the lanes. The
  plans still running come first under "In corso", at heading size (20 px), with only how long
  they have been going as meta ("da 3 min", "appena avviato"; the group says "In corso", screen
  readers read both; read again every 15 s); then the latest eight finished ones under "Recenti"
  at title size, quieter: the status word, the cost and when it was created in ink-2 (the word in
  error red for the failures). The rest is closed behind "Mostra gli altri N". Every row carries
  when it was created in its meta line, so two plans with one title are told apart without a
  special case. **The rail column is 36 px and the columns 10 px apart on the phone**, so the title
  column is about 190 px at 393 px; the title is clamped to two lines (the desktop column cuts it
  with an ellipsis) and **a date range in it never breaks** ("14–18 aprile" is a `nowrap` span, see
  `splitDateRange`). One plan, **the running one, else the newest ready**, is featured and leaves
  the rows (Cover photos, "Featured plan"). Dates are relative to today on Michele's clock ("Oggi,
  17:36", "Ieri, 21:40", "8 ott", the year only when it is not the current one); the full date and
  time are in the element's `title`. The clock is read in the fetch callbacks, never in render
  (Cache Components prerenders the route: a `Date.now()` in render is frozen into the shell).
- **The eval history** (`/evals`) is a dashboard over a line. On top, "Ultima valutazione": the
  newest run's verdict as a pill on its wash (green passed, red blocked, the notice wash otherwise),
  what it means, why it stopped (its first two blocking findings, the rule in Italian, the request
  linked to its open row, compare.py's sentence), and four figures (piani accettati, richieste
  senza blocchi, voto medio, costo) each with how it moved since the run before, a signed change
  in green when it is good news and in red when it is not ("invariato" in ink-2), and the run it
  is measured against named once under them. Then "Andamento" over the twenty newest runs, one
  card: the "Esito" line across it (every run a station carrying its verdict's glyph in its
  colour), then three figures side by side from 1080 px with hairlines between them (voto medio,
  costo a piano, piani accettati). On the figures the stations are plain ink rings, the newest one
  larger, so colour never competes with the figure; the line breaks where a run has no figure;
  the baseline the gate measures against is a dashed `rule-strong` hairline labelled
  "riferimento 4,1"; the axis is named only by its bounds (the judge and the cost per plan on
  tight clean bounds, the plans from zero) and its two ends' days. One tab stop per chart (arrows,
  Home, End, Enter opens the run), the reading in the caption (never a floating box), each key
  move said once, the values in a table for screen readers. The charts wait for the third run.
  Then "Tutte le valutazioni", the rail list, ten runs a page with numbered pages (`?pagina=N`,
  the scroll kept). A run's page steps to its neighbours ("Più recente" to the left, "Più
  vecchia" to the right, as the list reads), gives its figures with their changes since the run
  before, and lists its reference requests as closed rows (glyph and colour, title, plan, checks,
  score, cost, and the blocking check and the low scores named), the failing ones first; a row
  opens the deep dive, and `#richiesta-<id>` opens one.
- **Layers**: the sticky bar is `z-20`, the lanes' sticky heads `z-10` (above the lanes' own
  marks, below the bar), the floating "Vai all'ultimo" `z-10`, the toast region `z-40`, sheets are
  in the browser's top layer (native `<dialog>`). No other z-index.

## Elevation & Depth

Flat by default. Depth comes from tone (surface on ground), hairlines and the line glyphs, not from
shadows. Two shadows exist, both soft and offset downward, both tinted from ink (black in dark):

- **Plate** (`shadow-plate`: `0 1px 2px rgb(27 34 48 / .06), 0 10px 28px -14px rgb(27 34 48 /
  .22)`; dark `0 1px 2px rgb(0 0 0 / .4), 0 10px 28px -14px rgb(0 0 0 / .7)`): the live tool plate
  only. It lifts "you are here" off the line.
- **Pop** (`shadow-pop`: `0 1px 2px rgb(27 34 48 / .08), 0 16px 32px -18px rgb(27 34 48 / .32)`;
  dark `0 1px 2px rgb(0 0 0 / .45), 0 18px 36px -16px rgb(0 0 0 / .75)`): sheets and toasts.

The sticky control bar is the one translucent surface: ground at 92 % with an 8 px backdrop blur,
because lanes scroll under it. Nothing else is glass.

**The Flat Until It Floats Rule.** A surface gets a shadow only if it floats above the page (a
sheet, a toast) or marks the present (the live plate). Cards, notices, chips and fields are flat.

## Shapes

- **Radii** (Tailwind's are replaced): `rounded-xs` 4 px (message summaries, small marks),
  `rounded-sm` 10 px (plates, notices, date fields, inputs, the amber pill in compact dates),
  `rounded-md` 16 px (lane cards, sheets, toasts, gallery panels), `rounded-full` for every control
  (buttons, icon buttons, chips, steppers, the segmented track) and every node and roundel.
- **Borders**: 1 px `rule` hairlines for structure; 1.5 px for control edges (`rule-strong` on icon
  buttons and inputs, ink on secondary buttons); the amber stroke is a 1.5 px inset ring.
- **The station glyphs** are the form language of the whole product. Each state of a line has its
  own shape, so it reads without colour:

| Glyph | Meaning | Drawing |
| --- | --- | --- |
| Hollow ring | a finished tool call | 11 px, 2.5 px line-colour ring, surface fill |
| Red ring | a tool call that failed | 11 px, error ring, error-wash fill |
| Bar across the line | a status ("Al lavoro", "Finito") | 20 × 6 px, line colour, 3 px radius |
| Large ink ring | a wave ("Ondata 1", "Scelta", "Ondata 2") | 16 px, 3.5 px ink ring |
| Lozenge | an interchange (message between agents) | 18 × 12 px, 2.5 px ink edge, 7 px radius |
| Red cross, line broken above | the lane stopped on an error | `x-circle` 20 px on a surface disc |
| Thick ring and halo | the live station | 18 px, 4 px line-colour ring, halo while running |
| Dashed stub | the next stop | 3 px dashed line at 70 % |
| Dashed line with an empty ring | a lane still waiting | as above, with a hollow ring on top |
| Dashed ring (a badge glyph) | a lane that never started on a plan that is over ("Non partita") | 15 px box, eight dashes, 2.5 px stroke in ink-2 |

## Components

All primitives live in `web/components/ui/`, one file each, and render in every state on `/dev/ui`.
They take tokens only; `className` is for layout (width, margins, grid placement), never for colour
or shape (there is no class merging, on purpose: see JavaScript weight below).

| Component | File | What it is | States |
| --- | --- | --- | --- |
| `Button`, `LinkButton`, `buttonClasses` | `button.tsx` | Ink pill; `LinkButton` uses next/link inside, `<a target="_blank" rel="noopener noreferrer">` with `external` | primary, secondary, quiet; md 40 px, sm 32 px; icon; hover, press, focus, disabled, busy |
| `IconButton` | `icon-button.tsx` | Round icon-only button with a required Italian `label` | outline, bare; md, sm; disabled |
| `iconButtonClasses` | `icon-button.tsx` | An icon button's classes, for a link that must look like one | md, sm; outline, bare |
| `ThemeToggle` | `theme-toggle.tsx` | Pins the opposite of the theme on screen | moon in light, sun in dark (CSS, no flash) |
| `Chip` | `chip.tsx` | Static tag ("verificato", "stimato") | outline, quiet |
| `ToolChip` | `chip.tsx` | The running tool | `plate` (line colour, "in corso da 0:14"), `inline` (ring + title + time) |
| `AgentRoundel`, `AGENT_ICONS` | `agent.tsx` | The agent's disc with its icon | sm 26, md 30, lg 34 px |
| `StatusBadge` | `status-badge.tsx` | A lane's state, word + glyph | in attesa, al lavoro, finito, errore, fermato, **non partita** (a dashed ring, for a lane with no event on a plan that is over: "in attesa" would promise work that will not come) |
| `PlanStatusBadge`, `PlanStatusGlyph` | `status-badge.tsx` | A plan's status, word + glyph; the glyph alone (the home rail's node) | In corso, Pronto, Budget raggiunto, Interrotto, Non riuscito, Bloccato; md, lg; glyph also `node` |
| `CostMeter` | `cost-meter.tsx` | The session's API cost on a line that ends at its limit ("limite 0,60 $": the word "budget" stays with the trip's money), `role="meter"`, `aria-valuetext` in words | loading, **pending** ("Costo non ancora aggiornato": no usage reported yet, the backend reports at the end of a turn), no budget, 0, partial, at limit, over limit |
| `Disclosure` | `disclosure.tsx` | Native `<details>` | `row` (message, `contentLang="en"`), `section` (closed section with a count); open, closed, exclusive `name` |
| `Notice`, `InlineStatus` | `notice.tsx` | Framed note; the discreet one-line status | info, warning (the MCP-source style), error with title and action; turning, static |
| `DatePair`, `formatBookingInstant` | `date-pair.tsx` | "Prenota entro" and "Quando" | due soon (amber), not due, past, book now, none, pending, unknown, `now` null; `fields`, `compact` |
| `isDueSoon`, `dueDistance`, `DUE_SOON_HOURS` | `due-soon.ts` | The 72-hour rule and "tra 2 giorni" | |
| `Timeline`, `TimelineItem`, `TimelineTitle`, `TimelineMeta`, `TimelineNext`, `TimelineWaiting`, `TimelineEarlier` | `timeline.tsx` | A lane's line of stations | the nine glyphs above; `fresh`; `TimelineEarlier`: the folded start of a long line |
| `Sheet` | `sheet.tsx` | Modal on native `<dialog>`: bottom sheet on the phone, centred dialog from 768 px | open, closing; Esc, scrim tap, close button |
| `Toaster`, `toast`, `dismissToast` | `toast.tsx` | One message confirming the user's own action | neutral (5 s), error (stays) |
| `Skeleton` | `skeleton.tsx` | Placeholder in the final shape | line, block, round |
| `VisuallyHidden` | `visually-hidden.tsx` | Text for screen readers only | |
| `Icon`, `IconSprite`, `ICON_PATHS` | `icon.tsx`, `icon-sprite.tsx`, `icons.ts` | Phosphor bold, from a sprite | 35 icons |
| `Field`, `TextInput`, `TextArea`, `Select`, `NumberStepper`, `SegmentedControl` | `field.tsx` | Form controls with label above, hint, error below | default, hint, error, disabled, optional |
| `Mark` | `mark.tsx` | "A di linee" in the theme's line tokens (Brand) | any size via `className` |
| `Wordmark` | `wordmark.tsx` | The lockup: mark and "Atlas", optionally the link home | `compact` (name hidden below 400 px) |
| `ThemeScript` | `theme-script.tsx` | Applies the pinned theme before the first paint | |
| `cx` | `cx.ts` | Joins class names | |

`AppHeader` and `AppHeaderBar` (`web/components/nav/`) are app chrome, not primitives: see Navigation.

### Buttons

- **Shape:** pill (`rounded-full`), 1.5 px border, 40 px tall (32 px small), 16 px side padding,
  14.5 px semibold label, 16 px icon 8 px before it. Labels fit on one line. **Exception**: the
  request form's "Pianifica il viaggio" is 44 px tall below 640 px, level with the fields above it
  (the most important tap of the page is not its smallest control); 40 px from `sm` up.
- **Primary:** ink fill, `on-action` text. One per view: "Pianifica il viaggio", "Prenota su
  <sito>", "Continua con 2 $ in più".
- **Secondary:** ink outline on transparent; hover fills with `notice-wash`. `aria-current="page"`
  (a link to the page you are on: the header's "Nuovo piano" on the form) thickens the ink edge to
  3 px, like the current station. "Interrompi", "Apri in
  TripTracker", "Nuovo piano" where a primary already exists.
- **Quiet:** no edge until hover; inside notices and footers ("Riprova", "Annulla").
- **States:** hover in 160 ms; press scales to 0.98 in 120 ms (none with reduced motion); focus is
  the 2 px ink ring 3 px out; disabled is 55 % opacity with a not-allowed cursor; `busy` disables,
  sets `aria-busy` and turns the arrows icon (still with reduced motion).
- **Never amber**, and there is no prop that could make one.

### Chips

- **Style:** pill, 12.5 px semibold ink, 0 8 px; `outline` with a `rule-strong` edge, `quiet` on
  `notice-wash`. Static labels only, never a button, never a status colour.

### Cards / Containers

- **Lane card (phone):** `rounded-md`, `surface`, 1 px `rule` edge, 12 by 14 px padding, flat.
  From 1080 px a lane is a bare column with no card.
- **Notice:** `rounded-sm`, 8 by 10 px, a 17 px glyph, 13.5 px text. Info on `notice-wash`;
  warning on `notice-wash` with a dashed `rule-strong` edge and the warning glyph in ink (a dead MCP
  source is a note on its lane, not a plan error); error on `error-wash` with a soft error edge and
  the red cross, a semibold title saying what happened, the body saying what was saved and what to
  do, an optional quiet action.

### Inputs / Fields

- **Style:** `surface`, 1.5 px `rule-strong` edge, `rounded-sm`, 44 px tall, 12 px padding, 16 px
  text, placeholder in `ink-2` (never a label).
- **Label** above (13.5 px semibold), **hint** under it (ink-2), **error** under the control in
  error red with a cross, wired with `aria-describedby` and `aria-invalid` by `Field`.
- **Focus:** the edge turns ink and the focus ring shows. **Error:** the edge turns red.
  **Disabled:** 55 %.
- **Steppers** for counts (− and + around a real number input), **segmented control** (native
  radios in a pill track, the chosen one ink; segments 40 px on the phone with the track's padding
  added to the tap area, 46 px, 36 px from 640 px) for two or three exclusive choices, **native
  select** for months.

### Navigation

- **One header on every signed-in page** (`AppHeader`), in this order:
  - the lockup, the link to the plans (`ROUTES.plans`)
  - the sections "Piani" and "Valutazioni" as **stations on one line**. The line runs past the
    outer stations, a route that goes on beyond the map's edge, so the pair never reads as a
    two-step progress bar. The current station is the larger "you are here" ring (11 px, 3 px ink
    edge) with `aria-current="page"`; the others are 9 px hollow nodes that fill on hover.
  - the theme toggle, **bare** (no ring), so it never reads as a twin of the button after it
  - "Nuovo piano", **always the last item**, so the corner never changes meaning from page to
    page. It is always the *secondary* button, so each view keeps its single primary; on the
    phone a ringed 40 px "+" icon link named "Nuovo piano". On the form itself it stays in place
    with `aria-current="page"`, drawn as the current station is (a 3 px ink edge: the 1.5 px border
    plus a 1.5 px inset ring), so nothing shifts.
- At most 72 px tall, one line, no menu drawer at 393 px, 44 px targets (under a finger the 40 px
  icon controls grow to 44 px, `pointer-coarse:size-11`).
- On the live screen the header is the compact `AppHeaderBar` (`components/nav/app-header-bar.tsx`):
  the slim top row (56 px) above the sticky control bar, which keeps the theme toggle (bare there
  too, so it never sits as a twin of the ringed "+") and stays the only sticky, translucent surface. The bar imports no toggle, so the plan page ships one copy;
  `AppHeader` is the bar with the toggle at its end. The plan page's error boundary shows the lockup
  alone (JS budget, README).
- Links between pages read `ROUTES` (`web/lib/routes.ts`), never a hand-written path.

### Lane line (signature component)

`Timeline` and its items draw one lane: the line in the agent's colour (`data-agent` sets
`--line`), stations with the glyphs listed under Shapes, the live `ToolChip` plate on the `current`
item (with `aria-current="step"`), the dashed `TimelineNext` stub below it, and `TimelineWaiting`
for a lane with no events. Messages are `Disclosure` rows inside a `message` item, in both lanes they
connect, with the English text marked `lang="en"`. Only lane state changes are announced
(`aria-live="polite"`, one region per page, owned by the screen), never each tool call.

What a station is, for the person reading: the agents' file handling (writing `results/x.json.tmp`,
`mv`, reading a results file) is not work to decide on, so reads and the coordinator's writes leave
no station and a subagent's writes merge into one quiet "Consegna l'esito" ("1 file"); the English
hand-off ("flights.json v1 written") shows only on the coordinator's line; messages between agents
have an Italian row ("coordinatore → voli: incarico", "nuovo incarico", "voli → coordinatore: esito
consegnato") with the English text inside the disclosure (`lang="en"`); the "Scelta" station quotes
the first sentence of the coordinator's decision, un-clamped. A file call that failed is still drawn.
When a plan ends interrupted, failed or blocked, a lane that took part and delivered no result (a
subagent that sent nothing to the coordinator, a coordinator with no accepted plan) is "Fermato",
never "Finito"; the lane a blocked plan waited on says what it waited for ("Aspettava il permesso
per usare lastminute.com") and the state panel names that agent and tool.

### Motion

Motion reports a change and stops (motion knob 5). Durations are tokens in `globals.css`; the
one easing is `--ease-expo` (`cubic-bezier(.16, 1, .3, 1)`), linear only for a continuous turn.
Only `transform`, `scale`, `translate`, `rotate` and `opacity` animate; the one exception is a
phone lane's `grid-template-rows` (0fr to 1fr), the way it opens and closes, which jumps with
reduced motion. Every animation has a
declared reduced-motion equivalent, which keeps colour and opacity feedback and drops movement in
space:

| What moves | Normal | Reduced motion |
| --- | --- | --- |
| A new station arrives (`fresh`) | its line segment draws down, `scaleY` 0 to 1, 320 ms expo; then its glyph and text fade in, 260 ms after 140 ms | no drawing; glyph and text fade in, 120 ms |
| The live node | a halo ring grows and fades, 2.6 s expo, repeating while the tool runs | no halo |
| The stream is reconnecting | the arrows icon turns, 1.8 s linear | still icon |
| A busy button | the arrows icon turns, 1.8 s linear | still icon; label and `aria-busy` carry it |
| The cost meter | the fill scales and the ring slides to the new value, 400 ms expo | jumps |
| A disclosure opens | the caret turns half a circle, 220 ms expo; content fades in, 120 ms | caret flips; content fades in, 120 ms |
| A lane opens on the phone | its body expands (grid rows 0fr to 1fr, the layout exception above), 240 ms expo | jumps |
| "Vai all'ultimo" appears | fades in and rises 8 px, 200 ms expo (the toast's animation) | fades in, 120 ms |
| A cover photo arrives | fades in over its tile, 260 ms expo | fades in, 120 ms |
| Sheet | phone: rises from the bottom edge, desktop: rises 8 px; 240 ms expo; scrim fades | fades only, 120 ms |
| Toast | fades in and rises 8 px, 200 ms expo | fades in, 120 ms |
| Skeleton | breathes between 100 % and 55 % opacity, 1.6 s | still |
| Button and icon button press | scale to 0.98 / 0.96, 120 ms; hover colour 160 ms | no scale; colour stays |
| The landing map, once per load | lines draw with `--ease-pen`, 2 s, staggered; stations stamp (scale 1.35 to 1, 350 ms); the live tool plate rises, holds and retires before the destination stamps; the destination's ring draws, 1.2 s | the final map, still, without the plate (the finished plan) |

**The Report, Don't Perform Rule.** If an animation does not report a state change or answer the
user's action, it does not ship. No celebratory motion, no entrance choreography, no loops except
the halo (a tool is running) and the turning arrows (something is reconnecting or busy).

### Iconography

**Phosphor Icons 2.1.1, weight bold, MIT**, the set the study used. 35 icons are copied unchanged
from `@phosphor-icons/core@2.1.1` (`assets/bold/<name>-bold.svg`) into `components/ui/icons.ts`
with a provenance header. The root layout renders them once as a hidden SVG sprite
(`IconSprite`, a Server Component), and `<Icon name>` references a symbol: 1 em square (or the
`size` in px), filled with `currentColor`, decorative unless it is given a `label`. Icon sizes are
their own scale, set with `size`, never with a text class: 12 (message caret), 13 (compact
deadline clock), 14 (small buttons, failed-tool warning), 15 (state glyphs, field errors, the
stream line, small roundels), 16 (buttons, select caret, steppers), 17 (notices, toasts, roundels),
18 (icon buttons, header plan state), 19 (large roundels), 20 (the error station). The path data travels once as HTML and
never as JavaScript; the icon names are a TypeScript type.

Agents: `tree-structure` coordinatore, `airplane-tilt` voli, `bed` alloggio, `ticket` attività,
`tram` spostamenti. States: `hourglass-medium` in attesa, `check-circle` finito, `x-circle` errore,
`stop-circle` fermato and interrotto, `pause-circle` budget raggiunto, `prohibit` bloccato. Copy
the path of any new icon from the same version and weight; never draw one, never mix a family.

**Why not lucide-react** (the spec lists it as Agent Plan's dependency): one family per product,
and Phosphor's bold weight is the one the chosen study was drawn and checked with; lucide is
stroke-based, so mixing them would show two line weights side by side. The sprite also costs no
JavaScript, while an icon package adds a component per icon to every client bundle that uses one.

Phosphor's licence (MIT): "Copyright (c) 2023 Phosphor Icons. Permission is hereby granted, free of
charge, to any person obtaining a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
and to permit persons to whom the Software is furnished to do so, subject to the following
conditions: The above copyright notice and this permission notice shall be included in all copies
or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND."

### Components from 21st.dev and Kokonut UI

Each component the spec names was checked on 2026-10-12, licence first. Only MIT source may be
copied, by hand, with a provenance comment. What was decided:

| Spec's choice | Licence found | Decision | Why |
| --- | --- | --- | --- |
| Timeline, Dice UI (21st.dev `@diceui/timeline`; github.com/sadmann7/diceui) | MIT (21st.dev label and the repository's LICENSE, "Copyright (c) 2024 Sadman Sakib") | **Adapted** into `timeline.tsx`, licence notice included | Kept its anatomy, roles and `aria-current="step"`. Dropped `@base-ui/react`, `class-variance-authority`, `cn` and its item-registration store (each item sorts every sibling with `compareDocumentPosition` on every change, too costly for lanes of up to 300 events, and the reducer already knows each station's kind); dropped horizontal, alternate and RTL layouts; dots replaced by the Linee glyphs. |
| Agent Plan by isaiahbjork (21st.dev) | MIT (21st.dev label; no public repository) | **Not copied** | It is a screen-level component (the coordinator's task plan), not a primitive; its dependencies, `framer-motion` and `lucide-react`, conflict with the Phosphor decision and the 180 KB first-load target of `/plans/[id]`. If the plan screen needs a task list, build it from `Timeline` and `Disclosure`. |
| Agent Status (21st.dev, Syed Hasnain, Pasta UI) | MIT (21st.dev label; github.com/syeddhasnainn/pastaui is MIT) | **Written from scratch** (`StatusBadge`) | It conflicts with the design: a task summary with a tray, drawn with Solar Icons (`@solar-icons/react`). Linee needs a word plus a line-form glyph per state, nothing more. |
| A Date Range Picker (21st.dev; the spec names none in particular) | Checked: Jolly UI's by James Shopland is MIT but depends on `react-aria-components` and `lucide-react`; the others list `react-day-picker`, `date-fns`, `lucide-react` | **None copied** | The form's dates are two native `<input type="date">` fields (`TextInput type="date"` in a `Field`): the phone's own picker, accessible, zero JavaScript. A calendar popover is heavy and fiddly on a 393 px screen. |
| Bottom sheet (21st.dev or Kokonut UI) | Kokonut UI is MIT ("Copyright (c) 2025 kokonutUI"); its Smooth Drawer wraps shadcn's Drawer on `vaul` and imports `motion`, `lucide-react`, `next/image` | **Written from scratch** (`Sheet`) | The native `<dialog>` gives focus handling, Esc, an inert page and the top layer for free; the Kokonut piece is a pricing demo with gradient text and three dependencies. |
| Toast (21st.dev, the shadcn Sonner wrappers) | MIT (shadcn's wrapper and `sonner`) | **Written from scratch** (`Toaster`, `toast`) | Atlas needs one short message at a time, confirming the user's own action. Sonner's stacking and swipe gestures are more show than the calm control room wants, and a 1 KB store and live region do the job. |

### JavaScript weight

`/plans/[id]` has a 180 KB gzip first-load target. The design system adds no runtime dependency:
no animation library (all motion is CSS), no icon package (a sprite in HTML), no `clsx`,
`tailwind-merge` or `class-variance-authority`. Only `Sheet`, `Toaster` and `ThemeToggle` are
Client Components; everything else renders on the server or inside the screen's own client tree
without hooks.

The one exception is the itinerary map's `maplibre-gl` (about 250 KB gzip with its worker), which
lives in a lazy chunk loaded only when the map is near the viewport (Map, above), so it is not part of
the first load.

## Landing

`/` is public and prerendered, with no client fetch: the front door for anyone Atlas is shown to.
Its only client JavaScript is the theme toggle and `next/link`. Components live in
`web/components/landing/`; decided with Michele from a mockup on 2026-10-17.

- **Returning visitors skip it.** The API client marks the browser (`atlas-signed-in` in
  localStorage) after any authenticated 2xx and clears the mark on a 401. `SkipLandingScript`, the
  first element of the page, runs `location.replace("/plans")` before paint when the mark is set
  and the visitor did not come from a page of this site (a bookmark, a typed URL, the login coming
  back). Blocked storage or an unreadable referrer fail safe: the landing shows. Client-side
  navigation never runs it.
- **Public header** (`PublicHeader`): the lockup to `/`, "Come funziona" (a jump down the page,
  hidden below 480 px), the bare theme toggle, "Accedi" to `/plans` (which sends a signed-out
  visitor to TripTracker's login and back).
- **Hero**: the tagline in `font-hero text-hero` (Semi Condensed 700), the lede in `text-lede`, one
  call to action: "Guarda una corsa" once `/demo` exists, "Scopri come funziona" until then
  (`DEMO_READY`). "Accedi" lives in the header and the closing, never in the hero. The legend names
  the five lines in run order with their jobs; on the phone the line map comes before it.
- **Line map** (`LineMap`): horizontal from 768 px, vertical below (the lines converge at the
  bottom, like the phone's lanes). Each line carries its name at its head (`AGENT_LABELS`,
  condensed 600, like a transit diagram), so no line is told apart by its colour alone. The phone's
  map is short (viewBox 360×274) so the destination stamps inside the first screen. It is the
  landing's one authored moment (Motion table), drawn only behind `motion-safe:`.
- **Come funziona** (`HowItWorks`): three stations on one ink line, vertical on the phone and
  horizontal from 1080 px, each holding a real component with sample data (the request summary, a
  lane with its live plate, a booking with `DatePair` and a price with its source). The samples are
  illustrations: each is a `<figure>` whose visually hidden `<figcaption>` says the sample in one
  sentence, while the drawing is `inert` and `aria-hidden`. On screen, an "Esempio" tab on each
  frame's top edge, like a map's inset label, says the same. The booking's "Prenota su Expedia" is
  never a link (CLAUDE.md contract rule 4: booking URLs are never hand-written) and is drawn
  secondary, below the page's own actions. The sample's fixed "now" makes its deadline due soon,
  so the amber appears there doing its one job. From 1080 px the three stations share their rows
  (subgrid), so the samples start on one line.
- **Closing** (`LandingClose`): the five lines entering the destination (`ConvergingLines`, the link
  preview's drawing), then, with the demo, "Guarda una corsa intera, senza account.", "Guarda una
  corsa", "Accedi" and "Accesso su invito."; until then, "Atlas è su invito." and "Accedi".
- **Footer**: the lockup and one honest line ("Prezzi e disponibilità si confermano sempre sul sito
  del fornitore.").
- **Motion**: the line map is a named exception to The Report, Don't Perform Rule, for the landing
  (and the demo in step 3) only: it presents the product. Nothing else on the landing moves.

## Map

The finished plan carries an itinerary map (`components/plan/map/`), supplementary to the list: the
day-by-day list stays the primary content and says everything the map does.

- **Where**: **from 1080 px in the sticky right cell**, under "Da prenotare" and "Apri in
  TripTracker" (28 rem wide, 18 rem tall, a hairline above it), so it stays in view while the
  days are read and a click in a day of the list is seen on the map at once; **on the phone inside
  "Giorno per giorno", above the list** at the full width (16 rem tall). Fixed height, so nothing
  moves when it arrives (`rounded-md`, 1 px `rule` edge, flat). The legend, a live line and the
  attribution sit under the frame. The map and the list share one model and one picked day
  (`ItineraryMapProvider`, `ItineraryMapPanel`, `ItineraryDays`), so the page can put them in
  different places.
- **No coordinates, no map.** Only stops with a `lat`/`lon` pair (finite, in range, not 0/0) are
  drawn; the line skips the others. A plan with no located stop renders the list alone, without a
  frame or an empty state. The text summary says how many stops are on it ("Mappa di 14 tappe su
  19, in 5 giorni.").
- **Marks, in the Linee vocabulary.** Each day with two or more located stops is a line (4 px,
  round caps, a surface casing under it so it reads over roads); stations are rings (11 px, 2.5 px
  line-colour ring, surface fill, growing to 15 px at zoom 12), the same form as the lanes'
  finished tool; the lodging, the trip's base (the stop a lodging booking points to), is the large
  ink ring (18 px, 3.5 px ink edge) with an ink core and the word **"Hotel"** under it (11.5 px,
  ink on a surface halo), so it is told apart by size, shape and word, never by colour alone.
  **From zoom 12 each station carries its number** inside the ring (10.5 px, ink, Noto Sans Bold):
  the stop's place in its day, counting the stops with no coordinates, which is **the same number the
  list shows** left of each stop's title (`text-ink-2`, hidden from screen readers, which already
  get the ordered list). Below zoom 12 the rings are too close to hold a figure and stay plain. A day is a
  line hue in a fixed order: **Giorno 1 blue, 2 green, 3 violet, 4 teal, 5 slate** (`line-flights`,
  `line-lodging`, `line-activities`, `line-transport`, `line-coordinator`), then again from the
  sixth day with the line **dashed** (so two days of one hue stay distinct). The day list draws
  each day in the same hue (its line, stations and badge, Layout, "The finished plan"), so a day is
  one line on the map and in the list. The itinerary, map and list, is the one place
  line hues stand for something other than an agent (a day, not a status): it extends The One Hue
  Per Line Rule on purpose, because five hues is all the system has and the legend names every
  one ("Giorno 3"), so no meaning rests on colour alone. Amber never appears on the map.
- **The legend is the day picker**: a row of toggle buttons under the frame, "Tutti i giorni" then
  "Giorno 1".."Giorno N" (40 px pills, `rule-strong` edge, the chosen one ink-edged on
  `notice-wash`, `aria-pressed`), each with its line in miniature, and "Alloggio" with the
  lodging glyph. Choosing a day fades the other days (line 22 %, stations 30 %), widens that
  line (4 to 6 px) and fits the map to it; choosing it again, or "Tutti i giorni", fits all
  stops. In the list, clicking inside a day does the same and marks that day's title with a 3 px
  underline in its hue (`data-day-selected`); the keyboard way is the legend. A click on a
  station opens a card at the bottom of the map (title, "Giorno 2, tappa 3, 10:00", the place and a
  quiet **"Vai alla tappa"** button; `shadow-pop` because it floats; a close button) and rings the
  station in ink. "Vai alla tappa" scrolls the stop's row in the list to the middle of the window
  (smooth, instant with reduced motion), gives it the `notice-wash` for 2.4 s and moves the focus
  to it. If the card or the zoom buttons would cover the picked station, the map eases it into the
  free part of the frame. The legend's pills are 40 px on the phone and 32 px from 1080 px (a
  pointer, and the sticky cell has to fit a 900 px window).
- **The first view is the core, not the outlier.** "Tutti i giorni" fits the located stops minus the
  ones **far from the trip's base** (`markFarStops` in `model.ts`): the base is the lodging (else the
  median point), "far" is beyond 10 km or twice the distance three quarters of the stops are
  within, whichever is larger, and only when there are at least five located stops and at most a
  third would be far (a trip over several centres has none). A day trip (Sintra from Lisbon) would
  otherwise squeeze the town into a sixth of the frame. The far stops are still drawn; their day has
  a quiet chip under the legend, **"Fuori mappa: Sintra (Giorno 3)"** (dashed `rule-strong` edge,
  `ink-2` text, the day's title when it is short, else the stop's), which picks that day. Fits leave
  60 px at the right for the zoom buttons and, with a card open, its height at the bottom.
- **A live line** under the legend (`role="status"`, `text-meta`, `ink-2`) says how much of the
  plan is on the map ("11 tappe su 19 sono sulla mappa, le altre solo nell'elenco.") and, once a day
  is picked, what that day has ("Giorno 3: 2 tappe sulla mappa, altre 2 solo nell'elenco."): the
  pick is heard on the phone, where the list is out of sight. It answers the person's own action,
  as a toast does (the live regions rule below is about the run's stream).
- **The basemap is quiet and made from the tokens**: OpenFreeMap's vector tiles (OpenStreetMap data,
  OpenMapTiles schema, `https://tiles.openfreemap.org/planet`, no key, no cookies) restyled by
  `style.ts`: land is `ground`; water, parks, buildings and roads are one step from it, mixed
  from `ground`, `rule` and `rule-strong` (maplibre does not read `color-mix()`, so
  `mixColors` computes them). **Water is the one cool tone**: in light it is that grey leaned 12 %
  toward `line-flights` (`WATER_COOL`), so the Tagus is told from land at a glance and a quarter on
  its bank is not "in the river" (land against water 1.44:1, was 1.22:1); the day lines keep
  at least 3.64:1 over it (spostamenti, the worst) in light, 5.4:1 in dark (`style.test.ts`
  recomputes both); in dark water stays the darkest step. No POIs, no road names, no shields, no rail. Labels are only
  places (city, town, district, neighbourhood) and water names, in Noto Sans (the glyphs
  OpenFreeMap serves), `ink-2` with a ground halo, Italian names first. Dark is the same
  recipe on the dark tokens; the style is rebuilt when the theme changes (the toggle's
  `data-theme` or the system), and everything is read from the CSS variables, so a pinned theme
  always wins.
- **Attribution is always visible** under the map, not folded in an "i": "© OpenStreetMap
  contributors, OpenFreeMap, © OpenMapTiles", each a new-tab link (OpenFreeMap's terms ask for
  OpenMapTiles and OpenStreetMap, and say OpenFreeMap itself is welcome). maplibre's own
  attribution control is off.
- **Supplementary, accessible**: `role="region"` named "Mappa delle tappe", described by a
  visually hidden summary (the counts, the day trips that are off the first view, then each day's
  first and last place). The page never
  scrolls into a map trap: the wheel scrolls the page and zoom needs Ctrl (or ⌘) + wheel, or two
  fingers on touch (`cooperativeGestures`, with Italian hints); the zoom buttons ("Ingrandisci
  la mappa", "Riduci la mappa") are real 40 px icon buttons; the canvas takes the keyboard like
  maplibre's own map (arrows pan, + and - zoom) and Tab always leaves it. Rotation and tilt are
  off.
- **Motion**: fitting to a day and the zoom buttons ease for 500 and 250 ms, and not at all with
  `prefers-reduced-motion` (duration 0, no tile fade). Nothing loops.
- **Loading**: the map is a separate chunk (`next/dynamic`, `ssr: false`), requested only when
  the finished plan renders and its frame comes within 400 px of the viewport
  (IntersectionObserver); a `Skeleton` of the same size holds the place and says "Caricamento
  della mappa…" to screen readers. maplibre-gl (BSD-3), its stylesheet and its worker (shipped as
  a static asset, `setWorkerUrl`) stay out of the first load of `/plans/[id]`. If WebGL is
  missing the frame says so in a `Notice` and points to the list; if the tile source cannot
  be reached the lines and stations still draw and a quiet line says the basemap did not load.

## Cover photos

The home list and the top of the finished plan carry a real photo of the destination, so a trip is
recognised before it is read. It is supplementary: every screen is complete without it.

- **Source and law.** `GET /plans/{id}/cover` (backend `covers.py`) answers one free-licensed
  Wikimedia Commons photo (CC0, public domain, CC BY, CC BY-SA) with its author, license and file
  page, or 404 `cover_unavailable`. `lib/schemas/api.ts` pins the hosts (image on
  `upload.wikimedia.org`, file page on `commons.wikimedia.org`, license link `http(s)`), so a wrong
  answer can never aim an `<img>` or a link elsewhere. **The credit is a legal requirement, not
  decoration:** the plan page shows "Foto: author, license, Wikimedia Commons" under the photo (the
  license and the source are new-tab links with `rel="noopener noreferrer"`; the author is plain
  text and absent for a public-domain file), at `micro` size in `ink-2`, never cut or hidden. The
  line reads "Foto: Vitor Oliveira (CC BY-SA 2.0), Wikimedia Commons" (with no author, "Foto: CC0,
  Wikimedia Commons"). **The home list credits the photos it shows**, whose thumbnails are too
  small to carry it: under the card, one such line per different photo (`useShownCovers`: the covers
  read so far, each photo once, since five plans for one destination show one photo), with the
  license and the source as links. With more than two different photos the lines sit in a closed
  "Crediti delle foto (N)" disclosure under the card. Nothing while no row has a photo.
- **Home thumbnail** (`CoverThumb`): 4:3, 72 px wide on the phone and 96 px from 1080 px,
  `rounded-sm`, 1 px `rule` edge, in a column of its own between the rail and the title (the node now
  sits at the row's middle). It asks for the photo only when the row comes within 300 px of the
  viewport and loads it `lazy`; **its alt text is empty**: the row's title names the place, so a
  screen reader does not hear "Lisbona in famiglia" twice per link (the plan page's band keeps the
  descriptive alt).
  **The tile**: a `notice-wash` block with the destination's initial in `ink-2` (a `map-pin` when the
  name has no letter) is under the photo at all times, so while the answer is on its way and when
  there is none the row is the same size and shape, and the photo only fades in over it. No
  illustration, no generated art.
- **Featured plan** (`FeaturedPlan` in the home list, `CoverFeature`): the plan running, else the
  newest ready, gets a card that reuses the band's shape: its photo across the top, **11 rem tall on
  the phone and 14 rem from 1080 px** (a `notice-wash` tile with the initial under it, like the
  thumbnails; `object-position` kept on the skyline; empty alt, the title names the place), then
  the title in `text-heading` with its status glyph and the status line (word, cost, created) under
  it; the whole card is the link. A label above it says why ("In corso", or "Ultimo piano pronto").
  It sits **above the list on the phone and up to 1279 px, and in a 22 rem right-hand column from
  1280 px** (`xl:sticky`), where the list is capped at 64 rem and the screen was empty; it leaves the
  rows (no duplicate link), and a list with only that plan has no list card. The other 19 rows
  keep their 4:3 stamps: big photos on every row would turn the calm ledger into a gallery.
- **Plan band** (`CoverBand`, first thing in `PlanView`, under the header): a fixed **8 rem** tall
  on the phone (so "Da prenotare" and its rows stay in the first screen; 11 rem pushed it to
  y = 822) and 18 rem from 1080 px `rounded-md` frame with a `rule` edge, the photo `object-cover`
  with `object-position: 50% 42%` (a city photo has its roofs a little above the middle), with its
  real `width`/`height`, so nothing moves when it arrives; while it is read the frame is a
  `Skeleton` block of the same size. No photo, or a file that does not load, and the band is simply
  not drawn (the plan reads as before). The title stays the page's `h1` in the header; over the
  photo's lower left corner sits a **plate** with the destination ("Lisbona, Portogallo", `map-pin`,
  condensed 600).
- **Text on a photo is never bare.** The plate is `surface` with `ink` text and a `rule` edge, so
  its contrast is the tokens' own (measured above, both themes) whatever the picture is; the foot of
  the photo is also darkened with the theme's `--scrim` token (`bg-linear-to-t from-(--scrim)`),
  heavier in dark, so the plate sits on calmer ground. The plate is `aria-hidden`: the image's alt
  text names the place. No white-on-photo text, no raw colours.
- **Sizes.** Photos are not run through `next/image`: Wikimedia already serves sized thumbnails from
  its own cache, and an optimizer would only add a hop. `coverSources` builds a `srcset` from the
  widths Wikimedia serves (250 and 500 for thumbnails, 960, 1280 and 1920 for the band; any other
  width is an HTTP 400) and never asks above the file's width. Images carry
  `referrerPolicy="no-referrer"`, because the page's address holds a plan id.
- **Requests.** `cover-store.ts` reads each plan's cover once per page (ready or none are kept; a
  failure is "none for now" and is asked again by the next screen that wants it), at most four at a
  time, and shares the answer: the plan page finds what the list already read. The response is
  cacheable by the browser (`Cache-Control: private, max-age=3600`).
- **Where it is not.** The live screen (a running or paused plan, or one that stopped) has no photo:
  it is for watching the lanes and its header is already the busiest line of the product. The
  finished plan's header keeps the title text only.

## Do's and Don'ts

### Do:

- **Do** show both dates of every booking, labelled "Prenota entro" and "Quando", with `DatePair`,
  in previews and compact strips too. They are never merged and one never stands in for the other.
- **Do** let `DatePair` decide amber from `dueAt` and `now` (72 hours, past included).
- **Do** give every agent its own line colour through `data-agent` and keep its icon from
  `AGENT_ICONS`.
- **Do** write every state as a word and a glyph (`StatusBadge`, `PlanStatusBadge`, `Notice`).
- **Do** use `formatUsd` for costs ("1,62 $", two decimals, Italian format) and `formatEur` for
  prices; never cents on screen.
- **Do** read the product's name from `BRAND_NAME`.
- **Do** read the tagline from `BRAND_TAGLINE` and every page path from `ROUTES`.
- **Do** declare a reduced-motion equivalent for every new animation, from the Motion table.
- **Do** check every new screen at 393 px and at desktop width, light and dark, and on `/dev/ui`
  when a primitive changes.
- **Do** open booking links in a new tab with `rel="noopener noreferrer"` (`LinkButton external`).

### Don't:

- **Don't** put amber on a button, a chip, a heading, an icon, a chart or anything decorative;
  don't use it for warnings (a dead source is a dashed `notice-wash` note, a failure is red).
- **Don't** use a line colour for anything but its agent, and don't add orange or yellow hues.
- **Don't** colour a button: buttons are ink (primary) or ink-outlined (secondary).
- **Don't** use Tailwind's default palette, sizes, radii or breakpoints; they are switched off.
  Don't type raw hex values in components.
- **Don't** use title case, all caps, letter-spaced eyebrows or em dashes.
- **Don't** add a second icon family or weight, or draw an icon by hand.
- **Don't** add shadows to cards, notices, chips or fields; don't add glass beyond the sticky bar.
- **Don't** announce tool calls or stream events through `aria-live`; only lane state changes, and
  toasts only for the user's own actions.
- **Don't** animate layout properties, and don't loop anything except the halo and the turning
  arrows.
- **Don't** draw another mark or redraw "A di linee": `<Mark>` and `lib/brand-mark.ts` are the only
  sources.
- **Don't** add glow, spotlight gradients, dot grids, gradient text, glass or blurred shapes (The No
  AI Chrome Rule).
