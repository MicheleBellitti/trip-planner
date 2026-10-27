# Security hardening: blast radius and follow-ups

Follow-ups from the security audit of 2026-10-27 (PR #33 shipped the urgent fixes: Next.js
16.4.3, certifi, the account line). This file tracks the deeper hardening, each with its
tradeoff, so the owner decides what is worth it. The threat model here is **a compromise of the
Railway host or a dump of the Postgres database**, not an ordinary external attacker (the app
code audited clean against that).

## If Railway (or the database) is breached, what leaks

One place holds, today:

- the **production Anthropic API key** (full spend until rotated);
- the **database**, which holds `auth_sessions` (session tokens to impersonate any user),
  `auth_accounts` (Google refresh/access tokens), the waitlist and every plan;
- the **eval ingest token**, and any TripTracker cookie in flight.

## Done

- **Encrypt the Google OAuth tokens at rest** (`web/lib/auth.ts`, `account.encryptOAuthTokens`).
  They are now stored symmetrically encrypted with `BETTER_AUTH_SECRET`, which lives in the
  environment, not the database, so a database dump alone no longer yields a usable Google
  token. The backend never reads these columns, so nothing it depends on changes. Existing rows
  (if any Google account was linked before this) would need a re-link; today the only accounts
  are the owner's, and the deployed auth mode is still `triptracker`, so there is nothing to
  migrate.

- **Federation is now a valid production credential** (`app/config.py`, `anthropic_auth_mode`
  and the startup check). Production previously refused to start without `ANTHROPIC_API_KEY`;
  it now accepts a full Workload Identity Federation configuration instead, so Railway can run
  on short-lived federated tokens with no stored key. The API key still takes precedence when
  both are present, so this only *adds* a path and changes nothing for a deploy that keeps the
  key. The security benefit lands once the runbook below is done and the key is removed.

- **Shorter session life** (`web/lib/auth.ts`, `expiresIn` 30 -> 7 days, sliding). A session
  token leaked from the database is now usable for at most 7 idle days instead of 30; an active
  user stays signed in through the daily refresh (`updateAge`).

## Runbook: move the production Anthropic key to federation

The code is ready; this is the deploy-side work, and it is reversible (keep the key set until
the last step).

1. In the Anthropic console, create a Workload Identity Federation rule for the production
   identity and note the rule id and organization id.
2. Give Railway a way to present an OIDC identity token for that rule (an identity token file
   the SDK can read, refreshed before expiry), and set `ANTHROPIC_IDENTITY_TOKEN_FILE`.
3. Set `ANTHROPIC_FEDERATION_RULE_ID` and `ANTHROPIC_ORGANIZATION_ID` (and
   `ANTHROPIC_WORKSPACE_ID` if used) on the Railway service, alongside the still-present key.
4. Redeploy and confirm the planner works (the key still wins, so this only proves the vars are
   accepted).
5. Remove `ANTHROPIC_API_KEY` from Railway and redeploy. `anthropic_auth_mode` now returns
   `federation`; a host compromise yields no reusable long-lived key.
6. Rotate the old key at Anthropic.

## Still recommended (owner's call, not coded)

1. **Hash the session token at rest.** A leaked `auth_sessions` table is still a ring of valid
   cookies for up to 7 days. Better Auth 1.7 has no option to hash the session token (it
   compares the raw token on its own `get-session` path, and the backend's
   `verify_atlas_session` looks the raw token up directly), so hashing is a coordinated
   backend-first change (contract rule 7), not a flag. Left out deliberately rather than built
   against the framework.

2. **Scope the database role.** The Railway service connects as a role that can read every
   table including `auth_sessions`. A plans-only role would keep a plans-side compromise from
   handing over the session ring. The web app still needs full access, so the benefit is
   partial. Sketch, to run by hand against the production database (adjust names), NOT applied
   here:

   ```sql
   CREATE ROLE planner_api LOGIN PASSWORD '...';
   GRANT CONNECT ON DATABASE <db> TO planner_api;
   GRANT USAGE ON SCHEMA public TO planner_api;
   GRANT SELECT, INSERT, UPDATE, DELETE ON plans, events, fx_rates, choices,
     destination_covers, eval_runs TO planner_api;  -- no auth_* tables
   ```

   Then point the backend's `DATABASE_URL` at `planner_api`. The web app keeps its own
   full-access role for Better Auth.

## Out of scope / accepted

- A prompt-injected subagent can still send the trip request (cities, dates, traveller ages,
  budget -- no names, emails or payment data by construction) to an attacker host under
  unrestricted networking: documented accepted risk (`agents/environment.yaml`). It cannot place
  a clickable malicious link: the Plan model rejects non-https stop URLs, and `links.check_link`
  plus `plan_to_trip` drop any booking link outside the per-provider allowlist (verified
  deterministically on 2026-10-27).
- No CSP / X-Frame-Options on the web app: hardening, no concrete exploit with `SameSite=Lax`
  cookies.
