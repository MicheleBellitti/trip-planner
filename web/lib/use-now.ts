"use client";

import { useSyncExternalStore } from "react";

/** One shared one-second clock for every component that shows elapsed time. */
let current: number | null = null;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (timer === null) {
    current = Date.now();
    timer = setInterval(() => {
      current = Date.now();
      for (const notify of listeners) notify();
    }, 1000);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };
}

/** Milliseconds since the epoch, updated every second; null during server rendering and before
 * the first tick (render a placeholder then). */
export function useNow(): number | null {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
}
