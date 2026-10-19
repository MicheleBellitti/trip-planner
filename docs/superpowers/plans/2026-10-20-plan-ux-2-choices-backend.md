# Plan UX, PR 2: the backend for choices and the travel mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The backend accepts a travel mode in the request and handles the coordinator's
`ask_traveller` custom tool end to end: it validates the call, finds the photos, stores the
pending choice, shows it on the timeline and in `GET /plans/{id}`, takes the traveller's answer
through a new endpoint, picks for them after 4 minutes, and survives restarts, interrupts and
budget pauses. The local demo, the CLI and the evals answer choices. No agent asks yet: that
starts in PR 4.

**Architecture:** `app/choices.py` holds the tool's contract (`ChoiceRequest`, the answer texts,
the limits) and the `choices` table's queries. The consumer answers an `ask_traveller` use by
storing a row and a `choice` timeline event, then arming a deadline that reaches its inbox like
a stream event. Whoever closes the row first (the endpoint, the deadline, the platform's own
closure on interrupt) wins a conditional update. That update runs inside `EventSink`'s plan-row
lock, together with the "answered" event. Only the winner sends `user.custom_tool_result`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async + Alembic, httpx, pytest + respx +
time-machine, the offline `FakeManagedAgentsClient`; the web only regenerates its schemas and
fixes the three spots a new request field touches.

**Spec:** `docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md`. This PR covers: §1 "The
request contract"; §2 "The mechanism" (input, answers, the backend's side), "Evals and the CLI",
the `DEMO_MODE` half of "Demo" and "Cost"; §4 row 2; §6's offline tests. The platform facts are
from live probe P14: `docs/probes/2026-10-18.md` and `docs/managed-agents-notes.md` §2e "A custom
tool left waiting".

## Global Constraints

- Paths this PR never touches: `agents/**`, `profiles/**`, `skills/**`, `backend/app/plan.py`
  (they trigger the paid `evals.yml` and, on merge, a production `ant apply`). `TransferMode`
  `car`, the coordinator prompt and the `tools/ask_traveller.json` rendering ship in PR 4.
- `journey_mode: Literal["flight", "train", "ferry", "car", "coach"] | None = None`. Null means
  the coordinator decides, exactly as today (contract rule 7: old clients, stored requests and
  eval requests carry no mode).
- `ask_traveller` input: `kind` one of `destination`, `journey`, `activities`, `food`, `other`.
  `question` at most 120 characters. `multiple` is true exactly for `activities` and `food`.
  `options` has 2 to 6 items (`activities` 3 to 6), with unique ids. Each option has
  `id`, `title` (≤ 80), `reason` (one line, ≤ 140), and optional `duration_min`,
  `price {amount_cents, currency}`, `area` (≤ 60) and `place` (≤ 120). No URL anywhere in the
  input.
- Limits: at most 3 pauses per plan, a kind at most once, and at most one of `destination`,
  `journey`, `other` (they share the third slot). A call refused for a limit or rejected as
  invalid is not a pause: it stores no row and shows nothing to the traveller.
- Tool answers, verbatim (English, to the coordinator):
  - picks: `The traveller chose: a1 "Torre di Belém", a3 "Alfama e i miradouros". Build the plan around these and drop the other options you offered.`
    The ids follow the order offered. With one pick the text says `around it` instead of
    `around these`.
  - skip or timeout, for `activities`, `food`, `other`: `The traveller let you choose. Pick what fits the request best and go on; do not mention it in the warnings.`
  - skip or timeout, for `journey`: `The traveller did not choose a mode. Take the most sensible one and say so in one warning line.`
  - skip or timeout, for `destination`: `The traveller let you choose. Take your leading candidate and go on.`
  - refused (a limit, or a plan already accepted): `No more questions: choose yourself.` (`is_error`)
  - invalid: `is_error`, with the header
    `ask_traveller rejected: {n} validation error(s). Nothing was shown to the traveller. Fix every one and call ask_traveller again.`
    followed by one `- path: message` line per problem.
- `CHOICE_TIMEOUT_SECONDS` defaults to 240 (Settings `ge=1, le=290`). The answer must come within
  the 5-minute prompt cache: P14 resumed warm after 243 s, and every cache write was a 5-minute
  write. Photo lookups get 3 s in all, then the event goes out without the photos still missing.
- Timeline titles (Italian, sentence case, no em dash):
  - asked: `Tocca a te: scegli la destinazione`, `Tocca a te: scegli come viaggiare`,
    `Tocca a te: scegli cosa vedere`, `Tocca a te: scegli cosa mangiare`,
    `Tocca a te: scegli tra le opzioni`
  - answered: `Hai scelto: {titles, comma separated}`, `Hai lasciato scegliere ad Atlas`,
    `Tempo scaduto: sceglie Atlas`, `Domanda chiusa: piano interrotto`
  - the raw tool use: `Domanda al viaggiatore`
- Errors use the envelope. `choice_not_found` 404 "Questa domanda non c'è.";
  `choice_closed` 409 "Questa scelta è già chiusa: il piano va avanti." (data
  `{answered_by}`); `invalid_choice_answer` 422 "La risposta non corrisponde alle opzioni
  proposte: ricarica la pagina e riprova." (data `{reason}`). A malformed body keeps FastAPI's
  422.
- Logs: `choice_asked` (kind, options, photos), `choice_answered` (kind, answered_by, options,
  selected, latency_ms), `choice_rejected` (errors) and `choice_refused` (reason). Never the
  question, a title, a place or a URL.
- One Alembic migration. Its `down_revision` is `origin/main`'s head at merge time:
  `924fdf7a0667` (link_health) once PR #25 lands.
- Code and logs are in English; what the user reads is in Italian. Generated files are
  regenerated, never hand-edited (the CLAUDE.md table). Backend commands run from `backend/`,
  web commands from `web/`. Tests need Postgres: export
  `TEST_DATABASE_URL=postgresql+asyncpg://localhost:5432/trip_planner_test_choices`.

## Decisions taken here (Michele: please confirm or overturn)

1. **`answered_by` gains `closed`.** The spec lists `traveller`, `skip` and `timeout`. P14 shows
   that on `user.interrupt` the platform closes the pending call itself, with an
   `agent.tool_result` (`is_error`). The backend then closes the row as `closed` and sends
   nothing.
2. **The endpoint sends the answer itself.** It does not hand the answer to the consumer: a
   request can land on the process that does not hold the plan's lease (a redeploy's overlap).
   The conditional update decides the winner. If the send fails, the consumer resends the stored
   answer at the deadline, because no result echo arrived.
