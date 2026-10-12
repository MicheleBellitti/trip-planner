import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UIEventSchema, type UIEvent } from "../schemas/generated/ui-event";
import happyPath from "./__fixtures__/happy-path.json";
import { defaultReconnectDelay, usePlanEvents, type UsePlanEventsOptions } from "./use-plan-events";

const PLAN_ID = happyPath.plan_id;
const EVENTS: UIEvent[] = happyPath.events.map((event) => UIEventSchema.parse(event));

/** A scriptable EventSource: the test drives open, messages, errors and `end`. */
class MockEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: MockEventSource[] = [];

  readonly url: string;
  readonly withCredentials: boolean;
  readyState = MockEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private listeners = new Map<string, Set<(event: Event) => void>>();

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    MockEventSource.instances.push(this);
  }

  static latest(): MockEventSource {
    const source = MockEventSource.instances[MockEventSource.instances.length - 1];
    if (!source) throw new Error("no EventSource was opened");
    return source;
  }

  addEventListener(type: string, listener: (event: Event) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(listener);
  }

  removeEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.readyState = MockEventSource.CLOSED;
  }

  // --- test controls ---

  open(): void {
    this.readyState = MockEventSource.OPEN;
    this.onopen?.(new Event("open"));
  }

  send(event: UIEvent | string): void {
    const data = typeof event === "string" ? event : JSON.stringify(event);
    const lastEventId = typeof event === "string" ? "" : String(event.seq);
    this.onmessage?.(new MessageEvent("message", { data, lastEventId }));
  }

  end(status: string): void {
    const message = new MessageEvent("end", { data: JSON.stringify({ status }) });
    for (const listener of this.listeners.get("end") ?? []) listener(message);
  }

  /** The connection dropped; the browser will retry by itself (readyState CONNECTING). */
  drop(): void {
    this.readyState = MockEventSource.CONNECTING;
    this.onerror?.(new Event("error"));
  }

  /** The browser gave up (e.g. an HTTP error status): readyState CLOSED, no automatic retry. */
  fail(): void {
    this.readyState = MockEventSource.CLOSED;
    this.onerror?.(new Event("error"));
  }
}

const eventsUrl = (planId: string, after: number | null) =>
  `https://api.test/plans/${planId}/events${after === null ? "" : `?after=${after}`}`;

interface HookProps {
  id: string | null;
  opts: UsePlanEventsOptions;
}

function options(extra: UsePlanEventsOptions = {}): UsePlanEventsOptions {
  return {
    eventsUrl,
    EventSource: MockEventSource as unknown as typeof EventSource,
    batchMs: 0,
    reconnectDelay: () => 1000,
    ...extra,
  };
}

