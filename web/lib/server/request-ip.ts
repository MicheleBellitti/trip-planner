import "server-only";

/**
 * The client's address behind Vercel, for the public forms' rate limit and Turnstile's
 * `remoteip`: Vercel sets `x-real-ip` and overwrites `x-forwarded-for` with the client's address
 * first, so neither can be forged there. Null when the request carries neither (a local call).
 */
export function clientIp(headers: Headers): string | null {
  const real = headers.get("x-real-ip")?.trim();
  if (real) return real;
  const forwarded = headers.get("x-forwarded-for");
  if (forwarded) {
    const first = forwarded.split(",")[0]?.trim();
    if (first) return first;
  }
  return null;
}
