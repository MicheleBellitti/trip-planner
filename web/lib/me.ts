"use client";

/**
 * Who the signed-in user is to the backend (GET /me): whether they manage the planner
 * (`is_admin`, the backend's ADMIN_EMAILS: the header's "Valutazioni" and "Inviti" stations, which
 * only admins see) and their month against the per-user quota (`quota`: the usage line on the
 * plans page and under the request form, null for the users exempt from it). Every page asks again
 * when it mounts, so the figures follow the plan just created or continued; the readers of one page
 * share the request in flight, and the last answer is drawn at once while the fresh one is on its
 * way. The admin flag is also kept in sessionStorage so the next page of the same tab draws the
 * stations without waiting (a per-viewer convenience: a missing or blocked storage only costs the
 * wait). The quota is never stored: it changes with every plan. A 401 is "not an admin, no quota"
 * and never redirects from here: the page's own calls do that.
 */

import { useEffect, useSyncExternalStore } from "react";

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

/** The last answer of this page load, drawn at once by the next reader while it asks again, and
 * pushed to every mounted reader when a fresh one lands (a small external store: the server render
 * and the hydration read null, so a chunk that hydrates after the header's request answered still
 * matches the server's HTML). */
let known: Identity | null = null;
const listeners = new Set<() => void>();
/** The request in flight, shared by the readers that mount together. */
let pending: Promise<Identity> | null = null;

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

/** The answer of GET /me: a fresh request, unless one is already on its way; any failure means a
 * plain user. */
export function fetchMe(): Promise<Identity> {
  if (pending) return pending;
  const request: Promise<Identity> = createApiClient({ onUnauthorized: () => undefined })
    .me()
    .then(
      (me: Me): Identity => ({ isAdmin: me.is_admin, quota: me.quota }),
      () => NOBODY,
    )
    .then((identity) => {
      remember(identity.isAdmin);
      publish(identity);
      return identity;
    })
    .finally(() => {
      if (pending === request) pending = null;
    });
  pending = request;
  return request;
}

/** The admin flag alone, from the same shared request. */
export function fetchIsAdmin(): Promise<boolean> {
  return fetchMe().then((identity) => identity.isAdmin);
}

/** Tests: forget the request in flight and the last answer. */
export function resetMeCache(): void {
  pending = null;
  publish(null);
}

function subscribeToNothing(): () => void {
  return () => undefined;
}

/** The last answer while the fresh one is on its way (null on the first page of the load), then
 * the fresh one. Pages that need the quota read this; the header reads `useIsAdmin`, which also
 * knows what the tab remembered. */
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
 * answer once it arrives. */
export function useIsAdmin(): boolean | null {
  const stored = useRememberedAdmin();
  const fetched = useMe();
  return fetched === null ? stored : fetched.isAdmin;
}
