/**
 * Public configuration of the web app, read from NEXT_PUBLIC_* variables (web/.env.example).
 *
 * Next.js inlines `process.env.NEXT_PUBLIC_*` into the browser bundle at build time, and only
 * for literal property reads, so each variable is read by name below. These values are public:
 * never put a secret in them.
 */

/**
 * Who signs the user in, mirroring the backend's AUTH_MODE (backend/app/config.py): `triptracker`
 * sends a 401 to TripTracker's `/accedi`, `atlas` to this app's own `/login` (lib/auth.ts).
 * The backend's `local` mode never answers 401, so the web app has no such value.
 */
export type AuthMode = "triptracker" | "atlas";

const AUTH_MODES: readonly AuthMode[] = ["triptracker", "atlas"];

export interface WebConfig {
  /** Base URL of the planner backend, without a trailing slash, e.g. http://localhost:8000. */
  apiUrl: string;
  /** TripTracker's origin, without a trailing slash: login (/accedi) and import (/import). */
  triptrackerUrl: string;
  /** Where a 401 sends the user: TripTracker's login or this app's own. */
  authMode: AuthMode;
}

/** Used only by `next dev` when web/.env.local is missing: the values of web/.env.example. A
 * production build never falls back, so a missing variable fails loudly instead of pointing the
 * deployed app at localhost. */
const DEVELOPMENT_DEFAULTS: WebConfig = {
  apiUrl: "http://localhost:8000",
  triptrackerUrl: "https://viaggi.bellittim.com",
  authMode: "atlas",
};

/** `NEXT_PUBLIC_AUTH_MODE`, or the mode a build without it keeps: `atlas` under `next dev`
 * (the login page is this app's), `triptracker` elsewhere (the deployed default until the switch,
 * so a build never fails for the lack of this one variable). Any other value is a configuration
 * error, not a silent fallback. */
export function parseAuthMode(value: string | undefined, nodeEnv: string | undefined): AuthMode {
  const chosen = value?.trim();
  if (!chosen) return nodeEnv === "development" ? DEVELOPMENT_DEFAULTS.authMode : "triptracker";
  if ((AUTH_MODES as readonly string[]).includes(chosen)) return chosen as AuthMode;
  throw new Error(`NEXT_PUBLIC_AUTH_MODE must be one of ${AUTH_MODES.join(", ")}, not "${chosen}".`);
}

export function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

function pick(value: string | undefined, fallback: string, name: string): string {
  const chosen = value?.trim() || (process.env.NODE_ENV === "development" ? fallback : "");
  if (!chosen) {
    throw new Error(`${name} is not set: copy web/.env.example to web/.env.local or set it in the deployment.`);
  }
  return stripTrailingSlash(chosen);
}

/** The configuration, read lazily so that rendering a page without it (a build without the
 * variables, a test) does not throw until something actually calls the backend. */
export function getConfig(): WebConfig {
  return {
    apiUrl: pick(process.env.NEXT_PUBLIC_API_URL, DEVELOPMENT_DEFAULTS.apiUrl, "NEXT_PUBLIC_API_URL"),
    triptrackerUrl: pick(
      process.env.NEXT_PUBLIC_TRIPTRACKER_URL,
      DEVELOPMENT_DEFAULTS.triptrackerUrl,
      "NEXT_PUBLIC_TRIPTRACKER_URL",
    ),
    authMode: getAuthMode(),
  };
}

/** The auth mode alone: readable without the other variables (the API client decides where a
 * 401 goes before it needs anything else). */
export function getAuthMode(): AuthMode {
  return parseAuthMode(process.env.NEXT_PUBLIC_AUTH_MODE, process.env.NODE_ENV);
}
