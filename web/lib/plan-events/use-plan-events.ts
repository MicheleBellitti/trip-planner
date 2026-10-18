"use client";

/**
 * usePlanEvents(planId): the live timeline of a plan, from GET /plans/{id}/events (SSE).
 *
 * - Opens `new EventSource(url, { withCredentials: true })`: the session cookie travels to
 *   the backend's origin.
 * - Validates every message with Zod (./stream.ts); an invalid one is dropped and counted.
 * - Resumes from the last received id: on its own reconnections the browser sends
 *   `Last-Event-ID` (the backend replays from Postgres); when the browser gives up (an HTTP
 *   error closes the EventSource for good) the hook reconnects itself with backoff and
 *   `?after=<last seq>`, because a new EventSource starts without Last-Event-ID. A remount
 *   (route hidden and shown again) also resumes with `?after=`.
 * - `event: end` dispatches the plan's terminal status and closes the stream for good.
 * - Exposes the connection status (connecting, open, reconnecting, closed) for the discreet
 *   "Stream in riconnessione" line.
 * - Feeds a pure reducer (./reducer.ts) in small batches, so a replay of hundreds of events
 *   renders a few times, not once per event.
 */

import { useCallback, useEffect, useEffectEvent, useReducer, useRef, useState } from "react";

import { api } from "../api";
import type { PlanDetail, PlanStatus } from "../schemas/api";
import type { UIEvent } from "../schemas/generated/ui-event";
import type { ConnectionStatus } from "./labels";
import { initialPlanLiveState, planEventsReducer, type PlanLiveState } from "./reducer";
import { END_EVENT, parseStreamEnd, parseUIEvent } from "./stream";

/** EventSource readyState values (the constants are not on every implementation's instance). */
const CONNECTING = 0;

export const DEFAULT_BATCH_MS = 32;

/** Manual reconnection backoff: 1 s, 2 s, 4 s ... capped at 30 s. */
export function defaultReconnectDelay(attempt: number): number {
  return Math.min(1000 * 2 ** Math.max(0, attempt - 1), 30_000);
}

type EventSourceConstructor = new (url: string, init?: EventSourceInit) => EventSource;

export interface UsePlanEventsOptions {
  /** A GET /plans/{id} snapshot: status, cost, budget and timestamps before the stream catches
   * up. Dispatched every time a new object is passed. */
  detail?: PlanDetail | null;
  /** False to stay disconnected (e.g. until the snapshot says the plan exists). */
  enabled?: boolean;
  /** The stream URL; defaults to `api.eventsUrl` (NEXT_PUBLIC_API_URL). */
  eventsUrl?: (planId: string, after: number | null) => string;
  /** Defaults to the global EventSource. */
  EventSource?: EventSourceConstructor;
  /** Called before each manual reconnection (after the browser gave up on the stream), e.g. to
   * call GET /plans/{id}: a 401 there redirects to login, a 404 means stop. Resolve false to
   * stay closed. A throw counts as "try again". */
  beforeReconnect?: () => boolean | Promise<boolean>;
  /** Delay before manual reconnection attempt `n` (1-based). */
  reconnectDelay?: (attempt: number) => number;
  /** Events arriving within this window are reduced together; 0 reduces each at once. */
  batchMs?: number;
  /** Every valid event, as it arrives (e.g. to refetch the snapshot on a status change). */
  onEvent?: (event: UIEvent) => void;
  /** The stream ended with this terminal status. */
  onEnd?: (status: PlanStatus) => void;
}

export interface UsePlanEventsResult {
  state: PlanLiveState;
  connection: ConnectionStatus;
  /** Messages dropped because they failed validation. */
  dropped: number;
  /** Close the stream and open a new one after the last received seq ("Riprova"). Does
   * nothing once the stream has ended. */
  reconnect: () => void;
}

