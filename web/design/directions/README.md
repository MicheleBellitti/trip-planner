# Live screen: three directions

Three design directions for the live screen of a plan, `/plans/[id]` while it is `running`.
Michele picks one. `impeccable document` then fixes the chosen one as tokens in `web/DESIGN.md`
(spec, "Interfaccia e design", step 3). Nothing in this folder is production code. Each page is a
static design study.

| Page | Direction | In one line |
| --- | --- | --- |
| [`1-linee/`](1-linee/index.html) | **Linee** | The run drawn as a transit line diagram. Each agent is a line, each event a station, each message an interchange on both lines, and the live tool is the "you are here" plate at the end of its line. |
| [`2-partitura/`](2-partitura/index.html) | **Partitura** | The run set as a conductor's score. The parts sit side by side and time runs down in one-minute bars shared by all five, so parallel work lines up. Messages are cues drawn across the parts, and a running tool is a held note that grows down to the "adesso" line. |
| [`3-sala/`](3-sala/index.html) | **Sala** | The calm control room, read literally. A night-blue shell holds the plan and the five bays. Each bay's live activity is a strip held up across the shell's edge, and finished steps drop into the rack below it, newest on top. |

## How to look at them

Each page is self-contained, with inline CSS, JS and icons. The fonts load from Google Fonts. You
can open `index.html` straight from disk, or serve the folder:

```sh
cd web/design/directions && python3 -m http.server 4817   # then http://127.0.0.1:4817/1-linee/
```

- **Theme.** The page follows `prefers-color-scheme`. The round button in the header switches
  to the other theme and remembers it in `localStorage` (`tp-theme`, shared by the three pages
  when they are served from one origin).
- **Layout.** At 1080 px and wider the five lanes sit side by side. Below that they stack, with
  the active lane (voli) open and the others collapsed to one line that shows their current tool
  or how they ended. The spec's 393 px phone is the reference width.
- **"Simula i prossimi eventi"** (page footer, prototype only) plays the next 8 seconds of the
  run. Voli finishes and reports, the coordinator picks flight and lodging, wave 2 starts, and
  spostamenti goes to work. This shows each direction's motion and its `aria-live`
  announcements ("Voli: finito", "Spostamenti: al lavoro"). Press it again to return to the
  snapshot.
- **"Interrompi"** opens an inline confirmation. Confirming it puts the plan in "In interruzione".

## What all three share

All three pages render the same synthetic snapshot from the same data object, so the comparison
is about design, not content. The snapshot is a production-profile plan (400 ¢ budget), 7:12
after it started: Milano → Lisbona, 14–18 nov 2026, 2 adults and 2 children aged 8 and 11, a
2,400 EUR budget. In it:

- **Header**: plan status ("In corso"), elapsed time ticking every second, cumulative cost
  (1,62 $) on a meter that ends at the session budget (4,00 $), "Interrompi" with
  confirmation, theme toggle.
- **"Stream in riconnessione. Gli eventi persi arrivano da soli."**: one discreet line under the
  header. It is not an `aria-live` region.
- **Five lanes** in the spec's order (coordinatore, voli, alloggio, attività, spostamenti), with
  all four states. Coordinatore and voli are *al lavoro*, alloggio is *finito*, attività is in
  *errore* with its partial result saved and the coordinator carrying on, and spostamenti is
  *in attesa*. Every state is a word plus a glyph, never colour alone.
- **Current tool chip** with its main parameters: "Expedia · voli MXP→LIS · 14–18 nov", plus
  how long it has been running.
- **MCP source warning** on the voli lane: "Kiwi non risponde dopo 2 tentativi. Cerco su
  Expedia e lastminute.com." It is a lane note, not a plan error. The two failed Kiwi calls stay
  in the event list.
- **Inter-agent rows** such as "coordinatore → voli: incarico", which open to show the message
  text. The text is in English, as the agents write it to each other, and is marked `lang="en"`.
  Each message shows in both lanes it connects. The backend sends one event per lane, so this is
  a reducer choice in the frontend.
- **Booking preview strip**: two bookings from a finished plan, each with two separate
  labelled dates, "Prenota entro" and "Quando". Each also shows price, verified or estimated
  status, source and retrieval time, and a "Prenota su <sito>" link
  (`target="_blank" rel="noopener noreferrer"`). The lodging deadline (mer 14 ott, two days from
  "today", 12 ott) is due soon, so it is the **only amber on the page**. The flight deadline (ven 30
  ott) is not due soon and stays neutral. Amber never appears on a button.
