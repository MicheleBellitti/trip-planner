# Atlas, the Trip Planner web app

The web frontend of the trip planner. Next.js 16 (App Router, Cache Components), TypeScript
strict, Tailwind 4, Zod 4 (`zod/mini`). It talks only to the planner backend (`backend/`), with
the TripTracker session cookie (`credentials: "include"`, `EventSource(..., { withCredentials:
true })`). The product is called Atlas on screen (`lib/brand.ts`); every string the user reads is
Italian, everything else is English.

What it is: a request form, a list of plans, and the page of one plan. While a plan runs the page
draws the five agents as a transit line diagram (direction 1, "Linee"), live, over SSE; when the
plan is ready it shows the finished trip with every booking's two dates ("Prenota entro",
"Quando") and a hand-off to TripTracker. The design authority is [DESIGN.md](DESIGN.md) (tokens),
the product decisions are in [PRODUCT.md](PRODUCT.md), the rules are in `../CLAUDE.md` ("UI rules").

## Run it

```sh
cp .env.example .env.local     # see "Environment variables"
npm ci
npm run dev                    # http://localhost:3000
```

### Against the offline demo backend (free, no API key, no network)

The backend can replay a scripted Managed Agents session (`DEMO_MODE`, `../CLAUDE.md` "Local
demo"), so the whole UI, SSE included, runs without spending anything. From `backend/`, with
Postgres up and migrated (`uv run alembic upgrade head`):

```sh
ENVIRONMENT=development AUTH_MODE=local DEMO_MODE=true DEMO_PACE=0.5 \
  PLANNER_ALLOWED_EMAILS=michele@example.com FRONTEND_ORIGIN=http://localhost:3000 \
  uv run uvicorn app.main:app --port 8000
```

`DEMO_PACE` scales the recorded gaps (1.0: `happy_path` takes about 75 s, 0.5 about 40 s). With
`NEXT_PUBLIC_API_URL=http://localhost:8000` in `.env.local` the app needs no login (`AUTH_MODE=local`).
Pick a scenario with `NEXT_PUBLIC_DEMO_SCENARIOS` (the form then shows a "Scenario demo" select), or
create a plan by hand and open it:

```sh
curl -s -X POST 'http://localhost:8000/plans?demo_scenario=budget_reached' \
  -H 'Origin: http://localhost:3000' -H 'Content-Type: application/json' \
  -d '{"origin":"Milano","destination":"Lisbona","dates":{"exact_start":"2027-04-14","exact_end":"2027-04-18"},"travelers":[{"kind":"adult"},{"kind":"adult"},{"kind":"child","age":8}],"budget_eur":2400}'
# -> {"id":"<id>"}: open http://localhost:3000/plans/<id>
```

The scenarios are the `.jsonl` files in `../backend/tests/fixtures/ma/`: `happy_path` (ready),
`rejected_then_accepted`, `three_rejections_failed` (failed), `budget_reached` (budget paused),
`requires_action_blocked` (blocked), `interrupt`, `mcp_failure` (a source that did not answer),
`end_turn_without_plan`, `unknown_event_type`, and the rest. They cover every state the plan page
draws. In development there are two more pages: `/dev/ui` (the gallery of `components/ui/`, every
variant and state, light and dark) and `/dev/plan` (the finished plan on saved demo data;
`?scenario=happy|kiwi|edge|fetch|failed`, or `?plan=<id>` for a plan of the running backend). Both
answer 404 in a production build.

## Environment variables

Read through `lib/config.ts`. `NEXT_PUBLIC_*` values are inlined into the browser bundle at build
time and are public: never put a secret in them. Details and the reason for each are in
[.env.example](.env.example).

| Variable | Used for |
|---|---|
| `NEXT_PUBLIC_API_URL` | The planner backend: every fetch and the SSE stream. Its `FRONTEND_ORIGIN` must be this app's origin. |
| `NEXT_PUBLIC_TRIPTRACKER_URL` | "Apri in TripTracker" (`/import?plan=<id>`) and, in `triptracker` mode, the login redirect on a 401. |
| `NEXT_PUBLIC_AUTH_MODE` | `atlas` (a 401 goes to this app's `/login`) or `triptracker` (TripTracker's `/accedi`); the backend's `AUTH_MODE`. Empty: `atlas` under `next dev`, `triptracker` otherwise. |
| `NEXT_PUBLIC_DEMO_SCENARIOS` | Development only: comma list of scenarios for the form's demo select. Never shown in production. |
| `NEXT_DIST_DIR` | Not an app setting: where `next build` writes (default `.next`). Set it (`.next-build`) to build without touching the output of a running `next dev`. |

The app's own accounts (`lib/auth.ts`, Better Auth: magic link by email and Google, no passwords)
read server-only variables, documented in the "Accounts" section of `.env.example`: `DATABASE_URL`
(the backend's Postgres, whose Alembic migrations create the `users`, `auth_sessions`,
`auth_accounts` and `auth_verifications` tables), `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL`,
`AUTH_COOKIE_DOMAIN`, `AUTH_ALLOWED_EMAILS` (who may sign up), `RESEND_API_KEY` and
`AUTH_EMAIL_FROM` (the sign-in email; unset in development, the link is printed to the server
console), `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Without `DATABASE_URL` the login page
says the accounts are not configured and everything else works.

## Commands

```sh
npm run lint                   # eslint (next core-web-vitals + typescript)
npm run typecheck              # tsc --noEmit
npm test                       # vitest run (jsdom, offline): units, components, tokens + contrast
npm run build                  # next build (NEXT_DIST_DIR=.next-build to keep the dev output)
npm run measure:js             # first-load JS per route (gzip + brotli) of the last build
npm run gen:schemas            # regenerate lib/schemas/generated from ../schema/*.json
npm run gen:schemas -- --check # fail if the generated schemas are stale (CI)
```

CI (`ci-web.yml`) runs `gen:schemas --check`, lint, typecheck, test and build; `ci-backend.yml` runs
`gen-backend-fixtures.py --check`.

## Structure

```
app/                       routes: / (landing, public), /plans (plans), /new (request form), /plans/[id] (live + finished plan),
                           /dev/ui and /dev/plan (development only), not-found.tsx
components/ui/             the design system's primitives (Button, Chip, Timeline, DatePair, CostMeter,
                           Disclosure, Field, Notice, Sheet, Toast, ...) and the tokens' tests
