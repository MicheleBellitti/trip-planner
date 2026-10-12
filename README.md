# Trip Planner

Trip Planner (on screen: **Atlas**) turns a trip request (origin, destination or "suggeriscimi
tu", dates, travellers, budget, preferences) into a complete, bookable plan. A Managed Agents
session runs a coordinator and four subagents (flights, lodging, activities, transport). You
watch them work live, and the finished trip opens in TripTracker with one click. Booking and
payment always happen on the supplier's site.

The full spec (Italian) is in [`docs/spec/implementation-doc.it.md`](docs/spec/implementation-doc.it.md).
Conventions, commands and rules for contributors (human or Claude) are in [`CLAUDE.md`](CLAUDE.md);
the deploy runbook is [`docs/deploy.md`](docs/deploy.md).

## Layout

| Path | What |
| --- | --- |
| `backend/` | FastAPI API, Postgres via SQLAlchemy/Alembic, the Managed Agents consumer (Python 3.12, uv) |
| `web/` | Next.js 16 planner UI: request form, live timeline, finished plan |
| `agents/` | Agent prompt templates and per-profile models and numbers |
| `profiles/` | The files `ant apply` reads, generated from `agents/` by `scripts/render_profiles.py` |
| `skills/` | Agent skills shared by both profiles (Trip schema, booking links, research rules) |
| `scripts/` | Profile rendering, an SDK fallback for `ant apply`, the paid live probes |
| `evals/` | Reference requests, checks, LLM judge, baseline comparison |
| `schema/` | JSON Schemas generated from the backend models |
| `docs/` | Spec, research notes, backend interfaces, deploy runbook, TripTracker patch |

## Quick start

You need [uv](https://docs.astral.sh/uv/), Node 24 and either Docker or a local PostgreSQL.

```sh
docker compose up -d                 # Postgres 16 on localhost:5432

cd backend
cp .env.example .env                 # development settings, local auth, no API key
uv sync
uv run alembic upgrade head
export TEST_DATABASE_URL=postgresql+asyncpg://trip_planner:trip_planner@localhost:5432/trip_planner_test
uv run pytest                        # creates and migrates trip_planner_test by itself
```

With a local Homebrew Postgres instead of Docker, set `DATABASE_URL` in `backend/.env` to
`postgresql://localhost:5432/trip_planner_dev` (create the database first) and leave
`TEST_DATABASE_URL` unset.

### Offline demo

The demo replays recorded agent sessions through the real backend and web app: no API key, no
network, no cost.

```sh
# terminal 1, in backend/
DEMO_MODE=true uv run uvicorn app.main:app --reload   # http://localhost:8000/health

# terminal 2, in web/
cp .env.example .env.local
npm ci && npm run dev                                 # http://localhost:3000
```

Every plan you create replays `happy_path`, about 75 seconds long. `DEMO_PACE=0.2` makes it five
times faster. To see another plan state, call the API with a scenario name, for example
`budget_reached` (it waits for "Continua") or `three_rejections_failed`:

```sh
curl -X POST 'http://localhost:8000/plans?demo_scenario=budget_reached' \
  -H 'Origin: http://localhost:3000' -H 'Content-Type: application/json' \
  -d '{"origin":"Milano","destination":"Lisbona","dates":{"exact_start":"2027-04-14","exact_end":"2027-04-18"},"travelers":[{"kind":"adult"},{"kind":"adult"}],"budget_eur":1500}'
```

Then open `http://localhost:3000/plans/<id>`. An unknown name answers 422 with the list of
scenarios. The agents' events come from the recording, whatever the request says.

Tests and the demo run offline. They never contact Anthropic or the travel MCP servers. A real
plan needs the development API key and an applied agent profile (`docs/deploy.md`, step 7).
