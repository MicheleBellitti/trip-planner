---
target: "/evals (eval history) and /evals/[id] (one run)"
slug: evals
round: 1
total_score: 33
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 0
p2_count: 3
p3_count: 5
date: 2026-10-12
---

⚠️ DEGRADED: single-context (no sub-agent/Task tool is exposed to this agent, so Assessment A and B ran sequentially in one context; A was written down before `impeccable detect` ran)

# Critique, round 1: eval history `/evals` and `/evals/[id]`

Surface: the real CI run of 2026-10-12 (`5d22125`, all five plans `budget_paused`, no judge scores, no baseline) imported
with `python -m app.cli import-evals`, plus a synthetic accepted run (`components/evals/__fixtures__/run-accepted.json`,
imported temporarily into the demo database and removed again) to see the plan summary, judge scores and a comparison
with a baseline. Viewed at 393x852 and 1440x900, light and dark. Judged against `web/DESIGN.md`, `web/PRODUCT.md` and
the CLAUDE.md UI rules. Mode: Operate (a developer tool for one person).

Checks run: `impeccable detect --json app/evals components/evals` returned `[]` (exit 0). The browser console showed one
hydration warning, traced to a stale Turbopack dev cache (see Minor observations), not to the code.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 4 | Skeleton shaped like the page, verdict word plus glyph in the first line of every row. |
| 2 | Match System / Real World | 3 | Labels are Italian and plain; the files' own sentences stay English (marked `lang="en"`), which is honest but mixed. |
| 3 | User Control and Freedom | 3 | Back link, whole-row link, collapsible raw JSON. No way to compare two runs. |
| 4 | Consistency and Standards | 4 | Same rail, glyphs and header as the home plan list; the verdict reuses the plan status vocabulary. |
| 5 | Error Prevention | 3 | Read-only screens; nothing to get wrong. |
| 6 | Recognition Rather Than Recall | 3 | Check and criterion names are translated; the index of requests sits above the sections. |
| 7 | Flexibility and Efficiency | 2 | No filter by profile or verdict, no sort, no link from a run to the previous one. Fine for a short history. |
| 8 | Aesthetic and Minimalist Design | 4 | Ink rail, one red for blocking, no amber. Failing requests come first. |
| 9 | Error Recovery | 4 | Error state with "Riprova", a "not found" panel that says what to do. |
| 10 | Help and Documentation | 3 | The empty state explains how runs arrive (CI upload or `import-evals`). |
| **Total** | | **33/40** | **Good** |

## Design Specificity Verdict

**LLM assessment.** It looks like Atlas, not like a generic CI dashboard. The run is a station on the same 3 px ink rail
as the home page's plans, the verdict is a word with a glyph (never colour alone), and the two dates rule is not in play
here but the "blocking is red, nothing is amber" rule is kept. The facts grid under the verdict (plans accepted, requests
without blocks, cost against the estimate, web searches, judge mean, judge model) answers the first question a developer
has: did this change get through, and what did it cost.

**Deterministic scan.** `impeccable detect` on `app/evals` and `components/evals`: no findings.

## What's working

- **The verdict is the page.** "Bloccato" with its sentence, then the figures, then the findings that cause it. Nothing
  to decode.
- **Failing first.** Requests and checks sort failing before passing, so a red run opens on its problems and a green run
  stays short.
- **Honest about missing data.** No judge scores shows "nessuno" instead of a zero; no baseline says so in the
  comparison section instead of inventing a delta.

## Priority issues

- **[P2] The verdict sentence contradicted the comparison when there was no baseline.** The real run said "Il confronto con
  il riferimento non lascia passare questa modifica" while the comparison below said "Nessun riferimento". *Fix (done):*
  `runVerdictExplanation` says a blocked run without a baseline had nothing to compare with and failed on its own checks.
  Command: /impeccable clarify.
- **[P2] "voto nessuno" on the phone list read as a typo.** *Fix (done):* "senza voto" on the phone, "nessuno" under the
  "Voto" column on desktop. Command: /impeccable clarify.
- **[P2] The compare findings of a 5-request failure repeat the same two sentences ten times.** A run where every plan hit
  the budget lists ten near-identical rows. Not fixed: grouping findings by request is a design change (one row per request
  with its failed checks) that the history does not need yet. Command: /impeccable distill.
- **[P3] No filter or sort on the list.** Fine up to a few dozen runs; revisit when production runs pile up next to PR runs.
  Command: /impeccable layout.

## Persona red flags

**Alex (power user, the developer who changed a prompt).** Wants to open the run of his PR and see which request regressed.
He gets it in two clicks, but cannot see the previous run's figures next to this one: the comparison shows the baseline,
not the last run.

**Jordan (first-timer, opens the page without context).** The empty state explains where runs come from. A single
"Bloccato" row with no baseline is explained by the sentence fixed above.

## Minor observations

- Check names and judge reasons are English in the eval files; the UI translates its own labels and marks the files'
  sentences `lang="en"`. Acceptable for a developer tool.
- The hydration warning seen once in the dev browser (`<nav>` expected, `<button>` found in the skeleton's header) comes
  from the running Turbopack dev server serving a stale server bundle of the client component after `site-header.tsx`
  changed. A production build served by `next start` renders the nav in all three headers of the streamed page.
  Restarting the dev server clears it.
- First load on `/evals/[id]` in the dev server takes 10 s or more under load; the production build is 180 KB gzip first
  load for the route (`/evals` 171 KB, `/plans/[id]` 190 KB).
- The raw request JSON uses an inline monospace stack because `globals.css` turns off Tailwind's `font-mono`. A
  `--font-mono` token would be cleaner (also needed by DESIGN.md).
- Desktop leaves the right 40 percent of the run page empty. Fine for a reading tool; a sticky index could use it.

## Questions to consider

- Should the history show the trend (cost and judge mean per run) as a small line, now that there is a second run to
  compare with?
- Should a blocked PR run link to the PR comment CI already posts?