export function usePlanEvents(planId: string | null, options: UsePlanEventsOptions = {}): UsePlanEventsResult {
  const { detail = null, enabled = true, batchMs = DEFAULT_BATCH_MS } = options;
  const [state, dispatch] = useReducer(planEventsReducer, undefined, initialPlanLiveState);
  const [connection, setConnection] = useState<ConnectionStatus>("connecting");
  const [dropped, setDropped] = useState(0);
  const [attemptKey, setAttemptKey] = useState(0);

  // Stream bookkeeping that must be current inside EventSource callbacks.
  const planIdRef = useRef<string | null>(planId);
  const lastSeqRef = useRef<number | null>(null);
  const endedRef = useRef(false);

  const streamUrl = useEffectEvent((id: string, after: number | null) =>
    (options.eventsUrl ?? api.eventsUrl)(id, after),
  );
  const createSource = useEffectEvent((url: string) => {
    const Source = options.EventSource ?? (globalThis.EventSource as EventSourceConstructor | undefined);
    if (!Source) throw new Error("EventSource is not available in this environment");
    return new Source(url, { withCredentials: true });
  });
  const shouldReconnect = useEffectEvent(async () => (options.beforeReconnect ? options.beforeReconnect() : true));
  const reconnectDelay = useEffectEvent((attempt: number) =>
    (options.reconnectDelay ?? defaultReconnectDelay)(attempt),
  );
  const notifyEvent = useEffectEvent((event: UIEvent) => options.onEvent?.(event));
  const notifyEnd = useEffectEvent((status: PlanStatus) => options.onEnd?.(status));

  // Effects run in declaration order: a new plan resets the state before its snapshot lands.
  useEffect(() => {
    if (planIdRef.current !== planId) {
      planIdRef.current = planId;
      lastSeqRef.current = null;
      endedRef.current = false;
      dispatch({ type: "reset" });
    }
  }, [planId]);

  useEffect(() => {
    if (detail && detail.id === planId) dispatch({ type: "detail", detail });
  }, [detail, planId]);

  useEffect(() => {
    if (!planId || !enabled || endedRef.current) return;

    let disposed = false;
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    const buffer: UIEvent[] = [];

    const update = (status: ConnectionStatus) => {
      if (!disposed) setConnection(status);
    };
    const flush = () => {
      if (flushTimer) clearTimeout(flushTimer);
      flushTimer = null;
      if (buffer.length > 0) dispatch({ type: "events", events: buffer.splice(0) });
    };
    const enqueue = (event: UIEvent) => {
      buffer.push(event);
      if (batchMs <= 0) flush();
      else flushTimer ??= setTimeout(flush, batchMs);
    };
    const close = () => {
      if (source) {
        source.onopen = null;
        source.onmessage = null;
        source.onerror = null;
        source.close();
      }
      source = null;
    };

    const scheduleReconnect = () => {
      attempt += 1;
      retryTimer = setTimeout(async () => {
        retryTimer = null;
        let proceed = true;
        try {
          proceed = await shouldReconnect();
        } catch {
          proceed = true;
        }
        if (disposed) return;
        if (proceed) open();
        else update("closed");
      }, reconnectDelay(attempt));
    };

    const open = () => {
      const es = createSource(streamUrl(planId, lastSeqRef.current));
      source = es;
      es.onopen = () => {
        attempt = 0;
        update("open");
      };
      es.onmessage = (message: MessageEvent) => {
        const event = parseUIEvent(message.data);
        if (!event) {
          if (!disposed) setDropped((count) => count + 1);
          return;
        }
        if (lastSeqRef.current === null || event.seq > lastSeqRef.current) lastSeqRef.current = event.seq;
        enqueue(event);
        notifyEvent(event);
      };
      es.addEventListener(END_EVENT, (message: Event) => {
        flush();
        endedRef.current = true;
        close();
        const status = parseStreamEnd((message as MessageEvent).data);
        if (status) {
          dispatch({ type: "end", status });
          notifyEnd(status);
        }
        update("closed");
      });
      es.onerror = () => {
        if (disposed || source !== es || endedRef.current) return;
        if (es.readyState === CONNECTING) {
          // The browser reconnects by itself and sends Last-Event-ID.
          update("reconnecting");
          return;
        }
        // CLOSED: the browser gave up (HTTP error, wrong content type). Take over.
        close();
        update("reconnecting");
        scheduleReconnect();
      };
    };

    update("connecting");
    open();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      flush();
      close();
    };
  }, [planId, enabled, attemptKey, batchMs]);

  const reconnect = useCallback(() => {
    if (!endedRef.current) setAttemptKey((key) => key + 1);
  }, []);

  return { state, connection: planId && enabled ? connection : "closed", dropped, reconnect };
}
