import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetTurnstileWarning, verifyTurnstile } from "./turnstile";

const answer = (status: number, body: unknown) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

/** Both keys set, the site at atlas.example. */
const ON = { secret: "s3cret", siteKey: "0x4AAAAAAA", siteUrl: "https://atlas.example" };
const GOOD = { success: true, action: "login", hostname: "atlas.example" };

let logged: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  resetTurnstileWarning();
  logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  logged.mockRestore();
});

describe("verifyTurnstile", () => {
  it("is off without keys and never calls out", async () => {
    const fetch = answer(200, GOOD);
    expect(await verifyTurnstile("tok", "1.2.3.4", "login", { secret: "", siteKey: "", fetch })).toBe("off");
    expect(await verifyTurnstile(null, null, "login", { secret: undefined, siteKey: undefined, fetch })).toBe("off");
    expect(fetch).not.toHaveBeenCalled();
    expect(logged).not.toHaveBeenCalled();
  });

  it("is off, and says so once, when only one key is set", async () => {
    const fetch = answer(200, GOOD);
    // A secret without the build-time site key: no widget issues tokens, so checking would lock
    // every sign-in link out.
    expect(await verifyTurnstile(null, null, "login", { secret: "s3cret", siteKey: "", fetch })).toBe("off");
    expect(await verifyTurnstile(null, null, "waitlist", { secret: "s3cret", siteKey: "", fetch })).toBe("off");
    expect(logged).toHaveBeenCalledTimes(1);
    expect(String(logged.mock.calls[0]?.[0])).toContain("NEXT_PUBLIC_TURNSTILE_SITE_KEY was not at build time");

    resetTurnstileWarning();
    expect(await verifyTurnstile("tok", null, "login", { secret: "", siteKey: "0x4AAAAAAA", fetch })).toBe("off");
    expect(String(logged.mock.calls[1]?.[0])).toContain("TURNSTILE_SECRET_KEY is not");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("fails a missing or oversized token without calling out", async () => {
    const fetch = answer(200, GOOD);
    expect(await verifyTurnstile(null, "1.2.3.4", "login", { ...ON, fetch })).toBe("failed");
    expect(await verifyTurnstile("x".repeat(2049), "1.2.3.4", "login", { ...ON, fetch })).toBe("failed");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("posts the secret, the token and the address to siteverify and reads success", async () => {
    const fetch = answer(200, GOOD);
    expect(await verifyTurnstile("tok-1", "203.0.113.9", "login", { ...ON, fetch })).toBe("passed");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://challenges.cloudflare.com/turnstile/v0/siteverify");
    expect(init.method).toBe("POST");
    const body = init.body as URLSearchParams;
    expect(Object.fromEntries(body)).toEqual({ secret: "s3cret", response: "tok-1", remoteip: "203.0.113.9" });
  });

  it("fails a token issued for another form or on another site", async () => {
    expect(await verifyTurnstile("tok", null, "waitlist", { ...ON, fetch: answer(200, GOOD) })).toBe("failed");
    expect(await verifyTurnstile("tok", null, "login", { ...ON, fetch: answer(200, { ...GOOD, hostname: "evil.example" }) })).toBe(
      "failed",
    );
    expect(await verifyTurnstile("tok", null, "login", { ...ON, fetch: answer(200, { success: true }) })).toBe("failed");
    // Without a site URL (development) only the action is checked.
    expect(await verifyTurnstile("tok", null, "login", { ...ON, siteUrl: "", fetch: answer(200, { ...GOOD, hostname: "localhost" }) })).toBe(
      "passed",
    );
  });

  it("takes Cloudflare's test secret at its word: its answers carry no real action or hostname", async () => {
    const test = { ...ON, secret: "1x0000000000000000000000000000000AA" };
    expect(await verifyTurnstile("XXXX.DUMMY.TOKEN.XXXX", null, "waitlist", { ...test, fetch: answer(200, { success: true, hostname: "example.com" }) })).toBe(
      "passed",
    );
  });

  it("fails closed on a refusal, a bad status and a network error", async () => {
    expect(await verifyTurnstile("tok", null, "login", { ...ON, fetch: answer(200, { success: false, "error-codes": ["timeout-or-duplicate"] }) })).toBe(
      "failed",
    );
    expect(await verifyTurnstile("tok", null, "login", { ...ON, fetch: answer(500, {}) })).toBe("failed");
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    expect(await verifyTurnstile("tok", null, "login", { ...ON, fetch: down })).toBe("failed");
  });
});