- **Accessibility**: keyboard reachable (lane toggles are buttons, messages are
  `<details>`), a visible focus ring, a meter with `aria-valuetext`, and `aria-live="polite"`
  only for agent state changes. Every animation has a reduced-motion version (below).
- **Icons**: Phosphor Icons 2.1.1 (MIT), inlined as an SVG sprite with a provenance comment.
  Each direction uses its own weight: bold for Linee, light for Partitura, regular for Sala.

The knobs are the spec's: layout variance 5, motion 5, density 6. That means more density and
less show than a landing page.

## Side by side

| | 1 Linee | 2 Partitura | 3 Sala |
| --- | --- | --- | --- |
| Colour strategy | Full palette: one line colour per agent on a cool neutral ground | Restrained: graphite on paper, one verdigris for "live" | Committed: a night-blue shell carries the top third of the screen |
| Type pairing | Barlow Semi Condensed (lane names, title) + Barlow (text), from road-sign lettering | Red Hat Text (text) + Red Hat Mono (times, durations, cost, bar numbers) | Archivo on its width axis: expanded 118 % for the title, condensed 75–88 % for strips, normal for prose |
| Lane shape | A vertical line with stations; the live plate closes the line | A column ("part") in a shared minute grid; cues cross the columns | A bay: held strip on top, rack of strips below |
| Event order | Oldest at top, live at the bottom | Oldest at top, by minute, aligned across lanes | **Newest at top** |
| Where "now" is | End of each line | One horizontal "adesso" line across all parts, plus held notes | One row of held strips across the top of all bays |
| Rhythm / density | Medium. Station rows about 40 px with generous gaps, the airiest of the three | Densest and most regular: hairline bars, mono figures, equal columns | Dense and boxed: 38 px strips with field rules, tight 4 px gaps |
| Corners | Soft (10–16 px), round roundels and nodes | Nearly square (2–4 px) | Small (4–8 px), strip-like |
| Signature motion | The line draws down to a new station, and the live node sends a slow halo | The "adesso" line descends one second at a time, and held notes grow to meet it | New strips drop into the rack, and the held strip's hairline fills with time spent |

## 1 Linee

**Thesis.** You read a metro line without thinking: where it started, which stops are behind,
where you are now. Every agent gets its own line, and the five lines together are the run.

**Palette** (contrast measured on the surface each element actually sits on, WCAG 2.x):

| Token | Light | Dark | Contrast light / dark |
| --- | --- | --- | --- |
| ground | `#F2F4F7` | `#0C121B` | |
| surface (lane cards, booking fields) | `#FBFCFD` | `#131B26` | |
| ink | `#0F1A2A` | `#E6EBF2` | 17.02 / 14.46 on surface, 15.86 / 15.68 on ground |
| ink-2 (secondary text) | `#4B5768` | `#9BA7B8` | 7.14 / 7.10 on surface, 6.66 / 7.70 on ground |
| line: coordinatore | `#33404F` | `#A9B6C7` | 10.29 / 8.42 |
| line: voli | `#1F55C4` | `#7AA2F7` | 6.48 / 6.88 |
| line: alloggio | `#0F7348` | `#43C08A` | 5.73 / 7.54 |
| line: attività | `#6D3FC0` | `#B497F5` | 6.55 / 7.16 |
| line: spostamenti | `#08707F` | `#3FC0D3` | 5.63 / 7.99 |
| plate text on line colour | `#FBFCFD` | `#0C121B` | ≥ 5.63 / ≥ 7.46 (worst: spostamenti / voli) |
| error | `#B3261E` | `#F2766B` | 6.36 / 6.25 on surface, 5.61 / 6.23 on its wash |
| amber (stroke only) | `#C47A0B` | `#F3A845` | 3.33 on surface, 3.01 on amber wash |
| amber-ink (deadline text) | `#8A4A00` | `#F3A845` | 6.03 / 7.92 on amber wash |
| control borders (rule-strong) | `#7A8597` | `#5F6C7E` | 3.39 / 3.52 on ground |

