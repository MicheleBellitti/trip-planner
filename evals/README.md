# Evals

Every change to a prompt, a skill or a model goes through these evals before it reaches
production (spec: "Eval sui piani", "Eval strutturate e versioning dei prompt"). Six
reference requests run through the real backend, each plan gets deterministic checks and an
LLM judge, and the run is compared with a committed baseline.

**Runs spend real money.** Run them only when Michele asks, or let `evals.yml` run them on a
PR. The tests in `evals/tests/` are offline and free.

| File | What it is |
|---|---|
| `requests.yaml` | The dataset: six `PlanRequest`s with expected constraints and tags |
| `checks.py` | Deterministic checks: pure functions over (request, plan, trip, metadata) |
| `rubric.md` | The judge's rubric (its system prompt), five criteria scored 1 to 5 |
| `judge.py` | The LLM judge: `claude-sonnet-5-5`, structured JSON output, $1 cap per run |
| `run.py` | Runs the requests through the backend and writes `results/<date>-<git sha>.json` |
| `compare.py` | Compares a results file with `baseline.json`; decides whether the PR may merge |
| `baseline.json` | The accepted level. It changes only through an explicit commit |
| `results/` | One JSON file per run |
| `tests/` | Offline tests (fixtures, fake judge client, no network, no Postgres) |

## Running

From `backend/`, with `backend/.env` holding the **development** key, a reachable Postgres
and the development lockfile (`backend/claude-lock.development.json`, written by
`ant apply --lock-file backend/claude-lock.development.json profiles/development` from the
repository root, or by `scripts/bootstrap.py --profile development`):

```sh
cd backend
uv run python ../evals/run.py --dry-run                 # validate, show the resolved dates and the ceiling: free
uv run python ../evals/run.py --dry-run --run-date 2026-10-13   # dates as resolved on that day
uv run python ../evals/run.py                           # all six, development, asks first
uv run python ../evals/run.py --tags train,smoke        # requests with any of these tags
uv run python ../evals/run.py --ids sea-week-family --no-judge
uv run python ../evals/run.py --yes --concurrency 5     # no prompt, plans in parallel (CI)
uv run python ../evals/compare.py ../evals/results/<date>-<sha>.json
uv run python ../evals/compare.py <results> --markdown comment.md   # the PR comment
```

What `run.py` does for each selected request:

1. It builds the backend's own services in-process (`app.sessions.start_planner`) with the
   real SDK client, the profile's lockfile (`--lockfile` overrides it) and a **dedicated
   database**. That database is `DATABASE_URL` with `_evals` appended to its name, or
   `--database-url` / `EVAL_DATABASE_URL`. A name that already contains `eval` is used as is.
   `run.py` creates the database if it is missing and migrates it to head, so eval plans
   never mix with the plans of your dev database.
2. It starts the plan exactly like `POST /plans` (`app.sessions.start_plan`), then polls
   `plans.status` until the plan leaves `running`. `budget_paused` ends the eval of that plan:
   it is never continued. After `--timeout-minutes` (default 40, below the backend's 45-minute
   stuck threshold) the plan is interrupted. When the coordinator asks the traveller to pick
   (`ask_traveller`), each poll answers at once with the first option (the first two when
   several can be picked); the picks go to the judge in a `<picks>` block.
3. It reads the plan, the Trip, `submit_attempts` and `agent_versions` from the database, and
   the session usage (`list_cost`, web searches) from `client.retrieve_session`. When
   `list_cost` is absent it falls back to `plans.cost_cents`.
4. It runs `checks.py` and the judge, then writes `results/<date>-<git sha>.json`. A name
   that is already taken gets `-2`, `-3` and so on, and `--output` sets the path.

Guards: the profile is `development` unless `--profile production` is passed explicitly. An
`AGENT_PROFILE=production` in the environment without the flag is refused. `run.py` prints
the spending ceiling and asks for confirmation (`--yes` skips the question, and it is
required without a terminal). Ctrl-C interrupts the plans in flight and writes the partial
results, marked `aborted`, which `compare.py` always blocks.

Exit codes of `run.py`: 0 results written (even with failing checks: `compare.py` decides),
1 the planner cannot start plans (missing key, lockfile or trip.json; nothing was spent),
2 usage or configuration error, 130 aborted.

## Costs

| Run | Expected (spec estimate) | Ceiling |
|---|---|---|
| Development, 6 requests | 6 × ~$0.71 + judge ~$0.30 ≈ **$4.55** | 6 × $1.00 + $1.00 = **$7.00** |
| Production, 6 requests | 6 × ~$2.50 + judge ~$0.30 ≈ **$15** | 6 × $4.00 + $1.00 = **$25.00** |
| One request (`--ids`) | ~$0.71 + ~$0.05 | $1.00 + $1.00 |

