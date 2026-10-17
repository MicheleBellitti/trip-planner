import "server-only";

import { betterAuth } from "better-auth";
import { APIError, createAuthMiddleware } from "better-auth/api";
import { nextCookies } from "better-auth/next-js";
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
 *   no call back to this app, so a sign-out is effective on its next request.
 * - Sign-up is by invitation: an address may create an account when it is in AUTH_ALLOWED_EMAILS
 *   (lib/auth-policy.ts: the bootstrap list and the `*` of a public launch) or when an admin
 *   invited it on the waitlist (lib/server/waitlist.ts `isInvited`, the day-to-day list). The
 *   magic-link request is refused before any email leaves, and `user.create` is refused for every
 *   provider (Google's address is only known at its callback). Existing accounts always sign in.
 *
 * `auth` is null when the accounts are not configured (`readAuthConfig`): the route answers 503
 * and the login page says so.
 */
export const SIGNUP_REFUSED_MESSAGE = "Questo indirizzo non ha ancora un invito.";

export const COOKIE_PREFIX = "atlas";

const DAY_SECONDS = 60 * 60 * 24;

function build(config: AuthServerConfig) {
  const pool = getPool(config.databaseUrl);
  const refuseUnlessAllowed = async (email: unknown) => {
    const address = typeof email === "string" ? email : null;
    if (isSignupAllowed(address, config.allowList)) return;
    if (address && (await isInvited(pool, normalizeEmail(address)))) return;
    throw new APIError("FORBIDDEN", { message: SIGNUP_REFUSED_MESSAGE, code: "SIGNUP_NOT_ALLOWED" });
  };
  return betterAuth({
    appName: "Atlas",
    baseURL: config.baseUrl,
    secret: config.secret,
    database: pool,
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
    socialProviders: config.google
      ? { google: { clientId: config.google.clientId, clientSecret: config.google.clientSecret } }
      : {},
    plugins: [
      magicLink({
        expiresIn: MAGIC_LINK_MINUTES * 60,
        sendMagicLink: async ({ email, url }) => {
          await sendMagicLink(config, { email, url });
        },
      }),
      nextCookies(), // last, as its docs ask: it applies Set-Cookie from server actions
    ],
    hooks: {
      before: createAuthMiddleware(async (ctx) => {
        // Refuse a magic-link request for an address that may not sign up before any email is
        // sent; an address that already has an account is always let through.
        if (ctx.path !== "/sign-in/magic-link") return;
        const email = (ctx.body as { email?: unknown } | undefined)?.email;
        if (typeof email !== "string") return;
        const existing = await ctx.context.internalAdapter.findUserByEmail(email);
        if (existing) return;
        await refuseUnlessAllowed(email);
      }),
    },
    databaseHooks: {
      user: {
        create: {
          before: async (user) => {
            await refuseUnlessAllowed(user.email);
            return { data: user };
          },
        },
      },
    },
  });
}

export const authConfig = readAuthConfig();

export const auth = authConfig ? build(authConfig) : null;

export type Auth = NonNullable<typeof auth>;
