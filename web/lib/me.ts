"use client";

/**
 * Who the signed-in user is to the backend (GET /me): whether they manage the planner
 * (`is_admin`, the backend's ADMIN_EMAILS: the header's "Valutazioni" and "Inviti" stations, which
 * only admins see) and their month against the per-user quota (`quota`: the usage line on the
 * plans page and under the request form, null for the users exempt from it). One request per page
 * load, shared by every reader on the page; the admin flag is kept in sessionStorage so the next
 * page of the same tab draws the stations without waiting (a per-viewer convenience: a missing or
 * blocked storage only costs the wait). The quota is never stored: it changes with every plan. A
 * 401 is "not an admin, no quota" and never redirects from here: the page's own calls do that.
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import { ApiError, createApiClient } from "./api";
import { ADMIN_ONLY_CODE, type Me, type Quota } from "./schemas/api";

export const ADMIN_KEY = "atlas-admin";

/** The eval history's 403 for a signed-in user who is not an admin (routes `admin_only`). */
export function isAdminOnly(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.code === ADMIN_ONLY_CODE;
}

/** What the page knows once GET /me answered; a failure reads as a plain user with no quota. */
export interface Identity {
  isAdmin: boolean;
  quota: Quota | null;
}

const NOBODY: Identity = { isAdmin: false, quota: null };

let pending: Promise<Identity> | null = null;

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

/** The answer of GET /me, asked once per page load; any failure means a plain user. */
export function fetchMe(): Promise<Identity> {
  pending ??= createApiClient({ onUnauthorized: () => undefined })
    .me()
    .then(
      (me: Me): Identity => ({ isAdmin: me.is_admin, quota: me.quota }),
      () => NOBODY,
    )
    .then((identity) => {
      remember(identity.isAdmin);
      return identity;
    });
  return pending;
}

/** The admin flag alone, from the same shared request. */
export function fetchIsAdmin(): Promise<boolean> {
  return fetchMe().then((identity) => identity.isAdmin);
}

/** Tests: forget the shared request. */
export function resetMeCache(): void {
  pending = null;
}

function subscribeToNothing(): () => void {
  return () => undefined;
}

/** null until the answer arrives, then it. Pages that need the quota read this; the header reads
 * `useIsAdmin`, which also knows what the tab remembered. */
export function useMe(): Identity | null {
  const [identity, setIdentity] = useState<Identity | null>(null);
  useEffect(() => {
    let live = true;
    void fetchMe().then((value) => {
      if (live) setIdentity(value);
    });
    return () => {
      live = false;
    };
  }, []);
  return identity;
}

/** null until known, then the answer: what this tab remembered from an earlier page (read as an
 * external store, so the server render and the hydration see null and the client's first paint
 * after it sees the stored value), replaced by this page's own answer once it arrives. */
export function useIsAdmin(): boolean | null {
  const stored = useSyncExternalStore(subscribeToNothing, remembered, () => null);
  const fetched = useMe();
  return fetched === null ? stored : fetched.isAdmin;
}
