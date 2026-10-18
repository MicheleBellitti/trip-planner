import { describe, expect, it, vi } from "vitest";

import { verifyTurnstile } from "./turnstile";

const answer = (status: number, body: unknown) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

describe("verifyTurnstile", () => {
  it("is off without a secret and never calls out", async () => {
    const fetch = answer(200, { success: true });
    expect(await verifyTurnstile("tok", "1.2.3.4", { secret: "", fetch })).toBe("off");
    expect(await verifyTurnstile(null, null, { secret: undefined, fetch })).toBe("off");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("fails a missing or oversized token without calling out", async () => {
    const fetch = answer(200, { success: true });
    expect(await verifyTurnstile(null, "1.2.3.4", { secret: "s3cret", fetch })).toBe("failed");
    expect(await verifyTurnstile("x".repeat(2049), "1.2.3.4", { secret: "s3cret", fetch })).toBe("failed");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("posts the secret, the token and the address to siteverify and reads success", async () => {
    const fetch = answer(200, { success: true });
    expect(await verifyTurnstile("tok-1", "203.0.113.9", { secret: "s3cret", fetch })).toBe("passed");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://challenges.cloudflare.com/turnstile/v0/siteverify");
    expect(init.method).toBe("POST");
    const body = init.body as URLSearchParams;
    expect(Object.fromEntries(body)).toEqual({ secret: "s3cret", response: "tok-1", remoteip: "203.0.113.9" });
  });

  it("fails closed on a refusal, a bad status and a network error", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(await verifyTurnstile("tok", null, { secret: "s", fetch: answer(200, { success: false, "error-codes": ["timeout-or-duplicate"] }) })).toBe("failed");
    expect(await verifyTurnstile("tok", null, { secret: "s", fetch: answer(500, {}) })).toBe("failed");
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    expect(await verifyTurnstile("tok", null, { secret: "s", fetch: down })).toBe("failed");
  });
});
