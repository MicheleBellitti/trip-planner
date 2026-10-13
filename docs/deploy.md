# Deploy runbook

Michele's infrastructure checklist, in the order to do it, plus how releases flow once
everything is in place. The spec sections are "Deploy e configurazione" and "CI/CD e
operatività" (`docs/spec/implementation-doc.it.md`). Verified research overrides the spec:
`docs/managed-agents-notes.md` (cited as "notes §x") for `ant`, lockfiles and networking.

| Where | What runs | Domain | Deploys when |
|---|---|---|---|
| Railway, service `backend` | FastAPI (`backend/Dockerfile`), one process, one replica | `atlas.api.bellittim.com` | every push to `main` that touches `backend/` |
| Railway, service `cleanup` | same image, `python -m app.jobs cleanup` | none | same; runs nightly on a cron |
| Railway, `Postgres` | plans, events, fx_rates | private network only | never (managed) |
| Vercel, new project | Next.js app in `web/` | `atlas.bellittim.com` | preview per PR, production on `main` |
| Vercel, existing project | TripTracker | `viaggi.bellittim.com` | unchanged; three variables to set (step 6) |
| Anthropic | agents, environment, skills (two workspaces) | n/a | `ant apply`: evals on PRs, `deploy-agents.yml` for production |

The files that encode this setup:

| File | Role |
|---|---|
| `.github/workflows/ci-backend.yml` | PR checks for Python: ruff (backend, scripts, evals, and skills at Python 3.10), pyright, pytest on Postgres 16, generated-file freshness (including the web's timeline fixtures, made by the backend's normalizer), skill/script/eval tests, actionlint and the Anthropic-credentials guard (`.github/scripts/check_anthropic_credentials.py`, with a self-test: nothing production in PR workflows, the key only through the auth action, always inside a GitHub environment) |
| `.github/workflows/ci-web.yml` | PR checks for `web/`: generated schemas, eslint, tsc, vitest, next build |
| `.github/workflows/evals.yml` | paid evals of the development profile on PRs that change agents, skills or `plan.py` |
| `.github/workflows/deploy-agents.yml` | after merge: evals again, Michele's approval, `ant apply` of production, lockfile commit |
| `.github/actions/setup-ant/action.yml` | installs the pinned `ant` release (v1.40.0, sha256-checked) for both agent workflows |
| `.github/actions/anthropic-auth/` | `action.yml` + `mint-token.sh`: dual-mode Anthropic login. Federation when the environment variables are set (mints the GitHub OIDC token, exports the variables the SDK and `ant` read), otherwise the environment secret `ANTHROPIC_API_KEY` (masked, exported); see "Anthropic credentials in CI" |
| `.github/scripts/check_anthropic_credentials.py` | the guard `ci-backend.yml` runs over `.github/`, and its `--self-test` |
| `.github/workflows/anthropic-auth-check.yml` | by hand: smoke test of the credentials per environment, in either mode (prints the mode, lists one model; no cost) |
| `backend/Dockerfile`, `backend/.dockerignore` | the backend image (uv, Python 3.12 slim, non-root, uvicorn on `$PORT`); it ships `backend/pinned/trip.schema.json` and fails the build without it |
| `backend/railway.json`, `backend/railway.cron.json` | the two Railway services' settings, as reviewed code (read the warning in step 3) |

When each step happens, following the spec's four-day plan: steps 1-3 and 8 on day 1 (the
probe first thing: it is the project's main risk), the Railway variables and the first backend
deploy on day 2, step 5 on day 3, steps 6 and the production half of 7 on day 4.

---

## 1. Anthropic Console

