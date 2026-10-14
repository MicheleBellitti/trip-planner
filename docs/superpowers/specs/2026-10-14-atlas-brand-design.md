# Atlas: brand, front door and motion

Design spec, 2026-10-14. Decided by Michele in a brainstorming session (visual studies in
`.superpowers/brainstorm/`, not committed). Scope: `web/` only. When this spec and
`web/DESIGN.md` / `web/PRODUCT.md` disagree, this spec wins until those two files are rewritten
by the first delivery step (section 8).

## Goal

Atlas is meant to be **shown off**: to friends, in a portfolio, in a launch video. Today a visitor
without access is bounced straight to TripTracker's login and sees nothing, and the signed-in app
looks like an internal tool. That plainness was deliberate: the first `impeccable init`, written
without an interview, banned a logo, entrance motion and decorative loops. Michele now wants:

- a brand (a mark, a line, a world) that reads as a product and not as an AI template;
- a public front door: a landing page and a free, self-playing demo of a run;
- livelier motion where it pays: the live run, micro-interactions, page transitions;
- one consistent navigation bar.

Success: a visitor gets Atlas in one screen and can watch a whole run without an account. Opening
the app feels like a crafted object, and nothing in it reads as "a site clearly made by AI".

## Decisions at a glance

| Topic | Decision |
| --- | --- |
| World | **"Carta notturna"**: a printed night transit map. Flat ink ground, paper grain, cream type, matte line inks. |
| Theme | **Dark by default everywhere**, whatever the system says. Light, "Carta di giorno", is pinned with the toggle and remembered. |
| Tagline | **"Ogni viaggio ha il suo atlante."** |
| Mark | **"A di linee"**: the flights and lodging lines meet at a station to form an "A", and the coordinator's line is the crossbar. |
| Front door | Landing at `/`, the plans list moves to `/plans`, a public demo at `/demo` built from the real live components. |
| Motion | New motion on the live run, on micro-interactions and on page transitions. The finished-plan view keeps today's motion. |
| Navigation | One app header on every signed-in page, with the current page drawn as a station on a line. |
| Anti-cliché | No glow, no radial spotlight gradients, no dot grids, no gradient text, no glass beyond the sticky bar, no blurred orbs. |

## 1. Brand system

### Palette

Every existing token keeps its name. Only values change, so components need no renaming.
`web/app/globals.css` and the DESIGN.md frontmatter change together, and `tokens.test.ts`
re-measures every pair.

| Token | Dark, "Carta notturna" (default) | Light, "Carta di giorno" |
| --- | --- | --- |
| `ground` | `#1b2230` | `#f4efe4` |
| `surface` | `#222a39` | `#fbf8f1` |
| `ink` | `#efe8d8` | `#1b2230` |
| `ink-2` | `#aaa596` | `#5b5e66` |
| `rule` (decorative) | `#313a4a` | `#ddd5c5` |
| `rule-strong` (control borders) | `#6b7384` | `#8a8473` |
| `line-coordinator` | `#a3abb6` | `#33404F` (unchanged) |
| `line-flights` | `#7696e3` | `#1F55C4` (unchanged) |
| `line-lodging` | `#4fa77b` | `#0F7348` (unchanged) |
| `line-activities` | `#a089d9` | `#6D3FC0` (unchanged) |
| `line-transport` | `#4aa8b6` | `#08707F` (unchanged) |
| `on-line` (text on a line fill) | `#1b2230` | `#fbf8f1` |
| `error` / `error-wash` | `#f2766b` / `#36211f` | `#B3261E` / `#f8e3df` |
| `notice-wash` | `#283141` | `#ebe5d8` |
| `amber` (stroke) / `amber-ink` / `amber-wash` | `#F3A845` / `#F3A845` / `#33291a` | `#A86400` / `#8A4A00` / `#f6dca8` |
| `action` / `on-action` / `focus` | `#efe8d8` / `#1b2230` / `#efe8d8` | `#1b2230` / `#fbf8f1` / `#1b2230` |

