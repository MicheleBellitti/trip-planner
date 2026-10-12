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