function render(extra: UsePlanEventsOptions = {}, planId: string | null = PLAN_ID) {
  return renderHook(({ id, opts }: HookProps) => usePlanEvents(id, opts), {
    initialProps: { id: planId, opts: options(extra) },
  });
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("usePlanEvents", () => {
  it("opens the stream with credentials and reports the connection", () => {
    const { result } = render();
    const source = MockEventSource.latest();

    expect(source.url).toBe(`https://api.test/plans/${PLAN_ID}/events`);
    expect(source.withCredentials).toBe(true);
    expect(result.current.connection).toBe("connecting");

    act(() => source.open());
    expect(result.current.connection).toBe("open");
  });

  it("validates every message: valid events reach the reducer, invalid ones are dropped", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = render();
    const source = MockEventSource.latest();

    act(() => {
      source.open();
      source.send(EVENTS[0] as UIEvent);
      source.send("not json");
      source.send(JSON.stringify({ ...EVENTS[1], ts: "2026-10-12T15:00:03" })); // naive datetime
      source.send(JSON.stringify({ ...EVENTS[1], agent: "planner" }));
      source.send(EVENTS[1] as UIEvent);
    });

    expect(result.current.state.events.map((event) => event.seq)).toEqual([0, 1]);
    expect(result.current.dropped).toBe(3);
    expect(result.current.state.status).toBe("running");
    expect(warn).toHaveBeenCalledTimes(3);
  });

  it("lets the browser reconnect by itself (Last-Event-ID) and shows the reconnecting line", () => {
    const { result } = render();
    const source = MockEventSource.latest();

    act(() => {
      source.open();
      source.send(EVENTS[0] as UIEvent);
      source.drop();
    });
    expect(result.current.connection).toBe("reconnecting");
    expect(MockEventSource.instances).toHaveLength(1);

    act(() => {
      source.open();
      source.send(EVENTS[0] as UIEvent); // replayed twice by an overlapping replay: deduped
      source.send(EVENTS[1] as UIEvent);
    });
    expect(result.current.connection).toBe("open");
    expect(result.current.state.events.map((event) => event.seq)).toEqual([0, 1]);
  });

  it("reconnects itself with ?after=<last seq> when the browser gives up", async () => {
    const beforeReconnect = vi.fn(async () => true);
    const { result } = render({ beforeReconnect });
    const first = MockEventSource.latest();

    act(() => {
      first.open();
      for (const event of EVENTS.slice(0, 6)) first.send(event);
      first.fail();
    });
    expect(result.current.connection).toBe("reconnecting");
    expect(first.readyState).toBe(MockEventSource.CLOSED);
    expect(MockEventSource.instances).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(beforeReconnect).toHaveBeenCalledTimes(1);
    const second = MockEventSource.latest();
    expect(MockEventSource.instances).toHaveLength(2);
    expect(second.url).toBe(`https://api.test/plans/${PLAN_ID}/events?after=5`);
    expect(second.withCredentials).toBe(true);

    act(() => {
      second.open();
      for (const event of EVENTS.slice(4, 9)) second.send(event); // overlap 4-5: deduped
    });
    expect(result.current.connection).toBe("open");
    expect(result.current.state.events.map((event) => event.seq)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("backs off between failed reconnections", async () => {
    const { result } = render({ reconnectDelay: defaultReconnectDelay });

    act(() => MockEventSource.latest().fail());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(MockEventSource.instances).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(MockEventSource.instances).toHaveLength(2);

    act(() => MockEventSource.latest().fail());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(MockEventSource.instances).toHaveLength(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(MockEventSource.instances).toHaveLength(3);
    expect(result.current.connection).toBe("reconnecting");
    expect(defaultReconnectDelay(10)).toBe(30_000);
  });

  it("stays closed when beforeReconnect says stop (e.g. signed out, plan gone)", async () => {
    const { result } = render({ beforeReconnect: async () => false });

    act(() => MockEventSource.latest().fail());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(MockEventSource.instances).toHaveLength(1);
    expect(result.current.connection).toBe("closed");
  });

  it("handles `event: end`: final status, stream closed, no reconnection", async () => {
    const onEnd = vi.fn();
    const { result } = render({ onEnd });
    const source = MockEventSource.latest();

    act(() => {
      source.open();
      for (const event of EVENTS) source.send(event);
      source.end("ready");
    });

    expect(result.current.connection).toBe("closed");
    expect(result.current.state.ended).toBe(true);
    expect(result.current.state.status).toBe("ready");
    expect(result.current.state.planReady).toBe(true);
    expect(source.readyState).toBe(MockEventSource.CLOSED);
    expect(onEnd).toHaveBeenCalledWith("ready");

    act(() => source.fail());
    act(() => result.current.reconnect());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it("reconnect() opens a new stream after the last seq", () => {
    const { result } = render();
    const first = MockEventSource.latest();

    act(() => {
      first.open();
      first.send(EVENTS[0] as UIEvent);
      first.send(EVENTS[1] as UIEvent);
    });
    act(() => result.current.reconnect());

    expect(first.readyState).toBe(MockEventSource.CLOSED);
    expect(MockEventSource.latest().url).toBe(`https://api.test/plans/${PLAN_ID}/events?after=1`);
    expect(result.current.connection).toBe("connecting");
  });

  it("closes the stream on unmount and resumes after the last seq when shown again", () => {
    const { result, unmount, rerender } = render();
    const first = MockEventSource.latest();
    act(() => {
      first.open();
      first.send(EVENTS[0] as UIEvent);
    });

    rerender({ id: PLAN_ID, opts: options({ enabled: false }) });
    expect(first.readyState).toBe(MockEventSource.CLOSED);
    expect(result.current.connection).toBe("closed");

    rerender({ id: PLAN_ID, opts: options() });
    expect(MockEventSource.latest().url).toBe(`https://api.test/plans/${PLAN_ID}/events?after=0`);
    expect(result.current.state.events).toHaveLength(1);

    const last = MockEventSource.latest();
    unmount();
    expect(last.readyState).toBe(MockEventSource.CLOSED);
  });

  it("starts over for another plan", () => {
    const { result, rerender } = render();
    act(() => {
      MockEventSource.latest().open();
      MockEventSource.latest().send(EVENTS[0] as UIEvent);
    });

    const other = "0b9e8d7c-6a5f-4e3d-9c2b-1a0f9e8d7c6b";
    rerender({ id: other, opts: options() });

    expect(MockEventSource.latest().url).toBe(`https://api.test/plans/${other}/events`);
    expect(result.current.state.events).toHaveLength(0);
  });

  it("batches a burst of events into one reduction", async () => {
    const onEvent = vi.fn();
    const { result } = render({ batchMs: 32, onEvent });
    const source = MockEventSource.latest();

    act(() => {
      source.open();
      for (const event of EVENTS.slice(0, 20)) source.send(event);
    });
    expect(onEvent).toHaveBeenCalledTimes(20);
    expect(result.current.state.events).toHaveLength(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(32);
    });
    expect(result.current.state.events).toHaveLength(20);
  });

  it("applies the GET /plans/{id} snapshot", () => {
    const detail = {
      ...happyPath.detail,
      status: "running" as const,
      agent_profile: "development" as const,
      booking_links: [],
      alternative_links: [],
      plan: null,
    };
    const { result } = render({ detail });

    expect(result.current.state.budgetCents).toBe(60);
    expect(result.current.state.status).toBe("running");
    expect(result.current.state.startedAt).toBe("2026-10-12T13:00:00Z");
  });

  it("does not connect without a plan id", () => {
    const { result } = render({}, null);

    expect(MockEventSource.instances).toHaveLength(0);
    expect(result.current.connection).toBe("closed");
  });
});