These ratios were measured in brainstorming. They are WCAG 2.x, and the thresholds are the ones
`tokens.test.ts` already enforces:

- **Dark theme:**
  - ink on ground and surface: 13.05 and 11.80
  - ink-2 on ground and surface: 6.47 and 5.85
  - every line stroke on surface: at least 4.85
  - `on-line` on every line fill: at least 5.37, and at least 4.77 at 92 % on the plate (blended on 8-bit channels, as the browser does; the first values, `#6e8fe0` and `#9c84d6`, fell to 4.496 there)
  - rule-strong on ground and surface: 3.35 and 3.02
  - error on surface: 5.20
  - amber on amber-wash: 7.13
- **Light theme:**
  - ink on ground: 13.89
  - ink-2 on ground: 5.66
  - every line stroke on ground: at least 5.04
  - rule-strong on ground: 3.25
  - amber stroke on surface and on amber-wash: 4.41 and 3.50
  - amber-ink on amber-wash: 5.14

The implementation re-derives the remaining pairs and fails if any of them misses:

- selection colours
- the scrim
- the plate at 92 %
- the hover states

**Amber on cream.** In the light theme the cream ground is warm, so `amber-wash` barely differs
from it (1.16:1). For that reason the light amber stroke is darker (`#A86400`). A due-soon date
also keeps relying on its stroke and on the "In scadenza" words; the wash alone never carries
the meaning. The Amber Is Spoken For Rule is otherwise unchanged.

### Theme behaviour

- The default is dark. `prefers-color-scheme` no longer decides anything: `ThemeScript` applies
  dark unless `data-theme="light"` was pinned. The pinned choice and its storage key stay as they
  are today.
- The light theme is a full theme, not a fallback. Every screen is checked in both themes.

### Paper grain

- One static, tiny SVG `feTurbulence` tile as a data URI on the page `ground` in both themes, at
  about 6 % opacity, tinted cream on dark and ink on light.
- It is never animated and never sits on surfaces, inputs or plates.
- It is the one texture in the product, and it is what makes the ground read as printed rather
  than lit.

### Typography

- Barlow and Barlow Semi Condensed stay.
- One addition: **Barlow Semi Condensed 700**, for a new `text-hero` size, used only on the
  landing and demo headings: 66 / 0.98 from 1080 px, 44 / 1.0 on the phone.
- The rest of the type scale is unchanged.

### The mark

- **Geometry**: a 40-unit square.
  - left leg `M8.5 35 L20 7` in `line-flights`, 5 wide, round caps
  - right leg `M31.5 35 L20 7` in `line-lodging`
  - crossbar `M13.5 25 H26.5` in `line-coordinator`, 4.5 wide
  - apex station: a circle r 4.6 at (20, 7.5), filled with `ground`, stroked with `ink` at 2.8
- **Component**: `components/ui/mark.tsx`, a Server Component. It draws inline SVG coloured
  through the theme's CSS variables, so it follows the theme with no JavaScript.
- **Lockup**: `Wordmark` becomes the mark plus "Atlas". `BRAND_NAME` is still the only place
  the name is spelled. Below 400 px the lockup shows the mark only, and the link keeps "Atlas"
  as its accessible name.
- **Favicon and icons**, through Next's file conventions (check
  `node_modules/next/dist/docs/` for the current names before writing them):
  - an SVG icon, with a simplified 16 px geometry: thicker legs and a smaller station
  - a regenerated `favicon.ico` at 16 and 32 px
  - a 180 px apple icon: the mark on `ground`
- **Link preview**: an Open Graph image, 1200 × 630 and static at build time, with the mark, the
  tagline and the five lines converging. Every public page uses it.
- **Rule:** this is the only mark. It is never redrawn in another form, and it is animated only
  where it draws itself on the landing hero.

### Brand copy

- `web/lib/brand.ts` gains `BRAND_TAGLINE = "Ogni viaggio ha il suo atlante."` beside
  `BRAND_NAME`. Nothing else spells either.
