# Plan UX, PR 5: the travel mode in the form — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The request form asks how the traveller gets there (Aereo, preselected; Treno,
Traghetto, Auto, Pullman) right after the destination, always sends `journey_mode`, and the
three request summaries name the mode when it is not the plane ("in treno").

**Architecture:** Web only. A mode vocabulary with no runtime imports (`lib/journey-mode.ts`)
serves the form and the live header alike; the form's values gain `journeyMode`, and the body
always carries it. A new form primitive, `ChoiceChips` (native radios drawn as wrapping pills
with an icon), sits beside `SegmentedControl` in `field.tsx`, because five options do not fit a
segmented track at 393 px. Four Phosphor glyphs join the sprite.

**Tech Stack:** Next.js 16, React 19, TypeScript strict, Tailwind 4, vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md`. This PR covers §1 "The
form" and §4 row 5. The request contract (§1 "The request contract") shipped in PR 2
(`feat/choices-backend`, #26): `journey_mode` is in `schema/request.json` and in
`web/lib/schemas/generated/request.ts`.

## Global Constraints

- **Merge gate:** PR 5 merges only after PR 4 (the agents) is deployed to production, so a chosen
  mode is never ignored (§4). Open it as a draft and say so in its body.
- Only `web/` and `docs/` change. Nothing under `backend/`, `agents/`, `profiles/`, `skills/` or
  `schema/` (those trigger the paid evals or need a backend release).
- Labels, in the schema's enum order: `flight` **Aereo**, `train` **Treno**, `ferry`
  **Traghetto**, `car` **Auto**, `coach` **Pullman**. The enum is read from the schema
  (`fieldConstraints("journey_mode").options`); a test fails if the labels and the enum diverge.
- **Aereo is selected when the form opens**: empty form, the home page's example and a remembered
  request alike. The mode is never remembered (`lib/remembered-request.ts` is unchanged).
- The form **always** sends a mode. `omitNullJourneyMode` stays (it still guards a null).
- Place: inside "Il viaggio", right after the destination block (the destination field, or
  "Suggeriscimi tu"'s idea), before the "Quando" section.
- Copy: legend **"Come viaggi"** (also `REQUEST_FIELD_COPY.journey_mode.label` and the error
  summary's label), hint **"Per andata e ritorno. L'auto è la tua, anche se serve un
  traghetto."** Italian, sentence case, no em dash (`invariants.test.ts`).
- Summary phrases, only for a mode that is not the plane: `train` "in treno", `ferry` "in
  traghetto", `car` "in auto", `coach` "in pullman". `flight`, null, a missing key or an unknown
  value say nothing.
- Icons: Phosphor 2.1.1 bold, copied unchanged from `@phosphor-icons/core@2.1.1`
  `assets/bold/<name>-bold.svg` (one `<path>` each, checked): `train`, `boat`, `car`, `bus`.
  `airplane-tilt` is already in the sprite. Modes: flight `airplane-tilt`, train `train`, ferry
  `boat`, car `car`, coach `bus`.
- Never amber; the chosen chip is ink (`bg-action`), like the chosen segment.
- Michele prefers rebase to merge. Ask before pushing or opening the PR.

## Review Focus

1. **A stored request with an odd `journey_mode`** (`"plane"`, `3`, `null`, no key, an old row)
   must not break the plan header and must name no mode. Test: Task 4
   (`requestSummary` "ignores a mode it does not know").
2. **The example and the remembered request still open on Aereo**, and switching "Suggeriscimi
   tu" or the date mode keeps the chosen mode. Tests: Task 1 (`exampleRequestForm`,
   `applyRemembered`) and Task 3 ("keeps the chosen mode across the other choices").
3. **The backend answers 422 on `journey_mode`.** The message shows under the row and the focus
   goes to the chosen chip; with three problems or more the error summary names it "Come
   viaggi". Tests: Task 3 ("puts a 422 on the mode under its row", "visits the mode right after
   the destination").
4. **Enter on a mode chip** moves on to the dates and never sends a half-written request, while
   the arrow keys move between the five chips (one radio group). Test: Task 3 ("Enter on a mode
   moves to the dates").
5. **The row at 393 px**: five chips wrap onto two rows, with no horizontal scroll, and every chip
   has a 44 px tap area. Pinned by Task 5's browser check (393 px and desktop, light and dark).

---

### Task 0: Branch

- [ ] **Step 1:** The worktree `.claude/worktrees/journey-mode-form` is on `feat/journey-mode-form`,
  branched from `feat/choices-backend` `a805394` (PR #26 is open, and it sits on PR #25). This
  plan is the branch's first commit: `docs: the plan for PR 5, the travel mode in the form`.
- [ ] **Step 2 (whenever `git fetch origin` shows movement):**
  - #26 gained commits: `git rebase --onto origin/feat/choices-backend a805394 feat/journey-mode-form`
    (then use the new tip as the base next time).
  - #26 merged (a squash): `git rebase --onto origin/main <choices-backend tip we sit on>`.

  Never a plain `git rebase origin/main` while #25 or #26 is open. After a rebase, run
  `npm run gen:schemas -- --check` from `web/`.

### Task 1: The mode in the form's values and body

**Files:**
- Create: `web/lib/journey-mode.ts`, `web/lib/journey-mode.test.ts`
- Modify: `web/lib/request-form.ts` (`REQUEST_FIELD_COPY.journey_mode`, `RequestFormValues`,
  `emptyRequestForm`, `buildPlanRequest`, `validatePlanRequest`, a `JOURNEY_MODES` export)
- Test: `web/lib/journey-mode.test.ts`, `web/lib/request-form.test.ts` (its helpers `form()`
  and `request()` build valid form values and a valid body; the `applyRemembered` case goes here
  too, as `lib/` has no test file for it)

**Interfaces:**
- Produces (`web/lib/journey-mode.ts`, type-only imports, so the plan page pays no schema
  weight):
  - `type JourneyMode = NonNullable<PlanRequest["journey_mode"]>`
  - `DEFAULT_JOURNEY_MODE: JourneyMode` = `"flight"`
  - `JOURNEY_MODE_LABELS: Readonly<Record<JourneyMode, string>>` (the labels, enum order)
  - `journeyModePhrase(mode: unknown): string | null`: "in treno" etc.; null for `flight`,
    null, and anything that is not a known mode.
- Produces (`web/lib/request-form.ts`):
  - `JOURNEY_MODES: readonly JourneyMode[]`: the schema's enum, in its order.
  - `RequestFormValues.journeyMode: JourneyMode`, after `destinationIdea`.

- [ ] **Step 1: Write the failing tests**

```ts
// journey-mode.test.ts
it("says the mode in words, except the plane and anything unknown", () => {
  expect(journeyModePhrase("train")).toBe("in treno");
  expect(journeyModePhrase("ferry")).toBe("in traghetto");
  expect(journeyModePhrase("car")).toBe("in auto");
  expect(journeyModePhrase("coach")).toBe("in pullman");
  for (const odd of ["flight", null, undefined, "plane", 3, "Train", "__proto__"]) expect(journeyModePhrase(odd)).toBeNull();
});

