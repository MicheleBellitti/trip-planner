# Plan UX, PR 4: the agents ask the traveller and follow the travel mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The coordinator pauses the run with `ask_traveller` (what to see, what to eat, and one
optional pause: the destination, the travel mode or a real fork), builds the plan around the
picks, and follows `journey_mode`: it checks feasibility first, asks when the mode is impossible
or contradicted, and has `transport` research train, coach, ferry and car journeys. Transport
and activities cite only pages they opened or saw as search results.

**Architecture:** Prompts change in the templates `agents/*.md` and are rendered into
`profiles/**`. `scripts/render_profiles.py` renders a second custom tool,
`profiles/<profile>/agents/tools/ask_traveller.json`, from PR 2's `schema/ask_traveller.json`.
The result contract gains `TransferMode` `car` and `TransferOption.distance_km`, regenerated
into the travel-research-rules skill's schema. A new eval check, `choices_asked`, measures
whether the pauses happen. The backend side of `ask_traveller` shipped in PR 2 and does not
change here.

**Tech Stack:** Markdown agent templates with `{{ key }}` placeholders, Python 3.12 (Pydantic
models, the render script, pytest), `ant apply`, the paid `evals.yml` workflow.

**Spec:** `docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md`. This PR covers: §1
"What the agents do with it" and "Suggest a destination: the traveller picks"; §2 "Prompt
changes (coordinator)" and "What the picks change"; §3 "The root cause, in the prompts"; §4 row
4. The platform facts are from live probe P14: `docs/managed-agents-notes.md` §2e "A custom tool
left waiting". PR 2's plan (`docs/superpowers/plans/2026-10-20-plan-ux-2-choices-backend.md`)
fixes the tool's contract and its answer texts; this plan quotes them.

## Global Constraints

- Prompts are edited only in `agents/<name>.md`; `profiles/**` and
  `skills/travel-research-rules/schemas/*.json` are regenerated with `uv run python
  ../scripts/render_profiles.py` (from `backend/`), `schema/**` with `uv run python -m
  app.schemas`. Never hand-edit a generated file. Commit each template with its rendered files.
- Agent prompts and code are English. They tell the agent to write user-facing text in Italian.
  Italian examples in prompts are sentence case and use no em dash.
- `backend/app/plan.py` does not change (no Plan contract change).
- `ask_traveller` input, as PR 2 validates it: `kind` one of `destination`, `journey`,
  `activities`, `food`, `other`; `question` Italian, ≤ 120 characters; `multiple` true exactly
  for `activities` and `food`; `options` 2 to 6 (`activities` 3 to 6) with unique ids
  (`^[A-Za-z0-9_-]{1,32}$`); each option `title` ≤ 80, `reason` one line ≤ 140, optional
  `duration_min`, `price {amount_cents, currency}`, `area` ≤ 60, `place` ≤ 120; no URL anywhere.
  At most 3 pauses per plan, a kind at most once, at most one of `destination`, `journey`,
  `other`, one question open at a time.
- The tool's answers the coordinator receives (verbatim, from `backend/app/choices.py`):
  - `The traveller chose: a1 "Torre di Belém", a3 "Alfama e i miradouros". Build the plan around these and drop the other options you offered.`
  - `The traveller let you choose. Pick what fits the request best and go on; do not mention it in the warnings.` (activities, food, other)
  - `The traveller did not choose a mode. Take the most sensible one and say so in one warning line.` (journey)
  - `The traveller let you choose. Take your leading candidate and go on.` (destination)
  - `No more questions: choose yourself.` and `One question at a time: the traveller has not answered your open question yet. Ask again after the answer.` (both `is_error`)
  - `ask_traveller rejected: {n} validation error(s). Nothing was shown to the traveller. Fix every one and call ask_traveller again.` (`is_error`, then one `- path: message` line each)
- P14: subagents keep working while the coordinator waits; a report that arrives during the wait
  reaches the coordinator only after its first turn on the answer has ended.
- `journey_mode` is `flight`, `train`, `ferry`, `car`, `coach` or absent (null: the coordinator
  decides). The form's labels: Aereo, Treno, Traghetto, Auto, Pullman.
- The six eval requests keep no mode. One paid evals run for this PR (Michele, 2026-10-18), at
  most $7.00. `evals.yml` runs on every push to a non-draft PR that touches `agents/**`,
  `profiles/**`, `skills/**`: keep the PR a draft until everything is committed.