**Type.** Barlow Semi Condensed 600 for the title and lane names, Barlow 400/500/600 at
14.5–15 px for everything else, tabular figures throughout. Both come from highway-sign
lettering, which suits a diagram that is read in motion.

**Rhythm.** The airiest of the three. Stations are spaced like a printed line map, with a
2.6 rem time gutter, a 1.5 rem track and the label. On desktop the coordinator's line is 1.3×
wider than the four branches. On the phone each lane is a rounded card.

**Lane shape.** A 5 px line in the agent's colour. Station glyphs: a hollow ring for a tool call
(red ring if it failed), a bar for a status ("Al lavoro", "Finito"), a lozenge with an ink
border for an interchange (message), and an ✕ that breaks the line for an error. The live
station is a plate filled with the line colour, with a dashed stub below it for "next stop". A
waiting lane is a dashed line with nothing on it yet.

**Motion.** A new station draws its segment down (320 ms, expo out), then its label fades in.
The live node sends a slow halo (2.6 s) while the tool runs. The reconnect icon turns slowly.
**Reduced motion:** no halo, no drawing and no rotation. New stations fade in over 120 ms, and
the cost meter and lane toggles jump instead of sliding.

**Trade-offs.**
- (+) The most legible at a glance, and the most familiar travel language. Agent identity
  (one colour each) could carry into the finished plan, tagging each booking with the line that
  found it.
- (+) It maps directly onto the spec's chosen component, Dice UI's Timeline (a vertical line
  with completed, active and pending items), so the build cost is the lowest.
- (+) The best phone view. Lanes as cards, the open lane is a clean line, and the collapsed ones
  show the live tool in one line.
- (−) The biggest colour budget: five line hues, error red and amber. The hues were picked to
  avoid orange and yellow so amber stays unambiguous, but the screen is the least calm of the
  three.
- (−) Oldest-first means a long lane's live plate can fall below the fold on a 1280×800 desktop.
  The coordinator's lane does at 7:12. A fix would be to repeat the live tool under the lane
  name on desktop.

## 2 Partitura

**Thesis.** The product's mechanism is a coordinator cueing four parts that play at the same
time, in two waves. A score is the one notation built for exactly that. Bars make
simultaneity visible: things that happen in the same minute sit on the same row.

**Palette:**

| Token | Light | Dark | Contrast light / dark |
| --- | --- | --- | --- |
| ground (paper) | `#F3F3F0` | `#111213` | |
| surface | `#FAFAF8` | `#18191B` | |
| ink (graphite) | `#18191B` | `#ECECE8` | 15.82 / 15.83 on ground |
| ink-2 | `#55585D` | `#A3A6A8` | 6.42 / 7.66 on ground |
| accent (live: held notes, "adesso") | `#0B7566` | `#4CC2AE` | 5.04 / 8.60 on ground |
| accent-ink on the live chip | `#0A6658` on `#DCEDE8` | `#4CC2AE` on `#15302B` | 5.67 / 6.47 |
| error | `#B42318` | `#F27A6E` | 5.91 / 6.95 on ground |
| amber (underline stroke) | `#C27C0E` | `#F2AA48` | 3.05 / 9.48 on ground |
| amber-ink (deadline text) | `#8C4D00` | `#F2AA48` | 5.95 / 9.48 on ground |
| staff lines / control borders | `#848781` | `#6C7073` | 3.28 / 3.75 on ground |

**Type.** Red Hat Text 400/500/700 (an italic for status lines, the way a score writes "a tempo")
and Red Hat Mono 400/500 for every measured value: times, durations, bar numbers, cost and the
large elapsed clock. Mono is used for measurement here, not as a "technical" costume.

**Rhythm.** The densest and most regular. Equal columns with a hairline staff line on each,
an 86 px gutter of bar numbers (`0'` to `7'`) and rehearsal marks ("Avvio", "Ondata 1",
"Scelta", "Ondata 2"), and nearly square corners. A part that finished closes with a final
double bar line. A part in error is washed in a faint red from the next bar on. A waiting part
is one long dashed rest.

**Lane shape.** A column in a shared grid. On the phone the grid can't hold, so each part
becomes a stacked block that keeps its own minute gutter, and the held note lies flat as a bar
under the running tool.