// request-form.test.ts, "metadata from schema/request.json"
it("labels exactly the schema's travel modes, in its order", () => {
  expect(JOURNEY_MODES).toEqual(["flight", "train", "ferry", "car", "coach"]);
  expect(Object.keys(JOURNEY_MODE_LABELS)).toEqual([...JOURNEY_MODES]);
  expect(REQUEST_FIELD_COPY.journey_mode?.label).toBe("Come viaggi");
});

// "the form"
it("opens on the plane and always sends the chosen mode", () => {
  expect(emptyRequestForm().journeyMode).toBe("flight");
  expect(exampleRequestForm("2026-10-12").journeyMode).toBe("flight");
  expect(buildPlanRequest(form()).journey_mode).toBe("flight");
  const result = validateRequestForm(form({ journeyMode: "train" }), { today: TODAY });
  expect(result.ok && result.request.journey_mode).toBe("train");
});
it("refuses a mode the schema does not know, on its own path", () => {
  expect(validatePlanRequest(request({ journey_mode: "plane" }), { today: TODAY }))
    .toContainEqual({ path: "journey_mode", code: "literal_error" });
  expect(validatePlanRequest(request({ journey_mode: null }), { today: TODAY })).toEqual([]);
});
it("lays a remembered request in without touching the mode", () => {
  const values = applyRemembered({ ...emptyRequestForm(), journeyMode: "car" }, { origin: "Torino", adults: 2, childAges: [] });
  expect(values.journeyMode).toBe("car");
});
```

Update the existing expectations
that the new key breaks: "builds the POST /plans body" gains `journey_mode: "flight"`, and "starts
empty, one adult, destination mode, fixed dates" gains `journeyMode: "flight"`.

- [ ] **Step 2:** Run `npx vitest run lib/journey-mode.test.ts lib/request-form.test.ts` from
  `web/`. Expected: FAIL (module not found, `journeyMode` undefined).
- [ ] **Step 3:** Implement `web/lib/journey-mode.ts` and the `request-form.ts` changes.
  `journeyModePhrase` looks the value up with `Object.hasOwn` on a phrase table, so `"__proto__"`
  is unknown. `validatePlanRequest` adds one check: when `journey_mode` is neither `undefined`
  nor `null`, it must be one of `fieldConstraints("journey_mode").options`, else
  `{ path: "journey_mode", code: "literal_error" }` (Pydantic's code for a Literal; its Italian
  message, "Scelta non valida.", already exists).
- [ ] **Step 4:** Run the same command, then `npm run typecheck`. Expected: PASS. (Components that
  build `RequestFormValues` by hand may fail to typecheck until Task 3; fix only those that do,
  with `journeyMode: "flight"`.)
- [ ] **Step 5:** Commit: `feat(web): the travel mode in the request form's values and body`.