- Branch: `feat/choices-agents`, stacked on `feat/choices-backend` (PR #26, itself on
  `feat/link-health`, PR #25). Michele prefers rebase to merge.
- Backend commands run from `backend/`. Backend tests need Postgres: export
  `TEST_DATABASE_URL=postgresql+asyncpg://localhost:5432/trip_planner_test_agents`.

## Decisions taken here (Michele: please confirm or overturn)

1. **No new eval request.** A seventh request would raise every evals run's ceiling from $7 to
   $8 (on every agents PR and every deploy), and break the judge's six-plan worst case
   (`6 × 15.6¢ ≤ 1 $`, `test_full_run_of_six_plans_fits_the_spec_cap`). Instead, before the PR
   leaves draft, **one by-hand live plan with an impossible mode** (`journey_mode: "train"`, Roma
   to Cagliari) through `app.cli run --request`, at most $1, only with Michele's OK. It is the
   one path no eval request touches: the feasibility check and the `journey` pause.
2. **`TransferOption.distance_km`** (optional, 1 to 20,000). The spec asks transport for a
   drive's distance, and no existing field can carry it (the result models forbid extra keys).
3. **Parking near the lodging is a transport option with `mode: "other"`**: `from` the car park,
   `to` the lodging, `duration_min` the walk, `price` for the whole stay. No new mode: the spec
   adds only `car`.
4. **A coach is `mode: "bus"`** in transport.json: `TransferMode` has no `coach`, and the spec
   adds only `car`.
5. **`place` for a food card is the style's best-known dish** ("Bacalhau à Brás"): the photo
   lookup searches Wikipedia titles (`app/covers.py`), and a style such as "Tascas di quartiere"
   has no page. `ChoiceOption.place`'s description changes to say so (description only, no
   validation change; `schema/ask_traveller.json` is regenerated).
6. **constraints.json loses `candidates`.** Only the picked destination is researched; the
   offered candidates stay in the coordinator's own context (its `ask_traveller` call) for the
   summary.
7. **With no mode, the coordinator may pick any of the five**: the mode the preferences ask for,
   else the train when rail takes under about five hours, else a flight. So `sea-week-family`
   ("Traghetto con la nostra auto oppure volo più auto a noleggio") can run as a `car` trip, as
   spec §1 says.
8. **Flexible dates with a mode other than flight:** the coordinator fixes the dates itself
   (preferences first), then tasks wave 1. Only `flights` has a "best dates in the month" job.
9. ~~**`flights.md` and `lodging.md` do not change.**~~ Overturned by the PR review
   (2026-10-22): their descriptions are the coordinator's delegation roster, so "destination or
   candidates" still invited research of destinations the traveller did not pick, and every
   flights and lodging request paid for the per-candidate rules. The candidate wording is gone.

## Review Focus

1. **A report is pending when an answer arrives** (P14). The coordinator must end its turn and
   wait, not message or re-task a subagent that "seems slow" (each follow-up costs a research
   round). Test: Task 3 (`test_coordinator_waits_for_pending_reports_after_an_answer`).
2. **The wave-1 activities file has fewer than three options.** The backend refuses an
   `activities` pause with fewer than three; the coordinator must skip the pause, not loop on
   rejections. Test: Task 3 (`test_coordinator_prompt_covers_the_pauses`).
3. **An impossible mode, then "Scegli tu" or the timeout.** The coordinator takes the most
   sensible mode with one warning line; never a plan that fails or has no journey. Test: Task 3
   (`test_coordinator_prompt_covers_the_journey_modes`), live in decision 1.
4. **Transport files written before this PR** (no `distance_km`, `car_rental` drives) still
   validate in the backend and in `write_result.py`. Test: Task 1
   (`test_transfer_option_without_distance_still_validates`,
   `test_transport_draft_with_own_car_and_distance`).
5. **A refused or rejected question.** "No more questions" means decide alone; "One question at
   a time" means wait; a rejection means fix and ask again. Test: Task 3
   (`test_coordinator_prompt_handles_every_refusal`).

---

### Task 0: Branch

- [ ] **Step 1:** The worktree `.claude/worktrees/choices-agents` is on `feat/choices-agents`,
  created from `feat/choices-backend` at `a805394`. This plan is its first commit: `docs: the
  plan for PR 4, the agents for choices and the travel mode`.
