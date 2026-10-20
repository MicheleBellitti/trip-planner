# Plan UX, PR 3: the choice cards on the web — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While a plan runs, the traveller sees the coordinator's question as a panel of photo
cards, picks (or lets Atlas pick) before a 4-minute countdown runs out, and the answer becomes a
station on the coordinator's line. The public `/demo` replays a recorded run that pauses on two
such questions. The `/dev/ui` gallery shows the new primitives.

**Architecture:** One tolerant decoder (`lib/choices.ts`, no zod: it is on the demo's first load)
reads a choice from the backend's `choice` events and from `PlanDetail.pending_choice`. The
reducer derives the open choice from those events and the snapshot. `stations.ts` turns the
choice into a plate at the end of the coordinator's line, then into a station once answered.
`PlanScreenView` draws a lazy `ChoicePanel` (built from two new primitives, `ChoiceCard` and
`Countdown`) and takes its behaviour from a `ChoiceControls` prop. Live, the controls call
`POST /plans/{id}/choices/{choice_id}`. In the demo, `useReplayEvents` holds the replay on each
question and answers it locally. The recorded run is generated from the backend's `choices`
scenario by `gen-backend-fixtures.py`, with place photos captured once from Wikimedia.

**Tech Stack:** Next.js 16, React 19, TypeScript strict, Tailwind 4, `zod/mini` (API client
only), vitest + Testing Library; Python 3.12 for the fixture generator, the photo capture and two
small pure helpers extracted in the backend.

**Spec:** `docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md`. This PR covers:
- §2 "The experience";
- the `/demo` half of §2 "Demo";
- §4 row 3;
- §6's web tests and browser checks.

It builds on PR 2 (#26, branch `feat/choices-backend`). Read §2 of the spec, and in PR 2's plan
(`docs/superpowers/plans/2026-10-20-plan-ux-2-choices-backend.md`) its "Global Constraints" and
"Decisions taken here" (`answered_by` gains `closed`; the demo scenario `choices` is not the
default).

## Global Constraints

- **Branch:** `feat/choice-cards-web`, stacked on `origin/feat/choices-backend`. Its PR targets
  `feat/choices-backend`. When #26 merges, it is retargeted to `main`.
- **Paths this PR never touches:** `agents/**`, `profiles/**`, `skills/**`,
  `backend/app/plan.py`. They trigger the paid `evals.yml` and, on merge, a production
  `ant apply`. Backend changes are limited to:
  - two pure extractions (Task 1): `choices.choice_payload` and `consumer.choice_answered_event`;
  - the food option's copy in two `tests/fixtures/ma/*.jsonl` files.
- **The backend contract** (PR 2, do not change it):
  - The asked event: `kind: "choice"`, agent `coordinator`, `detail = {event_type:
    "backend.choice", phase: "asked", choice: PendingChoice}`.
  - The answered event: `detail = {event_type: "backend.choice", phase: "answered", choice_id,
    kind, answered_by, selected, answered_at}`. `answered_by` is one of `traveller`, `skip`,
    `timeout` or `closed`.
  - `PendingChoice = {id, kind, question, multiple, options: [{id, title, reason, duration_min?,
    price?: {amount_cents, currency}, area?, photo?: Cover}], asked_at, deadline_at}`.
  - The raw tool use is a `tool` event titled `Domanda al viaggiatore`, with `detail.tool ==
    "ask_traveller"` and `detail.tool_use_id` equal to the choice id.
  - `GET /plans/{id}` carries `pending_choice` (or null) only while the plan is `running` and no
    interrupt was asked.
  - The answer is `POST /plans/{plan_id}/choices/{choice_id}` with body `{"selected": [ids]}` or
    `{"skip": true}`. It returns 200 `{id, answered_by, selected}`. Its errors:
    - 404 `plan_not_found`;
    - 404 `choice_not_found`, "Questa domanda non c'è.";
    - 409 `choice_closed`, "Questa scelta è già chiusa: il piano va avanti.", data
      `{answered_by}`;
    - 422 `invalid_choice_answer`, "La risposta non corrisponde alle opzioni proposte: ricarica
      la pagina e riprova.", data `{reason}`;
    - 503 `planner_unavailable`.
- **Timeline titles are the backend's.** A station shows the event's own `title`. The web spells
  a title itself only where no event exists yet:
  - the plate from a snapshot (`askedTitle`);
  - the demo's synthesized answer (`answeredTitle`).

  Both are pinned against the generated fixture.
- **No zod on the demo's first load.** `lib/choices.ts`, `lib/plan-events/*` and
  `lib/demo/*` import schemas as types only (the `detail-imports` guard).
- **Photos are pinned to Wikimedia.** The image is `https` on `upload.wikimedia.org`, the file
  page is `https` on `commons.wikimedia.org` and the license link is `http(s)` or null, as
  `CoverSchema`. Anything else is no photo. Agents never write image URLs. The demo never calls
  Wikimedia: its photos are in the committed fixture.
- **Copy** (Italian, sentence case, buttons start with a verb, no em dash, `invariants.test.ts`):
  - the eyebrow:
    - activities: `Attività ha trovato {n} idee per {destination}`;
    - food: `Il coordinatore propone {n} modi di mangiare a {destination}`;
    - destination: `Il coordinatore propone {n} mete`;
    - journey: `Il coordinatore propone {n} modi di viaggiare`;
    - other: `Il coordinatore propone {n} opzioni`.

    Without a destination in the request, drop ` per …` and ` a …`.
  - the heading: the question;
  - the intro:
    - its first sentence: `Scegli quelle che ti piacciono, anche più di una.` (multiple) or
      `Scegline una.` (single);
    - live, a second sentence: `Se non scegli entro {4 minuti}, scelgo io.`, with the window
      from `deadline_at - asked_at`. At 60 s and more it is in whole minutes, rounded (`1
      minuto`, `4 minuti`); under 60 s in seconds (`15 secondi`);
    - in the demo, the second sentence is `Se non scegli entro 15 secondi, la corsa prosegue con
      le scelte registrate.`;
  - the count (multiple only): `Nessuna scelta`, `1 scelta`, `{n} scelte`;
  - the buttons: `Scegli tu` (secondary) and `Continua con queste` (primary; `Continua con
    questa` for one pick or a single-choice question; disabled with no pick);
  - the countdown: `m:ss` (`formatElapsed` of the time left), behind a visually hidden `Tempo
    per scegliere: `. At zero: `Tempo scaduto: scelgo io.`, and the buttons are disabled;
  - the one-minute announcement: `Manca un minuto per scegliere.`;
  - the tab title while a choice waits: `Tocca a te · {title} · {BRAND_NAME}`;
  - the coordinator's summary while asking: the asked title (`Tocca a te: scegli cosa vedere`);
  - an answered station: the event title, with the question as its second line;
  - a question left open on a plan that stopped: its asked title, with `Senza risposta`;
  - the demo notice: `Una corsa registrata: prezzi e disponibilità sono un esempio, e le scelte
    non cambiano il piano. I link portano ai siti veri.`
- **Never amber** on the clock, a card or a button. The countdown's bar is ink. No glow, no
  gradient, no glass (the No AI Chrome Rule).
- **Motion:**
  - A slow zoom on a card's photo on hover: scale 1.04, `--duration-zoom: 700ms`, ease-out,
    `motion-safe` only.
  - Nothing else moves. Arrival, selection and the countdown do not animate. The answered
    station draws in like any `fresh` station.
- **Layout:**
  - On the phone (`useLaneLayout() === "stack"`), the panel comes first under the live header,
    before the lanes.
  - From 1080 px, the panel sits under the lanes.
  - Cards: two columns on the phone. From 1080 px, three columns, or four for `food`.
  - Photo ratio: 4:3, or 16:10 for `food`.
- **Accessibility:**
  - The panel is a `section` labelled by its `h2` (the question, `tabIndex={-1}`). It gets focus
    once per choice id, which scrolls it into view under the sticky bar.
  - Cards are native checkboxes (multiple) or radios (single), in a group labelled by the
    heading.
  - Targets are 44 px under a finger.
  - The page keeps its one polite live region.
- **Errors** use the backend's Italian message when there is one, else `API_ERROR_MESSAGES`.
- **JS weight:** `ChoicePanel` is a lazy chunk, warmed with `PlanView`, so `/plans/[id]`'s first
  load grows only by the reducer and station code. Measure before and after (Task 0, Task 9) and
  record both in `web/README.md` "JS budget".
- **Commands:** web commands run from `web/`, backend commands from `backend/`. Backend tests
  need `TEST_DATABASE_URL=postgresql+asyncpg://localhost:5432/trip_planner_test_cards`.
  Generated files are regenerated, never hand-edited.

## Decisions taken here (Michele: please confirm or overturn)

1. **The photo credit sits behind a button on each card.** A small round `info` button sits on
   the photo's bottom-right corner (label "Crediti della foto", `aria-expanded`). It shows the
   credit as a solid `surface` strip across the photo's foot, with the license and the source as
   new-tab links. This follows the spec's "reachable on each card without crowding it". The home
   list's closed "Crediti delle foto" disclosure is the precedent for a credit shown on demand.
2. **Cards without a photo.** When some options of a question have a photo, the others show the
   cover tile (`notice-wash`, the title's initial in `ink-2`) at the same ratio, so the rows stay
   level. When none has one (the `food` question of the recording), the cards have no photo area.
   "No free photo, no photo": a tile is not a photo.
3. **The demo's pause:**
   - The replay holds on each question for 15 s of visible time, with the countdown and its own
     rule sentence. The window does not speed up at 2×, and it stops while the tab is hidden.
   - A visitor who selects a card takes over: the countdown and the rule go away, and the replay
     waits for "Continua" or "Scegli tu". Their answer becomes the answered station ("Hai
     scelto: …" with their titles, or "Hai lasciato scegliere ad Atlas").
   - Without a touch, the cards the recording picked show selected for 0.9 s. Then the
     recording's own answered event lands, as the spec says ("picks what the recording picked").
   - The finished plan is the recording's whatever the visitor picks, and the demo notice says
     so.
4. **The answered station is a lozenge** (`message`): the traveller's answer is an interchange
   with the coordinator, like the brief that opened the run.
5. **The waiting plate** is the live station's thick ring without its halo (a new `halo` prop on
   `TimelineItem`). Nothing runs while Atlas waits for you, and DESIGN.md gives the halo to "while
   running" only. The plate links to the panel (`#scelta`).
6. **The demo replays the new `choices` recording.** The local `DEMO_MODE` default stays
   `happy_path` (PR 2's decision 5). The browser check uses `?demo_scenario=choices` or
   `NEXT_PUBLIC_DEMO_SCENARIOS`.
7. **The recording's third food card is fixed.** "Pastelarias e pasticciotti" names a pastry from
   Lecce, not Lisbon, and the public demo shows it. In `choices.jsonl` and `choice_interrupt.jsonl`
   it becomes "Pastelarias e pastéis de nata", with the reason "Pause dolci a metà giornata, con
   le paste appena sfornate."

## Review Focus

1. **A reload during a pause.** The snapshot's `pending_choice` shows the cards before the
   stream replays. When the replay then brings the answered event, the panel goes away, and it
   never comes back from the stale snapshot. Tests:
   - Task 3: `the snapshot's open choice shows until its answered event arrives`;
   - Task 7: `shows the cards from GET /plans/{id} before the stream opens`.
2. **The traveller answers as the deadline fires.** The POST answers 409 `choice_closed`. The
   panel then says the backend's sentence, offers no buttons, and the page re-reads the plan. It
   never shows a generic error. Test: Task 7, `a 409 choice_closed closes the panel with the
   backend's words`.
3. **A browser clock that is minutes off.** The countdown never shows more than the question's
   own window, and never goes below 0:00. Test: Task 5, `Countdown clamps to the window and to
   zero`.
4. **Interrompi, or a budget pause, during a pause.** The panel goes as soon as "Interrompi" is
   confirmed (`interrupting`) or the plan leaves `running`. If the plan returns to `running`
   (after "Continua"), the same question shows again with its original deadline. Tests:
   - Task 3: `no open choice unless running: budget_paused, interrupted, ready`;
   - Task 7: `hides the cards while interrupting and on budget_paused, and shows them again after
     Continua`.
5. **The demo's camera after a pause.** A visitor who only watches keeps the camera following
   the work after each question: the jump to the panel is not read as the visitor scrolling
   away. Tests: Task 8, `the camera aims again after a hold`, plus the browser check in Task 9.

---

### Task 0: Branch and baseline

**Files:** none.

- [ ] **Step 1:** Already done when this plan was written: `git switch -c feat/choice-cards-web
  origin/feat/choices-backend`. Run `git fetch origin && git merge origin/feat/choices-backend`
  to catch up.
- [ ] **Step 2:** From `web/`: `npm ci && npm run typecheck && npm test`. Expected: PASS.
  - From `backend/`: `uv run python ../web/scripts/gen-backend-fixtures.py --check` and `uv run
    pytest tests/test_consumer_choices.py tests/test_choices_store.py -q`. Expected: PASS.
- [ ] **Step 3:** Measure the JS baseline from `web/`:
  `NEXT_DIST_DIR=.next-build npm run build && NEXT_DIST_DIR=.next-build npm run measure:js`.
  Note `/plans/[id]` and `/demo` (gzip) for Task 9. Nothing to commit.

### Task 1: The recorded run with its questions (fixture, photos, two backend extractions)

**Files:**
- Modify: `backend/app/choices.py` (add `choice_payload`; `insert_choice` uses it),
  `backend/app/consumer.py` (add `choice_answered_event`; `close_choice`'s `build` uses it)
- Modify: `backend/tests/fixtures/ma/choices.jsonl`, `backend/tests/fixtures/ma/choice_interrupt.jsonl`
  (the food card c3, decision 7)
- Create: `web/scripts/capture-choice-photos.py` (one-off, network: Wikimedia only)
- Create: `web/lib/demo/choice-photos.json` (the capture's output, committed)
- Modify: `web/scripts/gen-backend-fixtures.py` (`SCENARIOS["choices"]`, `Timeline.ask`,
  `Timeline.answer_choice`, the `await` branch)
- Generated: `web/lib/plan-events/__fixtures__/backend/choices.json`
- Test: `backend/tests/test_consumer_choices.py`, `web/lib/plan-events/backend-events.test.ts`

**Interfaces:**
- Produces:
  - `choices.choice_payload(request: ChoiceRequest, photos: Mapping[str, Cover]) -> dict[str,
    Any]`: exactly the `payload` `insert_choice` stores today (`{"request": ...model_dump(mode=
    "json", exclude_none=True), "photos": {id: cover.model_dump(mode="json")}}`).
  - `consumer.choice_answered_event(*, choice_id: str, request: ChoiceRequest, answered_by:
    AnsweredBy, selected: Sequence[str], now: dt.datetime, cost_cents: int | None) ->
    EventBuilder`: the event `close_choice` builds today (title `answered_title(...)`, the
    detail keys of the Global Constraints, `kind` from `request.kind`).
  - `web/lib/demo/choice-photos.json`: `{"captured_on": "YYYY-MM-DD", "source": "<one line: how
    and from what>", "photos": {"a1": Cover, ...}}`. It holds only options with a `place` whose
    lookup found a free photo.
  - `__fixtures__/backend/choices.json`, the generator's usual shape. For each question in it,
    in seq order:
    1. the tool event `Domanda al viaggiatore`;
    2. the asked event, 20 ms after the tool event, with `deadline_at` = `asked_at` + the
       Settings default of `choice_timeout_seconds` (240) and the captured photos;
    3. the `requires_action` idle;
    4. the answered event, 9 s after the idle, with `answered_by: "traveller"` and `selected =
       choices.auto_pick(request)` (the CLI's and the evals' picks: the first two);
    5. the `user.custom_tool_result` echo, carrying `answer_text`.

    It `end`s `ready`, and every status stays `running` until then.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_consumer_choices.py
def test_choice_answered_event_is_close_choices_event() -> None:
    # build with a fixed `now`: title "Hai scelto: Oceanário de Lisboa, Palácio da Pena a Sintra",
    # detail == {"event_type": "backend.choice", "phase": "answered", "choice_id": "c-1",
    #            "kind": "activities", "answered_by": "traveller", "selected": ["a1", "a2"],
    #            "answered_at": now.isoformat()}
def test_choice_payload_is_what_insert_choice_stores(...) -> None: ...  # insert, then compare row.payload
```

```ts
// web/lib/plan-events/backend-events.test.ts
it("choices: two questions, each asked then answered on the coordinator's lane, then ready", () => {
  // events with kind "choice": 4, agent "coordinator"; phases asked, answered, asked, answered;
  // the first asked choice has kind "activities", 3 options, a photo on every option with a place,
  // deadline_at - asked_at === 240_000 ms; answered selected ["a1","a2"] and ["c1","c2"];
  // reducePlanEvents(events, { end: "ready" }).status === "ready"
});
```

- [ ] **Step 2:** Run `uv run pytest tests/test_consumer_choices.py -q -k "answered_event or
  payload"` and `npm test -- lib/plan-events/backend-events.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement the two extractions.** `insert_choice` and `close_choice` call them.
  There is no behaviour change. Then run `uv run pytest tests/test_consumer_choices.py
  tests/test_choices_store.py tests/test_sessions.py -q`. Expected: PASS.
- [ ] **Step 4: Fix the food card** (decision 7) in both `.jsonl` files. Then `uv run pytest
  tests/test_demo.py tests/test_cli.py -q -k choice`. Expected: PASS.
- [ ] **Step 5: Capture the photos.** Write `capture-choice-photos.py`. It runs from `backend/`
  with `DATABASE_URL` set to the migrated dev database and Wikimedia reachable. It:
  1. reads each `ask_traveller` input from `tests/fixtures/ma/choices.jsonl`;
  2. builds `PlacePhotos(CoverResolver(...))` as `sessions.py` does (`key_prefix=
     PLACE_KEY_PREFIX`);
  3. calls `photos_for({id: place})`;
  4. writes the JSON above.

  Run it once and look at each photo: it must show the place. Then commit the JSON with the
  script.
- [ ] **Step 6: Extend the generator.** It reads `web/lib/demo/choice-photos.json` (missing:
  no photos). Build the in-memory `ChoiceRecord` from `choice_payload`, and the events from
  `consumer.choice_asked_event` and `choice_answered_event`. The answered event and the echo
  replace `answer_submit` for an `ask_traveller` id. Run `uv run python
  ../web/scripts/gen-backend-fixtures.py`, then the same with `--check`. Expected: the new file
  is written, then no diff.
- [ ] **Step 7:** Run the two Step 1 tests again. Expected: PASS. Then from `backend/`:
  `uv run ruff check . ../web/scripts && uv run ruff format --check . && uv run pyright`.
- [ ] **Step 8:** Commit: `feat: the recorded choices run for the web, with its place photos`.

### Task 2: The choice contract on the web: decoder, copy, formats, API client

**Files:**
- Create: `web/lib/choices.ts`, `web/lib/choices.test.ts`
- Modify: `web/lib/format.ts` (`formatMinutes`, `formatMoney`), `web/lib/format.test.ts`
- Modify: `web/lib/schemas/api.ts` (`PlanDetailSchema.pending_choice`, `PLAN_ERROR_CODES` +
  `choice_not_found`, `choice_closed`, `invalid_choice_answer`; `ChoiceAnswerResponseSchema`)
- Modify: `web/lib/api.ts` (`answerChoice`; a 422 with the envelope keeps its code and message)
- Modify: `web/lib/plan-events/detail-imports.test.ts` (the guard also reads `lib/choices.ts`)
- Test: `web/lib/api.test.ts`, `web/lib/schemas/api.test.ts`

**Interfaces:**
- Produces (`lib/choices.ts`, schema imports type-only):
  ```ts
  export type ChoiceKind = "destination" | "journey" | "activities" | "food" | "other";
  export type AnsweredBy = "traveller" | "skip" | "timeout" | "closed";
  export interface ChoiceOptionView { id: string; title: string; reason: string; durationMin: number | null;
    price: { amountCents: number; currency: string } | null; area: string | null; photo: Cover | null }
  export interface ChoiceView { id: string; kind: ChoiceKind; question: string; multiple: boolean;
    options: ChoiceOptionView[]; askedAt: string; deadlineAt: string }
  export interface ChoiceAnswerView { choiceId: string; kind: ChoiceKind | null; answeredBy: AnsweredBy;
    selected: string[]; answeredAt: string | null }
  export type ChoiceAnswerInput = { selected: readonly string[] } | { skip: true };
  export const ASK_TRAVELLER_TOOL = "ask_traveller";
  /** The panel's `id`, the plate's link target (`#scelta`); its heading is `${CHOICE_PANEL_ID}-domanda`. */
  export const CHOICE_PANEL_ID = "scelta";
  export function readChoice(value: unknown): ChoiceView | null;          // a PendingChoice object
  export function readAskedChoice(detail: UIEvent["detail"]): ChoiceView | null;   // phase "asked"
  export function readChoiceAnswer(detail: UIEvent["detail"]): ChoiceAnswerView | null; // phase "answered"
  export function readPhoto(value: unknown): Cover | null;               // host-pinned, else null
  export function askedTitle(kind: ChoiceKind): string;                   // the backend's five titles
  export function answeredTitle(choice: ChoiceView, by: AnsweredBy, selected: readonly string[]): string;
  export function choiceEyebrow(choice: ChoiceView, destination: string | null): string;
  export function choiceIntro(choice: ChoiceView): string;                // the first sentence
  export function choiceRule(windowMs: number): string;                  // "Se non scegli entro …, scelgo io."
  export function choiceWindowMs(choice: ChoiceView): number;             // deadlineAt - askedAt, >= 0
  ```
  `readChoice` is tolerant, like `detail.ts`. It returns null without an id, a known kind, a
  question, a boolean `multiple`, two options, or valid `asked_at`/`deadline_at`. It drops an
  option without an id, title or reason, and it drops one whose id repeats. A field that is
  missing or mistyped becomes null.
- Produces (`lib/format.ts`):
  - `formatMinutes(minutes)`: 45 → `45 min`, 180 → `3 h`, 150 → `2 h 30 min`;
  - `formatMoney(cents, currency)`: EUR → `formatEur`, USD → `formatUsd`, otherwise
    `"{formatCents} {CODE}"`, e.g. `12,50 GBP`.
- Produces (`lib/api.ts`): `ApiClient.answerChoice(planId: string, choiceId: string, answer:
  ChoiceAnswerInput, options?: RequestOptions): Promise<ChoiceAnswerResponse>`. It POSTs
  `{"selected": [...]}` or `{"skip": true}` to `/plans/{planId}/choices/{choiceId}` (both
  encoded).
  - A 422 whose body parses as the error envelope becomes `new ApiError({kind: "validation",
    code, message, data, status})`.
  - Every other 422 stays `RequestValidationError`.
- Produces (`schemas/api.ts`): `pending_choice: z._default(z.nullable(z.record(z.string(),
  z.unknown())), null)`, read with `readChoice`; `ChoiceAnswerResponseSchema = {id: string,
  answered_by: string, selected: string[]}`.

- [ ] **Step 1: Write the failing tests**

```ts
// lib/choices.test.ts (fixture: __fixtures__/backend/choices.json)
it("reads the fixture's first question: kind, question, three options, prices, durations, photos");
it("reads an answered event: choice id, who, picks");
it("gives no choice for a missing id, an unknown kind, one option or a bad deadline, and drops a bad option");
it("keeps no photo off Wikimedia: an http image, another host, a file page elsewhere, a javascript: license");
it("spells the five asked titles as the backend does");   // askedTitle(kind) === the fixture's titles where present
it("answeredTitle matches the recorded 'Hai scelto: …' and the three other answers");
// answeredTitle(first, "traveller", ["a2","a1"]) === recorded title (order offered, not order given);
// "skip" -> "Hai lasciato scegliere ad Atlas"; "timeout" -> "Tempo scaduto: sceglie Atlas";
// "closed" -> "Domanda chiusa: piano interrotto"
it("writes the eyebrow per kind, with and without a destination");
it("writes the intro and the rule: 'Scegline una.', '… anche più di una.', 4 minuti, 1 minuto, 15 secondi");

// lib/format.test.ts
it("formatMinutes: 45 min, 3 h, 2 h 30 min");
it("formatMoney: (6000, EUR) 60,00 €, (1250, USD) 12,50 $, (1250, GBP) 12,50 GBP");

// lib/api.test.ts
it("answerChoice posts the picks, or the skip, to the choice's path and parses the answer");
it("a 409 choice_closed is a conflict carrying the backend's message and answered_by");
it("a 422 invalid_choice_answer keeps its code and message; FastAPI's 422 stays a RequestValidationError");

// lib/schemas/api.test.ts
it("PlanDetail keeps pending_choice, and defaults it to null from an older backend");
```

- [ ] **Step 2:** Run `npm test -- lib/choices.test.ts lib/format.test.ts lib/api.test.ts
  lib/schemas/api.test.ts lib/plan-events/detail-imports.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** the signatures above.
- [ ] **Step 4:** Run the same tests, then `npm run typecheck`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(web): read a choice, its answer and its copy; answerChoice`.

### Task 3: The reducer knows the open choice

**Files:**
- Modify: `web/lib/plan-events/reducer.ts`
- Test: `web/lib/plan-events/reducer.test.ts`

**Interfaces:**
- Consumes: Task 2 (`readAskedChoice`, `readChoiceAnswer`, `readChoice`).
- Produces:
  ```ts
  export interface OpenChoice { choice: ChoiceView; /** the asked event; null from the snapshot */ seq: number | null;
    ts: string; title: string /* the event's title, or askedTitle(kind) */ }
  // PlanLiveState gains:
  openChoice: OpenChoice | null;   // only while status is "running" (or null before any status)
  ```
  The `detail` action also takes `pending_choice?: unknown`. It is optional, so callers that
  predate it compile unchanged.
  - The open choice is the latest asked choice (by seq) with no answered event.
  - Failing that, it is the snapshot's choice, unless an answered event for its id was folded.

- [ ] **Step 1: Write the failing tests**

```ts
it("opens the choice when its asked event lands and closes it when its answered event lands"); // choices.json, sliced
it("the snapshot's open choice shows until its answered event arrives");   // Review Focus 1
it("no open choice unless running: budget_paused, interrupted, ready");     // Review Focus 4
it("a choice asked again after Continua is open again, with its original deadline");
it("the second question opens after the first is answered (one at a time)");
```

- [ ] **Step 2:** Run `npm test -- lib/plan-events/reducer.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.** The fold keeps two things: the asked choices (`{choice, seq, ts,
  title}`) and the set of answered ids. `applyEvent` gains a `case "choice"`. `derive` computes
  `openChoice`. `DetailSnapshot` gains `pendingChoice: ChoiceView | null`.
- [ ] **Step 4:** Run `npm test -- lib/plan-events`. Expected: PASS, the existing tests
  unchanged.
- [ ] **Step 5:** Commit: `feat(web): the timeline reducer derives the open choice`.

### Task 4: The coordinator's line: the waiting plate and the answered station

**Files:**
- Modify: `web/components/live/stations.ts`, `web/components/live/agent-lane.tsx`,
  `web/components/ui/timeline.tsx` (`halo?: boolean` on `TimelineItem`, default true; it only
  matters for `current`)
- Test: `web/components/live/stations.test.ts`, `web/components/live/agent-lane.test.tsx`

**Interfaces:**
- Consumes: Task 3 `state.openChoice`; Task 2 `ASK_TRAVELLER_TOOL`, `CHOICE_PANEL_ID`,
  `readAskedChoice`, `readChoiceAnswer`.
- Produces: `LaneView.asking: { title: string; seq: number | null; ts: string } | null` (the
  coordinator's only). The plate links to `#${CHOICE_PANEL_ID}` (Task 2).

The rules:
- The `ask_traveller` tool event is no station and never the live plate. Its result closes it
  silently, even an `is_error` result (on interrupt the answered `closed` event tells it).
- A `requires_action` idle whose `event_ids` are all `ask_traveller` uses is no station.
- While `state.openChoice` exists, `views.coordinator.asking` is set and the coordinator's
  `summary` is the asked title. `LaneBody` ends the line with `TimelineItem kind="current"
  halo={false}`, which holds a `ToolChip` plate with the title inside a link to `#scelta`, then
  `TimelineNext`.
- An answered event is a `message` station on the coordinator's line: the event's title, with
  the question of its asked event as `meta`.
- An asked choice with no answer, on a plan that is not running, is a `status` station: its
  asked title, with meta `Senza risposta`.

- [ ] **Step 1: Write the failing tests**

```ts
// stations.test.ts, on choices.json
it("while a question waits, the coordinator's line ends at 'Tocca a te: scegli cosa vedere', no tool plate");
it("after the answer, a lozenge 'Hai scelto: …' with the question as its second line; no 'Domanda al viaggiatore'");
it("draws no 'In attesa di una risposta' station for a pause on the traveller");
it("an interrupt's closed answer leaves no failed-call station");          // agent.tool_result is_error on the ask id
it("a question left open on a stopped plan reads 'Senza risposta'");
// agent-lane.test.tsx
it("the waiting plate has no halo and links to #scelta");
```

- [ ] **Step 2:** Run `npm test -- components/live/stations.test.ts
  components/live/agent-lane.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `npm test -- components/live`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(web): the coordinator's line waits on the traveller, then shows the answer`.

### Task 5: Two primitives: `ChoiceCard` and `Countdown`, in the gallery

**Files:**
- Create: `web/components/ui/choice-card.tsx`, `web/components/ui/countdown.tsx`
- Modify: `web/app/globals.css` (`--duration-zoom: 700ms`), `web/app/dev/ui/page.tsx`,
  `web/app/dev/ui/demos.tsx` (interactive card demo)
- Modify: `web/DESIGN.md` (Components table rows; the glyph table gains "Thick ring, no halo:
  the line waits for the traveller"; Motion table: the photo zoom; a short "Choice cards"
  section)
- Test: `web/components/ui/primitives.test.tsx`

**Interfaces:**
- Consumes: Task 2 `ChoiceOptionView`, `formatMinutes`, `formatMoney`; `coverSources`,
  `coverCreditLine` (`components/plan/cover/cover-sources.ts`), `destinationInitial`.
- Produces:
  ```tsx
  export function ChoiceCard(props: {
    option: ChoiceOptionView;
    /** "checkbox" (several picks) or "radio" (one); `name` groups the radios */
    control: "checkbox" | "radio"; name: string;
    checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void;
    /** 4:3, or 16:10 for food; "none": the question has no photo at all */
    media: "4/3" | "16/10" | "none";
  }): JSX.Element;
  export function Countdown(props: {
    /** ms on the shared clock */ deadlineAt: number; /** the question's whole window, ms */ windowMs: number;
    now: number | null;
  }): JSX.Element;   // "m:ss" + an ink bar (transform: scaleX(left/window)); "Tempo scaduto: scelgo io." at zero
  ```
- `ChoiceCard` anatomy:
  - a `rounded-md` `surface` card with a 1 px `rule` edge; selected, a 2 px ink inset ring and
    no layout shift;
  - the photo on top (`srcSet` from `coverSources`, `sizes` for a third of the page from 1080 px
    and half below, `loading="lazy"`, empty `alt`: the title names it), or the initial tile, or
    nothing;
  - a 24 px tick roundel at the top-right: hollow on `surface` with a `rule-strong` edge, or
    filled ink with `check` in `on-action` when checked;
  - the title (semibold), the reason (`text-small` `ink-2`), then `Chip`s with a visually hidden
    `Durata: `, `Prezzo per il gruppo: ` and `Zona: ` before their values, and a chip left out
    when its value is unknown (no "gratis");
  - the photo credit (decision 1).
- The native input is visually hidden. Its `label` stretches over the whole card (the
  `after:inset-0` pattern of `AgentLane`'s header). The credit button and its links sit above it
  (`relative z-10`). The card shows the focus ring when the input is `:focus-visible`.

- [ ] **Step 1: Write the failing tests**

```ts
it("ChoiceCard is a checkbox or a radio named by its title, checked state on the input");
it("ChoiceCard shows duration, price and area chips, and leaves out the unknown ones");
it("ChoiceCard's credit opens on its own button, never toggling the card, with new-tab links");
it("ChoiceCard without a photo: the tile with the initial, or no media at all");
it("Countdown shows m:ss and the bar's share of the window");
it("Countdown clamps to the window and to zero");                      // Review Focus 3: now 5 min early -> 4:00; late -> expired copy
```

- [ ] **Step 2:** Run `npm test -- components/ui/primitives.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement**, then add the gallery entries:
  - cards: photo, tile and none; checked and not; single and multiple; every chip and no chip; a
    long title;
  - countdown: 4:12, 0:45 and expired.
- [ ] **Step 4:** Run `npm test -- components/ui` (`tokens.test.ts` and `invariants.test.ts`
  included) and `npm run lint && npm run typecheck`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(web): ChoiceCard and Countdown, in the gallery`.

### Task 6: `ChoicePanel`

**Files:**
- Create: `web/components/choice/choice-panel.tsx`, `web/components/choice/choice-panel.test.tsx`

**Interfaces:**
- Consumes: Tasks 2 and 5; `AgentRoundel`, `Button`, `Notice`.
- Produces:
  ```tsx
  export interface ChoiceControls {
    /** Sends the answer; resolves to an Italian error to show, null when it went, or
     *  { closed: message } when the backend says the question is closed (409). */
    answer(choiceId: string, answer: ChoiceAnswerInput): Promise<null | string | { closed: string }>;
    /** The countdown's deadline (ms). Default: the choice's deadline_at. Null: no countdown and no rule. */
    deadlineAt?: number | null;
    /** The countdown's whole window (ms), for its bar. Default: choiceWindowMs(choice). */
    windowMs?: number;
    /** The intro's second sentence. Default: choiceRule(choiceWindowMs(choice)). Null: none. */
    rule?: string | null;
    /** The demo picking for the visitor: these cards show selected, every control rests and the
     *  countdown is hidden. */
    autoPick?: readonly string[] | null;
    /** The visitor changed a pick (the demo stops its clock). */
    onTouch?: () => void;
  }
  export function ChoicePanel(props: {
    choice: ChoiceView; controls: ChoiceControls; now: number | null; destination: string | null;
  }): JSX.Element;
  export default ChoicePanel;   // for React.lazy
  ```
- The layout, in order:
  1. the eyebrow, with the roundel of `activities` for that kind and the coordinator's for the
     others;
  2. the `h2` (id `${CHOICE_PANEL_ID}-domanda`, `tabIndex={-1}`);
  3. the intro;
  4. the card grid;
  5. the countdown;
  6. the action row: the count, `Scegli tu`, the primary;
  7. an error `Notice` when the last send failed.

  The `section` carries `id={CHOICE_PANEL_ID}`. On mount, it focuses its heading.
- Its states:
  - picking;
  - sending: the primary is `busy`, and everything is disabled;
  - failed: the error, with the picks kept;
  - closed: the backend's sentence, with no buttons;
  - expired: the countdown at zero, with the buttons disabled;
  - auto-picking.

- [ ] **Step 1: Write the failing tests** (data: the two questions of `choices.json`)

```ts
it("names whose findings these are, asks the question, states the rule once");
it("multiple: picks two, the count says '2 scelte', 'Continua con queste' sends them in the order offered");
it("single: radios, 'Continua con questa', exactly one pick");
it("'Continua' is disabled with no pick; 'Scegli tu' sends a skip");
it("focuses its heading when it appears");
it("a failed send shows the error and keeps the picks; a closed answer shows the backend's words and no buttons");
it("at zero the buttons rest and it says 'Tempo scaduto: scelgo io.'");
it("autoPick shows those cards selected and rests every control");
it("no rule and no countdown when deadlineAt is null");
it("onTouch fires on the first change of a pick");
```

- [ ] **Step 2:** Run `npm test -- components/choice`. Expected: FAIL.
- [ ] **Step 3: Implement.** The selection lives in the panel's own state, keyed by `choice.id`.
- [ ] **Step 4:** Run `npm test -- components/choice && npm run lint && npm run typecheck`.
  Expected: PASS.
- [ ] **Step 5:** Commit: `feat(web): the choice panel`.

### Task 7: The live screen asks and answers

**Files:**
- Modify: `web/components/live/plan-screen-view.tsx` (the `choice?: ChoiceControls` prop; the
  lazy panel and `loadChoicePanel`; placement by layout; hide unless running and not
  interrupting; the one-minute note in the live region)
- Modify: `web/components/live/plan-screen.tsx` (the controls through `client.answerChoice`;
  the closed ids; the tab title; warm `loadChoicePanel` with the other chunks)
- Test: `web/components/live/plan-screen.test.tsx`, `web/components/live/plan-screen-view.test.tsx`

**Interfaces:**
- Consumes: Tasks 3, 4 and 6; `ApiClient.answerChoice`.
- Produces: `export const loadChoicePanel = () => import("@/components/choice/choice-panel")`
  (`plan-screen-view.tsx`).

How `PlanScreen.answer` maps the outcomes:
- 200: it adds the id to a local `closed` set (hidden until the event confirms it), then focuses
  `PLAN_STATE_ID`.
- 409 (`kind === "conflict"`): it returns `{closed: error.message}` and `scheduleRefresh(0)`.
- 401: `setLoginUrl`, and null.
- Anything else: the error's message.

The panel shows when `state.openChoice` is set, its id is not in `closed`, the status is
`running` and the viewer is not `interrupting`. Its `destination` is `detail.request.destination`
when that is a non-empty string, else null. The live region says `Manca un minuto per
scegliere.` once per choice, when 60 s or less are left of a window longer than 60 s (so never in
the demo's 15 s window).

- [ ] **Step 1: Write the failing tests** (the `MockEventSource` and fake client of
  `plan-screen.test.tsx`, the `choices.json` events)

```ts
it("shows the cards when the question arrives, focuses the heading, and prefixes the tab title 'Tocca a te ·'");
it("sends the picks and hides the cards at once; the answered event then draws the station");
it("shows the cards from GET /plans/{id} before the stream opens");                // Review Focus 1
it("a 409 choice_closed closes the panel with the backend's words");               // Review Focus 2
it("hides the cards while interrupting and on budget_paused, and shows them again after Continua"); // Review Focus 4
it("on the phone the panel comes before the lanes, from 1080 px after them");
it("announces once when a minute is left");
```

- [ ] **Step 2:** Run `npm test -- components/live/plan-screen.test.tsx
  components/live/plan-screen-view.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `npm test` (the whole suite: the existing live tests stay green unchanged)
  and `npm run lint && npm run typecheck`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(web): the live plan asks the traveller and sends the answer`.

### Task 8: The demo pauses on the questions

**Files:**
- Modify: `web/lib/demo/use-replay-events.ts` (holds), `web/components/demo/demo-plan-screen.tsx`
  (the `choices.json` recording, the demo's `ChoiceControls`, the notice, warm
  `loadChoicePanel`), `web/components/live/agent-lanes.tsx` (`cameraHeld?: boolean`),
  `web/components/live/plan-screen-view.tsx` (passes `cameraHeld` while a choice is open)
- Test: `web/lib/demo/use-replay-events.test.ts`, `web/components/demo/demo-plan-screen.test.tsx`,
  `web/components/live/lane-camera.test.tsx`

**Interfaces:**
- Consumes: Tasks 2, 3, 6 and 7 (`answeredTitle`, `readAskedChoice`, `readChoiceAnswer`,
  `ChoiceControls`).
- Produces:
  ```ts
  export const DEMO_CHOICE_WINDOW_MS = 15_000;
  export const AUTO_PICK_SHOW_MS = 900;
  export interface ReplayHold { choiceId: string; /** demo clock ms; null once the visitor took over */
    resumeAt: number | null; autoPick: readonly string[] | null }
  // ReplayResult gains:
  hold: ReplayHold | null;
  answer(input: ChoiceAnswerInput): void;  // lands a synthesized answered event in place of the recorded one, resumes
  touch(): void;                           // the visitor took over: resumeAt = null
  ```
  - Once an asked event lands, the replay holds: no later event lands, while `now` keeps
    running at 1× real time (not at 2×, and not while the tab is hidden).
  - Later events are stamped with the time held, so `ts` stays monotonic with the clock.
  - At `resumeAt`, `autoPick` takes the recorded answer's `selected`. After `AUTO_PICK_SHOW_MS`
    the recorded answered event lands.
  - `answer()` copies the recorded answered event: the same seq, `ts` now, `title =
    answeredTitle(...)`, and `answered_by`, `selected` and `answered_at` replaced.
  - `skip()` lands everything as recorded.
- The demo's controls:
  - `deadlineAt: hold.resumeAt`, `windowMs: DEMO_CHOICE_WINDOW_MS`;
  - `rule`: the demo's sentence while `resumeAt` is set, null after;
  - `autoPick: hold.autoPick`, `onTouch: touch`;
  - `answer`: calls `answer()`, focuses `PLAN_STATE_ID` (as live), and resolves to null.
- While the replay holds, the tab title starts with `Tocca a te · `; the previous title comes
  back when the hold ends.

`AgentLanes`: while `cameraHeld`, the camera does not move and no scroll, wheel, key or touch
counts as the visitor taking over. When the hold is released, it aims once and carries on
(unless the visitor had taken over before).

- [ ] **Step 1: Write the failing tests**

```ts
// use-replay-events.test.ts (choices.json)
it("holds on the first question: nothing after it lands, the clock keeps running at real time, at 2× too");
it("does not count hidden time against the hold");
it("without a touch, shows the recorded picks then lands the recorded answer and goes on");
it("answer() lands the visitor's picks under the recorded seq with answeredTitle's title, and goes on");
it("touch() stops the hold's clock: the replay waits for the answer");
it("skip() lands every event as recorded and ends ready");
// demo-plan-screen.test.tsx
it("plays the whole recording by itself, pausing on both questions, to the finished plan, never reaching the backend"); // WHOLE_RUN += 2 × (15 s + 0.9 s)
it("a visitor's picks become the coordinator's station, and the notice says the plan does not change");
it("the countdown shows 0:15 and the demo's rule, and both go once a card is picked");
// lane-camera.test.tsx
it("the camera aims again after a hold");                                           // Review Focus 5
```

- [ ] **Step 2:** Run `npm test -- lib/demo components/demo components/live/lane-camera.test.tsx`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** `DEMO_REQUEST` stays as it is: `choices.jsonl` sends the same
  request as `happy_path.jsonl` (checked).
- [ ] **Step 4:** Run `npm test` and `npm run lint && npm run typecheck`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(web): the demo pauses on the recorded questions`.

### Task 9: In the browser, the critique, the docs, the PR

**Files:**
- Modify: `web/README.md` (Structure: `components/choice/`; JS budget: the new figures; the demo
  backend: `?demo_scenario=choices`), `web/DESIGN.md` (anything the critique changed)
- Create: `web/.impeccable/critique/choice-cards-round<N>.md`

- [ ] **Step 1:** Look at it in the browser, at 393 px and 1440 px, in dark and light, and once
  with reduced motion:
  - the live screen against the local demo backend, with `?demo_scenario=choices`
    (`DEMO_PACE=0.5`, `web/README.md`): the cards, a pick, "Scegli tu", a wait to the timeout,
    "Interrompi" during a pause, and a reload during a pause;
  - `/demo`: a passive watch through both pauses (the camera keeps following), and a visitor's
    pick;
  - `/dev/ui`: the gallery entries.
- [ ] **Step 2:** Run the `impeccable` critique of the live pause and the demo pause. Fix and
  re-run until the score is at least 32/40 with no open P0 or P1. Save each round under
  `web/.impeccable/critique/`.
- [ ] **Step 3:** Measure again (Task 0 Step 3) and record `/plans/[id]` and `/demo` before and
  after in `web/README.md` "JS budget", with the cause of any growth.
- [ ] **Step 4:** Run every check.
  - From `web/`: `npm run gen:schemas -- --check && npm run lint && npm run typecheck && npm test
    && npm run build`.
  - From `backend/`: `uv run python ../web/scripts/gen-backend-fixtures.py --check`, `uv run
    ruff check . && uv run ruff format --check . && uv run pyright`, and `uv run pytest -q`.
  - `git diff --stat origin/feat/choices-backend...` shows nothing under `agents/`,
    `profiles/`, `skills/` or `backend/app/plan.py`.

  Expected: all PASS.
- [ ] **Step 5:** Commit the docs and critiques: `docs(web): the choice cards' critique, JS
  figures and README`.
- [ ] **Step 6:** Ask Michele before pushing and opening the PR. The PR:
  - its title: `feat(web): choice cards: the traveller picks during the run, and the demo
    pauses on them`;
  - its base: `feat/choices-backend`;
  - its body: the spec link, this plan's seven decisions, the critique score, the JS figures,
    "no agent change, no paid evals", and the two backend extractions.
