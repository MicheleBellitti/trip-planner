/**
 * Cloudflare Turnstile on the public forms (the landing's waitlist join, the login's magic-link
 * request): what the browser and the server share. The widget (components/ui/turnstile.tsx)
 * puts its token in the form field `TURNSTILE_FIELD` (Cloudflare's own name) or, for the
 * magic-link request, in the header `TURNSTILE_HEADER`; the server verifies it
 * (lib/server/turnstile.ts). Without a site key nothing is drawn; the server checks only when both
 * the site key and the secret are set (one alone is logged as a configuration error and checks
 * nothing): the development default, and the deployed state until the keys are set
 * (docs/deploy.md).
 */

export const TURNSTILE_SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

/** The hidden field a form sends the token in. */
export const TURNSTILE_FIELD = "cf-turnstile-response";

/** The header the magic-link request sends the token in (Better Auth's body is its own). */
export const TURNSTILE_HEADER = "x-turnstile-token";

/** Cloudflare's `action` of each form's widget; the server checks that a token was issued for the
 * form that sends it (lib/server/turnstile.ts). */
export const TURNSTILE_ACTIONS = { login: "login", waitlist: "waitlist" } as const;
export type TurnstileAction = (typeof TURNSTILE_ACTIONS)[keyof typeof TURNSTILE_ACTIONS];

/** What the forms say when the challenge was not passed. */
export const CHALLENGE_FAILED_MESSAGE = "Conferma di non essere un robot e riprova.";

/** `NEXT_PUBLIC_TURNSTILE_SITE_KEY`, inlined at build time; null when unset (no challenge). */
export function turnstileSiteKey(): string | null {
  const key = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY?.trim();
  return key ? key : null;
}