- `BRAND_DESCRIPTION` becomes the landing's lede: "Da Milano a Lisbona in un pomeriggio di
  lavoro, fatto da altri. Cinque agenti tracciano voli, alloggio, attività e spostamenti, e ti
  lasciano un piano con le date entro cui prenotare."
- The tagline appears in:
  - the landing hero
  - the page metadata and the Open Graph image
  - the empty state of `/plans`, as the invitation's heading

### Rules rewritten in PRODUCT.md and DESIGN.md

- "Don't invent a logo" and "No logo… do not invent them" become: the mark is "A di linee"
  (geometry above), and no other mark exists.
- The tone moves from "a calm control room, not a videogame" to **"a printed night map:
  crafted, alive, never neon"**. Add a named rule, **The No AI Chrome Rule**, banning:
  - glow (`drop-shadow` or `blur()` filters used as light)
  - radial spotlight gradients
  - dot or grid backgrounds
  - gradient text
  - glass beyond the sticky live bar
  - floating blurred shapes
  - sparkle iconography
- "Light is the default" becomes "dark is the default".
- **The Report, Don't Perform Rule** is replaced by the motion rule in section 4.
- The design directions README keeps "Linee" as the base and records "Carta notturna" as its
  2026-10-14 restyle.

## 2. Routes and the front door

### Route map

| Route | Who | What |
| --- | --- | --- |
| `/` | public | The landing, prerendered. |
| `/demo` | public | The self-playing demo run. It never calls the backend. |
| `/plans` | signed in | The plans list, moved here from `/`. |
| `/plans/[id]` | signed in | Unchanged in behaviour. |
| `/new`, `/evals`, `/evals/[id]` | signed in | Unchanged in behaviour; new header. |
| `/dev/*` | development | Unchanged. |

- Every internal link that meant "the list" moves from `/` to `/plans`: the in-app logo, "I tuoi
  piani" back links, and `not-found.tsx`'s way out.
- Login is unchanged. A 401 on `/plans` still goes to TripTracker's `/accedi?returnTo=…`.
- The backend, TripTracker and auth are untouched.

### Returning visitors skip the landing

- `lib/returning.ts` keeps one localStorage flag, `atlas-signed-in`. It holds no personal data.
- The API client sets it after any successful authenticated call and clears it on a 401. Every
  access to it is wrapped in try/catch, so it fails safe to "show the landing".
- An inline pre-paint script on `/` only, in the same pattern as `ThemeScript`, runs
  `location.replace("/plans")` when two things are both true:
  1. the flag is set;
  2. the visitor did not arrive from a same-origin page.

  So a bookmark or a typed URL goes straight to the plans, while clicking the logo inside the
  app still shows the landing.

### Landing (`/`)

It is prerendered and makes no client fetch. Its only client JavaScript is the theme toggle.
Its components live in `components/landing/`.

