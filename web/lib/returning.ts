/**
 * Returning visitors skip the landing (brand spec, "Returning visitors skip the landing"). The API
 * client marks the browser after a successful authenticated call and clears the mark on a 401. An
 * inline script on "/" (lib/skip-landing.ts, kept apart so the API client's bundle carries only
 * these two functions) reads it before paint. The mark holds no personal data, and every storage
 * access fails safe to "show the landing".
 */
export const SIGNED_IN_KEY = "atlas-signed-in";

export function markSignedIn(): void {
  try {
    localStorage.setItem(SIGNED_IN_KEY, "1");
  } catch {
    // Storage blocked: the landing simply shows next time.
  }
}

export function markSignedOut(): void {
  try {
    localStorage.removeItem(SIGNED_IN_KEY);
  } catch {
    // Storage blocked: nothing was stored either.
  }
}
