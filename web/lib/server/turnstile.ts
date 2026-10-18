import "server-only";

/**
 * Server side of Cloudflare Turnstile (lib/turnstile.ts): one call to siteverify per submitted
 * token. `TURNSTILE_SECRET_KEY` unset means the challenge is off (development, and a deployment
 * that has not set it up): every form passes. With the key, a missing, spent or forged token
 * fails, and so does a siteverify that cannot be reached: the forms fail closed and ask to try
 * again, since the two surfaces write rows or send email. Nothing here logs a token or an address.
 */

const SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const TIMEOUT_MS = 5000;
const MAX_TOKEN_LENGTH = 2048;

export type ChallengeVerdict = "passed" | "failed" | "off";

export interface VerifyOptions {
  secret?: string | undefined;
  fetch?: typeof globalThis.fetch;
}

/** The verdict on `token` for a request from `remoteIp` (null when unknown). */
export async function verifyTurnstile(
  token: string | null,
  remoteIp: string | null,
  { secret = process.env.TURNSTILE_SECRET_KEY, fetch = globalThis.fetch }: VerifyOptions = {},
): Promise<ChallengeVerdict> {
  const key = secret?.trim();
  if (!key) return "off";
  if (!token || token.length > MAX_TOKEN_LENGTH) return "failed";
  const body = new URLSearchParams({ secret: key, response: token });
  if (remoteIp) body.set("remoteip", remoteIp);
  try {
    const response = await fetch(SITEVERIFY_URL, { method: "POST", body, signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!response.ok) {
      console.error("[turnstile] siteverify answered", response.status);
      return "failed";
    }
    const data: unknown = await response.json();
    const success = typeof data === "object" && data !== null && (data as { success?: unknown }).success === true;
    return success ? "passed" : "failed";
  } catch (error) {
    console.error("[turnstile] siteverify failed", error instanceof Error ? error.name : typeof error);
    return "failed";
  }
}
