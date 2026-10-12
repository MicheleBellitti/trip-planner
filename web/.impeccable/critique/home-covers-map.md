---
target: home "/" with cover thumbnails (web/app/page.tsx, components/home/plan-list.tsx, components/plan/cover/cover-thumb.tsx, cover-credit.tsx, cover-store.ts)
round: 1 (covers and map pass)
total_score: 30
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 1
p2_count: 3
p3_count: 5
date: 2026-10-12
---

# Critique: home "/" with destination cover thumbnails

**⚠️ DEGRADED: single-context (no sub-agent/Task tool is exposed to this agent).** Assessment A (design review) was written down before the detector ran, in the same context. Detector: `impeccable detect --json components/home components/plan/cover app/page.tsx` returned `[]` (0 findings). No overlay was injected (the live server was not started, to leave the shared stack alone). Read-only run: no source file was changed.

How it was inspected: own browser tab, 393x852 and 1440x900, light and dark, against the running demo stack (20 plans, 8 shown under "Recenti", "Mostra gli altri 12" expanded once). Measured in the page: thumbnail boxes, title column width, row heights, network, alt text and accessibility tree, focus ring by keyboard (Tab), horizontal overflow (none), em dash (none), amber (none). Reduced motion was read from the code (`motion-reduce:duration-(--duration-reduced)` on the photo fade, 120 ms), not emulated.

## The question: does it now have a sense of place without losing calm?

**Calm: yes, fully kept. Sense of place: only half.** The list is still the Linee rail with status nodes, still ink on a cool ground, no amber, no em dash, keyboard focus is a clear 2 px inset ring on the whole row, no horizontal scroll at 393 px. The photo arrives as a 260 ms fade over a tinted tile with the same box, so nothing jumps (one tile was still showing 3 s after load on desktop dark, then filled in).

But the photo is a stamp: 72 x 54 px on the phone, 96 x 72 on desktop, in rows of 95 to 117 px. At that size a Lisbon skyline reads as "a coloured rectangle with sea at the bottom". It adds warmth and a little recognition, yet the screen is still a ledger of 20 near-identical rows, and the user's complaint ("spoglio, minimalista") is answered by decoration at the edge of each row, not by a place to look at. In the demo data every plan is Lisbon, so the same photo repeats 20 times and the effect is wallpaper; real data will vary, but "the same trip planned again" (the twins the list already handles) will repeat it too.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Status glyph + word, running rows alive. Covers arrive one by one (popcorn) and a failed cover is silent (fine, supplementary). |
| 2 | Match System / Real World | 4 | A photo of the place is the right metaphor; copy unchanged and clean. |
| 3 | User Control and Freedom | 3 | Nothing new here; still no way to archive or remove a plan from the list. |
| 4 | Consistency and Standards | 3 | Cover band on the plan, thumbnail on the list: coherent. The rail, node, photo and caret now make five columns on a 393 px row. |
| 5 | Error Prevention | 3 | Hosts pinned in the schema, fixed 4:3 box, no layout shift. |
| 6 | Recognition Rather Than Recall | 3 | Photo helps in principle; at 72 px, and repeated, it adds little over the title. |
| 7 | Flexibility and Efficiency | 2 | 20 plans, no search, no way to pin the trip you are working on. |
| 8 | Aesthetic and Minimalist Design | 3 | Calm and coherent, but still reads as a table; the photo is too small to carry the page. |
| 9 | Error Recovery | 3 | List error has "Riprova"; a missing cover falls back to a tile. |
| 10 | Help and Documentation | 3 | The credit note is one line and points elsewhere (P2-2). |
| **Total** | | **30/40** | **Good (75 %)** |

## Design Specificity Verdict

**LLM assessment.** Authored for this product: the node-on-a-rail list is Atlas, and the photo sits in its own column so the rail is not cut. The cover tile (a tinted block with the initial) is honest and quiet. What is category-interchangeable is the thumbnail itself: a small rounded photo to the left of a title is the default "list with avatars" pattern, and it does not use the product's own idea (a line map) at all. The biggest missed opportunity is that the place is shown as a picture but never as a place: no destination-first hierarchy, no dates as a headline, nothing that says "this is your next trip".

**Deterministic scan.** 0 findings on the three scanned paths. No false positives to dismiss. Visual overlays: none (not injected).

## What's Working

- **The tile under the photo.** Same size and shape while loading, when there is no photo, and after; the photo only fades in. No layout shift, and a missing photo does not look broken. Dark-mode tile (notice-wash with an ink-2 initial) is calm and legible.
- **The rail survives.** The photo has its own column, the status node sits at the row's middle, and the whole row is one link with a strong inset focus ring. The colour budget is untouched: red only for failed and blocked, amber absent.
- **Respect for the network and the licence in the schema.** Photos load only near the viewport, `loading="lazy"`, `no-referrer`, a 250 w / 500 w `srcset`, hosts pinned. The backend caches per destination for 30 days.

## Priority Issues

### [P1] The photo is a 72 px stamp, so the screen still feels bare

**Why it matters.** The user asked for a sense of place. Rows of 95 to 117 px with a 72 x 54 thumbnail give texture, not place; with repeated destinations it is wallpaper. This is the goal of the change, and it is met only in part.

**Fix.** Keep every row as is, and give the one plan that matters most a real image: a "featured" first row (the running plan, else the newest ready one) that uses the plan page's `CoverBand` shape at list width, 16:9 or 11 rem tall on the phone and 14 rem from 1080 px, rounded-md with the `rule` edge, the title and the status line under it (title in `text-heading`), and the rail node on its left. All other rows stay thumbnails. On desktop use the empty 400 px to the right of the 1024 px list for that featured card (list left, featured plan right), so the page has one place to look and 20 rows to scan. Not 20 big photos: that would break the calm.

