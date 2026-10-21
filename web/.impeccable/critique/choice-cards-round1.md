---
target: the choice cards (the live plan page's pause on /plans/[id], phone and desktop; the demo's pause on /demo)
slug: components-choice-choice-panel-tsx
round: 1
total_score: 30
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
---

⚠️ DEGRADED: single-context (the task's brief forbids sub-agents; Assessment A was written down before the detector ran, then Assessment B)

# Impeccable critique, round 1: the choice cards

Screens: `components/choice/choice-panel.tsx`, `components/ui/choice-card.tsx`, `components/ui/countdown.tsx`, inside `components/live/plan-screen-view.tsx` (live) and `components/demo/demo-plan-screen.tsx` (demo). Seen in the browser at 393x852 and 1440x900, dark and light, against the local demo backend (`DEMO_MODE`, `?demo_scenario=choices`, `DEMO_PACE=0.5`, `CHOICE_TIMEOUT_SECONDS` 40, then 120 for the one-minute note) and on `/demo`:

- live, phone dark: the activities question (cards without photos: the demo backend looks none up), two picks and "Continua con queste", then the food question left to time out;
- live, desktop: "Scegli tu" (dark), a reload during the food question (light), keyboard picks and "Continua con questa";
- live, phone light with reduced motion: the 2-minute window, "Manca un minuto per scegliere." at 1:00, "Interrompi" during the pause;
- `/demo`, phone dark: a passive watch through both pauses; the photo credits opened; desktop light: a visitor's pick, then the food question left to the recording.

Judged against DESIGN.md ("Choice cards", "Demo", Motion), PRODUCT.md, the spec's §2 "The experience" and §7 anti-goals, and the plan's decisions.

Browser notes (harness, not defects of the page): the Mac went into maintenance sleep between tool calls (15 minutes at a time), which froze the backend's replay and the browser's clock, so a few runs show elapsed times like "16:55"; a `caffeinate -s` kept it awake for the rest. The Next dev indicator covers the countdown's clock glyph at the bottom left on the phone; dev only.

## Design health score: 30/40 (Good; no P0, no P1; two below the 32 gate)

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | The plate "Tocca a te: scegli cosa vedere" on the coordinator's line, the tab title "Tocca a te ·", the count, the countdown and its bar all report. But on a desktop window the countdown and the buttons arrive below the fold (P2), and on the phone the traveller's answer lands inside the closed coordinator card: after "Continua" nothing on screen says what was chosen (P2) |
| 2 | Match system / real world | 3 | Plain Italian: "Cosa ti va di vedere?", "2 h 30 min", "60,00 €" for the group, no "gratis". "Scegli tu" right after "Scegli quelle che ti piacciono" uses one verb for two people (the spec's copy) |
| 3 | User control and freedom | 3 | Picks undo with a second tap, "Scegli tu" hands it back, "Interrompi" still works during a pause and the panel goes at once. An iPad crossing 1080 px remounts the panel and loses the picks |
| 4 | Consistency and standards | 3 | Tokens, ink buttons, quiet chips, the lane's own plate, sentence case, no amber anywhere. Three photo-credit buttons share one name; the count's width moves both buttons sideways |
| 5 | Error prevention | 3 | The primary is disabled with no pick, both buttons rest at zero, the minute is said once, a reload keeps the original deadline, a 409 shows the backend's sentence |
| 6 | Recognition rather than recall | 3 | The rule is stated once in the intro, the eyebrow says whose findings these are (with that line's roundel). The clock is off screen on the desktop arrival, so the rule has to be remembered |
| 7 | Flexibility and efficiency | 3 | Native checkboxes and radios, Space picks, one linear tab order, "Scegli tu" as the one-tap path. Each credit button stops the Tab path before its card |
| 8 | Aesthetic and minimalist design | 3 | Calm and photo-led, flat, the picked ring is an overlay so nothing moves. At 1440 px the cards stretch to 450 px and their 4:3 photos to 337 px: the panel is 650 px tall and the decision row falls out of the window |
| 9 | Error recovery | 3 | A failed send keeps the picks under "Scelta non inviata" with the backend's words; a 409 closes the panel with "Questa scelta è già chiusa: il piano va avanti." and re-reads the plan (tests; not reproducible against the demo backend) |
| 10 | Help and documentation | 3 | The intro says the rule and the window once; nothing says what a pick changes (the days are built around the picked options), which the traveller has to guess |
| | **Total** | **30/40** | **Good: the panel is right; where it lands and what it leaves behind are not yet** |

## Design specificity verdict

**LLM assessment (before the detector).** Authored. The question arrives as a station on the coordinator's line ("Tocca a te", the live ring without its halo), the eyebrow carries the asking line's roundel, the answer goes back onto the line as a lozenge like the brief that opened the run, and the countdown is the system's ink, never amber. Nothing here could be lifted into another product unchanged: it is the transit diagram asking a question. The cards themselves are the most generic part (photo, title, reason, chips), deliberately, and they are clean: no shadow, a hairline edge, the tick on a surface disc. The weaknesses are about placement and hand-off, not look.

**Deterministic scan.** `impeccable detect --json components/choice components/ui/choice-card.tsx components/ui/countdown.tsx components/live/plan-screen-view.tsx components/demo app/demo` found one item, `broken-image` at `choice-card.tsx:124`: a false positive (the `src` is the `coverSources` thumbnail, an expression the static scan cannot read; the photos load in the browser). The overlay ran in the page (`detect.js` injected after a mutation preflight): the live pause reported "No anti-patterns found"; the demo pause at 1440 light reported two, both pre-existing and outside the panel (`cramped-padding` on the lanes' sticky heads strip, `cream-palette` for the declared light ground; both in `demo.md`). In-page contrast over the panel's 21 visible text nodes: 0 failures in light (1440) and in dark (393). No horizontal overflow at 393 (`scrollWidth` 393). Targets: "Scegli tu" 90x40, the primary 263x40 on the phone (44 under a finger), credit buttons 32x32 with a mouse (44 under a finger). Reduced motion (emulated): nothing in the panel moves anyway; the photo zoom is `motion-safe` only.

## Overall impression

The pause reads as the run itself asking, which is the point of the feature, and every part the spec asked for is there and honest: the clock is ink, the cards are native controls, the credit is one tap away, a reload keeps the deadline, "Interrompi" removes the question at once. What is not yet right is the moment around the panel. On a desktop window the page brings the question into view but centres it, so the cards fill the screen and the clock and the buttons wait below the fold; and when the question goes (the traveller's answer on the phone, a timeout, the recording's answer in the demo) it leaves either no visible trace or a lost focus. The single biggest opportunity: land the whole panel on screen, and land the focus and the eye somewhere true when it leaves.

## What's working

1. **The question lives on the line.** The plate "Tocca a te: scegli cosa vedere" ends the coordinator's line (no halo: nothing runs while Atlas waits), the closed phone card says it, the heads strip on desktop says it, the tab title says it, and the answer comes back as a lozenge with the question underneath ("Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra / Cosa ti va di vedere?", "Hai lasciato scegliere ad Atlas", "Tempo scaduto: sceglie Atlas", "Domanda chiusa: piano interrotto").
2. **The edge cases hold.** A reload during the food question showed the cards 110 ms after the page came back, from the snapshot, with the original deadline (0:20 before, 0:19 after); "Interrompi il piano" removed the panel within 150 ms and moved the focus to "Interrotto"; the 2-minute window said "Manca un minuto per scegliere." once, at 1:00 exactly.
3. **The demo stays a demo.** Two pauses of 15 s, the recording's picks shown for 0.9 s, then the camera picks the work up again on both layouts (phone: the coordinator card with "Hai scelto", then Spostamenti; desktop: the coordinator's newest station). A visitor's pick takes over and becomes the station ("Hai scelto: Torre di Belém e Mosteiro dos Jerónimos").

## Priority issues

### [P2] On a desktop window the clock and the buttons arrive below the fold
- **What**: when the question comes, the heading takes the focus and the browser centres it in the scrollport. At 1440x900 on `/demo` the heading lands at y 530 and the panel ends at 1146: the visitor sees the question and the top half of three 450x337 photos, not the countdown, not "Continua". The live page will do the same with real photos (the demo backend looks none up, so the local live cards are short).
- **Why it matters**: the countdown is the rule at work; a visitor watching a 15 s window never sees it run out, and a traveller on the Mac has to scroll to find the way forward on the one screen that waits for him.
- **Fix**: focus the heading without scrolling and bring the section's top under the sticky bars (`scrollIntoView({ block: "start" })`; `scroll-padding-top` already keeps it clear of the bar and the heads), and cap the cards' grid on wide screens so the whole panel fits a 900 px window (the photos' `sizes` follow).
- **Suggested command**: /impeccable layout

### [P2] The focus falls to the page when the question leaves by itself
- **What**: the panel takes the focus when it opens; when it closes without the traveller (the live timeout, the demo's recording answering) the focused heading is removed and `document.activeElement` is `body`. The next Tab starts from the top of the page.
- **Why it matters**: a keyboard or screen-reader user waiting on the question loses his place exactly when the run resumes; the traveller's own answer already moves the focus to the plan's state, so the two endings disagree.
- **Fix**: when the panel goes and the focus went with it, move it to the plan's state (`#plan-state`, `preventScroll`), as the traveller's own answer does; leave it alone when it is anywhere else (the interrupt flow keeps its own).
- **Suggested command**: /impeccable harden

### [P2] On the phone the answer leaves no trace on screen
- **What**: after "Continua con queste" the panel goes, the coordinator card is closed and its line says "Aspetta alloggio.", and the open card is Alloggio ("Ora: Alloggio"). The lozenge "Hai scelto: …" exists, inside the closed coordinator card.
- **Why it matters**: the spec says the panel "collapses into a station on the coordinator's line"; on the phone that station is out of sight, so the traveller's only feedback is that the cards vanished.
- **Fix**: while the traveller's answer is the coordinator's newest station, the closed card's line says it ("Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra"), until the coordinator does something else.
- **Suggested command**: /impeccable clarify

### [P2] The photo credits stop the Tab path before each card and share one name
- **What**: Tab from the question goes "CC BY 2.5", "Wikimedia Commons" (when open), "Crediti della foto", then the card's checkbox, three times; a screen reader's button list has three "Crediti della foto" with nothing tying each to its option.
- **Why it matters**: the card is the control; its credit is secondary, but it comes first, and its name does not say whose photo it credits (WCAG 2.4.6).
- **Fix**: name each button after its option ("Crediti della foto: Oceanário de Lisboa") and put the photo after the card's label in the DOM, drawn first, so Tab reaches the card, then its credit.
- **Suggested command**: /impeccable harden

### [P3] Smaller items
- **The count moves the buttons**: on desktop "Nessuna scelta" becomes "1 scelta" and both buttons slide about 40 px left under the pointer that is heading for them. Give the count the width of its longest wording.
- **The minute stays in the live region**: the region is atomic, so after "Manca un minuto per scegliere." every lane change ("Alloggio: finito") is read with the minute note again, until the question closes. Say it once: keep it only until the next announcement.
- **Crossing 1080 px** (an iPad turning) moves the panel between its two slots and remounts it: the picks are lost and the focus jumps back to the heading.
- **The credit strip** covers 51 % of a phone card's photo, 63 % with a long author ("Brian Snelson from Hockley, Essex, England"). It is on demand and closes with the same button; acceptable.
- **"Scegli tu"** follows an intro that says "Scegli quelle che ti piacciono": the same verb addresses the traveller, then Atlas. The copy is the spec's and the plan's; a question for Michele, not a fix.
- **The demo's clock ignores a credit tap**: reading a credit does not count as taking over, so the 15 s can run out while the visitor reads it.

## Persona red flags

**Michele on the Mac (primary).** The question comes, the page scrolls to it and centres the heading; three large photos fill the window; the countdown and "Continua" are under the fold. After answering, the lanes come back with "Hai scelto" on the coordinator's line (visible on desktop).

**Michele on the iPhone, one-handed (primary).** The question is first under the bar, the cards are two across, the actions follow the cards (a natural scroll after picking). Red flag: after "Continua" the cards vanish and the screen shows Alloggio; what he chose is in a closed card.

**Sam, keyboard and screen reader.** The heading takes the focus and names the group; the cards are native checkboxes with their reason and chips as descriptions; Space picks; the count updates. Red flags: three identical "Crediti della foto" before each checkbox; after a timeout the focus is on `body`; after the minute note, every lane change re-reads it.

**Riley, edge cases.** Reload during a pause: right. Interrupt during a pause: right. Answer at the deadline: the 409 path is tested, not reproducible here. Rotating an iPad across 1080 px: picks lost.

## Minor observations

- The third card sits alone on its row on the phone (3 options, two columns); the food grid has an empty fourth column on desktop. Both are the spec's grid; fine.
- "Tempo scaduto: scelgo io." shows for under a second live (the backend closes the question within a second of the deadline); the demo hides the countdown while the recording picks.
- The expired, sending, closed and failed states are in `/dev/ui` "Scelte"; the gallery reads in both themes at 393 and 1440.
- Dark theme: the plate is the coordinator's light ink with dark text, the picked ring and the filled tick read on the photos.

## Questions to consider

- Should the question own the window on a desktop (its top under the bars, the whole panel in view), even if the coordinator's plate scrolls under the heads strip, which repeats it?
- On the phone, is a line on the closed coordinator card enough of a receipt for the answer, or should the panel stay as a one-line "Hai scelto" until the next station?
- "Scegli tu" or "Scegli tu, Atlas"? The voice switch is the only copy that can be misread.

## Fix list in priority order (for the next round)

1. P2 Land the panel whole: focus without scrolling, section top under the bars, the cards' grid capped on wide screens.
2. P2 Focus to the plan's state when the question leaves with the focus.
3. P2 The coordinator's closed card says the traveller's answer while it is the newest station.
4. P2 Credit buttons named per option and after their card in the Tab order.
5. P3 The count's width fixed; the minute note said once.

Expected score after items 1 to 4: 33/40.