3. **A refused or invalid call gets no backend timeline event.** The raw tool use ("Domanda al
   viaggiatore") and the result echo already show. Both are answered again, deterministically,
   on resume.
4. **A budget pause during a pause.** In P14 the subagents kept working, and spending, while
   the coordinator waited; development plans often hit the budget. So `budget_reached` during a
   pause is `budget_paused` as today. "Continua" restarts the consumer, which re-arms the choice
   (or times it out if its deadline has passed). It does not send `CONTINUE_MESSAGE` while a
   choice is still pending: the tool result is what resumes the coordinator. This is
   [INFERRED]; P14 did not test a budget pause during a wait.
5. **The demo scenario is new and not the default.** `choices` is offered with
   `?demo_scenario=choices`. `happy_path` stays the default until PR 3 can draw the cards, so the
   current web never waits 4 minutes on a card it cannot show. `choice_interrupt` is a test
   scenario and is not offered in the demo. Demo photos come with PR 3's fixture; here
   `DEMO_MODE` and `app.cli replay` look up no photos.
6. **Place photos share `destination_covers`.** They are keyed `place:<cache_key>`, so they
   cannot collide with a destination, and they use the same TTLs and the same free-licence rules.
   The spec allowed this.

## Review Focus

1. **The traveller answers in the very second the deadline fires.** Exactly one answer reaches
   the agent, and the row, the timeline and the tool result agree. Tests: Task 3
   (`test_close_choice_concurrent_one_wins`) and Task 7
   (`test_answer_before_the_deadline_cancels_the_timer`).
2. **The budget runs out during a pause** (subagents keep spending). The plan is
   `budget_paused`, the endpoint answers 409, and after "Continua" the choice is re-armed or timed
   out, with no `CONTINUE_MESSAGE` while it is pending. Test: Task 7
   (`test_budget_reached_during_a_pause_then_continue`).
3. **A restart or redeploy mid-pause.** The resumed consumer keeps the original deadline, not a
   fresh 4 minutes. It also delivers an answer that was given while no consumer ran. Tests: Task
   7 (`test_resume_rearms_with_the_original_deadline`,
   `test_resume_answers_from_an_answered_row`).
4. **The answer's send fails** after the row is stored. The coordinator is not left waiting
   forever: the deadline resends the stored answer once. Test: Task 7
   (`test_timer_resends_an_answer_whose_send_failed`).
5. **A reload during a pause shows the cards at once. After "Interrompi" none show, and an
   answer is 409.** Tests: Task 8 (`test_plan_detail_pending_choice`) and Task 7
   (`test_interrupt_while_waiting_closes_the_choice`).

---

### Task 0: Branch

- [ ] **Step 1:** In this worktree run `git branch -m feat/choices-backend`. The branch starts at
  `origin/feat/link-health` `fedcdab`, because PR #25 is still open. This plan is the branch's
  first commit (`docs: the plan for PR 2, the backend for choices and the travel mode`).
- [ ] **Step 2 (whenever `git fetch origin` shows movement):**
  - PR #25 gained commits: `git rebase --onto origin/feat/link-health <old tip> feat/choices-backend`.
  - PR #25 merged (a squash): `git rebase --onto origin/main <link-health tip we sit on>`.

  Never run a plain `git rebase origin/main`: it would replay #25's commits. Michele prefers
  rebase to merge. After a rebase, regenerate the generated files and re-point the migration's
  `down_revision`.

### Task 1: `PlanRequest.journey_mode`

**Files:**
- Modify: `backend/app/request.py`, `web/lib/demo/request.ts` (`journey_mode: null`),
  `web/lib/request-form.ts` (a `REQUEST_FIELD_COPY.journey_mode` entry, label `Mezzo di
  viaggio`, the same shape as its neighbours), `web/components/request/request-form.test.tsx`
  (the expected `createPlan` body gains `journey_mode: null`)
- Generated: `schema/request.json`, `web/lib/schemas/generated/request.ts`
- Test: `backend/tests/test_request.py`, `backend/tests/test_sessions.py`

**Interfaces:**
- Produces:
  - `JourneyMode = Literal["flight", "train", "ferry", "car", "coach"]` and
    `JOURNEY_MODES: tuple[JourneyMode, ...]`.
  - `PlanRequest.journey_mode: JourneyMode | None = None`, placed after `destination_idea`. Its
    description: the main journey's mode, out and back (`car` is the travellers' own car, car
    ferries included; `coach` a long-distance bus; `ferry` foot passengers); null lets the
    coordinator decide.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("mode", ["flight", "train", "ferry", "car", "coach"])
def test_journey_mode_accepts_each_mode(mode: str) -> None:
    assert PlanRequest.model_validate({**VALID, "journey_mode": mode}).journey_mode == mode

def test_journey_mode_defaults_to_none() -> None: ...           # VALID has no key -> None
def test_journey_mode_rejects_an_unknown_mode() -> None: ...    # "plane" -> error at ("journey_mode",)
def test_from_stored_reads_a_request_stored_before_the_mode() -> None: ...
def test_brief_omits_a_null_mode_and_carries_a_set_one() -> None:
    assert '"journey_mode"' not in build_brief(request_without_mode, today=TODAY)
    assert '"journey_mode": "train"' in build_brief(train_request, today=TODAY)
```

- [ ] **Step 2:** Run `uv run pytest tests/test_request.py tests/test_sessions.py -q -k "journey
  or brief"`. Expected: FAIL.
- [ ] **Step 3: Implement** the field, then `uv run python -m app.schemas`, then `npm run
  gen:schemas` from `web/`, then the three web edits. The form keeps sending no chosen mode
  (`null`); the mode row is PR 5.