**Motion.** All of it is driven by data, with no loops. The "adesso" line descends through the
current bar one second at a time. Held notes (running tools) grow down to it. Cues and events
fade in, rising 4 px. **Reduced motion:** events fade only, and toggles and the cost ruler stop
animating. The "adesso" line and held notes keep updating, because they are information that
moves about 1 px a second, not animation.

**Trade-offs.**
- (+) The only direction that shows timing. You can see that voli has been stuck on sources for
  three minutes while alloggio finished, and when each wave started.
- (+) The calmest palette, with colour spent only on "live", error and the deadline. The best
  fit for "a calm control room" and density 6.
- (−) The desktop and phone versions are two different renderings of the same reducer state,
  so it costs the most to build. The grid also does not fit the spec's Dice UI Timeline
  component, and virtualizing past 300 events means virtualizing minute rows across five
  columns.
- (−) Empty cells. Quiet minutes still cost a row, so the page is longer.
- (−) Cue arrows are delicate at 1080–1280 px, where labels wrap inside narrow spans.

## 3 Sala

**Thesis.** The brief's own metaphor: a calm control room. What is happening now is held up,
one strip per bay in a single row across the top. Everything already done drops into the
racks below, newest first.

**Palette:**

| Token | Light | Dark | Contrast light / dark |
| --- | --- | --- | --- |
| shell (night blue) | `#1B2440` | `#18213C` | |
| shell-ink | `#EEF1F8` | `#E9EDF7` | 13.53 / 13.56 on shell |
| shell-ink-2 | `#AEB8D2` | `#A7B1CC` | 7.71 / 7.42 on shell |
| shell-live (state "Al lavoro", cost segments) | `#8DB7FF` | `#8DB7FF` | 7.54 / 7.83 on shell |
| error on shell (desktop bay state) | `#FFB4AB` | `#FFB4AB` | 9.01 / 9.36 |
| ground | `#E7EBF3` | `#0C1120` | |
| surface (strips) | `#FBFCFE` | `#141B2E` | |
| ink | `#141A2B` | `#E6EAF4` | 16.87 / 14.23 on surface |
| ink-2 | `#4D576C` | `#A1ABC2` | 7.07 / 7.44 on surface, 6.07 / 8.17 on ground |
| live (held strip time field) | `#2C5FD0` on `#E3EBFB` | `#8DB7FF` on `#1A2747` | 4.80 / 7.26 |
| error | `#B42318` on `#F8E4E1` | `#F27A6E` on `#2D1719` | 5.38 / 6.24 |
| amber (outline) | `#B87308` | `#F2AA48` | 3.24 on amber wash |
| amber-ink | `#8C4D00` on `#F8EBD3` | `#F2AA48` on `#2B2112` | 5.61 / 7.99 |
| cost segment on vs off | `#8DB7FF` vs `#34406A` | `#8DB7FF` vs `#313C63` | 4.96 / 5.29 |

**Type.** Archivo alone, played on its width axis. The plan title is expanded (118 %), strip
fields are condensed (75–88 %) so long tool titles fit narrow bays, and prose stays at normal
width. The large condensed clock reads like a station clock.

**Rhythm.** Dense and boxed. Strips are 38 px with hairline field rules (time | title | duration),
4 px apart. The shell takes the top third of the screen on desktop. On the phone, each collapsed
bay still shows its held strip, so all five agents' current state fits on one screen.

**Lane shape.** A bay: a header on the shell, the held strip straddling the shell's edge (live
tool, or the outcome: a ✓ summary, an ✕ error, a dashed "in attesa"), then notices, then the
rack. Messages are tinted strips. Status changes are dashed divider strips.

**Motion.** A new strip drops into the rack (8 px, 300 ms). The held strip's bottom hairline
fills with the time spent on the tool, on a scale that slows down and never reaches the end, so
it says "how long", not "how much is left". The reconnect icon turns. **Reduced motion:** strips
fade in over 120 ms, the hairline jumps instead of easing, and the icon stands still.

**Trade-offs.**
- (+) "What is happening now" is always above the fold, for all five agents at once, on both
  desktop and phone. This is the strongest answer to the live screen's first question.
- (+) The strongest identity. The committed shell is very different from TripTracker's pine and
  paper, and the dark theme is the best of the three.
- (−) Newest-first reverses the story: to read how the run unfolded you scan upwards. The spec
  only asks for time order, but it is the less natural one for a log you read once.
