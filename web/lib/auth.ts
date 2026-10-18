import "server-only";

import { betterAuth, type BetterAuthOptions } from "better-auth";
import { APIError } from "better-auth/api";
import { nextCookies } from "better-auth/next-js";
import { after } from "next/server";
import { magicLink } from "better-auth/plugins";

import { isSignupAllowed, normalizeEmail } from "./auth-policy";
import { readAuthConfig, type AuthServerConfig } from "./server/auth-config";
import { getPool } from "./server/db";
import { MAGIC_LINK_MINUTES, sendMagicLink } from "./server/send-magic-link";
import { isInvited } from "./server/waitlist";

/**
 * The app's own accounts: Better Auth 1.7, served by app/api/auth/[...all]/route.ts.
 *
 * - Sign-in: a magic link by email (lib/server/send-magic-link.ts) and Google. No passwords.
 * - Storage: the same Postgres as the backend. Alembic owns the tables (backend/app/db.py
 *   `users`, `auth_sessions`, `auth_accounts`, `auth_verifications`; migration 600fbb922f91), in
 *   snake_case through the `fields` mapping below; this file never creates or alters them.
 * - Cookie: `__Secure-atlas.session_token` (prefix `atlas`, so it never collides with
 *   TripTracker's `better-auth` cookie on the shared `bellittim.com` domain), with `Domain=` set
 *   to AUTH_COOKIE_DOMAIN so the API subdomain receives it. The backend verifies it against the
 *   `auth_sessions` table of the shared database (backend/app/auth.py `verify_atlas_session`):
 *   no call back to this app, so a sign-out is effective on its next request. `/get-session`
 *   stays exempt from the rate limit until no deployed backend asks it any more (`rateLimit`).
 * - Sign-up is by invitation: an address may create an account when it is in AUTH_ALLOWED_EMAILS
 *   (lib/auth-policy.ts: the bootstrap list and the `*` of a public launch) or when an admin
 *   invited it on the waitlist (lib/server/waitlist.ts `isInvited`, the day-to-day list).
 *   `user.create` is refused for every provider (Google's address is only known at its callback).
 *   Existing accounts always sign in.
 * - No enumeration (Michele, 2026-10-18: "uguale per tutti"): a magic-link request answers the
 *   same 200 whether or not the address may sign in; for one that may not, `sendMagicLink` sends
 *   nothing, so the link's token never leaves the server (and its verification would hit the
 *   `user.create` refusal anyway). For one that may, the email leaves after the response
 *   (`after()`), so the two also answer in the same time. The login form says "if the address is enabled, a link
 *   arrives" and offers the waitlist to everyone.
 *
 * `auth` is null when the accounts are not configured (`readAuthConfig`): the route answers 503
 * and the login page says so.
 */
export const SIGNUP_REFUSED_MESSAGE = "Questo indirizzo non ha ancora un invito.";

export const COOKIE_PREFIX = "atlas";

const DAY_SECONDS = 60 * 60 * 24;

/** What the accounts need besides the configuration; lib/auth.test.ts passes an in-memory database. */
export interface AuthDependencies {
  database: BetterAuthOptions["database"];
  /** True when the normalized address was invited on the waitlist. */
  isInvited: (email: string) => Promise<boolean>;
  /** Runs a task once the response has left: Next's `after()` in the app (the auth route handler
   * runs inside Next's request scope, where `after` is allowed); the tests record the tasks. */
  defer: (task: () => Promise<void>) => void;
}

