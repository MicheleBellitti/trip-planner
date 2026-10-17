import "server-only";

import { parseAllowedEmails, type AllowList } from "@/lib/auth-policy";
import { stripTrailingSlash } from "@/lib/config";

/**
 * The server-side settings of the app's own accounts (lib/auth.ts), read from the environment
 * (web/.env.example, "Accounts"). None of these is NEXT_PUBLIC_*: they never reach the browser.
 *
 * `readAuthConfig()` answers null when `DATABASE_URL` is missing: the accounts are then "not
 * configured" (the login page says so, `/api/auth/*` answers 503), and the rest of the app works,
 * as TripTracker does. With a database, production needs the secret and a way to send the magic
 * link; development falls back to a fixed secret and prints the link to the server console.
 */
export interface AuthServerConfig {
  databaseUrl: string;
  /** Better Auth's signing secret (>= 32 characters). */
  secret: string;
  /** This app's public origin, the base of every callback URL, without a trailing slash. */
  baseUrl: string;
  /** `Domain=` of the session cookie, so the API subdomain receives it; unset = host-only. */
  cookieDomain: string | null;
  allowList: AllowList;
  google: { clientId: string; clientSecret: string } | null;
  /** Resend; null in development means "print the link instead of sending it". */
  email: { apiKey: string; from: string } | null;
  production: boolean;
}

const DEVELOPMENT_SECRET = "atlas-development-secret-never-use-in-production-0000";

function read(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value ? value : undefined;
}

function required(name: string, production: boolean, fallback?: string): string {
  const value = read(name);
  if (value) return value;
  if (!production && fallback !== undefined) return fallback;
  throw new Error(`${name} is not set: the accounts need it (web/.env.example, "Accounts").`);
}

let cached: AuthServerConfig | null | undefined;

export function readAuthConfig(): AuthServerConfig | null {
  if (cached !== undefined) return cached;
  const production = process.env.NODE_ENV === "production";
  const databaseUrl = read("DATABASE_URL");
  if (!databaseUrl) {
    cached = null;
    return cached;
  }
  const apiKey = read("RESEND_API_KEY");
  const from = read("AUTH_EMAIL_FROM");
  if (production && !(apiKey && from)) {
    throw new Error("RESEND_API_KEY and AUTH_EMAIL_FROM are not set: production cannot send the sign-in link.");
  }
  const clientId = read("GOOGLE_CLIENT_ID");
  const clientSecret = read("GOOGLE_CLIENT_SECRET");
  if ((clientId === undefined) !== (clientSecret === undefined)) {
    throw new Error("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET go together: set both or neither.");
  }
  cached = {
    databaseUrl,
    secret: required("BETTER_AUTH_SECRET", production, DEVELOPMENT_SECRET),
    baseUrl: stripTrailingSlash(required("BETTER_AUTH_URL", production, "http://localhost:3000")),
    cookieDomain: read("AUTH_COOKIE_DOMAIN") ?? null,
    allowList: parseAllowedEmails(process.env.AUTH_ALLOWED_EMAILS),
    google: clientId && clientSecret ? { clientId, clientSecret } : null,
    email: apiKey && from ? { apiKey, from } : null,
    production,
  };
  return cached;
}
