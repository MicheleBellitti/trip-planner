/**
 * Public configuration of the web app, read from NEXT_PUBLIC_* variables (web/.env.example).
 *
 * Next.js inlines `process.env.NEXT_PUBLIC_*` into the browser bundle at build time, and only
 * for literal property reads, so each variable is read by name below. These values are public:
 * never put a secret in them.
 */

export interface WebConfig {
  /** Base URL of the planner backend, without a trailing slash, e.g. http://localhost:8000. */
  apiUrl: string;
  /** TripTracker's origin, without a trailing slash: login (/accedi) and import (/import). */
  triptrackerUrl: string;
}

/** Used only by `next dev` when web/.env.local is missing: the values of web/.env.example. A
 * production build never falls back, so a missing variable fails loudly instead of pointing the
 * deployed app at localhost. */
const DEVELOPMENT_DEFAULTS: WebConfig = {
  apiUrl: "http://localhost:8000",
  triptrackerUrl: "https://viaggi.bellittim.com",
};

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
  };
}