- (−) The most boxes: strips inside bays on a shell. It is the closest of the three to a generic
  ops dashboard, and the hardest to keep from tipping into "costume" (the strip metaphor must stay
  a type and density choice, never fake hardware).
- (−) In light mode the dark shell on a phone is heavy. Half the first screen is night blue.

## Recommendation

**1 Linee**, with two borrowings that cost little:

1. From Sala, keep the live tool visible under each lane's name on desktop, so the "you are
   here" plate is never below the fold.
2. From Partitura, put the waves on the coordinator's line as named stations ("Ondata 1",
   "Scelta", "Ondata 2"), so the shape of the run is readable without a time grid.

Why Linee:

- **Phone first.** The spec makes 393 px the reference, and Linee has the best phone view. Its
  lane cards scan like a list and the open lane reads like a line.
- **It fits the components the spec already chose.** Dice UI's Timeline is a vertical line with
  completed, active and pending items, which is Linee's lane. That keeps the 180 KB JS target
  and the "virtualize past 300 events" rule simple (one list per lane). Partitura would need a
  bespoke grid.
- **It is the clearest at a glance.** The colour per agent costs calm, but it pays for itself in
  recognition across five lanes. With orange and yellow kept out of the line palette, it does not
  dilute the deadline amber.

Choose **Partitura** instead if most watching happens on the Mac and "who waited on whom, and for
how long" is what you want to learn from a run. It is the calmest and the most honest about
time. Choose **Sala** if the dark, night-blue identity matters more than reading the story, or if
you most often check a running plan from the phone in passing: its collapsed bays show all five
agents' state at once.

## How these were made

- `web/PRODUCT.md` comes from `impeccable init`. No interview could run in this session, so it was
  answered from the spec and CLAUDE.md, and the inferred facts are marked *(inferred)*. Check
  them: the due-soon window (72 h, from TripTracker's "In scadenza"), the cost unit (dollars),
  and the on-screen product name.
- `impeccable concept-seed --scope direction --mode operate` (seed `b1aed68e`) assigned the
  third of my seven grounded candidates, which is Linee. Partitura was my own top-ranked
  candidate. Sala is the brief's literal metaphor, which gets one slot at most. The roll's
  catalog challengers were weighed and none was adopted wholesale. One was borrowed, the
  spectrogram rail, whose rule is that state is carried by line form and not hue: Linee's
  solid, dashed, ring and broken lines, and Partitura's rests and double bars.
  From the Labanotation score, Partitura borrowed "length is duration" (held notes).
- `design-taste-frontend` set layout variance 5, motion 5 and density 6. Its landing-page rules
  (hero, imagery, logo walls) don't apply to a working screen and were not used. Its anti-default
  rules were: no em dashes, no eyebrows, no gradient text, no AI-purple, one radius system per
  page, and the copy audited.
- Event titles keep the spec's own format, "Expedia · voli MXP→LIS · 14–18 nov", with an en dash
  for the date range and two middle dots. They come from the backend's `normalize`, and they are
  the spec's example. There are no em dashes anywhere.

## Visual QA

Checked in a browser (the Claude desktop browser pane, pages served from this folder) at 393×852
and 1440×900, in light and dark, plus 1280×800 light. A scripted check at 393, 768, 1080, 1280
and 1600 px found no horizontal overflow on any page. The "Simula i prossimi eventi" playback was
run on all three (Partitura and Sala at desktop, Linee at 393 px), with no console errors.
Found and fixed: Sala's shell band overflowed horizontally on desktop, Partitura's sticky bar
overflowed at 393 px, Partitura's rehearsal marks wrapped, and Linee's sticky bar did not stick
on the phone. A few control borders were below 3:1 and were raised.

`impeccable detect` ends with three `cramped-padding` warnings, reviewed as false positives. Two
are the desktop header bars, whose desktop rule removes the border it is measured against. The
third is Sala's shell, whose bottom edge runs behind the held strips by design. The earlier
findings were fixed: pulsing dots, a side-stripe accent, a marquee-like progress loop, hairline
borders with wide shadows, and hatched stripes.

Not done:

- **Reduced motion** was checked by reading the CSS. It could not be emulated in the pane.
- **No `impeccable critique`** has been run (the 32/40 gate). It belongs to the chosen direction
  once it is built as real screens in `web/`.
