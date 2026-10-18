"use client";

/**
 * Who the signed-in user is to the backend (GET /me): whether they manage the planner
 * (`is_admin`, the backend's ADMIN_EMAILS: the header's "Collaudi" and "Inviti" stations, which
 * only admins see) and their month against the per-user quota (`quota`: the usage line on the
 * plans page and under the request form, null for the users exempt from it). Every page asks again
 * when it mounts, so the figures follow the plan just created or continued; the readers of one page
 * share the request in flight, and the last answer is drawn at once while the fresh one is on its
 * way. The admin flag is also kept in sessionStorage so the next page of the same tab draws the
 * stations without waiting (a per-viewer convenience: a missing or blocked storage only costs the
 * wait). The quota is never stored: it changes with every plan. Only an answer is kept: a failed
 * request is unknown, leaves the last answer and the tab's flag in place, and the next caller asks
 * again. A 401 is "not an admin, no quota" and never redirects from here (the page's own calls do
 * that); like every 401 it also forgets the stored flag (`markSignedOut`, lib/returning.ts), as a
 * sign-out does.
 */

import { useEffect, useSyncExternalStore } from "react";

import { ApiError, createApiClient, UnauthorizedError } from "./api";
import { ADMIN_KEY } from "./returning";
import { ADMIN_ONLY_CODE, type Me, type Quota } from "./schemas/api";

export { ADMIN_KEY };

/** The eval history's 403 for a signed-in user who is not an admin (routes `admin_only`). */
export function isAdminOnly(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.code === ADMIN_ONLY_CODE;
}

/** What the page knows once GET /me answered (a 401 reads as a plain user with no quota). */
export interface Identity {
  isAdmin: boolean;
  quota: Quota | null;
}

const NOBODY: Identity = { isAdmin: false, quota: null };

/** The last answer of this page load, drawn at once by the next reader while it asks again, and
 * pushed to every mounted reader when a fresh one lands (a small external store: the server render
 * and the hydration read null, so a chunk that hydrates after the header's request answered still
 * matches the server's HTML). */
let known: Identity | null = null;
const listeners = new Set<() => void>();
/** The request in flight, shared by the readers that mount together. */
let pending: Promise<Identity | null> | null = null;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function publish(identity: Identity | null): void {
  known = identity;
  for (const listener of listeners) listener();
}

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

/**
 * The answer of GET /me: a fresh request, unless one is already on its way. A 401 is a plain user
 * with no quota (the API client has already forgotten the stored flag); any other failure is null,
 * unknown: nothing is published or stored, so the last answer and what the tab remembered stand.
 */
export function fetchMe(): Promise<Identity | null> {
  if (pending) return pending;
  const request: Promise<Identity | null> = createApiClient({ onUnauthorized: () => undefined })
    .me()
    .then(
      (me: Me): Identity => {
        const identity = { isAdmin: me.is_admin, quota: me.quota };
        remember(identity.isAdmin);
        publish(identity);
        return identity;
      },
      (error: unknown): Identity | null => {
        if (!(error instanceof UnauthorizedError)) return null;
        publish(NOBODY);
        return NOBODY;
      },
    )
    .finally(() => {
      if (pending === request) pending = null;
    });
  pending = request;
  return request;
}

/** The admin flag alone, from the same shared request: null when unknown. */
export function fetchIsAdmin(): Promise<boolean | null> {
  return fetchMe().then((identity) => (identity === null ? null : identity.isAdmin));
}

/** Tests: forget the request in flight and the last answer. */
export function resetMeCache(): void {
  pending = null;
  publish(null);
}

function subscribeToNothing(): () => void {
  return () => undefined;
}

/** The last answer while the fresh one is on its way (null on the first page of the load, or
 * while nothing answered), then the fresh one. Pages that need the quota read this; the header
 * reads `useIsAdmin`, which also knows what the tab remembered. */
export function useMe(): Identity | null {
  const identity = useSyncExternalStore(subscribe, () => known, () => null);
  useEffect(() => {
    void fetchMe();
  }, []);
  return identity;
}

/** What this tab remembered of the admin flag from an earlier page, read as an external store
 * (the server render and the hydration see null, the client's first paint after it the stored
 * value); null when nothing is remembered. */
export function useRememberedAdmin(): boolean | null {
  return useSyncExternalStore(subscribeToNothing, remembered, () => null);
}

/** null until known, then the answer: what this tab remembered, replaced by this page's own
 * answer once it arrives (a failure other than a 401 leaves the remembered value in place). */
export function useIsAdmin(): boolean | null {
  const stored = useRememberedAdmin();
  const fetched = useMe();
  return fetched === null ? stored : fetched.isAdmin;
}