**Suggested command.** `/impeccable layout` then `/impeccable polish`.

### [P2] Photos on the home have no credit next to them

**Why it matters.** DESIGN.md calls the credit "a legal requirement, never cut or hidden". On the home, CC BY-SA photos (the Lisbon one is CC BY-SA 2.0, by Vitor Oliveira) are shown with only an unlinked line under the card pointing to another page. A pointer one page away is a weak reading of "reasonable" attribution.

**Fix.** Build the note from the covers actually shown, de-duplicated: "Foto: Vitor Oliveira (CC BY-SA 2.0), Wikimedia Commons", with the licence and source as links, like `CoverCredit`; for many different photos, a closed "Crediti delle foto" disclosure that lists them. `useAnyCover` already holds the data.

**Suggested command.** `/impeccable clarify`.

### [P2] The thumbnail takes the width the title needs on the phone

**Why it matters.** At 393 px the title column is 175 px (rail 44, gap 12, photo 72, gap 12, caret 16). "Lisbona in famiglia, 14–18 aprile 2027" breaks into three lines, and breaks inside the date range ("14–" then "18 aprile"), which reads as a typo; the twin timestamp is jammed inline after the title ("2027 Oggi, 18:41"). Rows grow from 95 to 117 px.

**Fix.** Make the date range unbreakable (`14⁠–⁠18`, or wrap it in a nowrap span; in `displayTitle`), narrow the rail column from 44 to 36 px and the gap to 10, and move the twin timestamp into the meta line (status, cost, time) instead of the title line. Two lines of title, maximum (`line-clamp-2`).

**Suggested command.** `/impeccable layout`.

### [P2] Each row's image repeats the title for a screen reader

**Why it matters.** The accessibility tree reads `image "Lisbona in famiglia"` and then the title "Lisbona in famiglia, 14–18 aprile 2027", in 20 links. The photo is decoration beside a title that already names the place.

**Fix.** `alt=""` on the home thumbnail (keep the descriptive alt on the plan band, where the photo is the content). The tile's initial is already `aria-hidden`.

**Suggested command.** `/impeccable harden`.

### [P3] One request per row, and the arrival is staggered

Each visible row calls `GET /plans/{id}/cover` (8 requests per load, all 200, identical payload for the same destination; the browser cache is `private, max-age=3600`). After 3 s on desktop one of eight was still a tile. Put `destination` (and ideally the cover) on `GET /plans` so the list needs no N+1, and the photos appear with the rows.

### [P3] The tile's initial and the alt come from the title, not the destination

`destinationFromTitle` takes the text before the first comma. An agent title such as "Weekend lungo a Parigi, 3–6 mag" gives the initial "W". Carry the destination in the plan summary (same fix as above).

### [P3] In dark mode the photos are the brightest thing on the card

Daylight thumbnails at full brightness on a #131B26 surface pull the eye from the title and the status. Add `brightness-90` (or a 1 px inset overlay) under `dark`, and check it on a night photo.

### [P3] The 3 px ink rail is now the heaviest object, and a dead strip sits between node and photo

On the phone the node is at x = 22 and the photo starts at x = 73: about 30 px of nothing, with a full-height black line beside it. Thinning the rail to 2 px, or tightening the rail column (see P2-3), lets the photo and the node read as one station.

### [P3] A list of 12 grey tiles would look like missing avatars

For a destination without a free photo the tile shows a letter. Seen once or twice it is fine; in a run of tiles it looks like a broken avatar set. Prefer the existing `map-pin` icon for every tile, or keep the initial and make the tile a little warmer than `notice-wash` (no illustration, per DESIGN.md).

## Persona Red Flags

**Michele on the phone (the one real user, one hand, spare moment).** Finds the trip he wants by the title, not the photo; the photo is too small to help him find it and the three-line wrapped title with an inline timestamp costs him the scan. Thumb targets are whole rows (95 px or more): good.

**Sam (keyboard and screen reader).** Tab order is natural, focus ring is a strong inset 2 px on the whole row. Each row announces the destination twice (P2-4). The credit is not reachable from the list (P2-2).

**Casey (distracted, slow connection).** 8 photo requests plus 8 cover requests at load; tiles hold the layout so nothing jumps, which is good. Wikimedia is a third-party host the phone must reach: if it is slow, the tile stays, which is the right failure.

## Minor Observations

- Desktop 1440: the list is capped at 1024 px and left-aligned; 390 px at the right is empty. With covers it is the natural place for a featured plan (P1).
- Group headings "Recenti" and "In corso" are `text-micro` ink-2 (12.5 px): quiet enough that the group structure is hard to see now that photos add weight.
- No em dash, no amber, sentence case, Italian: all hold on this screen.
- Loading rows reserve a 4:3 block for the cover, so the skeleton matches the final shape (code read, not seen: the data loads too fast to catch).

## Questions to Consider

- If one photo could be large on this page, which plan should own it: the running one, the newest, or the next to depart?
- Does a list of twenty trips need twenty photos, or one place to look and a quiet index?
- Should the destination, not the title, lead each row ("Lisbona" large, "14–18 apr 2027, famiglia" under it)?

## Verdict for the gate

No P0. One P1 (the sense-of-place goal only half met), three P2, five P3. 30/40 is below the 32/40 gate for a screen; fixing P1 and the three P2 (all small except the featured plan) puts it at about 34/40.
