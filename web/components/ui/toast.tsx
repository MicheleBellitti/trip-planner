"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { cx } from "./cx";
import { Icon } from "./icon";
import { IconButton } from "./icon-button";

export type ToastTone = "neutral" | "error";

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

/** Long enough to read two lines twice; errors stay until closed or replaced. */
const DISMISS_AFTER_MS = 5000;

let current: ToastItem | null = null;
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

/**
 * Shows one short message that confirms the user's own action ("Link copiato", "Interruzione
 * richiesta. Gli agenti chiudono il passo in corso.") or reports that it failed. One at a time:
 * a new toast replaces the old one. Never for stream events (lane changes have their own
 * aria-live region) and never amber.
 */
export function toast(message: string, options: { tone?: ToastTone } = {}): void {
  current = { id: nextId++, message, tone: options.tone ?? "neutral" };
  emit();
}

export function dismissToast(): void {
  current = null;
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * The toast region: render it once per page shell. The live region is always mounted (role
 * status, polite) so screen readers hear each message. Bottom of the screen above the safe area
 * on the phone, bottom left from 768 px. Enters with a 200 ms fade and 8 px rise (fade only with
 * reduced motion); a neutral toast leaves after 5 s unless hovered or focused.
 */
export function Toaster() {
  const item = useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
  const [paused, setPaused] = useState(false);
  const regionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!item || item.tone === "error" || paused) return;
    const timer = setTimeout(() => {
      if (current?.id === item.id) dismissToast();
    }, DISMISS_AFTER_MS);
    return () => clearTimeout(timer);
  }, [item, paused]);

  return (
    <div
      ref={regionRef}
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="pointer-events-none fixed inset-x-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-40 flex justify-center md:inset-x-auto md:bottom-7 md:left-7 md:justify-start"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(event) => {
        if (!regionRef.current?.contains(event.relatedTarget as Node | null)) setPaused(false);
      }}
    >
      {item ? (
        <div
          key={item.id}
          className={cx(
            "pointer-events-auto flex w-full max-w-[26rem] items-start gap-2.5 rounded-md border bg-surface py-2.5 pr-2 pl-3.5 text-small text-ink shadow-pop",
            "animate-fade-in motion-safe:animate-toast-in",
            item.tone === "error" ? "border-[color-mix(in_srgb,var(--error)_55%,transparent)]" : "border-rule",
          )}
        >
          {item.tone === "error" ? <Icon name="x-circle" size={17} className="mt-0.5 text-error" /> : null}
          <p className="min-w-0 flex-1 py-1">{item.message}</p>
          <IconButton icon="x" label="Chiudi il messaggio" size="sm" variant="bare" onClick={dismissToast} />
        </div>
      ) : null}
    </div>
  );
}