/** A failure's message without anything shaped like an address, for the logs. */
export function redactAddresses(message: string): string {
  return message.replace(/[^\s@<>"'`]+@[^\s@<>"'`]+/g, "<address>");
}

export function buildAuth(config: AuthServerConfig, deps: AuthDependencies) {
  /** True when `email` may create an account: the allow list, or an invitation. */
  const mayCreateAccount = async (email: unknown): Promise<boolean> => {
    const address = typeof email === "string" ? email : null;
    if (isSignupAllowed(address, config.allowList)) return true;
    return address !== null && (await deps.isInvited(normalizeEmail(address)));
  };
  return betterAuth({
    appName: "Atlas",
    baseURL: config.baseUrl,
    secret: config.secret,
    database: deps.database,
    user: {
      modelName: "users",
      fields: { emailVerified: "email_verified", createdAt: "created_at", updatedAt: "updated_at" },
    },
    session: {
      modelName: "auth_sessions",
      fields: {
        expiresAt: "expires_at",
        createdAt: "created_at",
        updatedAt: "updated_at",
        ipAddress: "ip_address",
        userAgent: "user_agent",
        userId: "user_id",
      },
      // Sliding: a get-session that may refresh, at most once a day, extends the session to 30
      // days again. Only the browser's call from components/auth/session-refresh.tsx can (the
      // backend sends disableRefresh=true, /login's RSC check cannot write cookies).
      expiresIn: 30 * DAY_SECONDS,
      updateAge: DAY_SECONDS,
    },
    account: {
      modelName: "auth_accounts",
      fields: {
        accountId: "account_id",
        providerId: "provider_id",
        userId: "user_id",
        accessToken: "access_token",
        refreshToken: "refresh_token",
        idToken: "id_token",
        accessTokenExpiresAt: "access_token_expires_at",
        refreshTokenExpiresAt: "refresh_token_expires_at",
        createdAt: "created_at",
        updatedAt: "updated_at",
      },
    },
    verification: {
      modelName: "auth_verifications",
      fields: { expiresAt: "expires_at", createdAt: "created_at", updatedAt: "updated_at" },
    },
    advanced: {
      cookiePrefix: COOKIE_PREFIX,
      useSecureCookies: config.baseUrl.startsWith("https://"),
      crossSubDomainCookies: config.cookieDomain ? { enabled: true, domain: config.cookieDomain } : { enabled: false },
    },
    rateLimit: {
      // A backend from before the switch (contract rule 7: the web may ship first) checks every
      // request here from its one IP, and Better Auth's per-IP limit would turn those checks into
      // 429s. Drop this in a later PR, once the deployed backend no longer calls get-session.
      // Every other path keeps the defaults.
      customRules: { "/get-session": false },
    },
    socialProviders: config.google
      ? { google: { clientId: config.google.clientId, clientSecret: config.google.clientSecret } }
      : {},
    plugins: [
      magicLink({
        expiresIn: MAGIC_LINK_MINUTES * 60,
        sendMagicLink: async ({ email, url }, ctx) => {
          // The same answer for every address (no enumeration): one that may not sign in gets no
          // email, and the request still answers 200. The decision is taken here; the email itself
          // leaves after the response, so an enabled address does not answer later than a refused
          // one (Resend's round trip would tell them apart). Never log the address.
          const existing = ctx ? await ctx.context.internalAdapter.findUserByEmail(email) : null;
          if (!existing && !(await mayCreateAccount(email))) {
            console.info("[auth] magic link withheld: the address may not sign up");
            return;
          }
          deps.defer(async () => {
            try {
              await sendMagicLink(config, { email, url });
            } catch (error) {
              // It can no longer reach the browser: the sent state already says what to do when
              // nothing arrives. Logged here, and never thrown out of the deferred task.
              const message = error instanceof Error ? redactAddresses(error.message) : typeof error;
              console.error("[auth] sign-in email failed", message);
            }
          });
        },
      }),
      nextCookies(), // last, as its docs ask: it applies Set-Cookie from server actions
    ],
    databaseHooks: {
      user: {
        create: {
          before: async (user) => {
            if (!(await mayCreateAccount(user.email))) {
              throw new APIError("FORBIDDEN", { message: SIGNUP_REFUSED_MESSAGE, code: "SIGNUP_NOT_ALLOWED" });
            }
            return { data: user };
          },
        },
      },
    },
  });
}

export const authConfig = readAuthConfig();

function build(config: AuthServerConfig) {
  const pool = getPool(config.databaseUrl);
  return buildAuth(config, { database: pool, isInvited: (email) => isInvited(pool, email), defer: after });
}

export const auth = authConfig ? build(authConfig) : null;

export type Auth = NonNullable<typeof auth>;
