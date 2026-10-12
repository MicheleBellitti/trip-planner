# scripts/

Agents as code: render the per-profile agent files, apply them without the `ant` CLI, and run
the live probes. Run everything from `backend/` with `uv run` (the backend venv has anthropic
1.13.0, httpx2, PyYAML and jsonschema).

| Script | What it does | Network |
|---|---|---|
| `render_profiles.py` | Renders `profiles/<profile>/**` from the templates in `agents/` and copies `schema/results/*.json` into `skills/travel-research-rules/schemas/`. `--check` fails on anything stale. | none |
| `bootstrap.py` | The SDK equivalent of `ant apply --lock-file backend/claude-lock.<profile>.json profiles/<profile>`: uploads skills, creates or updates the environment and the agents, writes ant's lockfile. | `--dry-run`: none |
| `probe_session.py` | The live probe checklist P1..P13 of `docs/managed-agents-notes.md` §4, on the development profile, with a report in `docs/probes/<date>.md`. **Spends money.** | `--dry-run`: none |
| `session_report.py` | Read-only report on what fills the context of one or more sessions (events of the session and of every thread: requests, context per request, biggest tool results, skill loads, messages), and `--static`: the fixed context of each agent from `profiles/`, `skills/` and `submit_plan.json`. Also the by-hand workflow `session-report.yml`. | `--static`, `--from-raw`: none |

## Changing a prompt, a model or a number

`profiles/**` is generated: never edit it by hand.

- Prompts and agent settings: `agents/<name>.md` (coordinator, flights, lodging, activities,
  transport). The frontmatter is the `POST /v1/agents` body in the format `ant apply` reads;
  the Markdown body is the system prompt. Relative paths (`./tools/submit_plan.json`,
  `./flights.md`, `../../../skills/<name>`) are written as seen from the rendered file in
  `profiles/<profile>/agents/`. Lines starting with `#!` are template notes and are dropped.
- Models and numbers per profile: `agents/profiles.yaml` (models, session budget, web search
  cap, follow-ups). Templates use `{{ key }}`; only models and numbers differ between
  profiles, so a prompt change always reaches both.
- The environment: `agents/environment.yaml` (cloud, unrestricted networking: see the comment
  there and notes D4).
- `submit_plan`: generated from `schema/plan.json` with every `$ref` inlined. When the Plan
  model changes, run `uv run python -m app.schemas` first, then render.

```sh
uv run python ../scripts/render_profiles.py          # write profiles/** and the skill schemas
uv run python ../scripts/render_profiles.py --check  # CI: exit 1 when something is stale
```

Commit the templates and the rendered files together.

## Applying a profile

With the `ant` CLI (preferred once installed), from the repository root:

```sh
ant apply --lock-file backend/claude-lock.development.json profiles/development
```

Never point `ant apply` at the repository root or at `agents/`: the templates sit in a
directory named `agents/` and would be read as agents.

Without `ant`, `bootstrap.py` does the same work with the SDK, from `backend/`:

```sh
uv run python ../scripts/bootstrap.py --profile development --dry-run   # plan + payloads, no network
uv run python ../scripts/bootstrap.py --profile development             # plan against the server
uv run python ../scripts/bootstrap.py --profile development --yes       # apply
uv run python ../scripts/bootstrap.py --profile production --i-know-this-is-production --yes
```

- `--profile` is required; `production` is refused without `--i-know-this-is-production`, dry
  runs included. It builds `anthropic.Anthropic()`, so it uses `ANTHROPIC_API_KEY` when set (the
  setup for an Individual Organization, docs/deploy.md), else Workload Identity Federation from
  the environment (`ANTHROPIC_IDENTITY_TOKEN_FILE`, `ANTHROPIC_FEDERATION_RULE_ID`,
  `ANTHROPIC_ORGANIZATION_ID`, optional `ANTHROPIC_WORKSPACE_ID`); either must belong to the
  profile's workspace.
  Production applies belong in `deploy-agents.yml` (CLAUDE.md: never use production
  credentials locally).