Sessions stop at their budget (`SESSION_BUDGET_CENTS`: 100 or 400 US cents). The API can
overshoot by one model request per running thread. The judge has a **hard $1 cap per run**.
Before each call it counts the input (`messages.count_tokens`, which is free) and reserves the
worst case: the input plus 10%, and all of `max_tokens` (6,000) as output, at Sonnet 5.5 list
prices. When the worst case doesn't fit in what is left, the call is not made and the run
stops judging. A judge call costs about 3 to 6 cents.

The `cost_and_searches_vs_estimate` check compares each plan with the spec's estimate: 55¢ and
20 web searches in development, 250¢ and 60 searches in production. It only warns, because
`compare.py` gates cost regressions.

## What is checked

Deterministic checks (`checks.py`; zero cost). A check blocks when it is blocking and its
status is `fail` or `error`:

| Check | Rule |
|---|---|
| `schema_valid` | The plan validates with `app.plan.Plan`, and the Trip with TripTracker's trip.json (vendored copy) plus `endDate >= startDate` |
| `book_by_before_scheduled_for` | Every `book_by` (bookings and alternatives) and every Trip `dueAt` is strictly before its event, with a UTC offset |
| `within_budget_or_warned` | The bookings' EUR total (the Trip's `costCents`) is within `budget_eur`, or a plan warning mentions "budget" |
| `prices_have_source` | Every price has an http(s) `source_url` and a `retrieved_at` with an offset |
| `links_on_allowed_domains` | Every booking link and Trip URL passes `app.links.check_link` (stop URLs are informational and not checked) |
| `no_empty_days` | Every day strictly between arrival and departure has stops (an empty arrival or departure day only warns) |
| `submit_plan_attempts` | The plan is `ready`, accepted at the first or second `submit_plan` call |
| `cost_and_searches_vs_estimate` | Cost and web searches recorded and compared with the spec's estimate (never blocks) |
| `dead_links` | Counts the plan's links the backend found dead (host and reason only; never blocks; a skip when the links were not checked) |
| `choices_asked` | The plan asked about activities and food (and the destination with "Suggeriscimi tu"), through `ask_traveller` (never blocks) |
| `matches_request` | Travellers, dates (or a flexible month and nights), destination, `must_mention` keyword groups, no `must_not_book` keyword in a booking |

The judge (`judge.py` + `rubric.md`) scores each accepted plan from 1 to 5, with a reason, on
time coherence, realistic transfers, respect of preferences, quality of alternatives and
clarity of the summary. It uses structured outputs, so the reply is JSON that matches a
schema, and Pydantic validates it again. A refusal, a truncated reply or an API error is
recorded as a judge error and never retried. There is deliberately no refusal fallback to
another model, because that would make the scores incomparable with the baseline.

## The gate (`compare.py`)

Against `evals/baseline.json`:

1. any blocking check that fails blocks, and so does an aborted or empty run;
2. a judge criterion whose mean drops by **more than 0.5** blocks;
3. a mean cost per plan that rises by **more than 30%** blocks.

Rules 2 and 3 compare the requests present in both files, so a `--tags` run is compared on
its own requests. A request that was scored or costed in the baseline but not in the run
blocks, because the regression can't be ruled out. Different profiles are refused
(`--allow-profile-mismatch` overrides). Exit codes: 0 passed, 1 blocked, 2 usage error.

**No baseline yet:** rule 1 needs no baseline, so a failing blocking check, an aborted run or
an empty run still blocks (exit 1). Rules 2 and 3 have nothing to compare with and are
report-only: the report says "not compared" and, when every check passed (exit 0), prints the
commands that create the baseline.

`--json <file>` also writes the verdict for machines: `status` (`passed`, `blocked`, or
`report_only` when there is no baseline and nothing blocks), one entry per rule in `rules`
(`checks`, `judge`, `cost`; each `ok`, `blocking` or `not_compared`), every finding, the judge
means, the cost change and the per-request rows. It is written for exit 0 and 1, not for a usage
error.

## Eval history (`upload.py`)

`upload.py` sends a results file, its `--json` comparison and the CI run URL to Atlas's eval
history (`POST <EVALS_INGEST_URL>/evals/runs`, bearer `EVALS_INGEST_TOKEN`; both come from the
environment). CI calls it after `compare.py`. It retries three times, never prints the token and
exits 0 with a `::warning::` on failure (`--strict` exits 1). Setup, rotation and the local
import: docs/deploy.md, "Eval history".

## Updating the baseline (explicit commits only)

The baseline never changes by itself: neither `run.py` nor `compare.py` without the flag
writes it, and CI never commits it. To accept a new level (the first baseline, an intended
cost increase, a new request):

```sh
cd backend
uv run python ../evals/run.py                                      # or download the CI artifact
uv run python ../evals/compare.py ../evals/results/<file>.json     # read the report first
uv run python ../evals/compare.py ../evals/results/<file>.json --update-baseline
git diff ../evals/baseline.json                                    # review it
git add ../evals/baseline.json && git commit -m "evals: update baseline from <file>"
```

