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

## Recommended, each with a tradeoff (owner's call)

1. **Remove the static Anthropic key from Railway (highest value).** The SDK client builder
   already supports a `federation` mode (`anthropic_auth_mode == "federation"`,
   `app/ma_client.py:829`): short-lived Workload Identity tokens, no stored key, the way CI
   authenticates today. It is currently gated to development (production refuses to start
   without the key, `app/config.py`). If Railway can provide an OIDC identity token file,
   production could run on federated credentials and a host compromise would yield no reusable
   key. Tradeoff: deploy-time plumbing, and Anthropic must have a federation rule for the
   production identity. This is the real "OBO-equivalent": the Anthropic leg is acted as the
   service, not the user, so the mitigation is short-lived service credentials, not a token
   exchange.

2. **Hash the session token at rest + shorten the session.** A leaked `auth_sessions` table is
   a ring of valid cookies for up to 30 days (`expiresIn`, `web/lib/auth.ts`). Storing only a
   hash would make the dump useless, but Better Auth validates sessions against the stored
   token on its own `get-session` path, and the backend's `verify_atlas_session`
   (`app/auth.py`) looks the raw token up directly, so hashing is a coordinated backend+web
   change (contract rule 7: backend first, accepting both forms during the switch), not a flag.
   Shortening `expiresIn` (e.g. 30 → 7–14 days) is a one-line change but costs active users a
   re-login; it is a product decision.

3. **Scope the database credential.** The Railway service connects as a role that can read and
   write every table including `auth_sessions`. If the plans workload used a role without
   access to the auth tables, a plans-side compromise would not hand over the session ring. The
   web app still needs both, so the benefit is partial; weigh it against the operational cost of
   two roles.

## Out of scope / accepted

- A prompt-injected subagent can still send the trip request (cities, dates, traveller ages,
  budget — no names, emails or payment data by construction) to an attacker host under
  unrestricted networking: documented accepted risk (`agents/environment.yaml`). It cannot place
  a clickable malicious link: the Plan model rejects non-https stop URLs, and `links.check_link`
  plus `plan_to_trip` drop any booking link outside the per-provider allowlist (verified
  deterministically on 2026-10-27).
- No CSP / X-Frame-Options on the web app: hardening, no concrete exploit with `SameSite=Lax`
  cookies.
