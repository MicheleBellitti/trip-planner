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

const { buildAuth } = await import("./auth");

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

function setup(invited: string[] = []) {
  const now = new Date();
  const db: Record<string, Record<string, unknown>[]> = {
    users: [{ id: "u1", name: "", email: "member@example.com", email_verified: true, image: null, created_at: now, updated_at: now }],
    auth_sessions: [],
    auth_accounts: [],
    auth_verifications: [],
  };
  const auth = buildAuth(config, {
    database: memoryAdapter(db),
    isInvited: async (email) => invited.includes(email),
  });
  return { auth, db };
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
    sendMagicLink.mockReset();
    sendMagicLink.mockResolvedValue(undefined);
  });

  it("answers an unknown, uninvited address exactly as an account's, and sends it nothing", async () => {
    const { auth } = setup();
    const member = await requestLink(auth, "member@example.com");
    const stranger = await requestLink(auth, "stranger@example.com");

    expect(member).toEqual({ status: 200, body: JSON.stringify({ status: true }) });
    expect(stranger).toEqual(member);
    expect(sendMagicLink).toHaveBeenCalledTimes(1);
    expect(sendMagicLink.mock.calls[0]?.[1].email).toBe("member@example.com");
  });

  it("sends the link to an address on the allow list or invited on the waitlist", async () => {
    const { auth } = setup(["guest@example.com"]);
    expect((await requestLink(auth, "Boss@Example.com")).status).toBe(200);
    expect((await requestLink(auth, "guest@example.com")).status).toBe(200);
    expect(sendMagicLink.mock.calls.map((call) => call[1].email.toLowerCase())).toEqual([
      "boss@example.com",
      "guest@example.com",
    ]);
  });

  it("keeps the request's own validation for everyone: an address without a shape is a 400", async () => {
    const { auth } = setup();
    expect((await requestLink(auth, "not-an-address")).status).toBe(400);
    expect(sendMagicLink).not.toHaveBeenCalled();
  });
});