- [ ] **Step 4:** Run the backend tests again, `uv run python -m app.schemas --check`, and from
  `web/`: `npm run gen:schemas -- --check && npm run typecheck && npm test`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(backend): PlanRequest.journey_mode; null lets the coordinator decide`.

### Task 2: The `ask_traveller` contract

**Files:**
- Create: `backend/app/choices.py` (the module docstring cites spec §2 and the P14 facts)
- Modify: `backend/app/schemas.py` (`"ask_traveller.json": ask_traveller_input_schema`, the
  docstring's file list)
- Generated: `schema/ask_traveller.json` (`render_profiles.py` and the web's generator ignore it
  until PR 4)
- Test: `backend/tests/test_choices.py`, `backend/tests/test_schemas_export.py`
  (`EXPECTED_FILES`)

**Interfaces:**
- Consumes: `app.plan.ContractModel`, `describe_validation_errors`, the cap of
  `plan.Price.amount_cents` (imported, never edited).
- Produces, in `app/choices.py`:
  - Constants and types:
    - `ASK_TRAVELLER_TOOL = "ask_traveller"`
    - `ChoiceKind` (the five kinds); `MULTIPLE_KINDS = frozenset({"activities", "food"})`;
      `SHARED_SLOT_KINDS = frozenset({"destination", "journey", "other"})`
    - `MAX_CHOICES_PER_PLAN = 3`
    - `AnsweredBy = Literal["traveller", "skip", "timeout", "closed"]`
  - Models (`ContractModel`; every field description states its rule, because the schema is the
    agent's documentation):
    - `ChoicePrice`: `amount_cents`, `currency` matching `^[A-Z]{3}$`.
    - `ChoiceOption`: the fields of Global Constraints; `id` matches `^[A-Za-z0-9_-]{1,32}$`;
      `duration_min` runs 1 to 1440.
    - `ChoiceRequest`: its after-validator checks that `multiple` matches the kind, that
      `activities` has at least 3 options, that the ids are unique, and that no text field
      matches `URL_PATTERN = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.-]*://|www\.)")`.
  - Parsing and admission:
    - `@dataclass(frozen=True, slots=True) class ChoiceRejected: message: str; errors: list[str]`
    - `parse_choice_request(tool_input: Any) -> ChoiceRequest | ChoiceRejected`
    - `NO_MORE_QUESTIONS_TEXT`
    - `admission_refusal(kind: ChoiceKind, asked: Collection[str], *, accepted: bool) -> str | None`
      returns the log reason `"accepted"`, `"limit"`, `"same_kind"` or `"shared_slot"`, else None.
  - Answers:
    - `class ChoiceAnswer(BaseModel)` (extra forbid; the endpoint's body):
      `selected: list[str] | None = Field(None, min_length=1, max_length=6)`,
      `skip: bool = False`. Exactly one of the two must be given.
    - `selection_problem(request: ChoiceRequest, selected: Sequence[str]) -> str | None`
      returns `"duplicate"`, `"unknown_option"` or `"single_choice"` (not exactly one pick when
      `multiple` is false).
    - `answer_text(request: ChoiceRequest, answered_by: AnsweredBy, selected: Sequence[str]) -> str`
    - `auto_pick(request: ChoiceRequest) -> list[str]` gives the first id, or the first two when
      `multiple` (evals and CLI).
  - Titles: `asked_title(kind: ChoiceKind) -> str` and
    `answered_title(request: ChoiceRequest, answered_by: AnsweredBy, selected: Sequence[str]) -> str`
    (passed through `events.one_line`).
- Produces, in `app/schemas.py`: `ask_traveller_input_schema() -> JsonSchema`, an object schema
  that passes `check_self_contained`, like `plan_input_schema`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_valid_activities_request_parses() -> None: ...       # 4 options, multiple=True
@pytest.mark.parametrize(("change", "path"), [
    ({"multiple": False}, ()),                                   # activities must be multiple
    ({"kind": "journey"}, ()),                                   # journey must be single
    ({"options": OPTIONS[:2]}, ("options",)),                    # activities needs 3
    ({"options": [*OPTIONS, *OPTIONS[:3]]}, ("options",)),       # 7 > 6
    ({"options": [OPTIONS[0], OPTIONS[0], OPTIONS[1]]}, ()),     # duplicate ids
    ({"question": "x" * 121}, ("question",)),
])
def test_invalid_requests_are_rejected(change, path) -> None: ...
@pytest.mark.parametrize("text", ["vedi https://x.pt", "www.visitlisboa.com", "ftp://a"])
def test_no_url_anywhere(text: str) -> None: ...                 # in reason, title, area or place
def test_parse_choice_request_message() -> None:
    rejected = parse_choice_request({"kind": "food"})
    assert isinstance(rejected, ChoiceRejected)
    assert rejected.message.startswith("ask_traveller rejected: ")
    assert "Nothing was shown to the traveller." in rejected.message
@pytest.mark.parametrize(("kind", "asked", "accepted", "reason"), [
    ("food", ["activities"], False, None),
    ("other", ["activities", "food"], False, None),
    ("destination", ["activities", "food", "other"], False, "limit"),
    ("food", ["food"], False, "same_kind"),
    ("journey", ["destination"], False, "shared_slot"),
    ("food", [], True, "accepted"),
])
def test_admission_refusal(kind, asked, accepted, reason) -> None: ...
def test_answer_texts_are_the_spec_s() -> None:
    assert answer_text(ACTIVITIES, "traveller", ["a3", "a1"]) == (
        'The traveller chose: a1 "Torre di Belém", a3 "Alfama e i miradouros". Build the plan '
        "around these and drop the other options you offered.")
    assert answer_text(JOURNEY, "traveller", ["c2"]).endswith(
        "Build the plan around it and drop the other options you offered.")
    assert answer_text(FOOD, "timeout", []) == answer_text(FOOD, "skip", []) == (
        "The traveller let you choose. Pick what fits the request best and go on; do not "
        "mention it in the warnings.")
    # journey and destination: the exact texts of Global Constraints
def test_selection_problem() -> None: ...    # unknown id; two on single; duplicate; ok -> None
def test_choice_answer_needs_exactly_one_of_selected_or_skip() -> None: ...
def test_auto_pick() -> None: ...            # ["a1", "a2"] multiple; ["c1"] single
def test_titles() -> None:
    assert asked_title("activities") == "Tocca a te: scegli cosa vedere"
    assert answered_title(ACTIVITIES, "traveller", ["a3", "a1"]) == (
        "Hai scelto: Torre di Belém, Alfama e i miradouros")
    assert answered_title(FOOD, "closed", []) == "Domanda chiusa: piano interrotto"
def test_ask_traveller_schema_is_self_contained() -> None: ...   # and listed in EXPECTED_FILES
```

- [ ] **Step 2:** Run `uv run pytest tests/test_choices.py tests/test_schemas_export.py -q`.
  Expected: FAIL.
- [ ] **Step 3: Implement,** then `uv run python -m app.schemas`.
- [ ] **Step 4:** Run the tests, `uv run python -m app.schemas --check`, `uv run python
  ../scripts/render_profiles.py --check` (unchanged), `uv run ruff check . && uv run pyright`.
  Expected: PASS.
- [ ] **Step 5:** Commit: `feat(backend): the ask_traveller contract and schema/ask_traveller.json`.

### Task 3: The `choices` table, the `choice` event kind and closing a choice once

**Files:**
- Create: `backend/migrations/versions/20261020_<rev>_choices.py` (autogenerate, then review:
  one table, its index and its two check constraints; nothing else)
- Modify: `backend/app/db.py` (`ChoiceRecord`), `backend/app/events.py` (`EventKind.CHOICE =
  "choice"`), `backend/app/choices.py` (the views and the queries),
  `backend/app/consumer.py` (the `EventSink` guard, `close_choice`, `choice_asked_event`)
- Generated: `schema/ui_event.json`, `web/lib/schemas/generated/ui-event.ts`. Today's web then
  accepts a `choice` event, stores it in its lane and draws nothing for it; PR 3 draws it.
- Test: `backend/tests/test_choices_store.py`, `backend/tests/test_db.py` (the drift check,
  unchanged)

**Interfaces:**
- Consumes: Task 2; `covers.Cover`.
- Produces:
  - `ChoiceRecord`, table `choices`:

    | Column | Type |
    |---|---|
    | `id` | Text PK (the `agent.custom_tool_use` id) |
    | `plan_id` | UUID FK `plans.id`, `ondelete="CASCADE"`, indexed |
    | `kind` | Text, check: one of the kinds |
    | `payload` | JSONB, not null: `{"request": <ChoiceRequest json>, "photos": {<option id>: <Cover json>}}` |
    | `asked_at`, `deadline_at` | timestamptz |
    | `answer` | JSONB null: the list of picked ids |
    | `answered_by` | Text null, check: one of `AnsweredBy` |
    | `answered_at` | timestamptz null |

  - `app/choices.py`, the views:
    - `class ChoiceOptionView(BaseModel)`: id, title, reason, duration_min,
      price (`ChoicePrice | None`), area, photo (`Cover | None`). There is no `place`: it is only
      the lookup key.
    - `class PendingChoice(BaseModel)`: `id`, `kind`, `question`, `multiple`,
      `options: list[ChoiceOptionView]`, `asked_at`, `deadline_at` (both `AwareDatetime`).
      Built by `from_record(record) -> PendingChoice`.
    - `request_of(record: ChoiceRecord) -> ChoiceRequest`
  - `app/choices.py`, the queries:
    - `insert_choice(db, *, choice_id, plan_id, request, photos: Mapping[str, Cover],
      asked_at, deadline_at) -> ChoiceRecord` (`ON CONFLICT DO NOTHING`; returns the stored
      row, so an existing row wins)
    - `get_choice(db, plan_id, choice_id) -> ChoiceRecord | None`
    - `asked_kinds(db, plan_id) -> list[str]`
    - `pending_choice(db, plan_id) -> ChoiceRecord | None` (`answered_by IS NULL`, the latest
      `asked_at`)
    - `answered_choices(db, plan_id) -> list[ChoiceRecord]` (by `asked_at`)
  - `app/consumer.py`, the guard: `Guard = Callable[[AsyncSession], Awaitable[bool]]`.
    `EventSink.emit(build, *, ma_event_id, update=None, guard: Guard | None = None)` runs
    `guard` after the plan-row lock and the duplicate check. When it returns False, nothing is
    stored or changed. `EmitResult.refused: bool = False` records that.
  - `app/consumer.py`, closing:
    - `close_choice(sink: EventSink, choice_id: str, *, answered_by: AnsweredBy, selected:
      Sequence[str], now: dt.datetime, cost_cents: int | None = None) -> ChoiceRecord | None`
      returns the closed row only when this call closed it, else None (already closed, or
      absent). The guard is
      `UPDATE choices SET answer, answered_by, answered_at WHERE id = :id AND plan_id = :plan
      AND answered_by IS NULL RETURNING *`; the returned row feeds the event's title.
    - The event: kind `choice`, key `backend_event_id(plan_id, "choice", f"{id}:closed")`, title
      `answered_title(...)`, detail `{"event_type": "backend.choice", "phase": "answered",
      "choice_id", "kind", "answered_by", "selected", "answered_at"}`.
  - `app/consumer.py`, asking: `choice_asked_event(record: ChoiceRecord, *, cost_cents: int |
    None) -> EventBuilder` builds a kind `choice` event with title `asked_title(kind)` and
    detail `{"event_type": "backend.choice", "phase": "asked", "choice":
    PendingChoice.from_record(record) as JSON}`. Its key is
    `backend_event_id(plan_id, "choice", f"{id}:asked")`.

- [ ] **Step 1: Write the failing tests** (`db_session_factory`, a seeded plan row)

```python
async def test_insert_choice_is_idempotent(...) -> None: ...     # 2nd insert, other photos: 1st row returned
async def test_pending_choice_is_the_open_one(...) -> None: ...  # an answered row is not pending
async def test_asked_kinds(...) -> None: ...
async def test_close_choice_once(...) -> None:
    first = await close_choice(sink, "sevt_q1", answered_by="traveller", selected=["a1"], now=NOW)
    second = await close_choice(sink, "sevt_q1", answered_by="timeout", selected=[], now=NOW)
    assert first is not None and first.answered_by == "traveller" and second is None
    assert [e.title for e in await choice_events()] == ["Hai scelto: Torre di Belém"]
async def test_close_choice_concurrent_one_wins(...) -> None:
    results = await asyncio.gather(close(traveller), close(timeout))
    assert sum(r is not None for r in results) == 1     # one event; the row says the winner
async def test_close_choice_of_an_unknown_id_stores_nothing(...) -> None: ...
async def test_emit_guard_false_stores_nothing(...) -> None: ... # refused=True, no event, no update
async def test_choices_are_deleted_with_their_plan(...) -> None: ...
def test_ui_event_kind_includes_choice() -> None: ...
```

- [ ] **Step 2:** Run `uv run pytest tests/test_choices_store.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run alembic revision --autogenerate -m "add choices"`, keep
  only the table, and set `down_revision = "924fdf7a0667"`. Then `uv run alembic upgrade head`
  on the dev database, `uv run python -m app.schemas`, and `npm run gen:schemas` from `web/`.
- [ ] **Step 4:** Run `uv run pytest tests/test_choices_store.py tests/test_db.py
  tests/test_ui_event.py -q`, `uv run python ../web/scripts/gen-backend-fixtures.py --check`,
  and from `web/`: `npm run gen:schemas -- --check && npm run typecheck && npm test`.
  Expected: PASS.
- [ ] **Step 5:** Commit: `feat(backend): the choices table, the choice event kind and a choice closed once`.

### Task 4: Place photos

**Files:**
- Modify: `backend/app/covers.py`, `backend/app/config.py` (`choice_photos_enabled: bool =
  True`), `backend/.env.example` (`CHOICE_PHOTOS_ENABLED=true`, with the reason "free-licence
  Wikimedia photos for the choice cards; false = no lookup, cards without photos"),
  `backend/tests/conftest.py` (`TEST_ENV["CHOICE_PHOTOS_ENABLED"] = "false"`)
- Test: `backend/tests/test_covers.py` (its `wikimedia` fake), `backend/tests/test_config.py`

**Interfaces:**
- Produces:
  - `CoverResolver(..., key_prefix: str = "", lookup_deadline_seconds: float =
    LOOKUP_DEADLINE_SECONDS)`. The prefix goes before the cache key, in memory and in the table.
  - Constants: `PLACE_KEY_PREFIX = "place:"`, `PHOTO_DEADLINE_SECONDS = 3.0`.
  - `class ChoicePhotos(Protocol): async def photos_for(self, places: Mapping[str, str]) ->
    dict[str, Cover]`. It maps option id to place name and returns option id to `Cover` for the
    photos found in time. It never raises, except on cancellation.
  - `class PlacePhotos(resolver: CoverResolver, *, deadline_seconds: float =
    PHOTO_DEADLINE_SECONDS)`: runs the lookups in parallel, waits at most the deadline, and
    cancels the rest.
  - `class NoPhotos` and `NO_PHOTOS` (returns `{}`).

- [ ] **Step 1: Write the failing tests**

```python
async def test_place_photos_finds_a_place(wikimedia, make_place_photos) -> None: ...
async def test_place_photos_leaves_out_a_place_without_a_free_photo(...) -> None: ...
async def test_place_photos_returns_what_is_found_by_the_deadline(...) -> None:
    # one place's Wikipedia route sleeps 5 s, deadline 0.2 s: the other place is returned,
    # the slow one is missing, elapsed < 0.7 s
async def test_place_keys_do_not_collide_with_destination_covers(...) -> None:
    # resolving destination "Lisbona" and place "Lisbona": rows "lisbona" and "place:lisbona"
async def test_place_photos_send_only_the_place_name(...) -> None: ...  # titles= the place parts
async def test_no_photos() -> None: assert await NO_PHOTOS.photos_for({"a1": "X"}) == {}
def test_choice_photos_setting(make_settings) -> None: ...      # default True
```

- [ ] **Step 2:** Run `uv run pytest tests/test_covers.py tests/test_config.py -q -k "place or
  photos"`. Expected: FAIL.
- [ ] **Step 3: Implement.** The destination path keeps its 15 s deadline and its keys, so every
  existing covers test passes unchanged.
- [ ] **Step 4:** Run `uv run pytest tests/test_covers.py tests/test_config.py -q`. Expected:
  PASS.
- [ ] **Step 5:** Commit: `feat(backend): free-licence photos for the choice cards, under a 3 s deadline`.

### Task 5: The fake client closes a waiting call on interrupt; the choice scenarios

**Files:**
- Modify: `backend/tests/fakes/__init__.py` (`send_interrupt`), `backend/tests/fakes/README.md`
  (the semantics table, the scenario rows), `backend/tests/fakes/demo.py`
  (`EXCLUDED_SCENARIOS` gains `choice_interrupt`)
- Create: `backend/tests/fixtures/ma/choices.jsonl`, `backend/tests/fixtures/ma/choice_interrupt.jsonl`
- Test: `backend/tests/test_fake_client.py` (`ReferenceConsumer` answers `ask_traveller` with
  `auto_pick`), `backend/tests/test_fixture_shapes.py` (every `ask_traveller` input validates as
  `ChoiceRequest`)

**Interfaces:**
- Consumes: `choices.ChoiceRequest`, `choices.auto_pick`.
- Produces:
  - The fake's new behaviour (P14), on `send_interrupt` without a thread id: every
    `agent.custom_tool_use` of the scripted session that has no result yet gets an
    `agent.tool_result` on the session scope, before the interrupt's echo. The event is
    `{tool_use_id, is_error: true, content: [{"type": "text", "text": "Tool execution was
    interrupted before completion. Please retry."}]}`. The call then counts as answered: a later
    `user.custom_tool_result` is accepted and recorded in `sent`, but never echoed.
  - `choices.jsonl`: happy_path's run with two pauses.
    - An `activities` pause right after wave 1's activities report. Its options come from that
      results file, with the same ids, `place` set, and price and duration copied.
    - A `food` pause before wave 2: three options `c1` to `c3`, without `place`.
    - Each pause is: an `agent.custom_tool_use` named `ask_traveller`, a `session.status_idle`
      `requires_action` with `event_ids: [<that id>]`, a `usage` step, an
      `await {"type": "user.custom_tool_result", "custom_tool_use_id": <id>}` (no step timeout),
      then `session.status_running`.
    - The run ends like happy_path.
  - `choice_interrupt.jsonl`: the brief, one subagent thread working, a `food` pause, then
    `await {"type": "user.interrupt"}`, then the thread's and the session's `end_turn` idles.

- [ ] **Step 1: Write the failing tests**

```python
async def test_interrupt_closes_a_pending_custom_tool_call() -> None:
    # history after send_interrupt: [..., agent.tool_result(tool_use_id=X, is_error=True), user.interrupt]
async def test_a_late_result_after_the_closure_is_accepted_without_echo() -> None: ...
async def test_interrupt_leaves_answered_calls_alone() -> None: ...  # an answered call: no agent.tool_result
def test_ask_traveller_inputs_validate() -> None: ...                 # test_fixture_shapes
# test_fake_client, section "scenarios, end to end", one test each like the others:
async def test_choices_scenario() -> None: ...           # ReferenceConsumer auto-picks both pauses; ready
async def test_choice_interrupt_scenario() -> None: ...  # interrupt at the pause: closure, end_turn idles
```

- [ ] **Step 2:** Run `uv run pytest tests/test_fake_client.py tests/test_fixture_shapes.py
  tests/test_demo.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the fake's behaviour and write both scenarios. Every scripted event
  must parse with the SDK's union (`test_fixture_shapes`).
- [ ] **Step 4:** Run the same tests. Expected: PASS. Every existing scenario is unchanged.
- [ ] **Step 5:** Commit: `test(backend): the fake closes a waiting custom tool call on interrupt; choice scenarios`.

### Task 6: The consumer asks; `sessions.answer_choice`

**Files:**
- Modify:
  - `backend/app/consumer.py`:
    - `ConsumerDeps.photos`
    - `_answer_tool_use` dispatches `ask_traveller` first
    - `_ask_traveller`
    - `UNKNOWN_TOOL_TEXT = "Unknown tool {name!r}: the custom tools are submit_plan and
      ask_traveller."`
    - `decide_idle`: the docstring, and `log_reason` `"requires_action:custom_tool"`
    - the module docstring, step 4b
  - `backend/app/events.py` (`_custom_tool_use`: for `ask_traveller`, kind `tool`, title
    `Domanda al viaggiatore`, detail `{tool, tool_use_id}`, no params)
  - `backend/app/config.py` (`choice_timeout_seconds`) and `backend/.env.example`
    (`CHOICE_TIMEOUT_SECONDS=240`, reason: "how long a choice waits for the traveller before
    Atlas picks; keep it under 300, the prompt cache's lifetime (probe P14)")
  - `backend/app/sessions.py`: wiring in `start_planner`, `answer_choice`,
    `answer_pending_choice`, the errors
- Test: `backend/tests/test_consumer_choices.py` (new; reuse `test_consumer.py`'s harness, and
  move it into a shared helper if importing it is awkward), `backend/tests/test_events.py`,
  `backend/tests/test_config.py`, `backend/tests/test_sessions.py`

**Interfaces:**
- Consumes: Tasks 2 to 5.
- Produces:
  - `Settings.choice_timeout_seconds: int = Field(default=240, ge=1, le=290)`
  - `ConsumerDeps.photos: ChoicePhotos = NO_PHOTOS`
  - `start_planner`: `PlacePhotos(CoverResolver(session_factory=..., http=http,
    user_agent=settings.wikimedia_user_agent, key_prefix=PLACE_KEY_PREFIX))` when
    `settings.choice_photos_enabled` and neither `DEMO_MODE` nor `fx_offline`; else `NO_PHOTOS`.
  - `PlanConsumer._ask_traveller(raw) -> PlanStatus | None`, the same path live and on resume:
    1. `parse_choice_request`. Rejected: send the message with `is_error`, log `choice_rejected`,
       done.
    2. `get_choice`. With no row:
       - `admission_refusal(kind, asked_kinds, accepted=state.accepted)`. Refused: send
         `NO_MORE_QUESTIONS_TEXT` with `is_error`, log `choice_refused`, done.
       - `photos_for({id: place})`, then `insert_choice` with `asked_at = deps.now()` and
         `deadline_at = asked_at + choice_timeout_seconds`.
    3. Emit `choice_asked_event`. Log `choice_asked` unless the event was a duplicate.
    4. A row answered by `traveller` or `skip`: resend `answer_text` from the row. A row
       `closed`: send nothing. (The deadline is Task 7.)
  - `sessions.py`:
    - The errors: `ChoiceNotFoundError`; `ChoiceClosedError(answered_by: str | None)`;
      `InvalidChoiceAnswerError(reason: str)`.
    - `@dataclass(frozen=True, slots=True) class AnsweredChoice: id: str; answered_by:
      AnsweredBy; selected: list[str]`
    - `answer_choice(plan_id: uuid.UUID, choice_id: str, answer: ChoiceAnswer, user:
      CurrentUser, *, services: PlannerServices) -> AnsweredChoice`. It requires
      `require_ready()` and `get_user_plan` (else `PlanNotFoundError`). The plan must be
      `running` with no interrupt requested, else `ChoiceClosedError(None)`. The row must exist
      (else `ChoiceNotFoundError`) and still be open (else `ChoiceClosedError(row.answered_by)`).
      Then `selection_problem`, raising `InvalidChoiceAnswerError` on a problem. Then
      `close_choice` with `traveller` or `skip`; losing the race raises
      `ChoiceClosedError(<the winner>)`. Then it sends `answer_text`. A failed send
      (`ManagedAgentsError`) is only logged, as `choice_answer_send_failed`: Task 7's deadline
      resends. Last it logs `choice_answered`.
    - `answer_pending_choice(plan_id, user, *, services, pick:
      Callable[[ChoiceRequest], list[str]] = auto_pick) -> AnsweredChoice | None` answers the
      open choice, if any. It returns None when there is none, or when the timeout won the race.

- [ ] **Step 1: Write the failing tests** (`choices` scenario; a stub `ChoicePhotos` recording
  its argument and returning a Cover for `a1`)

```python
async def test_ask_traveller_stores_the_choice_and_waits(harness) -> None:
    # at the first pause: a row with deadline_at == asked_at + 240 s; one "choice" event, title
    # "Tocca a te: scegli cosa vedere", detail.choice.options[0].photo set; plan running;
    # no user.custom_tool_result sent
def test_requires_action_on_ask_traveller_is_a_wait() -> None: ...       # decide_idle -> WAIT
async def test_traveller_answer_reaches_the_agent(harness) -> None:
    # answer_choice(selected=["a3", "a1"]) -> the sent text is the spec's picks text in offered
    # order; event "Hai scelto: ..."; then skip the food pause; the plan ends ready
async def test_skip_sends_let_you_choose(harness) -> None: ...
async def test_invalid_input_is_an_error_not_a_pause(harness) -> None:
    # no row; the is_error text starts "ask_traveller rejected:"; the corrected call is a pause
async def test_limits_refuse_a_fourth_pause_and_a_repeated_kind(harness) -> None:
    # activities, food, other answered; then destination -> NO_MORE_QUESTIONS_TEXT is_error, no row;
    # a second food -> the same
async def test_ask_after_acceptance_is_refused(harness) -> None: ...
async def test_photos_get_only_the_place_names(harness) -> None:
    assert stub.calls == [{"a1": "Torre de Belém, Lisboa", ...}]       # food options: no call
async def test_choice_logs_carry_no_card_text(harness) -> None: ...  # structlog LogCapture, as test_consumer
@pytest.mark.parametrize("case", ["closed", "unknown_option", "single_choice", "not_running",
                                  "interrupt_requested", "foreign_plan", "unknown_choice"])
async def test_answer_choice_refuses(case) -> None: ...
async def test_answer_pending_choice_uses_auto_pick(...) -> None: ...
def test_ask_traveller_tool_use_event() -> None: ...   # title "Domanda al viaggiatore", no params
def test_choice_timeout_setting(make_settings) -> None: ...   # 240 default; 291 rejected
```

- [ ] **Step 2:** Run `uv run pytest tests/test_consumer_choices.py tests/test_events.py
  tests/test_config.py tests/test_sessions.py -q -k "choice or ask_traveller"`. Expected: FAIL.
- [ ] **Step 3: Implement.** Then run `uv run python
  ../web/scripts/gen-backend-fixtures.py --check` and regenerate if `samples.json` moved.
- [ ] **Step 4:** Run the whole suite: `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(backend): the consumer asks the traveller and waits; sessions.answer_choice`.

### Task 7: Deadlines, the platform's closure, resume and "Continua"

**Files:**
- Modify:
  - `backend/app/clock.py` (`sleep_until`)
  - `backend/app/consumer.py`:
    - `ConsumerDeps.sleep_until`
    - the `_ChoiceDeadline` inbox item, handled in `_tail` and ignored by `_drain`
    - `_arm_choice` and `_close_by_timeout`
    - timers cancelled on a result echo, on closure and on stop
    - `agent.tool_result` closes a choice
    - `_reconcile`: the `answered` set, and closures from history
  - `backend/app/sessions.py` (`_continue_session` step 5)
- Test: `backend/tests/test_consumer_choices.py`, `backend/tests/test_sessions.py`

**Interfaces:**
- Consumes: Task 6.
- Produces:
  - `clock.sleep_until(deadline: dt.datetime, *, now: Callable[[], dt.datetime] = now,
    step_seconds: float = 1.0) -> None` polls `now()` at most every `step_seconds`, so
    time-machine shifts are honoured.
  - `ConsumerDeps.sleep_until: Callable[[dt.datetime], Awaitable[None]] = clock.sleep_until`
  - Arming: `_ask_traveller` step 5 handles an open row. Past its deadline it calls
    `_close_by_timeout` now; otherwise it calls `_arm_choice(id, row.deadline_at)`, a task that
    awaits `sleep_until` and then puts `_ChoiceDeadline(id)` in the inbox.
  - `_close_by_timeout(choice_id)`:
    - `close_choice(..., "timeout")` won: send `answer_text(..., "timeout", [])` and log.
    - Lost to `traveller` or `skip`, and the id has no result echo in
      `state.answered_tool_use_ids`: resend the stored answer once.
  - `_handle`: the session stream's `agent.tool_result` adds `tool_use_id` to
    `answered_tool_use_ids`, as `user.custom_tool_result` already does. Either echo cancels that
    choice's timer. Acting on an `agent.tool_result` whose id is a custom tool use calls
    `close_choice(..., "closed")`, and sends nothing.
  - `_reconcile`:
    - `answered` also holds the `tool_use_id` of every `agent.tool_result`. This fixes the gap
      noted in notes §2e: a call the platform closed is never re-armed.
    - After the history pass, every `ask_traveller` use that only the platform answered, and
      whose row is still open, is closed as `closed`.
  - `_continue_session` step 5 sends no `CONTINUE_MESSAGE` while
    `choices.pending_choice(db, plan_id)` is not None (logged `continue_message_skipped`).

- [ ] **Step 1: Write the failing tests**

```python
async def test_timeout_answers_for_the_traveller(harness) -> None:
    # sleep_until returns at once: both pauses time out; texts per kind; rows "timeout";
    # events "Tempo scaduto: sceglie Atlas"; ready
async def test_timeout_under_time_machine(harness, time_machine) -> None:
    # real clock.sleep_until(step_seconds=0.01); shift 241 s -> the choice closes as "timeout"
async def test_answer_before_the_deadline_cancels_the_timer(harness) -> None:
    # answered, echo seen, then the deadline fires: no second result, row stays "traveller"
async def test_timer_resends_an_answer_whose_send_failed(harness) -> None:
    # fail_next("send_custom_tool_result", "api_unavailable") for the endpoint's send; at the
    # deadline the consumer resends the traveller's text exactly once
async def test_interrupt_while_waiting_closes_the_choice(harness) -> None:
    # choice_interrupt: request_interrupt -> the fake's agent.tool_result -> row "closed",
    # event "Domanda chiusa: piano interrotto", no result sent by the backend, plan interrupted
    # and archived; answer_choice then raises ChoiceClosedError
async def test_resume_rearms_with_the_original_deadline(harness) -> None:
    # stop at the pause; the resumed consumer's sleep_until gets row.deadline_at
async def test_resume_past_the_deadline_times_out(harness) -> None: ...
async def test_resume_answers_from_an_answered_row(harness) -> None:
    # answered while no consumer ran (close_choice directly): resumed consumer sends it
async def test_resume_without_a_row_stores_and_asks(harness) -> None:
    # the use is in events, no row: the resumed consumer inserts it (fresh deadline), one asked event
async def test_resume_counts_the_platforms_closure(harness) -> None:
    # history has the agent.tool_result: not re-armed, no result sent, the open row -> "closed"
async def test_budget_reached_during_a_pause_then_continue(harness) -> None:
    # budget_reached idle while waiting -> budget_paused, answer_choice -> ChoiceClosedError;
    # continue_plan -> resumed consumer re-arms; no CONTINUE_MESSAGE sent while pending
```

- [ ] **Step 2:** Run `uv run pytest tests/test_consumer_choices.py tests/test_sessions.py -q -k
  "timeout or deadline or resume or interrupt or budget or continue"`. Expected: FAIL.
- [ ] **Step 3: Implement.** `_stop_threads`' sibling cancels every timer when the consumer
  stops. A plan that ends with a choice still open keeps the row as it is: it is no longer
  pending, because `pending_choice` callers check that the plan is `running`.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS, including `test_consumer_resume.py`
  and `test_plan_lease.py`.
- [ ] **Step 5:** Commit: `feat(backend): a choice times out, closes on interrupt and survives restarts`.

### Task 8: The answer endpoint and `PlanDetail.pending_choice`

**Files:**
- Modify: `backend/app/routes.py` (three `PlanErrorCode`s with status and message,
  `ChoiceAnswerResponse`, the route, `PlanDetail.pending_choice`, `plan_detail(...,
  pending_choice=None)`, `get_plan`)
- Test: `backend/tests/test_routes.py` (or a new `test_choice_routes.py`)

**Interfaces:**
- Consumes: `sessions.answer_choice` and its errors; `choices.pending_choice`, `PendingChoice`.
- Produces:
  - `POST /plans/{plan_id}/choices/{choice_id}`: status 200, `dependencies=[RequireOrigin]`,
    body `ChoiceAnswer`, response `ChoiceAnswerResponse {id: str, answered_by: str, selected:
    list[str]}`. Errors:
    - `PlanNotFoundError`: 404 `plan_not_found`
    - `ChoiceNotFoundError`: 404 `choice_not_found`
    - `ChoiceClosedError`: 409 `choice_closed` (`{answered_by}`)
    - `InvalidChoiceAnswerError`: 422 `invalid_choice_answer` (`{reason}`)
    - `PlannerUnavailableError`: 503
  - `PlanDetail.pending_choice: PendingChoice | None = None`, described as the open choice,
    shown only while the plan is `running` with no interrupt requested. `get_plan` loads it under
    those conditions only. `plan_detail` stays pure.

- [ ] **Step 1: Write the failing tests**

```python
async def test_answer_choice_route_selected(client, ...) -> None: ...  # 200 {"answered_by": "traveller", ...}
async def test_answer_choice_route_skip(client, ...) -> None: ...
async def test_answer_choice_needs_the_origin(client, ...) -> None: ...   # 403 bad_origin
async def test_answer_choice_body_needs_selected_or_skip(client, ...) -> None: ...  # {} and both -> 422
async def test_answer_choice_closed_is_409(client, ...) -> None: ...      # data.answered_by "timeout"
async def test_answer_choice_unknown_option_is_422(client, ...) -> None:  # code invalid_choice_answer
async def test_answer_choice_of_another_users_plan_is_404(client, ...) -> None: ...
async def test_answer_choice_unknown_id_is_404_choice_not_found(client, ...) -> None: ...
async def test_plan_detail_pending_choice(client, plan_rows, ...) -> None:
    # open row on a running plan -> options, photo, deadline_at; answered -> null;
    # interrupt requested -> null; budget_paused -> null; a plan without choices -> null
```

- [ ] **Step 2:** Run `uv run pytest tests/test_routes.py -q -k choice`. Expected: FAIL.
- [ ] **Step 3: Implement.** The web needs nothing yet: `PlanDetailSchema` strips the unknown key
  until PR 3.
- [ ] **Step 4:** Run `uv run pytest tests/test_routes.py tests/test_e2e_offline.py -q`.
  Expected: PASS.
- [ ] **Step 5:** Commit: `feat(backend): POST /plans/{id}/choices/{choice_id}; GET /plans/{id} carries the open choice`.

### Task 9: The CLI and the local demo answer choices

**Files:**
- Modify: `backend/app/cli.py` (`run --choose`; `_follow_timeline`'s `catch_up` answers asked
  choices)
- Test: `backend/tests/test_cli.py`, `backend/tests/test_demo.py`

**Interfaces:**
- Consumes: `sessions.answer_pending_choice`, `choices.auto_pick`, the `choices` scenario.
- Produces: in `catch_up`, a stored event of kind `choice` with `detail.phase == "asked"`
  awaits `chooser(plan_id)`.
  - The default chooser (`run`, `replay`) calls `answer_pending_choice` and prints
    `Scelta automatica: <titles>`.
  - `--choose` (`run` only) prints the options numbered (title and reason), then reads `1,3`, or
    an empty line for "Scegli tu", through `asyncio.to_thread(input, ...)`. It answers through
    `answer_choice`. A `ChoiceClosedError` (the timeout won) prints `Tempo scaduto: sceglie
    Atlas`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_replay_choices_answers_each_pause_and_ends_ready(...) -> None:
    # exit 0; output contains "Tocca a te: scegli cosa vedere" and "Hai scelto: "
async def test_run_choose_reads_the_terminal(monkeypatch, ...) -> None: ...  # input "2" -> option 2
async def test_demo_choices_waits_for_the_answer(...) -> None:
    # DEMO_MODE app (fast pace): POST /plans?demo_scenario=choices; pending_choice appears in
    # GET /plans/{id}; POST the answer; then the food pause; the plan ends ready
def test_demo_offers_choices_but_not_choice_interrupt() -> None: ...  # default still happy_path
```

- [ ] **Step 2:** Run `uv run pytest tests/test_cli.py tests/test_demo.py -q -k choice`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run the tests. Then, by hand, `uv run python -m app.cli replay
  tests/fixtures/ma/choices.jsonl` with the environment of CLAUDE.md's "Commands". Expected:
  PASS and exit 0.
- [ ] **Step 5:** Commit: `feat(backend): app.cli and the local demo answer choices`.

### Task 10: The evals answer choices and the judge sees the picks

**Files:**
- Modify: `evals/run.py` (`answer_choices`, `wait_for_terminal(..., on_poll=None)`,
  `run_case`, the picks for the judge), `evals/judge.py` (`build_params` / `judge_plan` gain
  `picks: Sequence[str] = ()`), `evals/rubric.md` (one line under `preference_respect`),
  `evals/README.md` (one line)
- Test: `evals/tests/test_eval_run.py`, `evals/tests/test_eval_judge.py`

**Interfaces:**
- Consumes: `sessions.answer_pending_choice`, `choices.answered_choices`, `request_of`.
- Produces:
  - `async def answer_choices(planner: PlannerServices, plan_id: uuid.UUID, user: CurrentUser)
    -> None` (module level, so tests monkeypatch it, as they do `load_plan`)
  - `wait_for_terminal(session_factory, plan_id, *, timeout_seconds, poll_seconds,
    on_poll: Callable[[], Awaitable[None]] | None = None)` awaits `on_poll` once per pass.
  - `run_case` passes `on_poll=lambda: answer_choices(ctx.planner, plan_id, user)`.
  - `picks` lines, one per answered choice, e.g.
    `activities (traveller): a1 Torre di Belém; a3 Alfama` and
    `food (timeout): none, the coordinator chose`.
  - `build_params` adds a `<picks>` block (data, not instructions) only when `picks` is
    non-empty.
  - The rubric line: "When the traveller picked options in the pauses (the <picks> block), the
    plan is built around the picked activities and food styles and leaves out the options they
    did not pick."

- [ ] **Step 1: Write the failing tests**

```python
async def test_wait_for_terminal_calls_on_poll_each_pass(...) -> None: ...
async def test_run_case_answers_pending_choices(monkeypatch, ...) -> None: ...  # called with the plan id
def test_build_params_lists_the_picks() -> None: ...       # "<picks>" present; absent when empty
def test_the_rubric_mentions_the_picks() -> None: ...      # five "### <criterion>" headings kept
```

- [ ] **Step 2:** Run `uv run pytest ../evals/tests -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The evals' paid workflow does not run for this PR: `evals.yml`
  triggers on `agents/**`, `profiles/**`, `skills/**` and `backend/app/plan.py` only.
- [ ] **Step 4:** Run `uv run pytest ../skills ../scripts ../evals/tests -q`, `uv run ruff check
  ../evals && uv run pyright -p ../evals`, `uv run python ../evals/run.py --dry-run`. Expected:
  PASS.
- [ ] **Step 5:** Commit: `feat(evals): answer each choice at once; the judge sees the picks`.

### Task 11: Docs, every check, the PR

**Files:**
- Modify:
  - `CLAUDE.md`:
    - Layout: `app/choices.py`.
    - "Database and migrations": the `choices` table.
    - Commands: `replay` plays `choices`, and `choice_interrupt` joins the scenarios that wait
      for a test.
    - "Testing offline": the fake closes a waiting call on interrupt.
    - Config: `CHOICE_TIMEOUT_SECONDS` and `CHOICE_PHOTOS_ENABLED`.
  - `docs/backend-interfaces.md`: decision 41 (the six decisions above, and why the endpoint
    sends), and §5 a flow "ask_traveller" beside "submit_plan".
  - `docs/managed-agents-notes.md` §2e: the "Reconciliation must count `agent.tool_result`"
    bullet now points at the code that does it.

- [ ] **Step 1:** `git fetch origin`, then rebase as Task 0 says. If #25 merged, check that
  `down_revision` equals `alembic heads` on `origin/main`. Regenerate everything the CLAUDE.md
  table lists.
- [ ] **Step 2:** Run every check CI runs. From `backend/`:

  ```sh
  uv run ruff check . && uv run ruff format --check . && uv run pyright
  uv run python -m app.schemas --check
  uv run python ../scripts/render_profiles.py --check
  uv run python ../web/scripts/gen-backend-fixtures.py --check
  uv run pytest -q
  ```

  Then CLAUDE.md's non-backend checks. From `web/`:

  ```sh
  npm run gen:schemas -- --check && npm run lint && npm run typecheck && npm test && npm run build
  ```

  Then `git diff --stat origin/main...` must show nothing under `agents/`, `profiles/`, `skills/`
  or `backend/app/plan.py`. Expected: all PASS.
- [ ] **Step 3:** Commit: `docs: choices and the travel mode in CLAUDE.md and the interfaces`.
- [ ] **Step 4:** Ask Michele before pushing and opening the PR. The title is `feat(backend):
  choices and the travel mode: ask_traveller, the choices table, the answer endpoint`. The body
  has the spec link, this plan's six decisions, the migration, "no agent change, no paid
  evals", and what PR 3 builds on (`pending_choice`, the `choice` events, the endpoint, the
  `choices` demo scenario).
- [ ] **Step 5:** After the merge, nothing runs on its own. PR 3 (the web cards) can start; PR 4
  adds `ask_traveller` to the coordinator, renders `tools/ask_traveller.json` and tells the
  coordinator to end its turn after an answer and wait for the pending reports (P14).
