"use client";

/**
 * Whether the signed-in user manages the planner (GET /me `is_admin`: the backend's ADMIN_EMAILS),
 * for the header's "Collaudi" station, which only admins see. One request per page load,
 * shared by every header on the page; the answer is kept in sessionStorage so the next page of
 * the same tab draws the station without waiting (a per-viewer convenience: a missing or blocked
 * storage only costs the wait). A 401 is "not an admin" and never redirects from here: the page's
 * own calls do that.
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import { ApiError, createApiClient } from "./api";
import { ADMIN_ONLY_CODE } from "./schemas/api";

export const ADMIN_KEY = "atlas-admin";

/** The eval history's 403 for a signed-in user who is not an admin (routes `admin_only`). */
export function isAdminOnly(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.code === ADMIN_ONLY_CODE;
}

let pending: Promise<boolean> | null = null;

function remembered(): boolean | null {
  try {
    const value = sessionStorage.getItem(ADMIN_KEY);
    return value === "1" ? true : value === "0" ? false : null;
  } catch {
    return null;
  }
}

function remember(isAdmin: boolean): void {
  try {
    sessionStorage.setItem(ADMIN_KEY, isAdmin ? "1" : "0");
  } catch {
    // Storage blocked: the next page asks again.
  }
}

/** The answer of GET /me, asked once per page load; any failure means "not an admin". */
export function fetchIsAdmin(): Promise<boolean> {
  pending ??= createApiClient({ onUnauthorized: () => undefined })
    .me()
    .then(
      (me) => me.is_admin,
      () => false,
    )
    .then((isAdmin) => {
      remember(isAdmin);
      return isAdmin;
    });
  return pending;
}

/** Tests: forget the shared request. */
export function resetMeCache(): void {
  pending = null;
}

function subscribeToNothing(): () => void {
  return () => undefined;
}

/** null until known, then the answer: what this tab remembered from an earlier page (read as an
 * external store, so the server render and the hydration see null and the client's first paint
 * after it sees the stored value), replaced by this page's own answer once it arrives. */
export function useIsAdmin(): boolean | null {
  const stored = useSyncExternalStore(subscribeToNothing, remembered, () => null);
  const [fetched, setFetched] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    void fetchIsAdmin().then((value) => {
      if (live) setFetched(value);
    });
    return () => {
      live = false;
    };
  }, []);
  return fetched ?? stored;
}