1. **Two workspaces** (Settings > Workspaces > Create): `trip-planner-development` and
   `trip-planner-production`. A lockfile is bound to the workspace of the key that wrote it,
   and `ant apply` refuses a key from another workspace (notes §2h). Separate workspaces also
   give separate spend limits and keep the per-workspace unique names (environments) apart.

   > **Individual Organization (Michele's account, found 2026-10-12).** Workspaces cannot be
   > created (the workspaces endpoints answer 403), so there is one workspace, the default.
   > The setup below still works with it: one lockfile per profile (notes §2h) holds either
   > way, and the environments already have distinct names per profile
   > (`trip-planner-development`, `trip-planner-production`). What is lost is isolation: a
   > development key can see and act on the production agents and sessions, and spend limits
   > exist only for the organization. The protections that remain are the GitHub environments
   > (the production key reaches only `main` jobs that you approve), Railway (the production
   > key never leaves it) and your discipline with the keys (CLAUDE.md).
2. **API keys**, each created inside its workspace (Settings > API keys). One key per place,
   so any one can be revoked without touching the others:

   | Key | Workspace | Stored in | Used by |
   |---|---|---|---|
   | dev, laptop | development | `backend/.env` (gitignored) | local backend, `app.cli run`, evals by hand, the probe, the first development apply |
   | prod, Railway | production | Railway `ANTHROPIC_API_KEY` (sealed) | real plans, the nightly cleanup |
   | dev, GitHub | development | secret `ANTHROPIC_API_KEY` of the GitHub environment `development` | `evals.yml`, `anthropic-auth-check.yml` |
   | prod, GitHub | production | secret `ANTHROPIC_API_KEY` of the GitHub environment `production` | the `deploy-agents.yml` apply and production evals |

   Four keys, so any one can be revoked without touching the others. The two GitHub keys are
   separate from the laptop and Railway ones (a key stored in GitHub is a key GitHub can
   read). A production key never goes on a laptop (CLAUDE.md), so every production apply and
   the production eval run happen in GitHub Actions. When your organization supports Workload
   Identity Federation, item 4 replaces the two GitHub keys.
3. **Spend limits and alerts.**
   - Organization: Settings > Billing > Spend limits > Set limit (a monthly cap below the
     tier's cap).
   - Each workspace: Settings > Workspaces > select it > Spend limits. Set the monthly cap and
     email alerts at **50%** and **80%**. Add the same 50/80 alerts on the Billing page if it
     offers them for the organization.
   - Suggested caps: production a little above the planner's own `MONTHLY_LIMIT_CENTS` (5000 =
     $50), for example $60, so the planner refuses new plans first (HTTP 429 with an Italian
     message) and the workspace cap stays the hard stop. Development about $40: one eval run
     costs up to $6.00 (five sessions at 100 cents plus at most $1 of judge), a manual plan up
     to $1.00. The organization cap is the sum.
   - At a cap you set, the API answers HTTP 400 `invalid_request_error` ("You have reached
     your specified ... API usage limits"); new sessions then fail to start.
4. **CI access.** Read "Anthropic credentials in CI" right below: today two API keys (the two
   GitHub rows above), later Workload Identity Federation.

### Anthropic credentials in CI

**Current setup: an API key per GitHub environment** (the only option for an Individual
Organization).

**Finding of 2026-10-12.** Michele's Anthropic organization is an *Individual Organization*.
Probed with the SDK from his laptop: the federation admin endpoints (issuers, rules, service
accounts) answer **404**, and the workspaces and API-keys admin endpoints answer **403**. So
Workload Identity Federation cannot be set up, nor can workspaces be created, for this
organization today. This was found right after the workflows were first switched to federation
only; they now support both modes.

**What to set (key mode).**

1. Console > Settings > API keys: create two keys, named for what they are (for example
   `trip-planner-github-development` and `trip-planner-github-production`). The Console shows
   each key once.
2. GitHub > Settings > Environments > `development` > Environment **secrets** > Add: name
   `ANTHROPIC_API_KEY`, value the development key. Do the same in `production` with the
   production key. Use **environment** secrets, never repository secrets: the guard rejects a
   job that has no environment, and the environment decides which key a job gets.
3. Run Actions > anthropic-auth-check > Run workflow, once with `development` and once with
   `production` (the second needs your approval and runs only on `main`). It prints
   `Anthropic auth mode: api-key` and lists one model. Costs nothing.

That is all: set no variables, and do not set `ANTHROPIC_API_KEY` as a repository secret or in a
workflow's `env:`.

**How a job picks its mode.** Every job that calls Anthropic runs `./.github/actions/anthropic-auth`
with the environment's three variables and its secret:

| The environment has | Mode | Effect |
|---|---|---|
| variables `ANTHROPIC_FEDERATION_RULE_ID` and `ANTHROPIC_ORGANIZATION_ID` | federation | OIDC token minted and refreshed; no key is exported, even when the secret exists (a notice says so) |
| no (complete) federation variables, secret `ANTHROPIC_API_KEY` non-empty | api-key | the key is masked and exported as `ANTHROPIC_API_KEY` for the rest of the job; never printed |
| neither | none | the step fails with a message naming both options |

The action prints the mode it chose and sets it as the step output `mode`. The backend and the
evals take either (see "What the backend and evals accept" below). `id-token: write` stays on
the jobs that call Anthropic only; in key mode it is unused and harmless.

**What the key protects.** A key in a GitHub environment is readable by any workflow job that
runs in that environment. Pull requests run in `development` (the evals), so a pull request
that edits a workflow can use, and can exfiltrate, the **development** key: keep its spend
limit low (about $40 a month, item 3 above) and rotate it if a PR you did not write ever runs.
The **production** key is reachable only by jobs in the `production` environment, which accepts
`main` after your approval (step 2.3 of the GitHub section). `ci-backend.yml`'s guard
(`.github/scripts/check_anthropic_credentials.py`) fails any PR that adds a production job to a
PR-run workflow, reads the secret outside the action's `api-key` input or without an
environment, sets `ANTHROPIC_API_KEY` in an `env:`, uses `pull_request_target`, or mentions the
retired names `ANTHROPIC_API_KEY_DEV` / `ANTHROPIC_API_KEY_PROD`. Pull requests from forks get
no secrets.

**Rotation.** Create the new key in the Console, overwrite the environment secret, re-run
anthropic-auth-check, then revoke the old key.

**Upgrade path.** When your organization supports Workload Identity Federation, follow the
section below, then delete the `ANTHROPIC_API_KEY` secret of each environment and revoke the
two GitHub keys in the Console. Nothing else changes: the workflows already prefer federation
when its variables exist.

### Anthropic Workload Identity Federation

*The upgrade path: available to organizations that are not Individual Organizations
(see the finding above).* When your organization supports Workload Identity Federation: create
the issuer with `check_jti` off, the service accounts and the rules (steps 2 to 4 below), set
the three variables (step 5), verify (step 6), then delete the `ANTHROPIC_API_KEY` secrets
(step 7).

CI then authenticates to Anthropic with **no stored API key**. A GitHub job asks GitHub for an OIDC
token (a signed JWT that says "I am job X of repository Y, running in environment Z"); the
Anthropic SDK and `ant` swap it for a short-lived Anthropic access token (`jwt-bearer` grant on
`/v1/oauth/token`, beta header `oidc-federation-2026-04-01`). The access token acts as a
**service account** in one workspace. This is a **beta** feature: names in the Console may move.

What stays as it is: the **Railway backend keeps its own `ANTHROPIC_API_KEY`** (the "prod,
Railway" key above) and your laptop keeps the development key in `backend/.env`. Federation
replaces only the two GitHub keys (the `ANTHROPIC_API_KEY` secret of each environment).

What you create, once (the org id and workspace ids are not secrets):

| Object | `development` | `production` |
|---|---|---|
| Service account | `trip-planner-ci-development`, org role `developer` | `trip-planner-ci-production`, org role `developer` |
| Member of workspace (role `workspace_developer`) | `trip-planner-development` | `trip-planner-production` |
| Federation rule name | `trip-planner-github-development` | `trip-planner-github-production` |
| `match.subject_prefix` (exact: no trailing `*`) | `repo:MicheleBellitti@64275646/trip-planner@1416043486:environment:development` | `repo:MicheleBellitti@64275646/trip-planner@1416043486:environment:production` |

GitHub's `sub` for this repository embeds the immutable owner and repository ids (`owner@<id>/repo@<id>`), not the plain `owner/repo` form older examples show. Verified on 2026-10-12: a rule with `repo:MicheleBellitti/trip-planner:...` was rejected (401, `match_subject_prefix`). The `anthropic-auth` action prints the token's exact `sub` (`OIDC token ready: sub=...`); copy it from that log line when creating or fixing a rule.
| `match.audience` | `https://api.anthropic.com` | `https://api.anthropic.com` |
| `oauth_scope` | `workspace:developer` (needed by `ant apply`; inference-only would not be enough) | `workspace:developer` |
| Rule enabled for workspace | `trip-planner-development` | `trip-planner-production` |

The two rules share one issuer. A job presents the `...:environment:<name>` subject only when
it declares `environment: <name>`, and GitHub lets a job into `production` only from `main`
after your approval (step 2.3). So a pull request can reach the development identity (as it
could the old development key) but never the production one.

**Steps** (Console: "Workload identity" in the Console's settings, or the API snippet below):

1. **Organization id.** Console > Settings > Organization (a UUID). Workspace ids
   (`wrkspc_...`) are in the URL of each workspace's page.
2. **Issuer.** Create one: URL `https://token.actions.githubusercontent.com` (it must equal
   the token's `iss` exactly), name `github-actions`, signing keys by OIDC discovery (the
   default), `max_jwt_lifetime_seconds` 900 (GitHub's tokens live minutes; the default 3600 is
   fine too). **Single-use tokens (`check_jti`)**: it defaults to on, and each GitHub token
   carries a `jti`, so every token could be exchanged once. The SDK exchanges the token file
   again for every client it builds and for a retry after a 401, so with it on, the evals (a
   backend client plus the judge's) can be rejected as replays. Create the issuer with
   `check_jti` **off**: the token is short-lived, audience-bound, readable only by the job
   (mode 0600) and the rules pin repository and environment. Turn it back on only if you decide
   that `ant apply` alone is enough; the verification below tells you.
3. **Service accounts.** Create the two accounts above (role `developer`; never `admin`), and
   add each to its workspace as `workspace_developer`. A rule is rejected at exchange time
   unless its service account is a member of the rule's workspace.
4. **Rules.** Create the two rules from the table (issuer from step 2, target the matching
   service account). Keep `token_lifetime_seconds` at its default (3600), see "Token lifetimes".
   Copy each rule's id (`fdrl_...`).
5. **GitHub environment variables** (Settings > Environments > *name* > Environment
   **variables**, not secrets; step 2.3 of the GitHub section):

   | Variable | `development` | `production` |
   |---|---|---|
   | `ANTHROPIC_FEDERATION_RULE_ID` | the development rule's id | the production rule's id |
   | `ANTHROPIC_ORGANIZATION_ID` | the organization UUID | the same UUID |
   | `ANTHROPIC_WORKSPACE_ID` | `trip-planner-development`'s `wrkspc_...` | `trip-planner-production`'s `wrkspc_...` |
   | `ANTHROPIC_SERVICE_ACCOUNT_ID` | `svac_...` of the development service account (optional; the official GitHub guide sets it) | `svac_...` of the production service account |

   Without the first two, `.github/actions/anthropic-auth` does not use federation: it falls
   back to the environment's `ANTHROPIC_API_KEY` secret, or fails with a message naming both
   options when there is none. `ANTHROPIC_WORKSPACE_ID` is optional (the rule has one
   workspace) but recommended, and `ant` sends it as a header that must match.
6. **Verify.** Actions > anthropic-auth-check > Run workflow, once with `development`, once
   with `production` (the second needs your approval and runs only on `main`). It prints the
   token's `sub` and `aud`, lists one model through `ant`, then through two SDK clients in a
   row. Costs nothing. On a 401 compare `sub`/`aud` with the rule, and read the Console's
   Workload identity page for the rejected exchange. If client 1 works and client 2 fails, the
   issuer enforces `check_jti`: turn it off (step 2). The run must print `Anthropic auth mode:
   federation`; if it says `api-key`, a variable is missing or empty.
7. **Retire the keys.** Only after step 6 is green for both environments, and after the first
   real `evals` run in federation mode: delete the environment secret `ANTHROPIC_API_KEY` from
   `development` and from `production`, and revoke the matching two keys in the Console
   (Settings > API keys). Federation wins while both exist, so nothing breaks in between, but
   an unused key is only a liability. The guard keeps `ANTHROPIC_API_KEY` out of every
   workflow `env:` (a static key beats federation).

**API alternative** (one time, from the laptop, never in CI). The federation admin endpoints
(`organization.federation.issuers`/`rules`, `organization.service_accounts`,
`organization.workspaces.service_accounts`) do **not** accept Admin API keys: they need an OAuth
access token with the `org:admin` scope, from `ant auth login --scope org:admin` (browser
sign-in as an organization admin; the SDK then finds the stored profile). Make sure
`ANTHROPIC_API_KEY` is unset in that shell, because a static key wins. Reference:
`/docs/en/manage-claude/wif-admin-api` in the Anthropic docs. An `admin`-role service account
(or an `org:admin` rule) can only be created interactively, and we never need one.

```python
import anthropic

REPO = "MicheleBellitti/trip-planner"
AUDIENCE = "https://api.anthropic.com"
WORKSPACES = {  # environment -> workspace id (Console: the workspace's URL)
    "development": "wrkspc_...",
    "production": "wrkspc_...",
}

client = anthropic.Anthropic()  # credentials from `ant auth login --scope org:admin`
print("ANTHROPIC_ORGANIZATION_ID =", client.organization.retrieve().id)

issuer = client.organization.federation.issuers.create(
    name="github-actions",
    issuer_url="https://token.actions.githubusercontent.com",
    jwks={"type": "discovery"},
    max_jwt_lifetime_seconds=900,
    check_jti=False,  # see step 2
)
for environment, workspace_id in WORKSPACES.items():
    account = client.organization.service_accounts.create(
        name=f"trip-planner-ci-{environment}",
        description=f"GitHub Actions, {REPO}, environment {environment}",
        organization_role="developer",
    )
    client.organization.workspaces.service_accounts.add(
        workspace_id,
        service_account_id=account.id,
        workspace_role="workspace_developer",
    )
    rule = client.organization.federation.rules.create(
        issuer_id=issuer.id,
        name=f"trip-planner-github-{environment}",
        oauth_scope="workspace:developer",
        target={"type": "service_account", "service_account_id": account.id},
        match={
            "subject_prefix": f"repo:{REPO}:environment:{environment}",  # exact: no "*"
            "audience": AUDIENCE,
        },
        workspace_id=workspace_id,
        token_lifetime_seconds=3600,
    )
    print(environment, "ANTHROPIC_FEDERATION_RULE_ID =", rule.id)
```

**Token lifetimes, and why the action refreshes.** GitHub's OIDC token lives for minutes (the
action prints its `valid_for` when it mints one). Anthropic caps the access token it hands
back at `max(60, min(token_lifetime_seconds, 2 x the assertion's remaining validity))`
seconds, so with the default 3600 the access token lives about twice what is left of the
GitHub token: minutes, not an hour. The SDK renews it when 120 s remain (30 s at the latest),
and a renewal is a new exchange that **re-reads `ANTHROPIC_IDENTITY_TOKEN_FILE`**. A token
minted once at the start of a job would therefore be expired (and, with `check_jti`, already
spent) by the first renewal. So for jobs that outlive it, `anthropic-auth` leaves a background
process that rewrites the file every 120 s (`refresh-interval-seconds`; 0 turns it off) until
the job ends; the `evals` job (up to two hours) and the production evals need it, `ant apply`
(minutes) does not need it but pays nothing. Raising `token_lifetime_seconds` does not help:
the cap follows the assertion. If the refresher cannot reach GitHub it keeps the last token and
logs to `$RUNNER_TEMP/anthropic-auth/refresh.log` (no token ever goes in it); the next
renewal then fails with the SDK's own error naming the rejected exchange.

**What the backend and evals accept.** `ANTHROPIC_API_KEY` if set, else (only with
`ENVIRONMENT=development`: the CI evals, local) federation from the process environment:
`ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID` and `ANTHROPIC_IDENTITY_TOKEN_FILE`
(or `ANTHROPIC_IDENTITY_TOKEN`), plus the optional `ANTHROPIC_WORKSPACE_ID`, which
`anthropic-auth` exports in federation mode. `app.config.Settings` decides (`anthropic_auth_mode`) and
`app.ma_client.anthropic_client_kwargs` builds every client from it, in the backend and in
`evals/run.py` / `evals/judge.py`: with a key the client gets `api_key=`, with federation it
gets none and the SDK exchanges the token itself. The SDK ranks an explicit profile
(`ANTHROPIC_PROFILE`, `ANTHROPIC_CONFIG_DIR`, an `active_config` file) above federation, so
leave those unset on the runner. Production at Railway is unchanged: Settings refuses to
start there without `ANTHROPIC_API_KEY`, and refuses a federation-only configuration with a
clear error.


## 2. GitHub

1. **Repository** `trip-planner`, private, default branch `main`.
2. **Settings > Actions > General**
   - Workflow permissions: "Read repository contents and packages permissions". Each job
     asks for what it needs; only the production apply job can write.
   - "Allow GitHub Actions to create and approve pull requests": off.
   - Fork pull requests: leave "Run workflows from fork pull requests" off (the default for a
     private repository). Forks never receive environment secrets anyway.
3. **Settings > Environments**

   | Environment | Variables | Secrets | Protection |
   |---|---|---|---|
   | `development` | none in key mode. Federation: `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_WORKSPACE_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID` (development values). Optional, eval history: `EVALS_INGEST_URL` | `ANTHROPIC_API_KEY` (the development GitHub key; delete it once federation works); optional, eval history: `EVALS_INGEST_TOKEN` | No reviewers. Deployment branches: no restriction (PR evals need it). |
   | `production` | none in key mode. Federation: the same three names (production values). Optional, eval history: `EVALS_INGEST_URL` | `ANTHROPIC_API_KEY` (the production GitHub key; delete it once federation works); optional `LOCKFILE_PUSH_TOKEN` (see 4); optional, eval history: `EVALS_INGEST_TOKEN` | Required reviewer: **Michele**. "Prevent self-review": **off** (the run is triggered by your own merge, and you must be able to approve it). "Allow administrators to bypass": off. Deployment branches and tags: **selected, `main` only**. |

   The Anthropic key is an **environment** secret, one per environment under the same name, so
   the job's environment decides which key it gets. No repository or organization secret holds
   an Anthropic credential. Production is unreachable from any pull request in independent
   ways: the production key (or, in federation mode, the production rule's subject
   `...:environment:production`) goes only to a job that declares that environment, that
   environment accepts only `main` after your approval, and no workflow triggered by
   `pull_request` uses it. `ci-backend.yml` fails any PR that adds such a job, a job that
   reaches Anthropic credentials without an environment or outside `development` in a PR-run
   workflow, a read of the secret outside the auth action's `api-key` input, the retired
   `ANTHROPIC_API_KEY_DEV` / `ANTHROPIC_API_KEY_PROD` names, an `ANTHROPIC_API_KEY` in an
   `env:`, or a `pull_request_target` trigger. Pull requests from forks get no secrets, no
   variables and no OIDC token.
4. **Rules for `main`** (Settings > Rules > Rulesets, target the default branch): restrict
   deletions and block force pushes.
   - Required status checks: do **not** mark `ci-backend`, `ci-web` or `evals` as required.
     They run only when their paths change, and a required check that never starts keeps a
     PR waiting forever. Merge only on green. For agents the hard gate is `deploy-agents.yml`
     anyway: it reruns the evals on `main` and waits for your approval.
   - `deploy-agents.yml` pushes `backend/claude-lock.production.json` straight to `main` with
     the workflow's `GITHUB_TOKEN`. If you add "Require a pull request before merging", that
     push is rejected. Then create a fine-grained personal access token limited to this
     repository with Contents read and write, store it as the `production` environment secret
     `LOCKFILE_PUSH_TOKEN`, and add "Repository admin" to the ruleset's bypass list. The job
     uses the token when it exists and `GITHUB_TOKEN` otherwise.
5. **Installing `ant` in CI.** The anthropic-cli README's CI example uses
   `anthropics/setup-ant@v1`, but on 2026-10-12 GitHub answered 404 for it. Both agent
   workflows use the repository's own composite action instead,
   `.github/actions/setup-ant` (`uses: ./.github/actions/setup-ant`, after the checkout). It
   downloads `ant_1.40.0_linux_amd64.tar.gz` from the v1.40.0 release, refuses it unless its
   sha256 is `9845b2a2d44ff3204b3fdaebb64c9da8e7558ad6b9b4547ce4c0eda36dea6e8f` (the value in
   the release's `ant_1.40.0_checksums.txt` and in GitHub's asset digest, both checked on
   2026-10-12), extracts the `ant` binary from the archive root and puts it on `PATH`. A step
   right after still fails if `ant --version` is below 1.30.0, the first release with `ant
   apply`. To upgrade, change the action's `version` and `sha256` defaults together, taking
   the hash from the new release's checksums file, never from the downloaded archive.

## 3. Railway

> **Config as Code is deprecated on Railway.** Its docs (fetched 2026-10-12) say new
> services cannot opt into `railway.json`, and existing files stop being read on
> **2026-12-01**. So `backend/railway.json` and `backend/railway.cron.json` are the reviewed
> record of each service's settings: enter the values below in the dashboard (leave the
> service's "Config file path" empty). To put the settings back under version control later,
> `railway config pull` writes the live project into `.railway/railway.ts` (Railway
> Infrastructure as Code); that is a follow-up, not needed to ship.

1. **Project** `trip-planner`. Region: EU West (Amsterdam), the closest to Italy. Keep the
   database and both services in the same region.
2. **Database**: New > Database > PostgreSQL (service name `Postgres`). Its `DATABASE_URL`
   points at the private network.
3. **Service `backend`** (New > GitHub repo > `trip-planner`, branch `main`):

   | Setting | Value | Why |
   |---|---|---|
   | Root directory | `/backend` | Railway pulls only this directory: the lockfiles live there |
   | Watch paths | `/backend/**` | pushes that only touch `web/`, docs or agents don't redeploy |
   | Builder | Dockerfile (`backend/Dockerfile`, detected) | |
   | Start command | empty | the image's CMD: one uvicorn process on `$PORT` |
   | Pre-deploy command | `alembic upgrade head` | runs before every start; if it fails, the deploy stops and the previous one keeps serving |
   | Pre-deploy timeout | 300 s | a stuck migration fails the deploy instead of holding it |
   | Healthcheck path / timeout | `/health` / 120 s | the new deployment takes traffic only when this answers 2xx |
   | Restart policy | On failure, 10 retries | |
   | Replicas | **1**, never more | the live SSE channel and the plan consumers are in memory |
   | Serverless (app sleeping) | **off** | a sleeping container would stop the consumers of running plans |
   | Overlap / draining | 0 s / 30 s | uvicorn closes open SSE streams after 20 s, then the lifespan stops the consumers |
   | Wait for CI | off | `deploy-agents.yml` waits for a human approval; Railway would hold the backend deploy (and skip it after 2 h) |
   | Networking | custom domain `atlas.api.bellittim.com` | step 6 below |

   The image runs as uid 10001, without access logs (they carry client IPs: the app logs
   structlog JSON instead), trusts Railway's proxy headers (`FORWARDED_ALLOW_IPS=*`, so the
   scheme is `https`), and excludes `tests/` and any `.env`.

   A redeploy starts the new container before it stops the old one, so for a few seconds two
   processes may follow the same running plans. Overlap 0 keeps that window as short as
   Railway allows; the consumer's dedupe (unique `events.ma_event_id`, each `submit_plan`
   answered once) is what makes it harmless.
4. **Service `cleanup`** (New > GitHub repo > `trip-planner` again, then rename it):

   | Setting | Value |
   |---|---|
   | Root directory / watch paths / builder | `/backend` / `/backend/**` / Dockerfile, the same image |
   | Start command | `python -m app.jobs cleanup` |
   | Cron schedule | `0 1 * * *` |
   | Pre-deploy command | none: `backend` migrates, and two migrations at once would race |
   | Healthcheck | none: the process exits when done |
   | Restart policy | Never: a failed night is retried the next night (the job is idempotent) |
   | Replicas / domain | 1 / none |

   **Time zone and daylight saving.** Railway runs cron schedules in UTC and cannot follow
   Europe/Rome. `0 1 * * *` is 03:00 in Rome during summer time (CEST, UTC+2, from the last
   Sunday of March to the last Sunday of October) and **02:00** during winter time (CET,
   UTC+1). After 25 October 2026 it runs at 02:00 until 28 March 2027. The job deletes what is
   older than 90 days (exchange rates older than a year), so an hour's shift changes nothing,
   and Railway only promises cron times within a few minutes anyway. To keep exactly 03:00 all
   year, switch to `0 2 * * *` at the end of October and back in March, or schedule it hourly
   and make `app.jobs cleanup` do nothing outside 03:00-03:59 Rome time (a backend change).
   The process must exit when done: Railway skips a run while the previous one is still
   Active.
5. **Variables.** Put the shared ones in Project Settings > Shared Variables (environment
   `production`) and reference them from both services. Seal the secret ones.

   | Variable | Value | `backend` | `cleanup` | Notes |
   |---|---|---|---|---|
   | `ENVIRONMENT` | `production` | yes | yes | unset also means production; set it anyway |
   | `ANTHROPIC_API_KEY` | the "prod, Railway" key | yes | yes | sealed; the cleanup deletes Managed Agents sessions |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | yes | yes | reference variable; Settings rewrites it to asyncpg |
   | `AGENT_PROFILE` | `production` | yes | yes | required in production; selects `backend/claude-lock.production.json` |
   | `SESSION_BUDGET_CENTS` | `400` | yes | | US cents per session; empty = the profile's default (400) |
   | `MONTHLY_LIMIT_CENTS` | `5000` | yes | | POST /plans refuses new plans at or above it |
   | `PLANNER_ALLOWED_EMAILS` | your TripTracker login email | yes | | empty means nobody; never commit it |
   | `FRONTEND_ORIGIN` | `https://atlas.bellittim.com` | yes | | the only CORS origin and the required `Origin` on POST |
   | `TRIPTRACKER_ORIGIN` | `https://viaggi.bellittim.com` | yes | | session check, `trip.json`, CORS of `GET /plans/{id}/trip` |
   | `TRIP_SCHEMA_URL` | **`file:///app/pinned/trip.schema.json`** until TripTracker serves `/schema/trip.json`, then unset | yes | | the pinned copy `backend/pinned/trip.schema.json` ships in the image (`tests/` doesn't) and equals the test fixture (a backend test checks it); production never falls back on its own: without this setting POST /plans answers 503 until TripTracker serves the schema |
   | `EVALS_INGEST_TOKEN` | a random token ("Eval history" below) | yes | | sealed; optional. Empty (the default) disables `POST /evals/runs` (404); the same value goes in both GitHub environments |
   | `LOG_LEVEL` | `INFO` | yes | yes | |
   | `WIKIMEDIA_CONTACT_URL` | an https page or `mailto:` where Wikimedia can reach you | yes | | optional; empty = `FRONTEND_ORIGIN` (Wikimedia's User-Agent policy for the cover photos) |
   | `AUTH_MODE`, `LOCKFILE_PATH`, `GIT_SHA` | leave unset | | | `triptracker`; `backend/claude-lock.<AGENT_PROFILE>.json`; Railway sets `RAILWAY_GIT_COMMIT_SHA` |
   | `PORT`, `FORWARDED_ALLOW_IPS` | leave unset | | | Railway injects `PORT`; the image sets `FORWARDED_ALLOW_IPS=*` |

   To try the deployed backend on the cheap roster before day 4, set `AGENT_PROFILE=development`,
   a development key and `SESSION_BUDGET_CENTS=100` (the development lockfile ships in the
   image too). Switch back before real use.
6. **Domain**: `backend` > Settings > Networking > Custom domain
   `atlas.api.bellittim.com`. Railway shows a CNAME target and, if it asks, a TXT
   verification record: add both in Cloudflare (step 4). Railway issues the certificate once
   the record resolves.
7. **First deploy and checks** (day 2, after the variables):
   - The deploy log shows the pre-deploy `alembic upgrade head`, then the healthcheck.
   - `curl -s https://atlas.api.bellittim.com/health` answers `{"status":"ok"}`.
   - `/docs` answers 404 (interactive docs are development only).
   - Until `backend/claude-lock.production.json` exists (step 7), POST /plans answers 503
     `planner_unavailable` while `/health` stays green. That is expected.
   - The startup log shows `trip_schema_loaded` with `source` `file` and no
     `trip_schema_unavailable`: with `TRIP_SCHEMA_URL` set to the pinned copy the schema loads
     from the image, not from TripTracker.

## 4. Cloudflare DNS

All records **DNS only** (grey cloud), TTL auto:

| Name | Type | Target | Notes |
|---|---|---|---|
| `atlas.api` | CNAME | the target Railway shows (`….up.railway.app`) | |
| the name Railway shows (`_railway-verify…`), only if asked | TXT | the value Railway shows | domain verification |
| `atlas` | CNAME | the target Vercel shows | |
| `viaggi` | unchanged | TripTracker on Vercel | already done |

Why the proxy stays off: for `atlas.api` it is essential (spec), because Cloudflare's
proxy closes idle connections and breaks the SSE stream. With DNS only, Railway and Vercel
also issue and renew their own certificates without interference.

## 5. Vercel: the planner web app

1. Add New > Project > import `trip-planner`. Root Directory `web`, framework Next.js
   (detected). Settings > Build and Deployment > Node.js Version: 24.x.
2. Environment variables (Production and Preview):

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://atlas.api.bellittim.com` |
   | `NEXT_PUBLIC_TRIPTRACKER_URL` | `https://viaggi.bellittim.com` |

   `NEXT_PUBLIC_*` values are inlined into the public bundle at build time: never a secret
   there. Changing one needs a redeploy.
3. Domains: add `atlas.bellittim.com`; Vercel shows the CNAME target for Cloudflare.
4. Git: production branch `main`, a preview for every PR (spec). Settings > Git > Ignored
   Build Step, custom command `git diff --quiet HEAD^ HEAD -- . ../schema` skips builds when
   neither `web/` nor `schema/` changed.
5. Previews can't use the production API: CORS allows only `FRONTEND_ORIGIN`, and the
   TripTracker session cookie is scoped to `bellittim.com`, not `*.vercel.app`. Use previews
   for visual review; the live flow works only on `atlas.bellittim.com` (and locally).

## 6. TripTracker

After the TripTracker PR (subdomain cookie, `/accedi?returnTo=`, `/import`, `trip.json`) is
merged, in the existing Vercel project of `viaggi.bellittim.com`, Settings > Environment
Variables (Production):

| Variable | Value | Effect |
|---|---|---|
| `COOKIE_DOMAIN` | `bellittim.com` | new: turns on Better Auth's cross-subdomain cookie, so `atlas.api` receives the session |
| `ORIGINI_FIDATE` | `https://trip-tracker-nu-ivory.vercel.app,https://atlas.bellittim.com` | existing, add the planner: keeps the old PWA origin (trusted origins, allowed `returnTo` targets) |
| `NEXT_PUBLIC_PLANNER_API_URL` | `https://atlas.api.bellittim.com` | new: where `/import` downloads the Trip (`GET /plans/{id}/trip` with the shared cookie). Unset, `/import` says the planner isn't configured and "Apri in TripTracker" can't import |

`NEXT_PUBLIC_PLANNER_API_URL` is inlined into TripTracker's bundle at build time, so set it
before the build and redeploy after any change (`docs/triptracker/pr/README.md`, "Environment
variables"). Then redeploy TripTracker: Vercel applies variables only to new deployments. Existing
sessions keep a host-only cookie until Better Auth refreshes it (daily) or you sign in again:
sign out and back in once on `viaggi.bellittim.com`, then open `atlas.bellittim.com`; it
should load without a redirect to `/accedi`. Once TripTracker serves `/schema/trip.json`,
unset `TRIP_SCHEMA_URL` on Railway (the backend then downloads it from `TRIPTRACKER_ORIGIN`
and refreshes it every 10 minutes). A later backend PR can then delete `backend/pinned/` and
the Dockerfile's `RUN test -s /app/pinned/trip.schema.json` line.

## 7. First `ant apply` for both profiles

`profiles/**` is generated from `agents/` (`uv run python ../scripts/render_profiles.py
--check` from `backend/` must pass), and each profile has its own lockfile in `backend/`.

**Development** (day 1, from the laptop, development key only):

```sh
brew install anthropics/tap/ant
xattr -d com.apple.quarantine "$(brew --prefix)/bin/ant"   # macOS
ant --version                                              # 1.30.0 or later

# From the repository root. The key is read from backend/.env, not typed in the shell.
export ANTHROPIC_API_KEY="$(sed -n 's/^ANTHROPIC_API_KEY=//p' backend/.env)"
ant apply --dry-run -v --lock-file backend/claude-lock.development.json profiles/development
ant apply --lock-file backend/claude-lock.development.json profiles/development
unset ANTHROPIC_API_KEY
```

Read the dry run first (probe P12, notes §4): every agent file is an agent, `cloud.yaml` is
an environment, `predefined_agents` resolve to `{type: agent, id, version}`, and
`tools/submit_plan.json` is spliced into the coordinator's tools. Then commit
`backend/claude-lock.development.json` in a PR. It must be on `main` before the first PR
that triggers `evals.yml`: without it, every eval run creates a new set of development agents.

Prefer `ant` for this first apply, the same tool CI uses. `scripts/bootstrap.py` (from
`backend/`: `uv run python ../scripts/bootstrap.py --profile development --yes`) does the same
with the SDK when `ant` can't be installed, and writes the lockfile exactly as `ant` does:
keys relative to the lockfile's directory (`../profiles/development/agents/<name>.md`,
`../skills/<name>`; anthropic-cli v1.40.0 `core/lock.go` `Root()` and `core/loader.go`
`keyFor`), so CI's `ant` takes over the same agents. The one difference is the skill
`version`: bootstrap records the GA API's version id (`skver_...`), `ant` the Beta API's,
which can be an epoch-like number string; the backend accepts both. A lockfile written by the
first bootstrap.py, keyed from the repository root (`./profiles/...`), still works: the
backend logs `lockfile_legacy_keys`, and the next bootstrap.py apply rewrites the keys
without creating anything new.

**Production** (day 4, never from the laptop): Actions > deploy-agents > Run workflow, branch
`main`, `force` off, `production_evals` on for the spec's final check (or off and run it
later). The run:

1. reruns the development evals (up to $6.00);
2. waits for your approval in the `production` environment;
3. applies `profiles/production` with the `production` environment's Anthropic credentials
   (its key, or in federation mode an OIDC token minted after your approval), commits
   `backend/claude-lock.production.json` to `main` ("Update production agents lockfile"),
   and Railway redeploys the backend with it, so POST /plans stops answering 503;
4. with `production_evals`, asks for a second approval and runs the five requests on the
   production profile (up to $21: five sessions at $4 plus the judge). The results are a
   report in the job summary and the `eval-results-production` artifact, not a gate (the
   baseline is a development run). The spec's closing bar: production plans under $4.

## 8. Day-1 live probe

The probe (notes §4, P1-P13) answers what the docs can't: whether the travel MCP servers
accept a Managed Agents session (the main project risk), the real MCP tool names, inter-agent
tools, budget pause and resume, ids and cross-posted events, and how `ant apply` behaves
(P12). `scripts/probe_session.py` runs it. Run it on the morning of day 1, before building on
those assumptions, from `backend/`:

```sh
uv run python ../scripts/probe_session.py --dry-run   # the plan and its worst case; no network, no key

# The key comes from the shell environment: the development key only, never the production
# one. The script refuses to run when CI is set.
export ANTHROPIC_API_KEY="$(sed -n 's/^ANTHROPIC_API_KEY=//p' .env)"
uv run python ../scripts/probe_session.py --yes                   # every probe: spends real money
uv run python ../scripts/probe_session.py --yes --only P4,P5      # or a subset
unset ANTHROPIC_API_KEY
```

- Each session is capped at the development profile's budget (60 cents; P9 uses 3 to reach
  the budget pause). No new session starts once the sessions' list cost reaches
  `--max-total-cents` (default 150, so $1.50; the dry run prints the worst case, at most one
  session's budget above it). Every resource it creates is named `probe-<stamp>-...` and
  removed at the end.
- The raw SSE log goes to the system temp directory (`--sse-log` to change it), never into the
  repository, because it carries web page text. The report is
  `docs/probes/<YYYY-MM-DD>.md`: tool names, event types, ids, statuses and hostnames only.
- Read the report, then copy each verdict into `docs/managed-agents-notes.md` (replace the
  `needs_live_probe` and `[INFERRED]` tags) and tell the owners of the seams in
  `docs/backend-interfaces.md` §8.
- P12's `ant` part runs only when `ant` is already installed (step 7); otherwise the report
  says it was skipped.
- P5 decides networking. The profiles use `unrestricted` networking today, because under
  `limited` the environment's `allowed_hosts` also filters `web_search` and `web_fetch`
  (notes D4). If P5 shows otherwise, change `agents/environment.yaml`, render, and ship it
  through a PR like any agent change.

---

## Release paths

Three independent paths (spec): the backend and the web app ship on every merge to `main`,
the agents only when prompts, skills or the contract change, and only with green evals plus
your approval.

| Workflow | Trigger | What it does | Anthropic access | Permissions |
|---|---|---|---|---|
| `ci-backend.yml` | PR touching `backend/`, `skills/`, `scripts/`, `evals/`, `schema/`, `agents/`, `profiles/`, `.github/workflows/`, `.github/actions/`, the web's backend-generated timeline fixtures | uv sync --locked, ruff check and ruff format --check (backend, `scripts/`, `evals/`, `skills/` at Python 3.10), pyright, `app.schemas --check`, `render_profiles.py --check`, skill/script/eval tests, `gen-backend-fixtures.py --check`; pytest on a Postgres 16 service; actionlint and the Anthropic-credentials guard | none | contents: read |
| `ci-web.yml` | PR touching `web/`, `schema/` | npm ci, `gen:schemas -- --check`, lint, typecheck, test, build | none | contents: read |
| `evals.yml` | PR touching `agents/`, `profiles/`, `skills/`, `backend/app/plan.py` (not drafts); called by `deploy-agents.yml`; by hand | freshness checks, `ant apply` of development, `evals/run.py`, `evals/compare.py` (also `--json`), sticky PR comment, upload to the eval history when configured (warning only); fails when the comparison blocks | `development` environment: federation or its `ANTHROPIC_API_KEY` secret | contents: read and id-token: write in the apply and evals jobs; pull-requests: write only in the comment job |
| `deploy-agents.yml` | push to `main` touching `agents/`, `profiles/`, `skills/`; by hand on `main` | `evals.yml` again, then approval, `ant apply` of production, lockfile commit; optional production evals (uploaded to the eval history when configured) | `production` environment: federation or its `ANTHROPIC_API_KEY` secret | contents: write and id-token: write only in the apply job; id-token: write in the production evals |
| `anthropic-auth-check.yml` | by hand | prints the auth mode, lists one model through `ant` and the SDK to prove the credentials | the chosen environment, either mode | contents: read, id-token: write |

**Backend.** Railway rebuilds on every push to `main` under `backend/`, runs the migration,
and switches traffic after `/health` answers. A failed migration or healthcheck leaves the
previous deployment serving. Rollback: redeploy the previous deployment from the Railway
dashboard, or revert the commit.

**Web.** Vercel builds a preview per PR and production from `main`. Rollback: Instant
Rollback to the previous production deployment.

**Agents.**

- *On a PR* (`evals.yml`): one run costs up to $6.00. Runs of the same PR queue instead of
  cancelling each other, because a cancelled job can't stop its sessions, which would keep
  spending up to their budget. Applies to the shared development workspace run one at a time
  across all PRs and `main`: concurrency group `ant-apply-development` with `queue: max`, so
  every waiting apply keeps its place (GitHub's default keeps only one waiting run and cancels
  it when a third arrives, which would fail a PR's evals or silently skip a promotion).
  Changes to `evals/` alone don't trigger it: run it by hand (Actions > evals > Run workflow)
  when the rubric or the requests change.
- *The development lockfile.* The workflow applies `profiles/development` with `--force`:
  the development workspace is shared scratch, other branches' runs move its agents to their
  own versions, so the committed lockfile always looks "edited outside these files" to `ant`.
  Sessions pin versions, so this never disturbs a running eval. The lockfile `ant` rewrites
  in the runner is used by that run only (its versions are the ones built from the PR's
  files), uploaded as the `claude-lock-development` artifact, and **never pushed**: PR
  workflows have no write access. The PR comment says whether it differs from the committed
  one. The PR author commits it: run the apply locally (step 7, add `--force` because CI moved
  the agents) or download the artifact, and commit `backend/claude-lock.development.json` in
  the same PR as the prompt or skill change. A difference on a PR that doesn't touch
  `profiles/development/` or `skills/` only means another branch moved the shared agents:
  nothing to commit. Local runs read the committed lockfile, which pins versions built from
  the committed files, so a stale workspace never changes what a checkout runs.
- *The baseline.* A failing blocking deterministic check (or an aborted or empty run)
  blocks the merge with or without `evals/baseline.json`: that rule needs nothing to compare
  with. Until the baseline is committed, only the judge rule (a criterion's mean dropping by
  more than 0.5) and the cost rule (mean cost per plan up more than 30%) are report only, and
  the PR comment says so. To create or update the baseline, download the `eval-results`
  artifact of a green run, then from `backend/`:
  `uv run python ../evals/compare.py <file> --update-baseline`, and commit
  `evals/baseline.json` in its own PR. It never changes by itself.
- *After merge* (`deploy-agents.yml`): the evals run again on `main`; a failure stops the
  promotion. Otherwise the job waits for your approval. Approve only after the backend that
  goes with the change is live on Railway (next section). The apply pins every subagent and
  skill version; the lockfile commit triggers a Railway redeploy, and new plans use the new
  coordinator version from then on. Plans already running keep the versions they started
  with.
- *Which lockfile the apply uses.* The files come from the merged commit, the production
  lockfile from the current `main`: only this job writes it, one run at a time, so `main`
  always has the newest copy, even for a run queued behind another promotion or a re-run. The
  job commits the new lockfile on top of the current `main` (never a rebase), as
  `github-actions[bot]`, retrying three times. If the push still fails, the job says so: the
  production workspace already has the new versions, so download the run's
  `claude-lock-production` artifact and commit it to `main` by hand rather than re-running.
- *"refusing to apply".* `ant` refuses when the production resources differ from what `main`'s
  lockfile records: someone edited them in the Console, a lockfile push failed and was never
  committed by hand (previous point), or `main`'s lockfile was reverted (next point). Look at
  what changed, then run the workflow by hand with `force`.
- *Rollback.* Fast: revert the lockfile commit on `main`; Railway redeploys and new plans
  start on the previous versions, which stay available on the platform. Then revert the
  prompt change in a PR. The next production apply will see that the remote agents moved past
  the lockfile and refuse: run it by hand with `force` after checking its plan.

## Eval history

Atlas shows the runs of `evals/run.py` in the planner web app (the "Valutazioni" page). CI sends
each run to the backend, which stores it in the `eval_runs` table; nothing about this is
required, and without it the evals work exactly as before.

**How it flows.** After `evals/compare.py` (which now also writes its verdict with
`--json <file>`: status `passed`, `blocked` or `report_only`, one result per rule, every
finding), the `Upload to the eval history` step of `evals.yml` runs `evals/upload.py`. It
POSTs `{"results", "comparison", "workflow_run_url"}` to `<EVALS_INGEST_URL>/evals/runs` with
`Authorization: Bearer <EVALS_INGEST_TOKEN>`. `deploy-agents.yml` does the same after the manual
production evals, without a comparison (that run is reported, not compared). The upload

- runs in the same environment-scoped job as the run, so it reads the environment's variable
  and secret; with either missing it logs a notice (`eval history upload skipped`) and goes on;
- retries three times on connection errors, timeouts, 429 and 5xx (pauses of 2, 4 and 8
  seconds); any other answer is final (401 wrong token, 404 ingest disabled on the backend or a
  wrong URL, 413 over 5 MB, 422 unknown format);
- never fails the job: a failure is a `::warning::` line and exit 0 (`--strict`, for local use,
  turns it into exit 1);
- never prints the token, and refuses a plain `http://` URL (except localhost) so the token
  can't travel in clear text;
- is idempotent: the backend keys a run by profile, git sha and start time, so a re-run of the
  workflow (or the same file sent again) updates the comparison and the workflow run URL
  instead of adding a row.

Pull request runs upload too (their row carries the PR head's sha); fork pull requests have no
environment secrets, so they skip with the notice. The token only lets a caller add or update
eval history rows. It is as exposed as `ANTHROPIC_API_KEY` in the `development` environment
(any workflow job in that environment can read it), which is why nothing else is behind it.

**Set it up, once.** The backend has one token, so the same value goes in three places.

1. Make the token and keep it out of shell history and logs:

   ```sh
   openssl rand -hex 32 | pbcopy      # paste it where asked below, then clear the clipboard
   ```

2. **Railway**, service `backend` only (not `cleanup`): Variables > New variable
   `EVALS_INGEST_TOKEN`, then seal it. Redeploy. Until it is set the endpoint answers 404
   `evals_ingest_disabled`, which is the intended "off".
3. **GitHub**, Settings > Environments > `development`, and again for `production`:
   - Secret `EVALS_INGEST_TOKEN`: the same value. From a terminal, `gh secret set
     EVALS_INGEST_TOKEN --env development` asks for it on the prompt (do not pass it with
     `--body`, which lands in the shell history); repeat with `--env production`.
   - Variable `EVALS_INGEST_URL`: the backend's origin, `https://atlas.api.bellittim.com`
     (no trailing path), a plain variable, not a secret: `gh variable set EVALS_INGEST_URL
     --env development --body https://atlas.api.bellittim.com`, and the same with
     `--env production`.
4. Check: run the `evals` workflow by hand (Actions > evals > Run workflow). The step prints
   `Eval run created in the history: <id>` (or `updated`), and the run appears in Atlas. A
   `::warning::` line says why it did not (the list above).

**Rotation.** Make a new token, set it on Railway and in both GitHub environments, redeploy.
Between the first and last change uploads warn with a 401; nothing else breaks. To switch the
history off, empty the Railway variable (the endpoint answers 404 and CI warns) or delete the
GitHub variable `EVALS_INGEST_URL` (CI skips with a notice).

**Local use.**

```sh
cd backend
# Into the local database (backend/.env's DATABASE_URL), no HTTP and no token: the same service
# function the endpoint calls. Run `uv run alembic upgrade head` once first.
uv run python -m app.cli import-evals ../evals/results/<date>-<sha>.json \
  --comparison comparison.json --workflow-run-url <url>        # the last two are optional
# To get a comparison file for an old run:
uv run python ../evals/compare.py ../evals/results/<date>-<sha>.json --json comparison.json
# To a deployed backend instead (a past run, an artifact of an earlier CI run): the token is
# read from the prompt, never typed in the command line.
read -rs EVALS_INGEST_TOKEN && export EVALS_INGEST_TOKEN
EVALS_INGEST_URL=https://atlas.api.bellittim.com \
  uv run python ../evals/upload.py ../evals/results/<date>-<sha>.json --strict
unset EVALS_INGEST_TOKEN
```

The `eval-results` artifact of an evals run (30 days; 90 for the production check) holds the
results file to import. Importing the same file twice updates the existing row.

## Deploy order when the contract changes

Contract rule 7 (CLAUDE.md): **backend first** (accepting both the old and the new format),
**then the agents, then the web app**.

1. **Backend PR.** `backend/app/plan.py` accepts both formats (and an additive Alembic
   migration if tables change). Because `schema/plan.json` and
   `profiles/*/agents/tools/submit_plan.json` are generated from it (CI's `--check` steps
   enforce that), the same PR also changes `profiles/`, so `evals.yml` runs on it, and its
   merge starts both the Railway deploy and `deploy-agents.yml`.
2. **Backend live.** Railway needs minutes; `deploy-agents.yml` needs its evals (up to about
   an hour) and your approval. Before approving, check in Railway that the backend deployment
   of that commit (or a later one) is Active and `/health` answers. While it isn't, the
   production agents keep submitting the old format, which the new backend still accepts.
3. **Agents.** Approve the production job. Its lockfile commit redeploys the backend with the
   new coordinator version; running plans finish on their pinned versions.
4. **Web.** Merge the UI change only after the production lockfile commit. Vercel deploys it.
5. **Cleanup, later.** Drop the old format in a separate backend PR once no running plan can
   still submit it, and keep reading plans already stored in the old format (or migrate them).

If the change also touches TripTracker's Trip, TripTracker ships first: its `/import` must
accept what the backend will start sending.

## Checking these files

None of these checks needs Docker, an API key or the network beyond package installs:

```sh
# Workflows (actionlint with shellcheck, both from PyPI). actionlint 1.7.12 doesn't know
# concurrency's `queue` key (evals.yml) yet, hence the -ignore, as in ci-backend.yml.
uvx --from actionlint-py==1.7.12.25 --with shellcheck-py \
  sh -c 'actionlint -shellcheck "$(command -v shellcheck)" -ignore '"'"'unexpected key "queue" for "concurrency" section'"'"' .github/workflows/*.yml'

# The setup-ant action's script (actionlint checks the workflows that use it, not its body)
uv run --no-project --with pyyaml==6.0.3 python -c 'import yaml; print(yaml.safe_load(open(".github/actions/setup-ant/action.yml"))["runs"]["steps"][0]["run"])' > /tmp/setup-ant.sh
uvx --from shellcheck-py shellcheck -s bash /tmp/setup-ant.sh

# The anthropic-auth action's scripts (actionlint checks the workflows that use the action)
uvx --from shellcheck-py shellcheck -s bash .github/actions/anthropic-auth/mint-token.sh
uv run --no-project --with pyyaml==6.0.3 python -c 'import yaml; print(yaml.safe_load(open(".github/actions/anthropic-auth/action.yml"))["runs"]["steps"][0]["run"])' > /tmp/anthropic-auth.sh
uvx --from shellcheck-py shellcheck -s bash /tmp/anthropic-auth.sh

# The Anthropic-credentials guard and its self-test (the negative cases)
uv run --no-project --with pyyaml==6.0.3 python .github/scripts/check_anthropic_credentials.py
uv run --no-project --with pyyaml==6.0.3 python .github/scripts/check_anthropic_credentials.py --self-test

# The eval scripts (compare.py --json, upload.py) and their tests, from backend/
(cd backend && uv run pytest ../evals/tests -q && uv run ruff check ../evals \
  && uv run ruff format --check ../evals && uv run pyright -p ../evals)

# Dockerfile
uvx --from hadolint-bin==2.15.1 hadolint --failure-threshold info backend/Dockerfile

# The image itself, when Docker runs
docker build -t trip-planner-backend backend
```

`backend/railway.json` and `backend/railway.cron.json` validate against
`https://railway.com/railway.schema.json`.