- It refuses to run when `profiles/` is stale, when the lockfile belongs to another
  organization or workspace, and when a tracked resource changed outside the files (the server
  reports a different version) or disappeared, unless `--force`.
- Order: skills, the environment, the subagents, then the coordinator, so the coordinator pins
  the subagent versions just written. A path reference becomes `{type: agent, id, version}` or
  `{type: custom, skill_id, version}`; `{path: ..., version: latest}` leaves it unpinned.
- The lockfile (`backend/claude-lock.<profile>.json`) is saved after every write, in ant's
  exact format (`version`, `origin`, `resources` keyed by path; `kind`, `id`, `version`,
  `hash`, `remote_hash`), so `ant` can take over and `backend/app/lockfile.py` reads it.
- Skill uploads skip what `ant` skips (dotfiles, `__pycache__`, `.venv`, `node_modules`,
  `dist`, `build`, symlinks) and the skills' tests (`test_*.py`, `*_test.py`, `conftest.py`,
  `tests/`). `ant` uploads the tests, so its first apply after bootstrap makes one new version
  of each skill that has tests.
- Lockfile keys are relative to the lockfile's directory, as `ant` v1.40.0 writes them
  (`../profiles/<profile>/...` and `../skills/<name>` for a lockfile in `backend/`), and the
  backend reads them that way. Entries an earlier bootstrap.py keyed from the repository root
  (`./profiles/...`, `./skills/...`) are rewritten to ant's keys on the next run that writes
  the lockfile (the dry run shows them as `rekey`), instead of being created again.
- Not implemented (use `ant` for these): `--prune`, URL-sourced skills, kinds other than
  skill, environment and agent, and ant's "the file changed into what the server already has"
  no-op.

## Live probes

Only by hand, on the development key (`ANTHROPIC_API_KEY`, or the federation variables when the
organization has them), never in CI. Each session is capped at the development
session budget (60 US cents; P9 uses 3), no new session starts past `--max-total-cents`
(default 150), and every resource it creates (`probe-<stamp>-...`) is removed at the end.

```sh
uv run python ../scripts/probe_session.py --dry-run          # the plan, no network
uv run python ../scripts/probe_session.py --yes              # all probes
uv run python ../scripts/probe_session.py --yes --only P4,P5
```

The report goes to `docs/probes/<date>.md` and records only tool names, event types, ids,
statuses and hostnames. The raw SSE log goes to the system temp directory (`--sse-log` to
change it) and never into the repository: it carries web page text. P12 runs `ant apply
--dry-run` only when `ant` is already installed.

## Tests and checks

Offline only: the SDK runs over `httpx2.MockTransport` against an in-memory API, credentials
are blanked and `ANTHROPIC_BASE_URL` points at a closed port.

```sh
uv run pytest ../scripts -q
uv run ruff check --config pyproject.toml ../scripts
uv run ruff format --config pyproject.toml --check ../scripts
uv run pyright -p ../scripts
```

## Where the context goes: `session_report.py`

```sh
uv run python ../scripts/session_report.py --static                    # fixed context per agent, no API
uv run python ../scripts/session_report.py --session sesn_... sesn_... --out report.md
uv run python ../scripts/session_report.py --session sesn_... --save-raw /tmp/raw   # keep the events
uv run python ../scripts/session_report.py --session sesn_... --from-raw /tmp/raw   # offline re-run
```

It only reads (GET listings and one retrieve; costs nothing), with the SDK's own credentials, and
never prints a key. Sizes are characters of event content and tokens are chars / 4. A tool result
costs its size times the model requests that come after it ("tokens carried"). `--save-raw` stores
page text: keep that directory out of the repository. The report goes to `--out` (default
`session-report.md` in the system temp directory) and to stdout; `--no-history` drops the event
list. In CI: Actions > session-report > Run workflow.