- [ ] **Step 2 (whenever `git fetch origin` shows movement):**
  - PR #26 gained commits: `git rebase --onto origin/feat/choices-backend <old tip>
    feat/choices-agents`.
  - PR #26 merged (a squash): `git rebase --onto origin/main <choices-backend tip we sit on>`.

  Never a plain `git rebase origin/main`. After a rebase, regenerate everything the CLAUDE.md
  table lists. If PR 3 landed first with a generated `web/lib/schemas/generated/*` file built
  from `schema/ask_traveller.json`, regenerate it too (Task 1 changes a description in it).

### Task 1: The result contract: `car`, `distance_km`, and the food card's `place`

**Files:**
- Modify: `backend/app/results.py` (`TransferMode`, `TransferOption`),
  `backend/app/choices.py` (`ChoiceOption.place` description only),
  `skills/travel-research-rules/references/option-fields.md` (the transport row)
- Generated: `schema/results/transport.json`, `schema/ask_traveller.json`,
  `skills/travel-research-rules/schemas/transport.json` (run `render_profiles.py`)
- Test: `backend/tests/test_results.py`, `skills/travel-research-rules/test_write_result.py`

**Interfaces:**
- Produces:
  - `TransferMode` gains `"car"`, placed before `"car_rental"`.
  - `MAX_DISTANCE_KM = 20_000` in `results.py`.
  - `TransferOption.distance_km: int | None = Field(default=None, ge=1, le=MAX_DISTANCE_KM,
    description=...)`, placed after `duration_min`. Description: road distance in km for a
    drive (`car`, `car_rental`); null for every other mode.
  - `TransferOption.mode` description: `car` is the travellers' own car, `car_rental` a rented
    one; a long-distance coach is `bus`.
  - `ChoiceOption.place` description: the place's name and its city ("Torre de Belém,
    Lisboa"), a destination's city and country, or a food style's best-known dish ("Bacalhau à
    Brás"); one line, ≤ 120, no URL; used only to look up a photo; omit it otherwise.
  - option-fields.md's transport row lists `car` and `distance_km`, with one line: `car` is the
    party's own car, `car_rental` a rented one, a coach is `bus`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_results.py
def test_transfer_option_accepts_own_car_with_distance() -> None:
    option = TransferOption.model_validate({**DRIVE, "mode": "car", "distance_km": 160})
    assert (option.mode, option.distance_km) == ("car", 160)

@pytest.mark.parametrize("distance", [0, -5, 20_001])
def test_transfer_option_rejects_a_distance_out_of_range(distance: int) -> None: ...

def test_transfer_option_without_distance_still_validates() -> None:
    # a transport option written before this PR: no distance_km key, mode car_rental
    assert TransferOption.model_validate(RENTAL_WITHOUT_DISTANCE).distance_km is None

# skills/travel-research-rules/test_write_result.py
def test_transport_draft_with_own_car_and_distance(tmp_path) -> None: ...   # exit 0, version 1
# and one case in the invalid-draft table:
("transport", _set("options.0.distance_km", 0), "distance_km"),
```

`DRIVE` is a new sample: Milano to Genova Porto, `duration_min` 110, `price` estimated with a
`source_url`, `depart_at` and `arrive_at` null.

- [ ] **Step 2:** Run `uv run pytest tests/test_results.py -q -k "transfer"` and `uv run pytest
  ../skills/travel-research-rules -q`. Expected: FAIL (`car` is not a mode; no `distance_km`).
- [ ] **Step 3: Implement**, then `uv run python -m app.schemas` and `uv run python
  ../scripts/render_profiles.py`. The render must not change any `profiles/**` file yet.
- [ ] **Step 4:** Run the two test commands again, `uv run python -m app.schemas --check`,
  `uv run python ../scripts/render_profiles.py --check`, `uv run ruff check . && uv run pyright`.
  Expected: PASS.
- [ ] **Step 5:** Commit: `feat(agents): TransferMode car and distance_km; a food card's photo comes from its dish`.

### Task 2: Render `ask_traveller.json` and give it to the coordinator

**Files:**
- Modify: `scripts/render_profiles.py` (module docstring, the tool table, `build_outputs`),
  `agents/coordinator.md` (frontmatter `tools`, `description`), `agents/profiles.yaml` (header
  comment's list of outputs), `scripts/session_report.py` (docstring: "the custom tools it
  declares (`agents/tools/*.json`)")
- Generated: `profiles/{development,production}/agents/tools/ask_traveller.json`,
  `profiles/*/agents/coordinator.md`
- Test: `scripts/tests/test_render_profiles.py`, `scripts/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `schema/ask_traveller.json` (PR 2, Task 1 regenerated it).
- Produces:
  - `@dataclass(frozen=True) class CustomTool: name: str; schema: Path; file: str;
    description: str` and `CUSTOM_TOOLS: tuple[CustomTool, ...]` = submit_plan
    (`schema/plan.json`, `agents/tools/submit_plan.json`, today's `SUBMIT_PLAN_DESCRIPTION`)
    then ask_traveller (`schema/ask_traveller.json`, `agents/tools/ask_traveller.json`).
  - `render_custom_tool(repo_root: Path, tool: CustomTool) -> str` replaces
    `render_submit_plan`; same JSON shape (`type`, `name`, `description`, `input_schema`,
    sorted keys, `ensure_ascii=False`, trailing newline).
  - `inline_refs(schema, *, source: str = "plan.json")`: error messages name `source`.
  - The coordinator's `tools` ends with `- ./tools/submit_plan.json` then
    `- ./tools/ask_traveller.json` (comment: generated from schema/ask_traveller.json).
  - The coordinator's `description`: "Plans one trip end to end. Delegates research to flights,
    lodging, activities and transport, asks the traveller up to three questions with
    ask_traveller, chooses, checks coherence and delivers the plan with submit_plan."
  - `ASK_TRAVELLER_DESCRIPTION` (exact):

    ```
    Ask the traveller to choose among 2 to 6 options, shown as cards with photos. Use it only at the moments your instructions name: at most three questions per plan, one at a time. The call returns when the traveller answers, or after a few minutes without an answer: the result names the picked option ids, or says the traveller let you choose. A call with invalid input shows nothing and returns the validation errors: fix every one and call it again. 'No more questions: choose yourself.' means decide alone and do not ask again.
    ```

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_ask_traveller_tool_is_fully_inlined(profile: str) -> None:
    tool = json.loads((REPO_ROOT / "profiles" / profile / "agents/tools/ask_traveller.json").read_text("utf-8"))
    assert set(tool) == {"type", "name", "description", "input_schema"}
    assert (tool["type"], tool["name"]) == ("custom", "ask_traveller")
    assert "$ref" not in json.dumps(tool) and "$defs" not in json.dumps(tool)
    raw = json.loads((REPO_ROOT / "schema/ask_traveller.json").read_text("utf-8"))
    assert tool["input_schema"]["required"] == raw["required"]
    option = tool["input_schema"]["properties"]["options"]["items"]
    assert "Bacalhau" in option["properties"]["place"]["description"]  # Task 1's description

def test_inline_refs_names_its_source() -> None:  # RenderError message contains "ask_traveller.json"
```

  In `test_coordinator_roster_and_custom_tool`: both includes, in that order. In
  `test_bootstrap.py`, beside `coordinator["tools"][1]["name"] == "submit_plan"`:
  `coordinator["tools"][2]["name"] == "ask_traveller"`.

- [ ] **Step 2:** Run `uv run pytest ../scripts -q`. Expected: FAIL.
- [ ] **Step 3: Implement**, then `uv run python ../scripts/render_profiles.py`.
- [ ] **Step 4:** Run `uv run pytest ../scripts -q`, `uv run python ../scripts/render_profiles.py
  --check`, `uv run python ../scripts/bootstrap.py --profile development --dry-run` (lists the
  coordinator with both custom tools), `uv run python ../scripts/session_report.py --static`
  (the coordinator row shows `ask_traveller`), and CLAUDE.md's ruff and pyright lines for
  `../scripts`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(agents): render ask_traveller.json and give the coordinator the tool`.

### Task 3: The coordinator asks, follows the mode and builds on the picks

**Files:**
- Modify: `agents/coordinator.md` (body)
- Generated: `profiles/*/agents/coordinator.md`
- Test: `scripts/tests/test_render_profiles.py`

**What the prompt says**, section by section (write it in the prompt's own voice, terse, as
the sections around it are; keep every phrase the tests below assert):

- **Role.** Two custom tools: `ask_traveller`, the only way to reach the traveller, and
  `submit_plan`. The Italian list adds the questions and options of `ask_traveller`.
- **The request.** The field list adds `journey_mode` (`flight`, `train`, `ferry`, `car`,
  `coach`; absent or null: you choose; `car` is the party's own car, `coach` a long-distance
  bus, `ferry` foot passengers).
- **constraints.json.** Drop `candidates` from the example. One line under it: `journey.mode`
  is the main journey's mode (`flight`, `train`, `ferry`, `car`, `coach`); `journey.file` is
  `results/flights.json` for a flight and `results/transport.json` otherwise; for a drive,
  `arrive_at` is the departure you chose plus the drive's `duration_min`. The food styles
  picked join `preferences`.
- **New section "The main journey"** (before "Steps"):
  - With `journey_mode`: check feasibility first, before any delegation, from your own
    knowledge (a train to Tenerife cannot; a ferry to Milano cannot; a car from Milano to Lisbona
    can, long but possible).
    - Impossible, or contradicted by the preferences ("Aereo" and "solo treno, niente aerei"):
      the `journey` pause (below) with the two to four modes that work (for a contradiction, the
      chosen mode and the one the preferences ask for), titled with the form's labels (Aereo,
      Treno, Traghetto, Auto, Pullman), each `reason` a rough door-to-door time ("Circa 3 h 30
      con scalo").
    - Possible but clearly worse than another mode: respect it; one warning line naming the
      easier mode ("Da Milano a Firenze il treno era più comodo del volo.").
    - With `suggest_destination`: the mode filters the candidates (each reachable by it); a
      contradiction with the preferences is settled by you, with one warning line; no
      `journey` pause.
  - Without `journey_mode`: choose as today: the mode the preferences ask for, else the train
    when rail takes under about five hours, else a flight. No pause and no warning about the
    mode.
  - Delegation by mode: `flight`: `flights`. `train`, `coach`: `transport` researches the main
    journey out and back in wave 1 (links from build_link.py). `ferry`: foot passengers;
    `transport` researches the crossing and the legs to and from the ports in wave 1; no ferry
    seller is a booking site, so a ferry booking has `link` null and the operator's page (its
    price's `source_url`) as the stop's `url`. `car`: the party's own car, car ferries included
    where the route needs one (Milano to Olbia: drive to Genova, then the ferry with the car);
    `transport` researches the drive in wave 1 (duration, distance, estimated fuel and tolls, any
    car ferry with its vehicle fare) and, in wave 2, parking near the lodging and driving to far
    stops. The drive is not a booking; a car ferry is; parking is one only if it must be booked.
    Local legs at the destination: as today, for every mode.
- **New section "Asking the traveller"** (after "The main journey"):
  - The pauses table from spec §2 "When" (`destination`, `journey`, `activities`, `food`,
    `other`: when, cards, select). `activities` and `food` always; `destination`, `journey`,
    `other` share the third slot in that order; a kind once; never more than three.
  - Fields: `question` in Italian, short ("Cosa ti va di vedere?", "Che cucina cerchi?", "Dove
    vuoi andare?", "Come preferisci viaggiare?"). Option ids are the result file's ids (`a3`,
    `l2`) when the option comes from one, else `c1`, `c2`, ... `title` ≤ 80, `reason` one line ≤
    140 on why it fits this party. `duration_min` and `price` (`amount_cents` and `currency`
    only) copied from the result file, never estimated. `area`: the district, when the
    option's location names one. `place`, for the photo: a place's name and city ("Torre de
    Belém, Lisboa", from the option's `location_name`), a destination's city and country
    ("Funchal, Portogallo"), a food style's best-known dish ("Bacalhau à Brás"); none for a
    mode. No URL anywhere. Offer only options you would put in the plan.
  - One `ask_traveller` call per turn, never in the same turn as a delegation.
  - The answers: picks: build the plan around them; the options offered and not picked never
    appear in the plan. "let you choose": choose yourself, no warning (journey: one warning
    line, as its answer says; destination: your leading candidate, which you list first).
  - Refusals: `ask_traveller rejected: ...`: nothing was shown; fix every listed error and ask
    again. `No more questions: choose yourself.`: decide alone, ask nothing more. `One question
    at a time: ...`: end your turn and wait for the open answer.
  - After an answer: subagents kept working while you waited, and a report that arrived
    meanwhile reaches you only after this turn ends. If a subagent you tasked has not replied,
    do only what depends on nothing pending, then end your turn without a message and wait for
    its report; never message, re-task or follow up a subagent because it seems slow.
- **Steps**, renumbered:
  1. Normalize (as today), and settle the main journey's mode ("The main journey"), asking the
     `journey` pause if needed, before any delegation.
  2. Suggest a destination (only with `suggest_destination`): before any delegation, at most
     three candidates from your own knowledge that fit `destination_idea`, the dates, the
     budget, the origin and the mode; ask the `destination` pause: leading candidate first,
     `reason` one line, `area` a rough travel time by the mode ("Circa 2 h di volo"), no prices.
     Then everything researches the chosen destination only. The summary names the candidates
     not taken.
  3. Wave 1, in parallel, by mode: a flight: `flights`, `lodging`, `activities`; any other mode:
     `transport` (the main journey), `lodging`, `activities`. Flexible dates: with a flight, as
     today (flights and activities first); with another mode, fix the dates yourself (the
     preferences first) and task all three.
  4. The `activities` pause, as soon as the wave-1 activities reply is in (do not wait for the
     others): read activities.json and offer the three to six most different options (kinds and
     areas). With fewer than three options in the file, skip this pause.
  5. Choose (today's step 4, unchanged), with the `other` pause only when the third slot is free
     and the fork is real (two very different lodgings, ferry or flight to an island).
  6. The `food` pause, once the journey and the lodging are chosen and before wave 2: three or
     four eating styles typical of the destination, from your own knowledge (no research), with
     no price, duration or area.
  7. Wave 2 (today's step 5), its tasks carrying the picks: activities gets "The traveller
     picked a1, a3: build the days around them and leave out a2, a5. Meals: tascas di quartiere,
     cena con fado." When the traveller let you choose, give your own picks the same way,
     without saying who chose. The picks also inform the rest (two food markets picked: more
     food stops). Transport's task adds, for a drive, parking near the lodging and driving to
     far stops.
  8. Close (today's step 6).
- **Delegating:** "Between steps, wait silently" also covers the wait on `ask_traveller`.
- **Times:** add: the port 1 hour before a ferry as foot passengers and 2 hours with a car,
  unless the operator's page says otherwise; the coach stop 15 minutes before a coach; a drive
  starts at a departure you choose (morning, unless the preferences say otherwise) and its
  arrival is that plus `duration_min`.
- **Composing:** a drive is a `transfer` stop with its duration, distance and estimated fuel and
  tolls in `notes`, not a booking; a car ferry is a `transport` booking; parking is a `parking`
  booking only when it must be booked; a ferry booking has `link` null and the operator's page
  in the stop's `url`. "Airport or station" becomes "airport, station or port" where the
  transfers are listed.
- **Coherence check:** the main journey uses `journey_mode`, or the mode the traveller picked;
  a clumsy mode has its warning line; no option the traveller did not pick is in the plan.
- **Your limits:** tools add `ask_traveller`. The "Nobody reads ..." bullet becomes:

  ```
  - The traveller is reachable only through `ask_traveller`, at most three times per plan, at the moments in "Asking the traveller". Never ask what the request already says, never ask anything else, and never ask a question in a message. Nobody reads or answers your messages during the run. The call returns the answer; waiting needs no other action. When anything else is unclear (which airport, a budget no option meets), choose the most reasonable option, go on, and state the assumption in `warnings`. Your work ends only with an accepted plan: if you stop while no subagent is still working, no question is waiting and `submit_plan` has not answered "Plan accepted.", the whole plan fails.
  ```

- [ ] **Step 1: Write the failing tests** (replace `test_coordinator_never_waits_for_the_user`)

```python
@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_coordinator_reaches_the_traveller_only_through_ask_traveller(profile: str) -> None:
    _, system = agent_file(profile, "coordinator")
    for phrase in ("only through `ask_traveller`", "at most three times per plan",
                   "Never ask what the request already says", "never ask a question in a message",
                   "Nobody reads or answers your messages during the run",
                   "state the assumption in `warnings`", "the whole plan fails"):
        assert phrase in system

def test_coordinator_prompt_covers_the_pauses() -> None:
    _, system = agent_file("development", "coordinator")
    for kind in ("destination", "journey", "activities", "food", "other"):
        assert f"`{kind}`" in system
    for phrase in ("the result file's ids", "skip this pause", "never in the same turn as a delegation",
                   "Bacalhau à Brás", "Torre de Belém, Lisboa", "leave out a2, a5"):
        assert phrase in system

def test_coordinator_waits_for_pending_reports_after_an_answer() -> None:
    # "end your turn without a message and wait for its report", "because it seems slow"

def test_coordinator_prompt_handles_every_refusal() -> None:
    # "ask_traveller rejected", "No more questions: choose yourself.", "One question at a time"

def test_coordinator_prompt_covers_the_journey_modes() -> None:
    # "`journey_mode`", "feasibility first, before any delegation", "Circa 3 h 30 con scalo",
    # "the easier mode", "foot passengers", "the party's own car", "car ferr", "under about five hours"
    # and "candidates" no longer appears in the constraints.json example
```

  `test_coordinator_prompt_honours_the_brief_contract` keeps passing unchanged ("at most three
  candidates" stays in step 2).

- [ ] **Step 2:** Run `uv run pytest ../scripts/tests/test_render_profiles.py -q`. Expected:
  FAIL.
- [ ] **Step 3: Implement** the template, then `uv run python ../scripts/render_profiles.py`.
  Read the rendered `profiles/development/agents/coordinator.md` once end to end: the steps,
  the two new sections and the limits must not contradict each other.
- [ ] **Step 4:** Run `uv run pytest ../scripts -q` and `uv run python
  ../scripts/render_profiles.py --check`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(agents): the coordinator asks the traveller, follows the travel mode and builds on the picks`.

### Task 4: Transport researches every mode; transport and activities cite only pages they saw

**Files:**
- Modify: `agents/transport.md`, `agents/activities.md`
- Generated: `profiles/*/agents/transport.md`, `profiles/*/agents/activities.md`
- Test: `scripts/tests/test_render_profiles.py`

**What the prompts say:**

- **Both, the source rule** (spec §3), in "Prices" (transport) and "Prices and links"
  (activities): a price's `source_url`, and any page URL in the file, is a page you opened with
  `web_fetch` or a URL you saw as a search result, copied exactly; never one composed from a
  site's structure (a path you guessed, a station, route, date or name filled into a URL). A
  fare (transport) or price (activities) read in a search snippet cites that result's URL.
  Activities' "`source_url` is the official page where you read the price" is reworded to fit.
- **Transport:**
  - `description`: "Connects airport, station or port, lodging and activities, and researches
    the main journey when it is not a flight (train, coach, ferry, the party's own car); writes
    /workspace/results/transport.json. Task it in wave 1 for such a main journey, otherwise once
    the journey and the lodging are chosen."
  - Jobs: "Main journey by train" becomes **by train or coach** (a coach is mode `bus`; links
    `trenitalia`, `italo`, `omio` as today). New **by ferry**: foot passengers; the crossing out
    and back as `ferry` options with the operator's times; the legs between the origin and its
    port and between the arrival port and the destination when they are not short walks; `link`
    null (no ferry seller is a booking site), the operator's page as the price's `source_url`.
    New **by car** (the party's own car): the drive out and back as `car` options with
    `duration_min` and `distance_km` from a route planner, times null, and `price` the estimated
    fuel and tolls for the drive (`"estimated"`, the page the figures came from); a car ferry
    where the route needs one, as a `ferry` option whose price includes the vehicle; on the
    follow-up, once the lodging is known, parking near it as one `other` option (`from` the car
    park, `to` the lodging, the walk's `duration_min`, the price for the whole stay, `link`
    null) and a `warnings` line when it must be booked ahead, and `car` options for far stops
    instead of slow public transport.
  - Options: the mode list adds `car` ("the party's own car; `car_rental` is a rented one");
    `distance_km` for drives (`car`, `car_rental`), null otherwise.
  - Sources: ferry companies join the official operators; route planners found with
    `web_search` give a drive's duration, distance and tolls.
  - Cost rules: a drive needs one search for the route (duration, distance, tolls) and one for a
    car ferry when the route has one; parking near the lodging one more at most, inside the cap.
  - Reply: a main-journey task's first line is `transport.json v<N>: <count> options; out <id>
    <mode> <HH:MM | no times>, back <id> <mode> <HH:MM | no times>.`; the local-transfers line
    stays as it is.
- **Activities, the picks** (round 2): when the task names the options the traveller picked,
  build the days around them and leave out the ones the task drops; fill the rest from your
  other options. When it names food styles, the meals follow them: food options of those styles
  from what you hold, or one search for them (inside the cap) when you hold none.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("agent", ["transport", "activities"])
@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_research_prompts_cite_only_pages_they_saw(agent: str, profile: str) -> None:
    _, system = agent_file(profile, agent)
    assert "you opened with `web_fetch` or a URL you saw as a search result" in system
    assert "never one composed from a site's structure" in system
    assert "cites that result's URL" in system

def test_transport_prompt_covers_every_main_journey() -> None:
    # "train or coach", "mode `bus`", "foot passengers", "the party's own car", "`distance_km`",
    # "`car_rental` is a rented one", "car ferry", "parking", "out <id> <mode>"; and in the
    # frontmatter description: "the main journey when it is not a flight"

def test_activities_prompt_builds_the_days_around_the_picks() -> None:
    # "the traveller picked", "food styles"
```

- [ ] **Step 2:** Run `uv run pytest ../scripts/tests/test_render_profiles.py -q`. Expected:
  FAIL.
- [ ] **Step 3: Implement** both templates, then render. Read both rendered files end to end.
- [ ] **Step 4:** Run `uv run pytest ../scripts ../skills -q` and `render_profiles.py --check`.
  Expected: PASS.
- [ ] **Step 5:** Commit: `feat(agents): transport researches train, coach, ferry and car journeys; research cites only pages it saw`.

### Task 5: The `choices_asked` eval check

**Files:**
- Modify: `evals/checks.py` (`RunMetadata`, the check, `CHECKS`), `evals/run.py`
  (`collect_choice_kinds`, `run_case`, `build_entry`), `evals/README.md` (the checks table)
- Test: `evals/tests/test_eval_checks.py`, `evals/tests/test_eval_run.py`

**Interfaces:**
- Consumes: `app.choices.asked_kinds(db, plan_id) -> list[str]` (PR 2; the kinds of the plan's
  rows, in the order asked).
- Produces:
  - `RunMetadata.choice_kinds: tuple[str, ...] | None = None` (None: not collected).
  - `CHOICES_ASKED = "choices_asked"`; `check_choices_asked(request, plan, trip, metadata) ->
    CheckResult`, never blocking. Expected kinds: `activities` and `food`, plus `destination`
    when `request.suggest_destination`. `pass` "asked: destination, activities, food"; `warn`
    "missing: food" with the asked kinds in the detail; `skip` "choices were not collected"
    when `choice_kinds` is None. With no plan: `_no_plan(...)`, not blocking (as `dead_links`).
  - `async def collect_choice_kinds(planner: PlannerServices, plan_id: uuid.UUID) -> list[str]`
    beside `collect_picks`; `run_case` records a failure in `extra["choice_kinds_error"]` and
    passes None; `build_entry(..., choice_kinds: Sequence[str] | None = None)` fills
    `RunMetadata` and adds `"choice_kinds"` to the entry.
  - README row: `choices_asked` | The plan asked about activities and food (and the destination
    with "Suggeriscimi tu"), through `ask_traveller` (never blocks).

- [ ] **Step 1: Write the failing tests**

```python
def test_choices_asked_passes_with_activities_and_food() -> None: ...
def test_choices_asked_expects_the_destination_with_suggest() -> None: ...   # warn "missing: destination"
def test_choices_asked_warns_when_a_pause_is_missing() -> None: ...           # ("activities",) -> warn "missing: food"
def test_choices_asked_skips_when_not_collected() -> None: ...
async def test_run_case_records_the_choice_kinds(monkeypatch, ...) -> None: ...  # entry["choice_kinds"]
```

- [ ] **Step 2:** Run `uv run pytest ../evals/tests -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `uv run pytest ../skills ../scripts ../evals/tests -q`, `uv run ruff check
  ../evals && uv run pyright -p ../evals`, `uv run python ../evals/run.py --dry-run`. Expected:
  PASS.
- [ ] **Step 5:** Commit: `feat(evals): choices_asked counts the pauses each plan asked`.

### Task 6: Docs, every check, the lockfile and the one paid run

**Files:**
- Modify: `CLAUDE.md` (Layout: `profiles/<profile>/` lists `agents/tools/ask_traveller.json`;
  "Agents, prompts and skills": `tools/ask_traveller.json` is built from
  `schema/ask_traveller.json`, so a `ChoiceRequest` change, like a Plan change, runs `python -m
  app.schemas` before rendering; one bullet: only the coordinator reaches the traveller, through
  `ask_traveller`, at most three pauses), `docs/managed-agents-notes.md` §2e (the "the prompt
  should tell it to end its turn" bullet points at coordinator.md's "Asking the traveller")
- Commit later: `backend/claude-lock.development.json`

- [ ] **Step 1:** `git fetch origin` and rebase as Task 0 says; regenerate everything the
  CLAUDE.md table lists.
- [ ] **Step 2:** Run every check CI runs. From `backend/`:

  ```sh
  uv run ruff check . && uv run ruff format --check . && uv run pyright
  uv run python -m app.schemas --check
  uv run python ../scripts/render_profiles.py --check
  uv run python ../web/scripts/gen-backend-fixtures.py --check
  uv run pytest -q
  ```

  Then CLAUDE.md's non-backend checks (pytest, ruff, ruff format, pyright for `../scripts`,
  `../evals`, `../skills`; the two `--dry-run`s). From `web/`: `npm run gen:schemas -- --check`.
  `git diff --stat origin/feat/choices-backend...` must show nothing under `backend/app/plan.py`
  and nothing in `backend/` beyond `results.py`, `choices.py`, `schema` and tests. Expected: all
  PASS.
- [ ] **Step 3:** Commit: `docs: ask_traveller in CLAUDE.md and the notes`.
- [ ] **Step 4 (Michele's OK):** `ant apply --lock-file backend/claude-lock.development.json
  --force profiles/development` from the repository root, with the development key (free: it
  creates agent and skill versions, no session). Commit the lockfile: `chore(agents):
  development lockfile for the choice pauses and the travel mode`. Without `ant` or the key
  locally: download CI's `claude-lock-development` artifact after the paid run and commit it
  with `[skip ci]` in the message, as `b442764` did.
- [ ] **Step 5 (Michele's OK, decision 1):** one by-hand plan with an impossible mode, at most $1:
  `uv run python -m app.cli run --request <scratchpad>/train-to-sardinia.json` (it runs the
  versions Step 4 applied, and answers each pause with the first option) with:

  ```json
  {"origin": "Roma", "destination": "Cagliari", "journey_mode": "train",
   "dates": {"exact_start": "2026-12-04", "exact_end": "2026-12-07"},
   "travelers": [{"kind": "adult"}, {"kind": "adult"}], "budget_eur": 900,
   "preferences": "Centro storico a piedi, cucina sarda."}
  ```

  (Move the dates to a Friday 5 to 7 weeks ahead if this runs after mid-November.) Expected: a
  `journey` pause offering modes that work, then `activities` and `food`, then a `ready` plan
  whose journey is not a train. A prompt fix here is re-rendered, recommitted and re-applied
  before Step 7.
- [ ] **Step 6:** Ask Michele before pushing. Push and open the PR **as a draft**, base
  `feat/choices-backend`. Title: `feat(agents): the coordinator asks the traveller and follows
  the travel mode`. The body: the spec link, this plan's nine decisions, "evals: one paid run
  when marked ready", and the merge order below.
- [ ] **Step 7: The paid run** (one, ≤ $7). Preconditions: PR #25 merged and its post-merge
  `dead_links` run done (spec §3 "Evals": the count's starting point), and every commit pushed.
  On Michele's go, mark the PR ready for review: `evals.yml` runs once. Do not push again
  afterwards without his OK: every push re-runs it.
- [ ] **Step 8:** Report from the PR comment and the results file: blocking failures;
  `choices_asked` per request; `dead_links` against the post-PR-1 run; the judge's
  `preference_respect`; cost per plan against the 100-cent budget and how many plans hit
  `budget_paused`.
- [ ] **Step 9: Merge order** (Michele merges): PR #25, #26, then PR 3 (the web cards)
  **deployed**, then this PR. Its merge runs `deploy-agents.yml`: the evals again, Michele's
  approval, `ant apply` of production. PR 5 (the mode in the form) merges after that apply.
