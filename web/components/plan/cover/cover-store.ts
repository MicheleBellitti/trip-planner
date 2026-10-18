"use client";

/**
 * Where destination covers are read once and kept for the page's life (GET /plans/{id}/cover).
 * The home list draws up to twenty thumbnails and the plan page draws the band of one of them: the
 * list asks as the rows come near the viewport, the plan page finds the answer already there and
 * draws the photo with no wait.
 *
 * - A cover is `ready`, or `none` (404 `cover_unavailable`: the screens work without a photo).
 *   Both are kept. A failure that says nothing about the destination (offline, 5xx, an answer
 *   that breaks the contract) is `none` for now and asked again the next time a screen asks.
 * - At most `MAX_IN_FLIGHT` requests go out together, so a list of twenty plans does not open
 *   twenty connections at once (the first lookup of a destination can take a second or two).
 * - Nothing here reads the clock or the network while rendering: `useCover` only subscribes, and
 *   `requestCover` is called from effects.
 */

import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";

import type { Cover } from "@/lib/schemas/api";

import { uniqueCovers } from "./cover-sources";

export type CoverState =
  /** Nobody has asked yet (also what the server render shows). */
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; cover: Cover }
  /** No photo to show. `retry`: the answer was a failure, not a 404. */
  | { kind: "none"; retry: boolean };

/** Loads a plan's cover: the page that shows it passes one (GET /plans/{id}/cover on the live
 * pages, a bundled copy in the demo); with none, nothing is requested. */
export type CoverLoader = (planId: string) => Promise<Cover | null>;

export const MAX_IN_FLIGHT = 4;

const IDLE: CoverState = { kind: "idle" };
const LOADING: CoverState = { kind: "loading" };
const NONE: CoverState = { kind: "none", retry: false };
const FAILED: CoverState = { kind: "none", retry: true };

const states = new Map<string, CoverState>();
const listeners = new Set<() => void>();
const queue: Array<() => void> = [];
let inFlight = 0;

function emit(): void {
  for (const listener of [...listeners]) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function stateOf(planId: string): CoverState {
  return states.get(planId) ?? IDLE;
}

function pump(): void {
  while (inFlight < MAX_IN_FLIGHT) {
    const next = queue.shift();
    if (!next) return;
    next();
  }
}

/** Starts reading a plan's cover unless it is known (or on its way). Safe to call on every
 * render of an effect: it does nothing twice. */
export function requestCover(planId: string, load: CoverLoader): void {
  const known = states.get(planId);
  if (known && !(known.kind === "none" && known.retry)) return;
  states.set(planId, LOADING);
  emit();
  queue.push(() => {
    inFlight += 1;
    let result: Promise<Cover | null>;
    try {
      result = Promise.resolve(load(planId));
    } catch (error) {
      result = Promise.reject(error);
    }
    result.then(
      (cover) => states.set(planId, cover ? { kind: "ready", cover } : NONE),
      () => states.set(planId, FAILED),
    ).finally(() => {
      inFlight -= 1;
      emit();
      pump();
    });
  });
  pump();
}

/** A plan's cover state; it re-renders when the answer arrives. `enabled` false only watches (a
 * row that has not come near the viewport yet does not ask). The latest `load` is used; a new
 * function on every render does not ask again. */
export function useCover(planId: string, enabled = true, load?: CoverLoader): CoverState {
  const state = useSyncExternalStore(
    subscribe,
    () => stateOf(planId),
    () => IDLE,
  );
  const loader = useRef(load);
  useEffect(() => {
    loader.current = load;
  });
  useEffect(() => {
    // No loader, no request: the page that shows the cover says where it comes from (the live
    // pages read GET /plans/{id}/cover, the demo its own copy), so this store needs no client.
    if (enabled && loader.current) requestCover(planId, loader.current);
  }, [planId, enabled]);
  return state;
}

/** The photos the plans have right now, each photo once, in the plans' order: what the home list's
 * credit is written from. It re-renders when an answer arrives (the answer is "ready" only for
 * the rows that came near the viewport and asked, so it is what the person can see). */
export function useShownCovers(planIds: readonly string[]): Cover[] {
  // The snapshot is a string, so React can tell "the same set" without a new array every time.
  const ready = useSyncExternalStore(
    subscribe,
    () => planIds.filter((id) => stateOf(id).kind === "ready").join("|"),
    () => "",
  );
  return useMemo(() => {
    const covers: Cover[] = [];
    for (const id of ready ? ready.split("|") : []) {
      const state = stateOf(id);
      if (state.kind === "ready") covers.push(state.cover);
    }
    return uniqueCovers(covers);
  }, [ready]);
}

/** Forgets everything. For tests. */
export function resetCoverStore(): void {
  states.clear();
  queue.length = 0;
  inFlight = 0;
  emit();
}
