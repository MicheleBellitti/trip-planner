"use client";

/**
 * The Cloudflare Turnstile widget (lib/turnstile.ts), drawn only when `NEXT_PUBLIC_TURNSTILE_SITE_KEY`
 * is set: the script is loaded once per page, the widget rendered explicitly into this component's
 * box in the page's theme (and again when the theme changes), flexible width. Every token it
 * issues goes to `onToken` (null when it expired or failed); the form keeps it and sends it. A
 * token is single-use: after every submit the form calls `reset()` through the handle, and a new
 * token follows. Without a site key the component renders nothing and never calls back: the
 * forms then send no token, and the server, without its secret, checks none.
 */

import { useEffect, useImperativeHandle, useRef, type Ref } from "react";

import { TURNSTILE_SCRIPT_URL, turnstileSiteKey, type TurnstileAction } from "@/lib/turnstile";

import { DEFAULT_THEME, isThemeName, THEME_EVENT, type ThemeName } from "./theme";

interface TurnstileApi {
  render(container: HTMLElement, options: Record<string, unknown>): string;
  reset(widgetId: string): void;
  remove(widgetId: string): void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

export interface TurnstileHandle {
  /** Ask for a fresh token (the last one was sent, or refused). */
  reset(): void;
}

interface TurnstileProps {
  onToken: (token: string | null) => void;
  ref?: Ref<TurnstileHandle>;
  /** Cloudflare's `action`: which form (lib/turnstile.ts `TURNSTILE_ACTIONS`); the server checks
   * that a token comes back from the form it was issued for. */
  action: TurnstileAction;
  className?: string;
}

let scriptLoading: Promise<void> | null = null;

/** The script tag, once per page; resolves when `window.turnstile` exists. */
export function loadTurnstileScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve();
  scriptLoading ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = TURNSTILE_SCRIPT_URL;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptLoading = null;
      script.remove();
      reject(new Error("turnstile script did not load"));
    };
    document.head.appendChild(script);
  });
  return scriptLoading;
}

/** Tests: forget the script's promise. */
export function resetTurnstileScript(): void {
  scriptLoading = null;
}

function themeOnScreen(): ThemeName {
  const pinned = document.documentElement.getAttribute("data-theme");
  return isThemeName(pinned) ? pinned : DEFAULT_THEME;
}

export function Turnstile({ onToken, ref, action, className }: TurnstileProps) {
  const siteKey = turnstileSiteKey();
  const container = useRef<HTMLDivElement>(null);
  const widget = useRef<string | null>(null);
  const latest = useRef(onToken);

  useEffect(() => {
    latest.current = onToken;
  }, [onToken]);

  useImperativeHandle(
    ref,
    () => ({
      reset() {
        if (widget.current) window.turnstile?.reset(widget.current);
      },
    }),
    [],
  );

  useEffect(() => {
    if (!siteKey) return;
    let gone = false;
    const draw = async () => {
      try {
        await loadTurnstileScript();
      } catch {
        latest.current(null);
        return;
      }
      const api = window.turnstile;
      if (gone || !container.current || !api) return;
      if (widget.current) api.remove(widget.current);
      widget.current = api.render(container.current, {
        sitekey: siteKey,
        theme: themeOnScreen(),
        size: "flexible",
        action,
        callback: (token: string) => latest.current(token),
        "expired-callback": () => latest.current(null),
        "error-callback": () => latest.current(null),
      });
    };
    void draw();
    const redraw = () => void draw();
    window.addEventListener(THEME_EVENT, redraw);
    return () => {
      gone = true;
      window.removeEventListener(THEME_EVENT, redraw);
      if (widget.current) {
        window.turnstile?.remove(widget.current);
        widget.current = null;
      }
    };
  }, [siteKey, action]);

  if (!siteKey) return null;
  return <div ref={container} className={className} data-testid="turnstile" />;
}
