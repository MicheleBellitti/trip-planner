---
target: "/plans/[id] finished plan (status ready): cover band, itinerary map, days, bookings"
slug: id-ready-covers-map
total_score: 30
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 1
---

⚠️ DEGRADED: single-context (no sub-agent/Task tool is exposed to this agent, so Assessment A and B ran sequentially in one context; A was written down before `impeccable detect` ran)

# Critique: finished plan with cover band and itinerary map

Surface: demo plan `6535b90d-702b-482f-a541-e6bf6bcdd9a1` (Lisbona in famiglia, 14–18 aprile 2027, ready, 19 stops, 11 with coordinates, 5 bookings). Viewed at 393x852 and 1440x900, light and dark, with the map's day picker, a station card, and the list-to-map click exercised. Judged against `web/DESIGN.md` (sections "Map" and "Cover photos"), `web/PRODUCT.md`, CLAUDE.md UI rules, and Michele's complaint that the UI felt bare. Mode: Operate. Previous round for this screen: `plan-round3.md` (32/40, before covers and map).

Browser note: the tab cap was reached (other agents' tabs), so `tabs_create` failed; the first `navigate` opened `tab-15`, used for every call. Viewport reset to desktop at the end. The dev server's first paint of a plan takes 7 to 10 s of skeleton in dev mode; not judged.

## Design Specificity Verdict

**LLM assessment (written before the detector ran).** Yes, it now has a sense of place, and it is authored for this product rather than borrowed. Three things carry it: (1) the real Lisbon photo in a fixed-height band, with the credit as a plain caption and the destination on a flat surface plate (never bare text on the picture); (2) the map drawn in the Linee vocabulary, each day a line in one of the five hues, stations as rings, the lodging as the large ink ring, the basemap restyled from the tokens so it reads as part of the page; (3) the legend as day picker, which reuses the pill and `aria-pressed` pattern of the rest of the product. The calm survives: still no cards-in-cards, no shadows except the station card that floats, no amber, no confetti. In dark the map is better than in light (water and land separate, rings glow).

What keeps it from being excellent: the map is a picture of the trip that cannot be read as a map. Stops have no labels or numbers, the downtown stops pile onto each other because one outlier (Sintra, Giorno 3) sets the zoom, and the list and the map are two separate pages that happen to be stacked (a click in the list changes a map that is scrolled out of view). The cover is a good first impression but costs the phone the "Da prenotare" entry point that round 1 fixed.

**Deterministic scan.** `impeccable detect --json web/components/plan web/app/plans` returned `[]` (exit 0). No em dash in the new components' strings (checked with grep). No false positives to dismiss. No browser overlay injected: the harness gives a read-only pane and the detector found nothing to show.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | Cover and map both hold their place with a same-size skeleton and nothing jumps. The map's "Caricamento della mappa…" is read to screen readers. No message when 8 of 19 stops are missing from the map except in the sr-only summary. |
| 2 | Match system / real world | 4 | A real photo of the place, Italian place names on the basemap, the credit and license a reader recognises, "Alloggio" legend. |
| 3 | User control and freedom | 3 | Day toggles can be undone, the station card has a close button, the wheel never traps (Ctrl or two fingers to zoom). The Lisbon end of a selected line can end up under the zoom buttons. |
| 4 | Consistency and standards | 3 | Pills, rings and hues reuse the system and the doc says why days borrow agent hues. The only departure is the plate on the photo, which is consistent with "text on a photo is never bare". |
| 5 | Error prevention | 3 | Fixed frames, no WebGL notice, no basemap fallback line. |
| 6 | Recognition rather than recall | 2 | The map has no station labels or numbers: to know which ring is which you tap one at a time, and the stack of 4 rings in downtown Lisbon cannot be tapped apart on a phone. The list gives no sign of which map ring it is. |
| 7 | Flexibility and efficiency | 3 | Canvas takes arrows and +/-; the legend is the keyboard path. Stations are not focusable, so the station card is pointer-only; the list click-to-select works but is invisible when the map is off screen. |
| 8 | Aesthetic and minimalist design | 3 | Calm and now has character. On the phone the cover plus a 530 px map block before day 1 lengthen the page (5,737 px, was about 5,024). The destination appears three times above the fold: h1, the plate, the photo's alt. |
| 9 | Error recovery | 3 | No photo: band not drawn. No WebGL: Notice pointing to the list. Light basemap blurs water and land (see P2). |
| 10 | Help and documentation | 3 | Cooperative-gesture hints in Italian, region label plus a real text summary of the map. |
| **Total** | | **30/40** | **Good** (was 32/40 before covers and map; the two additions raise the sense of place but add the P1 and three P2 issues below) |

## Overall Impression

The brief was "too bare, can we do better". The answer is yes: a first-viewport photo and a line map give the page a place and a personality that the previous four rounds of polish could not. It still feels like Atlas. The single biggest opportunity is to make the map earn its 530 px: label the stations, fit it to where the trip actually is, and tie it to the list (on desktop, keep it on screen next to the days).

## What's Working

1. **The cover plate and credit.** Surface plate with ink text over the lower left corner, a scrim underneath, the license as a caption at 12.5 px in ink-2 (6.66:1). Contrast is the token's whatever the picture is, in both themes, and the legal credit is never hidden. The same-size `bg-notice-wash` frame means nothing moves when the photo arrives.
2. **The map speaks Linee.** Rings, 4 px lines with a surface casing, the large ink ring for the hotel, legend swatches that match the lines, no POIs, no road names, no colour for status. In dark it is excellent.
3. **Restraint held.** No amber anywhere new, no shadow except the floating station card, no decorative motion, `fetchPriority="low"` on the photo so the data wins, the map loaded only when near the viewport.

## Priority Issues

### [P1] The map is unlabelled and zoomed to the outlier, so most of the trip is an unreadable clump
- **What**: "Tutti i giorni" fits the bounds of all located stops. Giorno 3 (Sintra, 25 km west) stretches the box, so the 9 other stops sit in about 15 % of the frame; on the phone four rings overlap in Baixa and cannot be told apart or tapped apart (393 px: the Day 1, 4 and 5 stations stack within about 20 px). There are no numbers or names on the rings, and Day 5 shows a single dot with no line. The Giorno 3 line is a straight chord from Sintra to Rossio.
- **Why it matters**: the user asked for a sense of place; today the map reads as "coloured lines over grey" and the information is still in the list. Michele cannot answer "where is the hotel relative to Belém?" from it, which is what a map is for.
- **Fix**: (a) fit "Tutti i giorni" to the core cluster: drop stops farther than about 2.5x the median distance from the lodging from the fit box, then show them with an edge pointer or a quiet chip "Fuori mappa: Sintra (Giorno 3)" that selects that day. (b) Give each ring a short visible label at zoom >= 12 (the stop's number in the day, 1..n, in `text-micro` on a surface halo; the list's time gutter can carry the same number) and let the station card list the day's stops. (c) On a day pick, add right padding for the zoom control (about 56 px) and bottom padding for the station card so the line's end is never under them (Giorno 3's Lisbon end is hidden under the + button on the phone). (d) Draw the lodging label "Hotel" next to the large ring.
- **Suggested command**: `/impeccable layout` (fit and padding) then `/impeccable shape` for the station numbering.

### [P2] The map and the list are not tied together where it counts
- **What**: the list-to-map link exists (clicking a day in the list selects it and underlines the title) but the map is not sticky, so on desktop at the list the map is 1,181 px off screen and the only feedback is a 3 px underline. On the phone the pill selects a day but the list does not move or mark anything visible.
- **Why it matters**: the two halves of the feature feel like separate widgets. The desktop layout already has a sticky right column ("Da prenotare") that spans the days; the map would be the natural second occupant of it.
- **Fix**: at `lg`, move the map into the sticky right cell under "Da prenotare" and "Apri in TripTracker" (28 rem wide, height about 20 rem) or make it its own sticky cell that follows the days; keep it in the flow on the phone. Add a visible `aria-live=polite` line under the legend ("Giorno 3: 2 tappe sulla mappa") and have the station card's title link to its row ("Vai alla tappa").
- **Suggested command**: `/impeccable layout`.

### [P2] Phone: the cover pushes "Da prenotare" back out of the first viewport (round 1's P1 reopened)
- **What**: on 393x852 the "Da prenotare" heading is at y=822 and the first row at about 850; before covers it was at y=564 with all five rows by y=830. The cover band is 218 px and the credit adds 38 px, above 160 px of summary prose.
- **Why it matters**: PRODUCT.md's success measure is "knows by when each one must be booked". The photo is nice but the task is the booking, and the fix for that task was the single most valuable change of round 3.
- **Fix**: shorten the phone band from 11 rem to 8 rem (the photo is a 16:10 crop at 360 px, `object-position` centred on the skyline), set the credit on the same line as the plate's corner only at lg (keep the caption, 2 lines, on the phone), and put "Da prenotare" above the summary prose and the facts on the phone (the strip is a compact list, the prose is 6 lines). Target: heading and first two rows visible at 852 px.
- **Suggested command**: `/impeccable layout`.

### [P2] The light basemap blurs water and land
- **What**: `water` is `ground` mixed 85 % toward `rule`, `land` is `ground`; in light the Tagus estuary is a barely darker grey and the teal Belém stations look as if they are in the river. In dark the same recipe works (water darker than land).
- **Why it matters**: the geography is what the map adds; if the one big river is invisible, the map does not orient.
- **Fix**: in `style.ts` make light water a cool step with a hint of the surface hue (for example `mixColors(ground, line-flights, 0.12)` or `notice-wash`) and keep roads and buildings as they are; keep water labels. Re-measure that line strokes keep 3:1 against it (tokens table: worst light stroke 5.24 on ground, the new water is darker, check).
- **Suggested command**: `/impeccable colorize`.

### [P3] Station card and keyboard
- **What**: stations are not focusable and the card opens by pointer only (the canvas takes arrows and +/-, the legend is the keyboard way to choose a day). The canvas also carries `role=region` and the label "Mappa delle tappe" inside the wrapper with the same role and label, so a screen reader announces two landmarks of one name. Zoom buttons are 40 px (DESIGN.md says 44 px minimum for touch on the product; the lanes' own targets are 44).
- **Fix**: remove `role`/`aria-label` from the canvas (maplibre sets them; strip them or label it "Mappa interattiva"), expose the day's stops as a list of buttons inside the card or a visually hidden list so a keyboard user can open a station, and make the zoom buttons 44 px with 8 px of space.
- **Suggested command**: `/impeccable harden`.

### [P3] Cover: crop, brightness, and a repeated name
- **What**: at 1440 the band is 1384x313 over a 1426x914 photo (the crop keeps 31 % of the height: roofs and no skyline); the photo is the brightest object on the page in dark (nothing dims it beyond the scrim at the foot); the plate repeats the destination that the h1 says directly above ("Lisbona in famiglia, 14–18 aprile 2027" then "Lisbona, Portogallo"). The photo's strong yellows and reds sit at the same weight as the five line hues, but they are content, so it is acceptable.
- **Fix**: `object-position: center 35%` or the file's own focal point if the API gives one; `filter: brightness(.88)` on the photo only in dark; keep the plate (it is the only place the country appears) or drop it on the phone where the h1 is already adjacent. Keep the band height on desktop at 18 rem but cap the aspect ratio to 4:1 for panoramas.
- **Suggested command**: `/impeccable polish`.

## Persona Red Flags

**Michele on the iPhone, one-handed, checking what to book (primary).** Opens the plan: sees the photo, the title, "Pronto", then reads six lines of summary before "Da prenotare" at the very bottom edge. Needs a scroll to see his deadlines; the earlier round had it on the first screen. Scrolling through the map on the phone, a one-finger drag scrolls the page (good), but the downtown stack is not tappable.

**Michele on the Mac, planning the days (primary).** Sees the cover and bookings together in the first 900 px (good). Clicks "Giorno 4" in the list and nothing visible happens on the map, which is far above; scrolls back up and finds Belém selected as two teal rings in what looks like the river.

**Sam (screen reader / keyboard).** The region announces its summary (good), then the canvas announces the same label again. Cannot open a station card or hear which stop is where except through the list (acceptable, the list is primary, but the card's content is not reachable).

## Minor Observations

- Legend: "Tutti i giorni" plus five day pills plus "Alloggio" is 7 controls in a row under the map on the phone (over the 4-option guideline, but they are one toggle group, readable, and wrap in two rows; if trips get to 10 days it becomes a wall. Past 6 days, collapse to a day scrubber or a select).
- The station card covers a third of the phone map when open; place it above the legend rather than over the frame, or limit it to a single line.
- The credit ("Foto: Vitor Oliveira from Torres Vedras, PORTUGAL, CC BY-SA 2.0, Wikimedia Commons") is long; keep it but remove "PORTUGAL"-style shouting only if the source allows (the author string is the author's own, so leave it).
- `sizes` says `100vw` below 1080 and the 960 px file is used even on a 393 px phone at 2x (about 80 KB of image); fine, but `250`/`500` widths exist for thumbnails only.
- Reduced motion: map camera moves have duration 0 under the media query (not exercised in the emulator, confirmed in code at `itinerary-map-gl.tsx:73`).
- No cover on `/plans/[id]` for running plans, as designed; the home list was not in scope for this round.

## Questions to Consider

- If the map's job is orientation, would one hotel pin and the day's first and last stop be enough, with the list carrying the rest?
- What if the cover were only on desktop and the phone kept the booking strip in the first screen, with the photo as the quiet header of the days section?
- Should a day in the list show a small swatch of its map line, so the two views are visibly the same thing?

## Verdict on the user's complaint

Not bare any more, and still calm. Score 30/40 (32/40 before the additions): the covers and map earn their place; the next step is making the map readable and connected, and giving the phone its booking entry back.