1. **Hero**, matching the chosen study:
   - the public header
   - the tagline as `h1` in `text-hero`
   - the lede, then "Guarda una corsa" (primary, → `/demo`) and "Accedi" (secondary, →
     `/plans`)
   - the **legend** of the five agents, a line swatch plus one line on each agent's job
   - the **line map**: the five lines draw in, the stations stamp, a live tool plate rises, and
     all lines converge on "Lisbona", whose ring draws once
   - a map margin: the sample trip on the left, coordinates on the right

   The map is pure SVG and CSS, horizontal from 768 px and vertical below it (lines run down and
   converge at the bottom, like the phone's lanes). Under reduced motion it shows its final
   state, still.
2. **Come funziona** (`id="come-funziona"`): three stations on one line, each holding a *real*
   component with sample data:
   - **Descrivi**: the request summary.
   - **Guarda gli agenti**: one lane fragment with a live plate.
   - **Prenota entro la data**: one booking with `DatePair` ("Prenota entro" and "Quando"), a
     price with its source and status, and "Prenota su Expedia".

   The sample uses a fixed `now`, so one deadline is honestly due soon and shows the amber. This
   is the deadline colour doing its one job, on purpose.
3. **Closing**: "Guarda una corsa" again, with "Accedi" and a small "Accesso su invito" beside
   it. Then a footer with the lockup and the tagline.

**Public header** (landing and demo): lockup (→ `/`), "Come funziona" (→ `/#come-funziona`),
"Accedi" (→ `/plans`) and the theme toggle.

**Metadata**: the title is "Atlas · Ogni viaggio ha il suo atlante.", the description is
`BRAND_DESCRIPTION`, and the Open Graph image is the one above.

### Demo (`/demo`)

- **Data**: the recorded `happy-path` run.
  - Events: `lib/plan-events/__fixtures__/backend/happy-path.json`, 120 events.
  - Finished plan: `components/plan/__fixtures__/happy-path.detail.json` and `.trip.json`.
  - Cover: a new `lib/demo/cover.json`, the Lisbon Wikimedia cover with its credit, captured
    once from the local backend.

  None of it carries an email or personal data (checked: no `@` in the files). They stay
  generated files and are imported into the `/demo` chunk only.
- **Seam**: today `PlanScreen` fetches the plan and opens the SSE stream itself. It is split into
  two parts that render the same view:
  1. a presentational `PlanScreenView`;
  2. two data sources:
     - `PlanScreen`: the live data, API plus `usePlanEvents`, behaviour unchanged, current
       tests green;
     - `DemoPlanScreen`: the replay.
- **Replay**: `useReplayEvents(events, { speed })` feeds the same `planEventsReducer`.
  - It compresses the recorded gaps so the run lasts about 45 s at 1×. Each gap is clamped
    between 80 ms and 2.5 s before scaling, and long silences do not stretch the show.
  - The elapsed clock follows replay time.
  - It ends in `ready`.
- **Demo bar**: it takes the place of `InterruptControl`. It reads "Corsa dimostrativa · dati di
  esempio, nessun costo" and holds "Ricomincia", "2×" and "Salta al piano".
- **Finished plan**: the real `PlanView`, with the fixture detail, a `TripLoader` that returns
  the fixture trip, and a cover loader that returns `cover.json`.
  - An info `Notice` says the prices and availability are an example.
  - "Apri in TripTracker" becomes "Pianifica il tuo viaggio" (→ `/new`, which sends a visitor to
    the login).
  - "Prenota su …" links stay real, allowlisted links.
- **No network to the backend**: a test asserts that the demo never constructs or calls the API
  client. The map's OpenFreeMap tiles and the Wikimedia cover are public.
- **Layouts**: the same phone and desktop layouts as the live screen.

## 3. Navigation

One **`AppHeader`** replaces `SiteHeader` and `TopBar` on every signed-in page.

- **Contents**:
  - the lockup (→ `/plans`)
  - the nav items "Piani" (`/plans`, current also on `/plans/[id]`) and "Valutazioni" (`/evals`,
    current also on `/evals/[id]`)
  - "Nuovo piano" (→ `/new`) at the right
  - the theme toggle
- **Current page as a station**: the nav items sit on a thin `rule` line. The current item has a
  filled station node, the others a small hollow node, plus `aria-current="page"`. Hover fills
  the node in `ink-2`.
- **"Nuovo piano"** in the header is always the *secondary* button, so each view keeps its single
  primary. On `/plans` the body's duplicate button is removed. On `/new` the header button is
  hidden, because you are already there.
- **Phone, 393 px**: the mark only, "Piani", "Valutazioni", a 44 px "+" icon button labelled
  "Nuovo piano", and the toggle, all on one line. There is no menu drawer.
- **Live screen**: the header is the slim top row (min 44 px) above the sticky control bar,
  which stays the only sticky and translucent surface.
- **Unchanged**: at most 72 px tall, one line, a visible focus ring, 44 px touch targets.

## 4. Motion

### The rule (replaces "Report, Don't Perform")

**The Motion Tells Something Rule.** An animation ships only if it does one of three things:

1. reports a state change;
2. answers the user's own action;
3. on the landing and demo only, presents the product.

There are no decorative loops. The only loops are three:

- the **train** (an agent is working)
- the turning arrows (reconnecting or busy)
- the skeleton's breathing

There is never a glow. Every animation has a reduced-motion equivalent that keeps opacity and
colour and drops movement in space. Only `transform`, `opacity` and SVG `stroke-dashoffset` (a
named exception, for drawing lines) animate. Phone lanes keep the existing `grid-template-rows`
exception.

New tokens, alongside today's:

- `--ease-pen: cubic-bezier(.65, 0, .35, 1)`, for drawing lines and routes
- `--duration-stamp: 350ms`
- `--duration-roll: 280ms`
- `--duration-route: 260ms`
- `--duration-finale: 1200ms`

### Live run

| What | Normal | Reduced motion |
| --- | --- | --- |
| A new station (`fresh`) | Its segment draws down with `--ease-pen`, 320 ms; then the glyph **stamps** (scale 1.35 → 1 with opacity, 350 ms) and the text fades in. | Glyph and text fade in, 120 ms. |
| The working agent (**train**, replaces the live halo) | A 6 px dot in the line colour, with a ground edge, runs down the last segment toward the live plate, 2.4 s, repeating while a tool runs. | No dot. The plate's "in corso da" carries it. |
| Lane state word ("in attesa" → "al lavoro" → "finito") | The old word rolls up and out and the new one rolls in, 280 ms. | Crossfade, 120 ms. |
| The live plate's tool changes | The new plate slides 8 px out from the line and fades in, 240 ms. | Fade, 120 ms. |
| A wave station ("Ondata 1", "Scelta", "Ondata 2") reached | Its large ring draws with `stroke-dashoffset`, 500 ms. | The ring appears. |
| A message between agents | Its lozenge stamps on both lanes in the same frame. | Fade on both. |
| Cost | The meter fill moves, 400 ms (unchanged), and the figure counts up over the same 400 ms. | Both jump. |
| **Finale** (`ready` seen live) | The five lane lines extend down to a common terminus bar, converge on the destination node ("Lisbona · piano pronto") and its ring draws once (`--duration-finale`). Then the finished plan rises into place, 260 ms. It plays only when the transition to `ready` happens on screen, never when a ready plan is opened. | The terminus and the plan appear with a fade. |

Animations run only on items marked `fresh`. A replayed or reloaded history renders still, so a
300-event run stays legible and cheap. Virtualization past 300 events is unchanged.

### Micro-interactions

| What | Normal | Reduced motion |
| --- | --- | --- |
| Buttons | Press scale as today. On hover the leading icon shifts 2 px, and the external "Prenota su …" arrow nudges up and right by 2 px. | No movement; colour changes stay. |
| Segmented control | The chosen pill slides to the new option (`translateX` of one indicator), 220 ms. | It jumps. |
| Number stepper | The digit rolls up on + and down on −, 200 ms. | It changes in place. |
| "Il tuo viaggio" summary | Its origin and destination stations stamp when the field gets a value. | Fade. |
| Plans list | On the first load the first 8 rows enter in sequence (opacity + 6 px, 40 ms apart). On hover the rail node fills. | No sequence; the hover fill stays. |
| Theme toggle | A View Transition reveals the other theme in a circle growing from the toggle (`clip-path`), 450 ms, "ink spreading". | Instant switch. |

### Page transitions

They use React 19.3's `<ViewTransition>` and Next 16.4's navigation transitions, which need no
library and no configuration (read `node_modules/next/dist/docs/01-app/02-guides/view-transitions.md`
first).

- **The header stays put**: it has its own view-transition name, and its group does not animate.
- **Content** fades with a 12 px slide over `--duration-route`. Links into depth ("Piani" → a
  plan, → `/new`, landing → demo) pass `transitionTypes={["forward"]}`, and back links pass
  `["back"]`, so the slide reverses. Browser back and forward get the plain fade.
- **The plan title travels** from its list row to the plan page heading (a shared name per plan
  id). The list stores the `PlanSummary` it rendered in a small in-memory seed (`lib/plan-seed.ts`),
  so the plan screen has the title on its first commit and the pair forms.
- **The skeleton fades into the content** through a `<ViewTransition>` around the Suspense
  boundary, instead of being swapped.
- **Reduced motion**: fade only. Browsers without the API get today's instant swap.

### Weight

- No animation library is added.
- `/plans/[id]` first-load JS must not grow: it is 189.1 KB gzip today, measured with
  `npm run measure:js`.
- The landing's first load must stay small: no `PlanScreen`, no map, no fixtures.

## 5. What does not change

- **Every booking has two labelled dates**, "Prenota entro" and "Quando", through `DatePair`,
  previews included.
- **Amber** means due within 72 hours and nothing else; it never appears on a button.
- **One hue per agent line**, with the itinerary-day exception as today.
- **The Word Beside The Colour Rule.**
- **Copy**: Italian UI copy in sentence case, buttons that start with a verb, no em dash.
- **Costs** use `formatUsd` and prices `formatEur`.
- **Phosphor bold** icons from the sprite, with no icon package.
- **Accessibility**: WCAG 2.2 AA, a visible focus ring, and `aria-live` only for agent and plan
  state changes. The demo's replayed events follow the same rule.
- **Booking links** open in a new tab with `rel="noopener noreferrer"`.

## 6. Testing and verification

- **`tokens.test.ts`**: the new values in both themes, the DESIGN.md contrast table rewritten
  from the measured ratios, and every pair at or above its threshold.
- **`invariants.test.ts`** keeps its checks and adds **The No AI Chrome Rule** as code. Outside
  an explicit allowlist it fails on:
  - `drop-shadow`, `blur(`, `radial-gradient` and `backdrop-filter`, except the sticky bar
  - `background-clip: text`
- **Reduced motion is enforced**: a test reads `globals.css` and fails if an `--animate-*` token
  or a keyframe used by a component has no reduced-motion override.
- **New unit tests**:
  - the returning-visitor decision (flag × referrer)
  - `useReplayEvents` timing (compression, clamps, 2×, skip) and the final `ready`
  - the demo making no API calls
  - `AppHeader`'s current item and the "Nuovo piano" rules
  - links to the list pointing at `/plans`
  - the finale playing only on a live transition to `ready`
- **Existing tests** that assume the list at `/` move to `/plans`. Live-screen tests stay green
  without changing their assertions.
- **In the browser**, every screen at 393 px and at desktop width, in dark and light, with
  reduced motion checked once per screen:
  - landing
  - demo, through the whole run and the finished plan
  - `/plans`
  - `/new`
  - a live plan
  - a finished plan
  - `/evals`
- **Impeccable critique** at or above 32/40 on each screen, with no open P0 or P1.
- **CI as today**: lint, typecheck, vitest, build, `gen:schemas --check`.

## 7. Out of scope

- A reveal animation for the finished-plan view (itinerary drawing, map tracing).
- Any change to the backend, to TripTracker, to auth or to the plan contract.
- A redesign of the request form beyond the micro-interactions and the palette.
- A redesign of the eval pages beyond the palette and the header.
- Public sign-up or a waitlist ("Accesso su invito" is a sentence, not a feature).

## 8. Delivery order

Five steps, each mergeable on its own with CI green and the browser check done:

1. **Brand system**:
   - tokens for both themes, dark by default, the grain, Semi Condensed 700
   - the mark, lockup, icons and Open Graph image
   - `BRAND_TAGLINE`
   - `AppHeader`
   - PRODUCT.md, DESIGN.md and the directions README rewritten to this spec
   - the No AI Chrome invariant
2. **Front door**: the move to `/plans`, the returning-visitor redirect, the landing and its
   public header.
3. **Demo**: the `PlanScreen` split, `useReplayEvents`, `/demo`, the demo bar and the fixture
   cover.
4. **Live-run motion**: stamps, the train, rolls, wave rings, the cost count-up, the finale.
5. **Micro-interactions and page transitions.**
