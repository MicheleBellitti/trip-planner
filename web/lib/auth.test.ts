// @vitest-environment node
import { memoryAdapter } from "better-auth/adapters/memory";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { parseAllowedEmails } from "./auth-policy";
import type { AuthServerConfig } from "./server/auth-config";

const sendMagicLink = vi.fn<(config: unknown, message: { email: string; url: string }) => Promise<void>>();

vi.mock("./server/send-magic-link", () => ({
  MAGIC_LINK_MINUTES: 5,
  sendMagicLink: (config: unknown, message: { email: string; url: string }) => sendMagicLink(config, message),
}));

const { buildAuth, redactAddresses } = await import("./auth");

const BASE = "http://localhost:3000";

const config: AuthServerConfig = {
  databaseUrl: "postgres://unused",
  secret: "atlas-test-secret-0000000000000000000000000000",
  baseUrl: BASE,
  cookieDomain: null,
  allowList: parseAllowedEmails("boss@example.com"),
  google: null,
  email: null,
  production: false,
};

/** The tasks deferred past the response, as Next's `after()` would hold them. */
let deferred: (() => Promise<void>)[] = [];

async function runDeferred() {
  const tasks = deferred;
  deferred = [];
  for (const task of tasks) await task();
}

function setup(invited: string[] = []) {
  const now = new Date();
  const tables: Record<string, Record<string, unknown>[]> = {
    users: [{ id: "u1", name: "", email: "member@example.com", email_verified: true, image: null, created_at: now, updated_at: now }],
    auth_sessions: [],
    auth_accounts: [],
    auth_verifications: [],
  };
  // Every read of a table and every standing lookup, in order: what a request costs.
  const lookups: string[] = [];
  const db = new Proxy(tables, {
    get(target, key: string) {
      if (key in target) lookups.push(`table:${key}`);
      return target[key];
    },
  });
  const auth = buildAuth(config, {
    database: memoryAdapter(db),
    standing: async (email) => {
      lookups.push("standing");
      return { hasAccount: tables.users!.some((user) => user.email === email), invited: invited.includes(email) };
    },
    defer: (task) => void deferred.push(task),
  });
  return { auth, lookups };
}

async function requestLink(auth: ReturnType<typeof setup>["auth"], email: string) {
  const response = await auth.handler(
    new Request(`${BASE}/api/auth/sign-in/magic-link`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: BASE },
      body: JSON.stringify({ email, callbackURL: "/plans" }),
    }),
  );
  return { status: response.status, body: await response.text() };
}

describe("the magic-link request (no account enumeration)", () => {
  beforeEach(() => {
    deferred = [];
    sendMagicLink.mockReset();
    sendMagicLink.mockResolvedValue(undefined);
  });

  it("answers an unknown, uninvited address exactly as an account's, and sends it nothing", async () => {
    const { auth } = setup();
    const member = await requestLink(auth, "member@example.com");
    const stranger = await requestLink(auth, "stranger@example.com");

    expect(member).toEqual({ status: 200, body: JSON.stringify({ status: true }) });
    expect(stranger).toEqual(member);
    expect(deferred).toHaveLength(1); // the member's email, after the response
    await runDeferred();
    expect(sendMagicLink).toHaveBeenCalledTimes(1);
    expect(sendMagicLink.mock.calls[0]?.[1].email).toBe("member@example.com");
  });

  it("makes the same lookups for an account, an allowed, an invited and an unknown address", async () => {
    const { auth, lookups } = setup(["guest@example.com"]);
    const costs: string[][] = [];
    for (const email of ["member@example.com", "boss@example.com", "guest@example.com", "stranger@example.com"]) {
      lookups.length = 0;
      expect((await requestLink(auth, email)).status).toBe(200);
      costs.push([...lookups]);
    }
    expect(costs[0]).toContain("standing");
    expect(costs[0]!.filter((lookup) => lookup === "standing")).toHaveLength(1);
    for (const cost of costs) expect(cost).toEqual(costs[0]);
    expect(deferred).toHaveLength(3); // the stranger gets nothing, and paid the same to find out
  });

  it("sends the link to an address on the allow list or invited on the waitlist", async () => {
    const { auth } = setup(["guest@example.com"]);
    expect((await requestLink(auth, "Boss@Example.com")).status).toBe(200);
    expect((await requestLink(auth, "guest@example.com")).status).toBe(200);
    await runDeferred();
    expect(sendMagicLink.mock.calls.map((call) => call[1].email.toLowerCase())).toEqual([
      "boss@example.com",
      "guest@example.com",
    ]);
  });

  it("keeps the request's own validation for everyone: an address without a shape is a 400", async () => {
    const { auth } = setup();
    expect((await requestLink(auth, "not-an-address")).status).toBe(400);
    expect(deferred).toHaveLength(0);
    expect(sendMagicLink).not.toHaveBeenCalled();
  });

  it("answers before the email leaves: a send that never finishes still gives the 200", async () => {
    sendMagicLink.mockImplementation(() => new Promise<void>(() => undefined)); // Resend hangs
    const { auth } = setup();
    expect(await requestLink(auth, "member@example.com")).toEqual({ status: 200, body: JSON.stringify({ status: true }) });
    expect(sendMagicLink).not.toHaveBeenCalled(); // not even started while the request was open
    void runDeferred();
    await vi.waitFor(() => expect(sendMagicLink).toHaveBeenCalledTimes(1));
  });

  it("logs a failed send without the address, and never throws it out of the deferred task", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    sendMagicLink.mockRejectedValueOnce(new Error("Resend refused the sign-in email: validation_error member@example.com is invalid"));
    const { auth } = setup();
    expect((await requestLink(auth, "member@example.com")).status).toBe(200);
    await expect(runDeferred()).resolves.toBeUndefined();
    expect(log).toHaveBeenCalledWith("[auth] sign-in email failed", "Resend refused the sign-in email: validation_error <address> is invalid");
    expect(JSON.stringify(log.mock.calls)).not.toContain("member@example.com");
    expect(redactAddresses("to <a.b+c@x.it>, cc d@e.f")).toBe("to <<address>>, cc <address>");
  });
});
