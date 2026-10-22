"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import type { ConnectionStatus } from "@/lib/plan-events/labels";

/** The lanes leave the stacked cards at DESIGN.md's `lg` breakpoint (1080 px): every lane is open
 * and the live tool repeats under the lane's name. */
const DESKTOP_QUERY = "(min-width: 67.5rem)";
/** From `xl` (1280 px) all five lanes are columns; between `lg` and `xl` the coordinator has a
 * full-width row and the four subagents share the one below. */
const COLUMNS_QUERY = "(min-width: 80rem)";

/** `matchMedia` is missing in some test and embedded environments: nothing matches there. */
function matches(query: string): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(query).matches;
}

function subscribeMedia(query: string) {
  return (onChange: () => void) => {
    if (typeof window.matchMedia !== "function") return () => {};
    const media = window.matchMedia(query);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  };
}

const subscribeDesktop = subscribeMedia(DESKTOP_QUERY);
const subscribeColumns = subscribeMedia(COLUMNS_QUERY);

/** True from 1080 px: lanes are columns, every lane is open, the live tool repeats under the
 * lane's name. False during server rendering (the phone layout is the reference). */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(
    subscribeDesktop,
    () => matches(DESKTOP_QUERY),
    () => false,
  );
}

export type LaneLayout = "stack" | "rows" | "columns";

/** How the lanes are laid out: stacked cards on the phone, the coordinator's row over a row of
 * four subagents from 1080 px, five columns from 1280 px. */
export function useLaneLayout(): LaneLayout {
  const desktop = useIsDesktop();
  const columns = useSyncExternalStore(
    subscribeColumns,
    () => matches(COLUMNS_QUERY),
    () => false,
  );
  if (!desktop) return "stack";
  return columns ? "columns" : "rows";
}

function subscribeOnline(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

/** False while the browser says it has no network (the page then shows its last known state,
 * marked as not updated). True during server rendering. */
export function useOnline(): boolean {
  return useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine,
    () => true,
  );
}

/** `clock` minus a server instant, when both are numbers: never NaN, which would differ from
 * itself and render again and again. */
function gapTo(clock: number, instant: string | null | undefined): number | null {
  const gap = instant ? clock - Date.parse(instant) : Number.NaN;
  return Number.isFinite(gap) ? gap : null;
}

/**
 * How far the browser's clock runs ahead of the server's, in ms (negative when it runs behind).
 *
 * - `serverNow` is the server's clock when it made its latest answer (GET /plans/{id}'s `now`).
 *   Each new value (compared by value) sets the skew to `clock` minus it, replacing what came
 *   before: a near-exact sample (high by the answer's delivery, low by at most the clock's
 *   one-second tick), and the way a device clock stepped forward since the last one heals.
 * - `timestamps` are the other server instants the page holds (the newest event's ts, the
 *   snapshot's updated_at). One never postdates its arrival, so `clock` minus it errs high, by the
 *   delivery delay (minutes after a reload in a quiet pause): they can only lower the skew, until
 *   the next `serverNow`. From a backend without `now` they are all there is.
 *
 * Kept while the page lives, across reconnects. 0 until the first sample; no sample with a null
 * `clock` (pass null too when the clock is not the browser's).
 */
export function useClockSkew(
  clock: number | null,
  serverNow: string | null | undefined,
  timestamps: readonly (string | null | undefined)[],
): number {
  const [kept, setKept] = useState<{ skew: number | null; serverNow: string | null }>({ skew: null, serverNow: null });
  let { skew, serverNow: sampled } = kept;
  if (clock !== null) {
    const fresh = serverNow && serverNow !== sampled ? gapTo(clock, serverNow) : null;
    if (fresh !== null) {
      skew = fresh;
      sampled = serverNow ?? null;
    }
    for (const timestamp of timestamps) {
      const gap = gapTo(clock, timestamp);
      if (gap !== null && (skew === null || gap < skew)) skew = gap;
    }
  }
  if (skew !== kept.skew || sampled !== kept.serverNow) setKept({ skew, serverNow: sampled });
  return skew ?? 0;
}

/** How long after the stream opens its replay of history counts as settled. */
export const SETTLE_MS = 600;

export interface LiveBaseline {
  /** Stations after this seq arrived live: they draw in (`fresh`). Null until settled. */
  freshAfterSeq: number | null;
  /** Lane announcements after this id are spoken. Null until settled. */
  announceAfterId: number | null;
}

/**
 * When the stream opens, the backend first replays the plan's history: none of it is news. A
 * moment after the first open, the newest seq and announcement are remembered; only what comes
 * after them animates in and is announced (aria-live, lane state changes only). The values are
 * read in the render after the moment passed, so every event received before it is counted.
 */
export function useLiveBaseline(connection: ConnectionStatus, lastSeq: number | null, announcementId: number | null): LiveBaseline {
  const [due, setDue] = useState(false);
  const [baseline, setBaseline] = useState<LiveBaseline>({ freshAfterSeq: null, announceAfterId: null });
  const opened = connection === "open" || connection === "closed";

  if (due && baseline.freshAfterSeq === null) {
    setBaseline({ freshAfterSeq: lastSeq ?? -1, announceAfterId: announcementId ?? 0 });
  }

  useEffect(() => {
    if (due || !opened) return;
    const timer = setTimeout(() => setDue(true), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [due, opened]);

  return baseline;
}
