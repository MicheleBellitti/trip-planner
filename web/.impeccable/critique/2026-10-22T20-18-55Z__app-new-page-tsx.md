---
target: /new, after the second critique fixes
total_score: 29
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
target_identity: "file:/Users/michb/dev/trip-planner/.claude/worktrees/journey-mode-form/web/app/new/page.tsx"
target_fingerprint: "sha256:7674cc65a6771006d72864b19eda733a8247a0b6afd5b8bd2cd2ff684139b33b"
target_path: /Users/michb/dev/trip-planner/.claude/worktrees/journey-mode-form/web/app/new/page.tsx
timestamp: 2026-10-22T20-18-55Z
slug: app-new-page-tsx
---
Method: dual-agent, run in sequence so they never shared the browser (B: detector + overlay, then A: design review).

Target: `/new` (web/app/new/page.tsx) after the second critique's fixes: Enter stops on the chosen travel mode, the note joins the group's description, the hint names local travel, the form remembers the last mode, and a chosen option is the current station (ink edge on notice-wash) instead of the primary fill.

## Design health score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | No recap on the phone; a remembered mode arrives silently (Aereo shows ~80 ms first in dev) |
| 2 | Match system / real world | 3 | Right vocabulary; three names for the system on one screen (Atlas, "Cinque agenti", "il planner") |
| 3 | User control and freedom | 3 | All editable; nothing shows or clears what was remembered |
| 4 | Consistency and standards | 3 | "Chosen" drawn at two weights (segment 1.5 px ring, chip 3 px edge) |
| 5 | Error prevention | 3 | The notes head off Traghetto/Auto; an implausible pair gets no word before paying |
| 6 | Recognition rather than recall | 3 | Icon + label chips, desktop read-back; on the phone the mode is far above the button |
| 7 | Flexibility and efficiency | 3 | Origin, party and mode remembered, the Enter chain stops on the mode |
| 8 | Aesthetic and minimalist design | 3 | Calm, on-token, hint-heavy (about ten grey helper lines) |
| 9 | Error recovery | 3 | Summary from three problems with links, focus handled |
| 10 | Help and documentation | 2 | Nothing says the planner asks when a mode cannot reach the destination |
| **Total** | | **29/40** | **Good** |

## Design specificity verdict

**LLM assessment.** Details specific to Atlas (the chosen option as the current station, the same 3 px ink edge as the header's current "Nuovo piano"; Phosphor travel glyphs; condensed heads on paper; domain-true Italian notes; the desktop RouteLine), composition generic (a good booking-site form). The line-map identity lives only in the desktop read-back, which the phone never shows.

**Deterministic scan.** `impeccable detect --json` over the form's sources: 0 findings (exit 0).

**Visual overlays.** detect.js in a "[Human]" tab: 1440 dark 1 finding (`line-length` ~89 chars on the page intro, `max-w-prose`, predates this change); 393 dark none; 1440 dark with Traghetto 1 (the same intro); 1440 light 2 (the same intro, and `cream-palette` on `#F4EFE4`, the documented "Carta di giorno" ground: false positive). Nothing in the travel-mode group or its note. The live server was stopped.

## What's working

- The ferry and car notes: short, domain-true, only for the two confusable modes, announced and part of the group's description.
- The chosen state as the current station: the primary fill stays reserved for "Pianifica il viaggio", and it reads in both themes.
- Keyboard wiring: the Enter chain stops on the chosen mode, one tab stop per group, arrows, the hidden "Date" legend; at 1440×900 a filled request with the five modes on one line fits.

## Priority issues

1. **[P1] In forced colours the chosen option disappears** (chips and segments): the state lived only in background, border colour and an inset shadow. **Fixed after the run** (`c87a271`): the chosen option takes Highlight / HighlightText, verified with forced colours emulated. Command: /impeccable harden.
2. **[P2] On the phone a remembered mode goes out unseen**: no sign it was carried over, no recap near the button. Fix: "Come l'ultima volta." in the note slot when a remembered mode other than Aereo is laid in, or a one-line recap above the phone's button. Command: /impeccable clarify.
3. **[P2] At 1080 px the 1.25:1 split squeezed the children's age selects to 81 px**, clipping "Scegli". **Fixed after the run** (`c87a271`): two across from 1080 px, 127 px. Command: /impeccable adapt.
4. **[P3] "Chosen" at two weights**: the segment's 1.5 px inset ring against the chip's 3 px edge. Fix: a 3 px inset ring on the segment. Command: /impeccable polish.
5. **[P3] The note shifts the content below by 27 px; the hint leaves an orphan ("il planner.")** at 393 and 1080. Fix: a tighter hint ("Andata e ritorno; sul posto sceglie il planner."). Command: /impeccable clarify.

## Persona red flags

**Jordan (first-timer).** Nothing says Aereo is a default; "costa circa 2–4 $" does not say who pays; three names for the system; Traghetto for Milano → Lisbona gets no word.

**Sam (screen reader / keyboard).** Mostly solid (group described by hint and note, note announced, Enter stops on the mode). High Contrast lost every chosen state (fixed). "Chi viaggia" heading and group share a name (predates).

**Casey (one-handed phone).** No recap near the thumb before paying; "Avanti" from the destination focuses the mode radio and closes the keyboard (iOS focus ring untested); 46 px tap areas.

## Minor observations

- The remembered mode flashes in after Aereo on hydration (~80 ms in dev).
- The boat glyph is the weakest of the five at 16 px.
- In dark, notice-wash against surface is ~1.1:1: the edge alone carries the chosen state.
- The 1440×900 fit holds by ~3 px.
- Out of scope, not counted: the intro's line length, "7 notti" without a month, "Meno di 1 anno" clipping.

## Questions to consider

- The mode is the line between the two stations: why a fact row under the RouteLine rather than the line itself, and why not on the phone, where it matters most?
- Is a remembered mode a choice or a default? Should the form say "Come l'ultima volta"?
- Would a five-across strip (icon over label, ~72 px each) make the mode one row and one glance, or read as a tab bar?