components/live/           the running plan: PlanScreen (data + states), LiveHeader (sticky bar), AgentLanes
                           and AgentLane (the transit lines), stations (reducer state -> lane stations),
                           InterruptControl, StreamStatus, RunSection
components/plan/           the finished plan: PlanView, PlanSummary, Itinerary, Bookings, BookingStrip,
                           plan-model (pure helpers), trip-dates (Italian calendar words)
components/states/         the states that need words: budget paused, ended (failed, blocked, interrupted),
                           session expired, load failed, the skeleton; `panels.tsx` is their lazy chunk
components/home/           the plan list ("Plan rail"), empty invitation, site header
components/request/        the request form: model, validation, summary, trip outline, failure copy
lib/api.ts                 typed backend client: errors, 401 -> the login (this app's or TripTracker's), 429, 503
lib/auth.ts                the app's own accounts: Better Auth server (Postgres, magic link, Google, invitations)
lib/auth-client.ts         its browser client; lib/auth-policy.ts the sign-up allowlist; lib/return-to.ts
lib/me.ts                  GET /me: whether the signed-in user manages the planner (the header's "Collaudi", "Inviti")
lib/waitlist-policy.ts     the waitlist's rules (pure); lib/invitation-email.ts the invitation
lib/server/                server-only: the accounts' configuration, the shared pg pool, the waitlist queries,
                           the emails through Resend (sign-in link, invitation), the admin check (GET /me)
app/actions/waitlist.ts    server actions: join the waitlist (public), invite (admins)
components/auth/           the login form and the signed-out header; app/login the page
components/waitlist/       the waitlist form and its one answer (the landing's closing, the login's sent state)
components/admin/          the invitations page's body; app/admin/waitlist the page (admins only)
lib/request-form.ts        form metadata from schema/request.json + validation (Italian)
lib/plan-events/           usePlanEvents (SSE), the timeline reducer, labels, detail keys, virtualization
lib/schemas/generated/     Zod schemas + types generated from ../schema (never edit by hand)
lib/schemas/api.ts         response shapes hand-written from backend/app/routes.py
scripts/gen-schemas.mts    the JSON Schema -> Zod (`zod/mini`) generator
scripts/measure-js.mts     first-load JS from a finished build
scripts/gen-backend-fixtures.py   timeline fixtures made by the backend's normalizer (Python)
design/directions/         the three static design studies; direction 1 "Linee" was chosen
.impeccable/critique/      the design critique reports, round by round (below)
```

When the contract changes: `uv run python -m app.schemas` in `backend/`, then `npm run gen:schemas`
here, and commit both. The UI event's `detail` keys the timeline reads are listed in
`lib/plan-events/detail.ts`; they are the backend's (`backend/app/events.py`).
`lib/plan-events/__fixtures__/backend/` holds real events from the backend's normalizer: after a
change to the backend's UI events, regenerate them from `backend/` with
`uv run python ../web/scripts/gen-backend-fixtures.py` (ci-backend runs it with `--check`).

## JS budget

The spec's budget is 180 KB gzip of first-load JavaScript on `/plans/[id]`. Turbopack prints no
sizes, so measure the build itself:

```sh
NEXT_DIST_DIR=.next-build npm run build
NEXT_DIST_DIR=.next-build npm run measure:js            # add --chunks to list them, --budget 180 to gate
```

`scripts/measure-js.mts` adds the root main files (React, the Next client runtime, the Turbopack
runtime: about 132 KB gzip, the floor of every route) to the chunks the page references in its
client reference manifest. Polyfills are nomodule and never counted. What keeps `/plans/[id]` small:

- `lib/schemas` use `zod/mini` (the generator emits it): the classic `zod` entry cost about 35 KB gzip
  here, `zod/mini` about 17 KB (its core is the rest).
- The finished plan (`PlanView`) and the state panels (`components/states/panels.tsx`) are lazy chunks:
  a running plan never needs them. `PlanScreen` warms them when the browser is idle.
- `plan-screen` imports `trip-dates`, not the whole of `plan-model`, and `isEndedStatus` from
  `ended-status`, so nothing heavy rides in on a one-line helper.

Measured on 2026-10-12: 213.0 KB before, 189.1 KB after (gzip), 163.9 KB in brotli (what Vercel
serves). `/` is 172.3 KB and `/new` 174.7 KB. What remains above 180 is zod's core (validating every
SSE event is a contract rule) on top of the framework floor: closing the last 9 KB would take
validating without zod, or a plain `<a>` instead of `next/link` (about 4 KB, and the home link would
lose client-side navigation). Neither is worth it, so treat 190 KB gzip as this page's real budget and
`--budget 190` as its gate until the spec's 180 is revisited.

Re-measured on 2026-10-14 for the brand restyle (step 1): `/plans/[id]` was 190.4 KB gzip at the
branch's start (the features merged since 2026-10-12) and is 192.2 KB after it, 166.9 KB in brotli.
The difference is the app header's nav on the live screen (about 1 KB) and the mark in the lockup. To
keep it there, the compact `AppHeaderBar` imports no theme toggle (the control bar already ships one)
and the plan page's error boundary shows the lockup alone. `/` is 176.3 KB and `/new` 176.6 KB. The
page is above the 190 gate: decide on the gate before tightening anything else.

Re-measured on 2026-10-17 for the front door (step 2): `/` is now the public landing at 140.0 KB gzip
(the list moved to `/plans`, 176.5 KB); `/plans/[id]` is 192.4 KB, unchanged from the branch's start
(the eval history, PR #3, had added 0.2 KB). The landing skip's script strings live in
`lib/skip-landing.ts`, so the API client carries only the mark's two functions.

Re-measured on 2026-10-17 for the step 1 polish, at the branch's last commit: `/plans/[id]` is
192.8 KB (+0.4: the theme swap's transition guard, the small mark's geometry and the header line's
fixed overhang), `/` 140.3, `/plans` 176.9, `/new` 177.1, `/evals/[id]` 186.7 (+1.2, ungated: its
error boundary's chunk now carries its own copy of the theme toggle and the mark). Turbopack keeps every export of a module a page loads, so code only
some pages need lives apart: the path builders in `lib/page-paths.ts`, the mark's geometry in
`lib/mark-geometry.ts` (not `lib/brand-mark.ts`), the tagline's line break in
`lib/tagline-lines.ts`.

## Accessibility

Built to WCAG 2.2 AA; checked by hand in the browser on every screen at 393 and 1440 px, light and
dark (the last pass is in `.impeccable/critique/audit-finish.md`).

- **Contrast** is measured, not eyeballed: `components/ui/tokens.test.ts` re-measures every text and
  ring pair of DESIGN.md on every `npm test`, and the audit script measured the real rendered pairs.
- **Keyboard**: one linear tab order (home, interrupt, theme, lanes); a 2 px focus ring with a 3 px offset
  in `--focus`; closed lanes are `inert`; `scroll-padding-top` follows the sticky bar and lane heads
  (LiveHeader and AgentLanes publish `--live-bar-h` and `--live-heads-h`), so a focused control is never
  left under them.
- **Targets** are 44 px under a finger (`pointer-coarse`) and 24 px at least with a mouse; the 1 px
  radio inputs of the segmented fields are covered by their 40 px labels.
- **Live region**: the plan page has one polite region. It speaks lane state changes ("Voli: finito") and the
  plan's own new state ("Piano: budget raggiunto"), never tool calls and never the replayed history.
- **Names and structure**: one `h1`, `h2` per section, `h3` per lane, `role="meter"` with words for the cost,
  `lang="en"` on the agents' English text, links that open a new tab say so for screen readers.
- **Motion**: every animation has a `motion-reduce` alternative that keeps the state change (a fade
  instead of a slide, an instant caret); nothing blocks on it.

## Design critique reports

`.impeccable/critique/` keeps the impeccable critiques (a screen merges at 32/40 or more with no open P0
or P1, `../CLAUDE.md`):

| Screen | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| Live plan page (running, budget paused, failed, blocked, interrupted): `live-round<N>.md` | 28 | 31 | 32 |
| Finished plan (ready): `plan-round<N>.md` | 30 | 31 | 32 |
| Home and request form: `home-form-round<N>.md` | 29 | 32 | 32 (one P1, fixed since) |

`audit-finish.md` is the technical audit that closed the work (accessibility, performance, theming,
responsive).
