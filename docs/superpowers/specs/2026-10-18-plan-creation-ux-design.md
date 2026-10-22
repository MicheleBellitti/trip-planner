# Plan creation: travel mode, choice cards and a link check

Design spec, 2026-10-18. Decided by Michele in a brainstorming session (the choice-card mockup is
in `.superpowers/brainstorm/`, not committed). Scope: `backend/`, `agents/`, `skills/`, `web/`,
`evals/`. Where this spec and `docs/spec/implementation-doc.it.md` disagree, this spec wins for
the three features below; the verified research files keep their authority on facts about the
platform.

## Why

Creating a plan today is a form and then a wait: the user watches the agents work and gets a
finished plan they had no say in. Michele wants three things:

1. **Choose the main travel mode** before the plan starts. Today the coordinator decides alone
   (train under about five hours, otherwise a flight). The plane stays the default, but train,
   ferry, car and coach must be choices.
2. **Take part while the plan is built.** A few times per plan the run pauses and the user picks,
   from cards, the options they like (places to see, the kind of food). The agents then tailor
   the rest of the plan to those picks. The user should feel involved in the decisions, not
   handed a result.
3. **Stop delivering dead links.** Some links in delivered plans answer 404. Michele has seen it
   only on local transport, so it is not severe, but it is a pattern that erodes trust.

Success: a user who sends a request is asked two or three short, pleasant questions with real
photos, sees their picks in the finished days, never meets an error because of the travel mode,
and never clicks a link that answers "page not found" without being told first.

## Decisions at a glance

| Topic | Decision |
| --- | --- |
| Travel mode | A single choice in the form, **after the destination**: Aereo (preselected), Treno, Traghetto, Auto, Pullman. It decides how the main journey (out and back) is researched; local legs stay with the agents. A request without a mode (old clients, evals) lets the coordinator decide, as today. |
| Mode against preferences | A mode the preferences contradict ("Aereo", and "solo treno" written below) is asked about in the first pause. |
| Impossible mode | Never an error. The coordinator checks first; if the mode cannot reach the destination, the first pause asks how to travel instead, with the modes that work. |
| Possible but clumsy mode | Respected, with one warning line (e.g. a flight Milano–Firenze: the train was easier). |
| "Suggeriscimi tu" | The traveller picks the destination: the first pause shows the (at most three) candidates as cards, before any research, so only the chosen one is researched. The mode filters the candidates. |
| Choice cards | At most three pauses per plan: what to see (always), what to eat (always), and one optional (the destination with "Suggeriscimi tu", else the travel mode when it is impossible or contradicted, else one real fork). |
| Cards | 3 to 6, each with a photo, a title, one line on why, and (for places) duration, price for the party and area. Multi-select for places and food. |
| Controls | "Continua con queste" (needs at least one pick) and "Scegli tu" (the agents decide). |
| No answer | After 4 minutes Atlas picks and the run carries on (4, not 5: see "Cost" in section 2). The rule is said once in the intro; the clock is a bare countdown with a thin bar, not amber. |
| Photos | Looked up by the backend on Wikimedia (free licences, credited), like the plan cover. Agents never write image URLs. No free photo, no photo. |
| Waiting cost | Nothing while idle; a pause longer than the prompt cache's 5 minutes costs about 5 to 10 cents, which the 4-minute timeout avoids. |
| Link check | Deterministic, in the backend, when the coordinator delivers the plan. No extra agent. |
| Dead link | If the site's homepage works, the link goes there, labelled "Sito di <sito>"; if not, the text "Pagina non trovata" and no link. |
| Unsure link | Bot walls, 403, timeouts: the link stays as it is (no false alarms). |
| Root cause | Prompt rule for transport and activities: a source URL is a page the agent opened or saw in search results, never one it composed. |

## 1. Travel mode

### The request contract

`PlanRequest` gains:

```python
journey_mode: Literal["flight", "train", "ferry", "car", "coach"] | None = None
```

- `car` is the traveller's own car. `coach` is a long-distance bus (the city bus stays a local
  leg). The names follow the `journey.mode` key the coordinator already writes in
  constraints.json.
