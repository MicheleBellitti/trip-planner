import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Cover } from "@/lib/schemas/api";

import { MAX_IN_FLIGHT, requestCover, resetCoverStore, useCover, useShownCovers } from "./cover-store";

const COVER: Cover = {
  url: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/1920px-X.jpg",
  width: 1920,
  height: 1080,
  author: null,
  license: "CC0",
  license_url: null,
  source_page: "https://commons.wikimedia.org/wiki/File:X.jpg",
  title: "X",
};

beforeEach(() => resetCoverStore());
afterEach(() => cleanup());

describe("useCover", () => {
  it("is idle until it is enabled, then loading, then ready", async () => {
    let resolve: (cover: Cover | null) => void = () => {};
    const load = vi.fn(() => new Promise<Cover | null>((done) => (resolve = done)));
    const { result, rerender } = renderHook(({ enabled }) => useCover("plan-1", enabled, load), {
      initialProps: { enabled: false },
    });
    expect(result.current.kind).toBe("idle");
    expect(load).not.toHaveBeenCalled();

    rerender({ enabled: true });
    expect(result.current.kind).toBe("loading");
    await act(async () => resolve(COVER));
    expect(result.current).toEqual({ kind: "ready", cover: COVER });
  });

  it("keeps a missing photo and does not ask again", async () => {
    const load = vi.fn(async () => null);
    const first = renderHook(() => useCover("plan-1", true, load));
    await act(async () => {});
    expect(first.result.current).toEqual({ kind: "none", retry: false });
    first.unmount();

    const second = renderHook(() => useCover("plan-1", true, load));
    await act(async () => {});
    expect(second.result.current.kind).toBe("none");
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("shares the answer between screens: the plan page finds what the list read", async () => {
    const load = vi.fn(async () => COVER);
    const list = renderHook(() => useCover("plan-1", true, load));
    await act(async () => {});
    const page = renderHook(() => useCover("plan-1", true, load));
    expect(page.result.current).toEqual({ kind: "ready", cover: COVER });
    expect(list.result.current.kind).toBe("ready");
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("treats a failure as no photo for now and asks again when a screen asks again", async () => {
    const load = vi.fn<() => Promise<Cover | null>>().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(COVER);
    const first = renderHook(() => useCover("plan-1", true, load));
    await act(async () => {});
    expect(first.result.current).toEqual({ kind: "none", retry: true });
    first.unmount();

    const second = renderHook(() => useCover("plan-1", true, load));
    await act(async () => {});
    expect(second.result.current.kind).toBe("ready");
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("survives a loader that throws at once", async () => {
    const { result } = renderHook(() =>
      useCover("plan-1", true, () => {
        throw new TypeError("no client");
      }),
    );
    await act(async () => {});
    expect(result.current.kind).toBe("none");
  });
});

describe("requestCover", () => {
  it("keeps at most MAX_IN_FLIGHT requests going and starts the next as one ends", async () => {
    const resolvers: Array<(cover: Cover | null) => void> = [];
    const load = vi.fn(() => new Promise<Cover | null>((done) => resolvers.push(done)));
    for (let i = 0; i < MAX_IN_FLIGHT + 2; i += 1) requestCover(`plan-${i}`, load);
    expect(load).toHaveBeenCalledTimes(MAX_IN_FLIGHT);

    await act(async () => resolvers[0]?.(COVER));
    expect(load).toHaveBeenCalledTimes(MAX_IN_FLIGHT + 1);
    await act(async () => resolvers[1]?.(null));
    expect(load).toHaveBeenCalledTimes(MAX_IN_FLIGHT + 2);
  });
});

describe("useShownCovers", () => {
  it("lists the photos the plans have, each photo once, as the answers arrive", async () => {
    const { result } = renderHook(() => useShownCovers(["plan-1", "plan-2", "plan-3"]));
    expect(result.current).toEqual([]);
    await act(async () => {
      requestCover("plan-1", async () => null);
      requestCover("plan-2", async () => COVER);
      requestCover("plan-3", async () => ({ ...COVER }));
    });
    // Two plans, one photo (a destination planned twice): one credit.
    expect(result.current).toEqual([COVER]);
    await act(async () => {
      requestCover("plan-4", async () => ({ ...COVER, source_page: "https://commons.wikimedia.org/wiki/File:Y.jpg" }));
    });
  });

  it("keeps the same array while nothing changes", async () => {
    const { result, rerender } = renderHook(() => useShownCovers(["plan-1"]));
    await act(async () => {
      requestCover("plan-1", async () => COVER);
    });
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
