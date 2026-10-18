// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { currentCaller, ME_TIMEOUT_MS } from "./admin";

vi.mock("next/headers", () => ({ headers: async () => new Headers({ cookie: "__Secure-atlas.session_token=abc" }) }));

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.atlas.test");
  vi.stubEnv("NEXT_PUBLIC_TRIPTRACKER_URL", "https://viaggi.atlas.test");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("currentCaller", () => {
  it("asks GET /me with the request's cookie, and reads the answer", async () => {
    const fetch = vi.fn(async () => Response.json({ email: "me@example.com", is_admin: true }));
    vi.stubGlobal("fetch", fetch);
    expect(await currentCaller()).toEqual({ email: "me@example.com", isAdmin: true });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.atlas.test/me");
    expect(new Headers(init.headers).get("cookie")).toBe("__Secure-atlas.session_token=abc");
  });

  it("gives up on a backend that never answers, and the rejection fails closed", async () => {
    expect(ME_TIMEOUT_MS).toBe(5000);
    const timeout = vi.spyOn(AbortSignal, "timeout").mockImplementation(() => AbortSignal.abort(new DOMException("timed out", "TimeoutError")));
    // A fetch that hangs until its signal aborts, as the real one does.
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            const signal = init.signal!;
            if (signal.aborted) reject(signal.reason);
            signal.addEventListener("abort", () => reject(signal.reason));
          }),
      ),
    );
    await expect(currentCaller()).rejects.toMatchObject({ name: "TimeoutError" });
    expect(timeout).toHaveBeenCalledWith(ME_TIMEOUT_MS);
  });

  it("a 401 is signed out and any other failure throws", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 401 })));
    expect(await currentCaller()).toBeNull();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 502 })));
    await expect(currentCaller()).rejects.toThrow(/502/);
  });
});
