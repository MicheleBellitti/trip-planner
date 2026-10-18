"use client";

import { useEffect } from "react";

import { authClient } from "@/lib/auth-client";
import { getAuthMode } from "@/lib/config";

/** One call per page load, however many headers mount (the plan page swaps its skeleton's bar). */
let asked = false;

/**
 * Keeps a daily user signed in (`AUTH_MODE=atlas`). The session lasts 30 days and Better Auth
 * extends it (and re-sets the cookie) only when get-session runs without `disableRefresh` and can
 * write cookies, once `updateAge` (1 day) has passed since the last extension (lib/auth.ts). No
 * other call can: the backend always sends `disableRefresh=true` and /login's server check runs
 * in an RSC, where nextCookies skips the refresh. So every signed-in page asks once from the
 * browser, a same-origin GET whose answer may carry the extended cookie. It renders nothing, and a
 * failure changes nothing: the API's own 401 still decides when the user must sign in again.
 */
export function SessionRefresh() {
  useEffect(() => {
    if (asked || getAuthMode() !== "atlas") return;
    asked = true;
    authClient.getSession().catch(() => undefined);
  }, []);
  return null;
}