- **`null` means "the coordinator decides"**, exactly as today (train under about five hours or
  when the preferences ask for it, otherwise a flight). Old clients, stored requests, the API,
  the existing eval requests and every plan sent between the agents PR and the form PR carry no
  mode, so nothing changes for them (contract rule 7: the backend ships first and accepts both).
  `PlanRequest.from_stored` needs no change.
- The **form always sends a mode**: Aereo is preselected (Michele, 2026-10-18).
- `python -m app.schemas` regenerates `schema/request.json`; the web form reads the enum from it.
- The existing eval requests stay without a mode, so their results stay comparable with the
  baseline. Whether a new request exercises an explicit mode or the journey pause is the
  builder's call, inside the evals' spending ceiling.

### The form

- A single-choice row placed right after the destination block (destination, or "Suggeriscimi
  tu" with its idea), before the dates. Labels: **Aereo**, **Treno**, **Traghetto**, **Auto**,
  **Pullman**. Aereo is selected when the form opens.
- Phosphor icons, built from `components/ui/` primitives (it is a choice chip row, like the
  other choice fields of the form). The sprite (`web/components/ui/icons.ts`) has `airplane-tilt`
  and `tram` today; add Phosphor's train, boat, car and bus glyphs to it.
- The request summary (`components/request/summary.ts`, `request-summary.tsx`, the live header's
  `request-summary.ts`) names the mode when it is not the plane ("in treno").

### What the agents do with it

The coordinator reads `journey_mode` from request.json. With `null` it decides the mode itself,
as today, and steps 1 to 4 do not apply. With a mode:

1. **Checks feasibility first**, before any delegation, from its own knowledge (it has no web
   tools): can this mode carry the party from the origin to the destination? A train to Tenerife
   cannot; a ferry to Milano cannot; a car to Lisbon from Milano can (long, but possible).
2. **Impossible, or contradicted by the preferences** ("Aereo", and "solo treno, niente aerei"
   in the preferences): it asks with `ask_traveller` (kind `journey`, single choice), offering
   the two to four modes that work (for a contradiction, the chosen mode and the one the
   preferences ask for), each with a rough door-to-door duration in the reason line ("Circa
   3 h 30 con scalo"). On "Scegli tu" or no answer it takes the most sensible mode and says so in
   one warning line.
3. **Possible but clearly worse** than another mode: it respects the choice and adds one warning
   line naming the easier mode.
4. **Suggest a destination:** candidates must be reachable by the chosen mode.
5. **Delegation by mode** (with a mode, the user's choice replaces today's "train trip"
   exception; with `null` the exception stays):
   - `flight`: `flights`, as today.
   - `train` and `coach`: `transport` researches the main journey (out and back) in wave 1;
     booking links from build_link.py (`trenitalia`, `italo`, `omio`).
   - `ferry`: the party crosses as foot passengers. `transport` researches the crossing and the
     legs to and from the port. No ferry seller is on the booking allowlist yet, so a ferry
     booking has `link` null and the operator's page as the stop's `url` (adding a ferry provider
     needs its own research in `docs/research/integrations.md` and is out of scope).
   - `car`: the party drives its own car, **car ferries included** where the route needs one
     (Milano to Olbia: drive to Genova, then the ferry with the car, its vehicle fare priced).
     `transport` researches the drive: duration, distance, an estimated cost of fuel and tolls (a
     `price` with `status: "estimated"` and the page the figures came from), any car ferry, and
     parking near the lodging. The drive itself is not a booking; a car ferry is, and parking is
     one only if it must be booked. The eval request `sea-week-family` ("Traghetto con la nostra
     auto") is a `car` trip.
   - Local legs at the destination stay as today for every mode. With `car`, the transport agent
     also considers driving to far stops.

`app/results.py` `TransferMode` gains `car` (the traveller's own car, distinct from
`car_rental`). It ships in the agents PR, not the backend one: regenerating
`schema/results/transport.json` changes the travel-research-rules skill schemas, which trigger
the paid evals; the backend only logs result-file problems, so the two can land together.

### Suggest a destination: the traveller picks

Today, with `suggest_destination`, wave 1 prices flights and lodging for every candidate and the
coordinator chooses. Instead (Michele, 2026-10-18):

- Before any delegation, the coordinator picks at most three candidates from its own knowledge
  (fitting `destination_idea`, the dates, the budget, the origin and the mode) and asks with
  `ask_traveller` (kind `destination`, single choice). Each card: the place, a one-line reason,
  and a rough travel time by the chosen mode in `area`'s place ("Circa 2 h di volo"). No prices
  yet: nothing has been researched.
- The photo is the destination's cover, from the existing `app/covers.py` resolver.
- On "Scegli tu" or no answer the coordinator takes its leading candidate.
- Then the normal flow runs for the chosen destination only: wave 1 researches one place, which
  is cheaper than pricing three. The summary still names the candidates not taken.
- `constraints.json`'s `candidates` and step 2 of `agents/coordinator.md` change accordingly.

## 2. Choice cards

### The experience (approved on the mockup)

**When.** At most three pauses per plan, all asked by the coordinator:

| Pause | When | Cards | Select |
| --- | --- | --- | --- |
| `destination` | At the very start, only with "Suggeriscimi tu" | the 2 or 3 candidates | one |
| `journey` | At the very start, only when the chosen mode is impossible or the preferences contradict it | 2 to 4 modes | one |
| `activities` | When the wave-1 activities reply is in | 3 to 6 of its options, the most different from each other | several |
| `food` | During wave 1, while the subagents research (Michele, 2026-10-22; first: after the journey and lodging were chosen, which left the session idle while the traveller answered) | 3 or 4 eating styles typical of the destination (written by the coordinator, no research) | several |
| `other` | At most once, only for a real fork the traveller would care about (two very different lodgings, ferry or flight to an island) | 2 to 4 | one |

`destination`, `journey` and `other` share the third slot, in that order of precedence: a plan
never pauses more than three times, and a kind appears at most once. With "Suggeriscimi tu" the
mode cannot be impossible (it filters the candidates); a contradiction with the preferences is
then settled by the coordinator, with one warning line.

**What the user sees** (the mockup, in Atlas's own tokens):

- The run pauses. The asking agent's line ends at a station with a plate "Tocca a te: <what>";
  the other lines wait. On desktop the choice panel sits under the lines; on the phone it comes
  first under the live header. The page scrolls to it and moves focus to its heading.
- An eyebrow names whose findings these are, with that line's roundel ("Attività ha trovato 6
  idee per Lisbona"); the coordinator's roundel for `destination`, `journey`, `food` and
  `other`.
- A heading question ("Cosa ti va di vedere?", "Che cucina cerchi?") and an intro that states
  the rule once: "Scegli quelle che ti piacciono, anche più di una. Se non scegli entro 4 minuti,
  scelgo io." (single-choice pauses say "Scegline una").
- Cards in a grid (three across on desktop, two on the phone; food four across): photo on top
  (4:3, food 16:10), title, one line on why, then chips: duration, price for the party (in the
  option's currency, Italian format), area. A chip whose value is unknown is left out. There is
  no "gratis" chip: a null activity price means "not checked" as often as "free"
  (`agents/activities.md`), so the data cannot tell. Selected cards get an ink ring and a filled tick
  roundel. A slow zoom on the photo on hover; no other motion.
- The action row: the count ("2 scelte"), "Scegli tu" (secondary) and "Continua con queste"
  (primary, disabled with no pick; "Continua con questa" for one). Above them, the countdown:
  `4:12` and a thin depleting bar in ink (never amber: amber belongs to booking deadlines).
  Screen readers hear the time once when one minute is left, not every second.
- A photo credit (author and licence, as the cover does) is reachable on each card without
  crowding it.
- While a choice waits, the tab title starts with "Tocca a te ·".
- After the answer the panel collapses into a station on the coordinator's line: "Hai scelto:
  Torre di Belém, Alfama", "Hai lasciato scegliere ad Atlas", or after the timeout "Scelto da
  Atlas: …". The run resumes.

Copy is Italian, sentence case, no em dash (`invariants.test.ts`). Build from `components/ui/`
and add the new primitives (choice card, countdown) to the `/dev/ui` gallery.

**What the picks change.** The coordinator passes them to wave 2: activities builds the days
around the picked options and drops the others; the food styles steer the meal stops; picks also
inform the rest (two food markets picked: more food stops). Unpicked options do not appear in the
plan.

### The mechanism

**A second custom tool on the coordinator: `ask_traveller`.** Only the coordinator has it;
subagents never ask. Like `submit_plan`, its input schema is generated: a Pydantic model
(`ChoiceRequest`, in a new `app/choices.py`) exported by `python -m app.schemas` as
`schema/ask_traveller.json`, and rendered by `scripts/render_profiles.py` into
`profiles/<profile>/agents/tools/ask_traveller.json`. Input:

| Field | Rule |
| --- | --- |
| `kind` | `destination`, `journey`, `activities`, `food` or `other` |
| `question` | Italian, at most 120 characters |
| `multiple` | true for `activities` and `food`, false for the others |
| `options` | 2 to 6 items (`activities` 3 to 6) |
| `options[].id` | the result-file option id when there is one (`a3`), else `c1`, `c2`, ...; unique |
| `options[].title` | Italian, at most 80 characters |
| `options[].reason` | Italian, one line, at most 140 characters |
| `options[].duration_min` | optional |
| `options[].price` | optional, `{amount_cents, currency}` copied from the result file's price, for display only (no `source_url`) |
| `options[].area` | optional, at most 60 characters |
| `options[].place` | optional, the place name and city for the photo lookup ("Torre de Belém, Lisboa"), at most 120 characters |

No URL of any kind in the input: links and photos are never the agent's to write.

**The tool's answer** (text to the coordinator, English):

- picks: `The traveller chose: a1 "Torre di Belém", a3 "Alfama e i miradouros". Build the plan
  around these and drop the other options you offered.`
- "Scegli tu" or timeout, for `activities`, `food` and `other`: `The traveller let you choose.
  Pick what fits the request best and go on; do not mention it in the warnings.`
- "Scegli tu" or timeout, for `journey`: `The traveller did not choose a mode. Take the most
  sensible one and say so in one warning line.`
- "Scegli tu" or timeout, for `destination`: `The traveller let you choose. Take your leading
  candidate and go on.`
- invalid input: `is_error` with the validation errors, as `submit_plan` does; the coordinator
  fixes them and asks again (an invalid call is not a pause).
- a fourth pause, or a second pause of the same kind: `is_error`, "No more questions: choose
  yourself." Nothing reaches the user.

**The backend's side.**

- `consumer.decide_idle`: a `requires_action` idle whose pending events are all our own custom
  tool uses (`submit_plan` or `ask_traveller`) is `WAIT`, as for `submit_plan` today. The plan
  stays `running`; there is no new plan status.
- On `agent.custom_tool_use` named `ask_traveller`: validate; resolve the photos; store a row in
  a new table `choices`; emit a timeline event; start the deadline timer.
- **`choices` table** (one Alembic migration): `id` (the `agent.custom_tool_use` event id),
  `plan_id` (FK, cascade on delete so the retention cleanup removes them), `kind`, `payload`
  (jsonb: the validated input plus the resolved photos), `asked_at`, `deadline_at`, `answer`
  (jsonb: the picked ids), `answered_by` (`traveller`, `skip`, `timeout`, or null while
  pending), `answered_at`.
- **Photos.** A resolver built on `app/covers.py`'s Wikimedia logic (free licences only,
  `upload.wikimedia.org` only, author and licence kept, a cache table or the covers table keyed
  by place). Lookups run in parallel under a short overall deadline (about 3 seconds) before the
  event is emitted; a card whose photo is not found in time has none. Only the place name leaves
  the backend.
- **Timeline events.** A new `EventKind.CHOICE` with two titles: asked ("Tocca a te: scegli cosa
  vedere", with the payload and the deadline) and answered (with who answered and the picks). The
  web reducer derives the pending choice from them, and `GET /plans/{id}` (`PlanDetail`) carries
  `pending_choice` so a reloaded page shows the cards at once.
- **Answer endpoint.** `POST /plans/{plan_id}/choices/{choice_id}` with `{"selected": [ids]}` or
  `{"skip": true}`. The plan's owner only, the `Origin` check like every state-changing request.
  Selected ids must be among the offered ones; a single-choice pause takes exactly one. The
  backend stores the answer with a conditional update (`WHERE answered_by IS NULL`), sends
  `user.custom_tool_result`, emits the answered event. A closed choice (answered, timed out) is
  409 `choice_closed`. Errors use the usual envelope with Italian messages.
- **Timeout.** `CHOICE_TIMEOUT_SECONDS` in Settings (default 240, documented in
  `backend/.env.example`; see "Cost" for why not 300). At the deadline the consumer does the
  same conditional update with `timeout` and sends the "let you choose" answer; whichever of the
  user and the timer updates the row first wins, the other is a no-op.
- **Restart and resume.** The consumer's reconciliation already re-answers a `submit_plan` use
  without a result in history; extend it: an `ask_traveller` use without a result is answered from
  its `choices` row if answered, re-armed if still before its deadline, answered as `timeout` if
  past it, and stored (with a fresh deadline) and emitted if no row exists. A second result for
  the same call has no effect on the platform, so a duplicate send is harmless.
- **Interrupt while a choice waits.** "Interrompi" must still work; the pending choice closes
  without an answer to the agent beyond what the interrupt flow needs. Verify with the fake client
  and with live probe P14 below.
- **Logs:** `choice_asked` and `choice_answered` with the kind, the number of options, who
  answered and the latency; no card text.

**Evals and the CLI.** `evals/run.py` drives plans through `sessions.start_plan`; it answers each
pending choice at once through the same backend function the endpoint uses, picking the first
option (the first two when `multiple`), so every eval exercises the picks. The judge rubric gains
one line: the picked activities and food styles are reflected in the plan. `app.cli run` answers
the same way unless a flag asks it to prompt in the terminal.

**Demo.**

- `DEMO_MODE` (local): a scripted scenario with an `activities` and a `food` pause; the fake
  client waits for the answer (or the timeout) before playing the rest. Whether it extends
  `happy_path` or is a new default scenario is the builder's call.
- `/demo` (public replay): the recorded run includes the pauses; the visitor can click the cards,
  and the replay picks what the recording picked after a few seconds without a click. Photos come
  from a committed fixture, like `web/lib/demo/cover.json`: the demo never calls Wikimedia.

**Cost.** An idle session does not spend its budget, but the prompt cache lives 5 minutes. A
pause that outlasts it makes the coordinator's next request rewrite its whole cached context
(about 17k tokens after the skill loads, plus the result files it read): roughly 5 to 10 cents on
the development profile, whose budget is 100 cents. Hence a 4-minute timeout: a timed-out pause,
and every answer given within 4 minutes, resumes on a warm cache. Evals answer at once, so they
never measure this; the `choice_answered` logs (latency) do.

### Prompt changes (coordinator)

- Replace "Nobody reads or answers your messages … never ask the user a question" with: the
  traveller is reachable only through `ask_traveller`, at most three times, at the moments in the
  table above; never ask what the request already says; never ask anything else; the call returns
  the answer, and waiting needs no other action.
- The activities pause offers the most different options of the wave-1 file, never more than six,
  with the result-file ids, `place` for the photo, and price and duration copied.
- The wave-2 tasks carry the picks: "the traveller picked a1, a3; build the days around them and
  drop the others; meals: tascas di quartiere, cena con fado".
- The journey-mode rules and the destination pick of section 1 (step 2 of the coordinator's
  steps no longer prices every candidate).

Whether the subagents keep working while the coordinator waits on `ask_traveller` is not
documented (probe P14). The design works either way: if they keep working, the wait overlaps the
research; if they pause, the plan takes as long as the wait.

## 3. Link check

### What the backend does

When `submit_plan` delivers a Plan that validates and translates, and before the backend answers
"Plan accepted.", it checks every distinct URL in the plan: `bookings[].link`,
`alternatives[].link`, every stop's `url` and every `price.source_url`.

- **Verdict per URL:** `ok`, `dead` or `unknown`.
  - `dead`: the final answer is 404 or 410; the host name does not exist; or a soft 404 (a 2xx
    HTML page whose `<title>` says "not found" in Italian, English, Spanish, Portuguese, French or
    German, read from at most the first 64 KB).
  - `unknown`: 401, 403, 405, 429, 5xx, timeouts, TLS errors, resets, bot walls. Treated like
    `ok` on screen: no false alarms.
- **Dead, homepage fallback:** the backend checks the URL's own origin (`https://<host>/`, same
  scheme and host, nothing else). If that is `ok` or `unknown`, the fallback is that homepage;
  if it is dead too, there is no fallback.
- **Limits:** GET, redirects followed by hand (at most 5, each hop vetted), 5 seconds per
  request, 8 in parallel, 10 seconds for the whole plan; a URL not checked in time is `unknown`.
  The check never delays the plan by more than that.
- **Safety (the URLs come from untrusted web content):** http and https only; the host is
  resolved and every address must be public (no private, loopback, link-local, CGNAT, multicast,
  reserved, IPv6 unique-local or IPv4-mapped private ranges); the request connects to the vetted
  address so a second DNS answer cannot swap it; the same checks on every redirect hop; no
  cookies, no credentials, no proxy from the environment. An honest User-Agent naming Atlas and
  its site, no personal data.
- **Never** rejects the plan or sends anything back to the coordinator: resubmitting the plan
  would cost more than the problem.
- **Stored** as a new column `plans.link_health` (jsonb, the link check PR's own migration):
  `{url: {status, http_status, reason, fallback, checked_at}}`.
- **Logs:** one `link_check` line per plan with the counts per verdict; per dead URL its host and
  reason.

### What the user sees

`PlanDetail` exposes `link_health` (not `link_checks`: `LinkCheck` already names the
allowlist verdict in `routes.py`). The web, wherever a plan URL is drawn (`itinerary.tsx` stop
pages, `bookings.tsx` booking buttons and price sources, the alternatives):

- `ok` or `unknown`: the link as today.
- `dead` with a fallback: the link points to the homepage, labelled "Sito di <host without
  www>". A booking button keeps "Prenota su <provider>" and points to the homepage, but only when
  the homepage itself passes `links.check_link` (Google Flights' homepage does not: its allowlist
  entry requires the `/travel/flights` path); otherwise it is treated as dead without a
  fallback.
- `dead` without a fallback: the plain text "Pagina non trovata" where the link was; no link, no
  button.

`mapping.plan_to_trip` (the TripTracker export) uses the fallback for `Stop.url` and, when it
passes the allowlist, for `Booking.url`, and drops a dead URL without one.

Contract rule 4 still holds: the fallback is derived by code from the agent's own URL (its
scheme and host), never written by hand, and booking links still pass the allowlist.

### The root cause, in the prompts

`agents/transport.md` and `agents/activities.md` gain one rule: a price's `source_url`, and any
page URL in the result file, is a page the agent opened with `web_fetch` or a URL it saw as a
search result, copied exactly; never one composed from a site's structure. A fare read in a
search snippet cites that result's URL. The coordinator only copies, as today.

### Evals

`evals/checks.py` gains `dead_links`: the number of `dead` URLs in the stored `link_health`,
reported in the eval history. It does not fail a run at first. Michele approved (2026-10-18) one
paid evals run right after PR 1 is merged, before any prompt change, so the count has a
starting point; PR 4's run then shows the prompt rule's effect.

### Later, not now

An agent that judges whether an existing page is the right one (relevance, beyond "it exists").

## 4. Delivery

Contract rule 7 says backend, then agents, then web. The choice cards add one constraint: the web
must be able to show a choice **before** the agents start asking, or a user would wait five
minutes in front of a screen with nothing to click. The order:

| PR | Content | Agents changed |
| --- | --- | --- |
| 1. Link check | backend (checker, consumer hook, migration, `PlanDetail`, mapping), web rendering, `dead_links` eval check | no |
| 2. Backend for choices and mode | `journey_mode` accepted, the `ChoiceRequest` model and `schema/ask_traveller.json`, `ask_traveller` handling, `choices` table and migration, endpoint, events, photo resolver, Settings, the demo scenario and fake-client support, evals answering choices. It must not change `profiles/**`, `skills/**` or `backend/app/plan.py`: those paths trigger the paid `evals.yml` and, on merge, a production `ant apply` | no |
| 3. Web: choice cards | the panel on the live screen, the gallery entries, `/demo` with a pause | no |
| 4. Agents | coordinator (`ask_traveller` in its tools, rendered into `profiles/**`; the pauses, the destination pick, the mode rules), transport (train, coach, ferry, car journeys; the source rule), activities (the source rule), `TransferMode` `car` with the regenerated skill schema (the backend only logs result-file problems, so the two can ship together); the existing eval requests keep no mode | yes: one paid evals run |
| 5. Web: mode in the form | the choice row, the summaries | no |

PR 5 merges after PR 4 is deployed to production, so a chosen mode is never ignored. PRs 1 and 2
both touch `consumer.py` and each adds a migration: they go in sequence, 1 first.

## 5. Working alongside the parallel branches

Other work is in flight. On 2026-10-18 the open branches touching nearby files were:

- `feature/atlas-quotas`: `request-form.tsx`, `failure.ts`, `schema/request.json`,
  `plan-screen.tsx`, `routes.py`, `sessions.py`, `db.py`, a migration.
- `feature/atlas-waitlist`, `feature/atlas-auth-switch`: `auth.py`, `config.py`, `db.py`,
  `routes.py`, `sessions.py`, migrations.
- `fix/date-pair-compact-zone`: `booking-strip.tsx`, `date-pair.tsx`, `PlanView.tsx`.

Rules for every PR of this work:

- Branch from the latest `origin/main`; fetch and merge `origin/main` at the start of each task
  and again before opening or updating the PR.
- A migration's `down_revision` is the head of `origin/main` at merge time; when another
  migration lands first, re-point ours (still one migration per PR).
- Generated files are regenerated after every merge, never hand-merged: `schema/*.json`
  (`app.schemas`), `profiles/**` (`render_profiles.py`), `web/lib/schemas/generated/*.ts`
  (`gen:schemas`), the web's backend fixtures (`gen-backend-fixtures.py`).

## 6. Testing

- Offline, as `CLAUDE.md` requires: the fake Managed Agents client with new scenarios
  (`ask_traveller` answered by the traveller, skipped, timed out under time-machine, a restart
  with a pending choice, an invalid input, a fourth pause refused, an interrupt while waiting);
  the link checker under respx (404, 410, soft 404, 403 as unknown, timeout, a host that does not
  exist, a redirect to a private address refused, a homepage fallback alive and dead).
- Web (vitest): the choice panel's states, the countdown, the reducer's pending choice, the link
  rendering for each verdict, the mode row and the summaries.
- In the browser before merge: 393 px and desktop, light and dark; impeccable critique at 32/40
  or more with no open P0 or P1.
- **Live probe P14** (paid; Michele approved one run, under 1 $, on 2026-10-18; P1 to P13 are
  taken; add it to `scripts/probe_session.py` and the notes' §4), run **before PR 2 is built**,
  so the interrupt flow and the pause timing are designed on facts: while the coordinator waits on a custom tool, do running subagent threads keep
  working? Does `user.interrupt` work while the session is idle on `requires_action`?

## 7. Goals, non-goals, anti-goals

Goals: the three features above, in Atlas's design language, with the demo showing the cards.

Non-goals: chatting with the agents; editing a finished plan with cards; marking the picked
stops in the finished plan ("Scelta tua", later: it needs a Plan contract change); push or email
notifications when a choice waits; a ferry booking provider; an agent reviewing links; checking
links again after delivery.

Anti-goals (a failure even if it works):

- a plan that stalls or fails because the user stepped away;
- an error page because of the travel mode;
- cards that show an invented link or an invented photo;
- amber on the clock, or anything that looks like a template made by AI (the No AI Chrome Rule);
- a plan rewritten by the coordinator because of links (cost).

## 8. Left to the builder

The component structure and names in `web/`; where the photo credit sits on a card; how the
reducer stores choices; the exact soft-404 title patterns; whether the demo's pauses extend
`happy_path` or live in a new scenario; the `app.cli run` flag's name; the photo cache's table.
