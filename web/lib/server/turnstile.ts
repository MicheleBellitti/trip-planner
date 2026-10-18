import "server-only";

import type { TurnstileAction } from "../turnstile";

/**
 * Server side of Cloudflare Turnstile (lib/turnstile.ts): one call to siteverify per submitted
 * token. The challenge is on only when both keys are set: `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (inlined
 * at build time: without it no widget is drawn, so no token could ever arrive) and
 * `TURNSTILE_SECRET_KEY` (without it nothing can be verified). Neither set is the development
 * default: every form passes. Only one set is a configuration error: the challenge stays off (a
 * secret alone would otherwise refuse every sign-in link and every join, since no widget issues
 * tokens) and the server logs it once, loudly. With both, a missing, spent or forged token fails,
 * and so does a token issued for another form (`action`) or another site (`hostname`), and so
 * does a siteverify that cannot be reached: the forms fail closed and ask to try again, since the
 * two surfaces write rows or send email. Nothing here logs a token or an address.
 */

const SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const TIMEOUT_MS = 5000;
const MAX_TOKEN_LENGTH = 2048;

/** Cloudflare's test secrets (always pass, always fail, token already spent): their answers carry
 * no real action or hostname, so those two checks are skipped for them. */
const TEST_SECRET = /^[123]x0{31}AA$/;

export type ChallengeVerdict = "passed" | "failed" | "off";

export interface VerifyOptions {
  secret?: string | undefined;
  siteKey?: string | undefined;
  /** The site's own URL (BETTER_AUTH_URL): a token must have been issued on its hostname. */
  siteUrl?: string | undefined;
  fetch?: typeof globalThis.fetch;
}

let warned = false;

/** Tests: log the configuration error again. */
export function resetTurnstileWarning(): void {
  warned = false;
}

/** The secret when the challenge is on (both keys set), else null; one key alone is logged once. */
function activeSecret(secret: string | undefined, siteKey: string | undefined): string | null {
  const key = secret?.trim() || null;
  const site = siteKey?.trim() || null;
  if (key && site) return key;
  if ((key || site) && !warned) {
    warned = true;
    console.error(
      key
        ? "[turnstile] TURNSTILE_SECRET_KEY is set but NEXT_PUBLIC_TURNSTILE_SITE_KEY was not at build time: no widget can issue tokens, so the challenge is OFF. Set both (and rebuild) or neither."
        : "[turnstile] NEXT_PUBLIC_TURNSTILE_SITE_KEY is set but TURNSTILE_SECRET_KEY is not: tokens cannot be verified, so the challenge is OFF. Set both or neither.",
    );
  }
  return null;
}

function hostnameOf(url: string | undefined): string | null {
  if (!url?.trim()) return null;
  try {
    return new URL(url.trim()).hostname;
  } catch {
    return null;
  }
}

/** The verdict on `token`, issued by the widget of the form `action`, for a request from
 * `remoteIp` (null when unknown). */
export async function verifyTurnstile(
  token: string | null,
  remoteIp: string | null,
  action: TurnstileAction,
  {
    secret = process.env.TURNSTILE_SECRET_KEY,
    siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY,
    siteUrl = process.env.BETTER_AUTH_URL,
    fetch = globalThis.fetch,
  }: VerifyOptions = {},
): Promise<ChallengeVerdict> {
  const key = activeSecret(secret, siteKey);
  if (!key) return "off";
  if (!token || token.length > MAX_TOKEN_LENGTH) return "failed";
  const body = new URLSearchParams({ secret: key, response: token });
  if (remoteIp) body.set("remoteip", remoteIp);
  let data: unknown;
  try {
    const response = await fetch(SITEVERIFY_URL, { method: "POST", body, signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!response.ok) {
      console.error("[turnstile] siteverify answered", response.status);
      return "failed";
    }
    data = await response.json();
  } catch (error) {
    console.error("[turnstile] siteverify failed", error instanceof Error ? error.name : typeof error);
    return "failed";
  }
  if (typeof data !== "object" || data === null) return "failed";
  const answer = data as { success?: unknown; action?: unknown; hostname?: unknown };
  if (answer.success !== true) return "failed";
  if (TEST_SECRET.test(key)) return "passed";
  if (answer.action !== action) {
    console.error("[turnstile] token issued for another form");
    return "failed";
  }
  const hostname = hostnameOf(siteUrl);
  if (hostname !== null && answer.hostname !== hostname) {
    console.error("[turnstile] token issued on another hostname");
    return "failed";
  }
  return "passed";
}