`--update-baseline` merges the run's requests over the existing baseline, so a `--tags` run
replaces only its own requests. It refuses a run with blocking failures, an aborted run, or a
run of another profile, unless you pass `--force`. Commit the baseline on its own, with the
reason in the message, so the reviewer sees exactly what level was accepted.

## Coordinator comparison: Opus 5.5 vs Sonnet 5.5 (spec decision 3)

Decision 3: after the first evals, the two production coordinators are compared on the six
requests. With the same number of valid plans and no more warnings, the production profile
switches its coordinator to Sonnet 5.5. A valid plan is `ready` with no blocking check
failure. This is a one-off procedure that costs about two production runs (about $30, ceiling
$50), so Michele has to agree to it first. It needs the production key, which never sits on
a developer machine: run steps 1 and 3 in the GitHub `production` environment.

1. **Opus baseline.** Run the production profile as committed:
   `uv run python ../evals/run.py --profile production --yes --output ../evals/results/coordinator-opus.json`.
2. **Sonnet variant, without touching production.** On a scratch branch, set
   `profiles.production.models.coordinator: claude-sonnet-5-5` in `agents/profiles.yaml`
   and render it (`uv run python ../scripts/render_profiles.py`). Copy the rendered
   `profiles/production/` and `skills/` into a scratch directory, keeping both paths, so the
   lockfile keys stay `./profiles/production/...` and `./skills/...`. Apply it there with a
   **new** lockfile (`ant apply --lock-file <scratch>/claude-lock.production-sonnet.json
   profiles/production`, run from the scratch directory). A new lockfile creates new agents,
   so `backend/claude-lock.production.json` and the live agents stay untouched.
3. **Sonnet run:** `uv run python ../evals/run.py --profile production --yes --lockfile
   <scratch>/claude-lock.production-sonnet.json --output ../evals/results/coordinator-sonnet.json`.
4. **Decide:**
   `uv run python ../evals/compare.py ../evals/results/coordinator-sonnet.json --baseline ../evals/results/coordinator-opus.json --decide-coordinator --markdown decision.md`.
   It prints valid plans, warnings, mean cost and judge means side by side, then the verdict
   of the spec's rule. The judge scores inform the reviewer but are not part of the rule.
5. **Act.** If the verdict is to switch, open a PR that changes
   `profiles.production.models.coordinator` in `agents/profiles.yaml` (and the profile
   description in CLAUDE.md), with `decision.md` in the description. That PR goes through the
   normal path: development evals, merge, `deploy-agents.yml` with Michele's approval. Then
   archive the scratch agents and delete the scratch branch. Otherwise record the decision
   and delete the scratch agents.

## Maintaining the dataset

- **Dates are relative to the run date**, so the dataset never goes stale and always asks for
  a trip a few weeks ahead (flight schedules, train timetables and hotel rates are published;
  the 2026-10-12 run asked for trips a year out and 4 of 5 plans had no flights). In
  `requests.yaml` a fixed trip is `exact_start: {in_weeks: 6, weekday: friday}` plus
  `nights: 2` (the first Friday on or after the run date plus 6 weeks; `in_days` also works,
  `weekday` is optional, `exact_end` is start plus `nights`), and a flexible one is
  `month: {in_months: 2}` plus `nights`. Pick offsets that land the trip 5 to 14 weeks ahead
  and keep the weekday the request implies. `expect.dates` is never written: it is derived
  from the same resolved dates.
- **The run date** is today on the Europe/Rome clock, or `--run-date YYYY-MM-DD` (today or
  later) for a repeatable dry run or a rerun with the dates of an earlier run. The results
  file records it as `dataset.run_date`, with `dataset.resolved_dates` (by request id); each
  entry's `request` and `expect` hold the resolved values. `compare.py` matches runs by request
  id and ignores dates, so runs on different days compare fine.
- **New cases.** Every real plan that goes wrong becomes a new entry (spec). Give it an `id`,
  a `title`, `tags`, a valid `request` without personal data, and `expect`: `travelers`,
  `budget_eur`, `dates`, `destination_any`, `must_mention` (groups of synonyms; Italian first,
  word-prefix and accent-insensitive matching) and `must_not_book`. Then update the baseline
  with that request.
- **Keywords block the PR**, so keep them generous: `bambin` matches "bambini" and "bambino",
  and `volo` never matches "tavolo".

## Offline tests

```sh
cd backend
uv run pytest ../evals/tests -q                     # checks, compare, upload, judge (fake client), dataset, run
uv run ruff check ../evals && uv run ruff format --check ../evals
uv run pyright -p ../evals
```

They never call the Anthropic API, a Managed Agents session, a travel MCP or Postgres. The
judge runs on a fake client, the backend's `start_plan` and `interrupt_plan` are
monkeypatched, and `tests/conftest.py` blanks every Anthropic credential and points
`ANTHROPIC_BASE_URL` at a closed port.