### Task 2: `ChoiceChips` and four icons

**Files:**
- Modify: `web/components/ui/icons.ts` (the four paths, in a "travel modes" group after
  `tram`), `web/components/ui/field.tsx` (`ChoiceChips`), `web/app/dev/ui/demos.tsx` (`FormDemo`
  gains the mode row), `web/DESIGN.md`
- Test: `web/components/ui/primitives.test.tsx`

**Interfaces:**
- Produces (`field.tsx`):

```ts
export interface ChoiceChipOption<T extends string> { value: T; label: string; icon: IconName }
export function ChoiceChips<T extends string>(props: {
  legend: ReactNode;          // the group's question, as its <legend>
  hint?: ReactNode;           // under the legend, ink-2, wired into each radio's description
  error?: ReactNode;          // under the chips, error red with the cross, like Field's
  name: string;
  options: readonly ChoiceChipOption<T>[];
  value: T;
  onValueChange: (value: T) => void;
  id?: string;                // set on the CHECKED radio: where a form moves focus for an error
  className?: string;
}): JSX.Element
```

- [ ] **Step 1: Write the failing test** (`describe("ChoiceChips")`):
  - renders a `group` named by the legend with one `radio` per option, all sharing `name`;
  - the chosen value is `checked`, and clicking another calls `onValueChange` with its value;
  - `id` lands on the checked radio only;
  - with `hint` and `error`, every radio's `aria-describedby` resolves to the hint's and the
    error's text, and every radio has `aria-invalid="true"`; without `error`, no `aria-invalid`;
  - each option shows its icon (`svg use` pointing at the option's symbol) and its label.
- [ ] **Step 2:** `npx vitest run components/ui/primitives.test.tsx`. Expected: FAIL (no export).
- [ ] **Step 3:** Copy the four `<path d>` values from `@phosphor-icons/core@2.1.1` (`npm pack`
  into a scratch directory, never into the repo). Implement `ChoiceChips` in `field.tsx`, next to
  `SegmentedControl` and drawn in its language: a borderless `fieldset`, the legend styled like
  `SegmentedControl`'s, the hint with Field's hint style, then `flex flex-wrap gap-2` pills, each
  a `label` around an `sr-only` radio: `rounded-full`, 1.5 px `rule-strong` edge, `surface`,
  16 px icon then the label in `text-small` semibold, 40 px tall on the phone with a 3 px
  `before:` extension (44 px and more of tap area), 36 px from 640 px; hover `notice-wash`;
  checked `bg-action text-on-action` with the edge in `action`; focus-visible the 2 px ink ring
  as `SegmentedControl` draws it. The error line copies Field's markup. In `FormDemo`, add a
  "Come viaggi" row with the five modes (its own `useState`, Aereo first).
- [ ] **Step 4:** DESIGN.md: the components table row for `field.tsx` gains `ChoiceChips`;
  "Inputs / Fields" gains **choice chips** (native radios drawn as wrapping pills with an icon,
  the chosen one ink, for four or more exclusive choices: the travel mode); "Iconography" says
  39 icons and adds "Travel modes: `airplane-tilt` aereo, `train` treno, `boat` traghetto, `car`
  auto, `bus` pullman."
- [ ] **Step 5:** `npx vitest run components/ui` (primitives, tokens, invariants). Expected: PASS.
- [ ] **Step 6:** Commit: `feat(web): ChoiceChips, and the train, boat, car and bus icons`.

### Task 3: The mode row in the form

**Files:**
- Modify: `web/components/request/request-form.tsx`, `web/components/request/form-model.ts`
- Test: `web/components/request/request-form.test.tsx`, `web/components/request/form-model.test.ts`

**Interfaces:**
- Consumes: `JOURNEY_MODES` and `RequestFormValues.journeyMode` (Task 1), `JOURNEY_MODE_LABELS`
  (Task 1), `ChoiceChips` (Task 2).
- Produces (`form-model.ts`): `JOURNEY_MODE_ICONS: Readonly<Record<JourneyMode, IconName>>`
  (the Global Constraints' mapping; Task 4 uses it), and `errorTargets` gains
  `{ path: "journey_mode", controlId: fieldId("journey_mode"), label: "Come viaggi" }` right after
  the destination's (or the idea's) target.

- [ ] **Step 1: Write the failing tests**

```ts
// form-model.test.ts
it("visits the mode right after the destination", () => {
  const targets = errorTargets(emptyRequestForm(), { demo: false });
  expect(targets.map((t) => t.path).slice(0, 3)).toEqual(["origin", "destination", "journey_mode"]);
  expect(targets[2]).toEqual({ path: "journey_mode", controlId: "field-journey_mode", label: "Come viaggi" });
  const suggest = errorTargets({ ...emptyRequestForm(), suggestDestination: true }, { demo: false });
  expect(suggest.map((t) => t.path).slice(0, 3)).toEqual(["origin", "destination_idea", "journey_mode"]);
});
```

`request-form.test.tsx`:
  - "labels every control …": the `group` "Come viaggi" holds five radios named Aereo, Treno,
    Traghetto, Auto, Pullman; Aereo is checked; the group comes after "Dove vuoi andare" and
    before "Partenza" in document order (`compareDocumentPosition`).
  - "starts the plan and opens it": the expected `createPlan` body gains `journey_mode: "flight"`;
    the assertion from 49ac694 (no `journey_mode` key) is replaced by this.
  - new "sends the chosen mode": click Treno, submit a complete form, the body has
    `journey_mode: "train"`.
  - new "keeps the chosen mode across the other choices": click Pullman, then "Suggeriscimi tu"
    and "Mese e notti" (fill the idea, month and nights), submit: `journey_mode: "coach"`.
  - new "Enter on a mode moves to the dates": `keyDown` Enter on the Treno radio moves focus to
    "Partenza" and sends nothing.
  - new "puts a 422 on the mode under its row": `createPlan` rejects with
    `new RequestValidationError(422, [{ type: "literal_error", loc: ["body", "journey_mode"], msg:
    "..." }])` (as the existing 422 test builds it); after submit, "Scelta non valida." describes the checked radio, which has
    the focus and `aria-invalid="true"`; choosing another mode clears it.

- [ ] **Step 2:** `npx vitest run components/request`. Expected: FAIL.
- [ ] **Step 3:** Add the row to `tripSection` after the destination conditional:
  `ChoiceChips` with `legend="Come viaggi"`, the hint of Global Constraints, `name` from a new
  `useId()`, options from `JOURNEY_MODES` with `JOURNEY_MODE_LABELS` and `JOURNEY_MODE_ICONS`,
  `id={fieldId("journey_mode")}`, `error={errors.journey_mode}`, and
  `onValueChange={(journeyMode) => change({ journeyMode }, is("journey_mode"))}`.
- [ ] **Step 4:** `npx vitest run components/request lib`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(web): ask how the traveller gets there, after the destination`.

### Task 4: The summaries name the mode

**Files:**
- Modify: `web/components/request/summary.ts` (`journeySummary`),
  `web/components/request/request-summary.tsx`, `web/components/live/request-summary.ts`
- Test: `web/components/request/summary.test.ts`, `web/components/live/request-summary.test.ts`

**Interfaces:**
- Consumes: `journeyModePhrase` (Task 1), `JOURNEY_MODE_ICONS` (Task 3).
- Produces: `journeySummary(values: RequestFormValues): string | null` ("In treno"; null for the
  plane).

- [ ] **Step 1: Write the failing tests**

```ts
// summary.test.ts
it("names the mode only when it is not the plane", () => {
  expect(journeySummary(values())).toBeNull();
  expect(journeySummary(values({ journeyMode: "train" }))).toBe("In treno");
  expect(journeySummary(values({ journeyMode: "coach" }))).toBe("In pullman");
});

// live/request-summary.test.ts
it("says how they travel right after where from, unless by plane", () => {
  expect(requestSummary({ ...LISBONA, journey_mode: "train" }))
    .toBe("Da Milano in treno, 2 adulti e 2 bambini (8 e 11 anni), budget 2.400 €");
  expect(requestSummary({ ...LISBONA, journey_mode: "flight" }))
    .toBe("Da Milano, 2 adulti e 2 bambini (8 e 11 anni), budget 2.400 €");
  expect(requestSummary({ travelers: [{ kind: "adult" }], journey_mode: "car" })).toBe("In auto, 1 adulto");
});
it("ignores a mode it does not know", () => {
  for (const odd of [null, "plane", 3, { mode: "train" }]) {
    expect(requestSummary({ ...LISBONA, journey_mode: odd })).toBe("Da Milano, 2 adulti e 2 bambini (8 e 11 anni), budget 2.400 €");
  }
});
```

(`LISBONA` is the request of the file's first test, lifted into a constant.) The desktop
summary: one render test in `request-form.test.tsx` (the summary renders with the form): with
Traghetto chosen, the "Il tuo viaggio" section lists "In traghetto"; with Aereo, no line starts
with "In ".

- [ ] **Step 2:** `npx vitest run components/request components/live/request-summary.test.ts`.
  Expected: FAIL.
- [ ] **Step 3:** `journeySummary` capitalises `journeyModePhrase(values.journeyMode)`.
  `RequestSummary` renders it as the first `TripFact` (before the dates) with
  `JOURNEY_MODE_ICONS[values.journeyMode]`, only when not null. `requestSummary` appends the
  phrase to "Da <origin>" and, without a readable origin, starts the line with it, capitalised.
- [ ] **Step 4:** Same command. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(web): the request summaries name a travel mode other than the plane`.

### Task 5: In the browser, the critique, full checks and the PR

**Files:**
- Create: `web/.impeccable/critique/journey-mode-form.md`

- [ ] **Step 1:** Task 0 step 2 if `origin` moved.
- [ ] **Step 2:** From `web/`: `npm run gen:schemas -- --check && npm run lint && npm run
  typecheck && npm test && npm run build`. Expected: all PASS.
- [ ] **Step 3:** In the browser (`npm run dev`, `/new` and `/dev/ui`): 393 px and desktop
  (1440 px), light and dark. Check Review Focus 5 (wrap, no horizontal scroll, tap areas), the
  focus ring on each chip with the keyboard, arrow keys moving the choice, the desktop summary
  with Treno, the live header of a `DEMO_MODE` plan started by train (the demo backend replays its
  script whatever the mode, so only the header's words are checked).
- [ ] **Step 4:** impeccable critique of `/new`, saved in
  `web/.impeccable/critique/journey-mode-form.md`; fix until 32/40 or more with no open P0 or P1.
  Commit fixes and the critique: `docs(web): the critique of the travel mode row`.
- [ ] **Step 5:** Ask Michele before pushing and opening the **draft** PR against
  `feat/choices-backend` (title `feat(web): the travel mode in the request form`; body: the
  spec link, screenshots at 393 px and desktop, the merge gate "after PR 4 is deployed to
  production", web only, no agent change, no paid evals).
