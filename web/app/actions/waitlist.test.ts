import { beforeEach, describe, expect, it, vi } from "vitest";

import { INVITE_IDLE, JOIN_IDLE, REMOVE_IDLE } from "@/lib/waitlist-state";

import { inviteAction, joinWaitlistAction, removeRequestAction } from "./waitlist";

const currentCaller = vi.fn();
const readAuthConfig = vi.fn();
const joinWaitlist = vi.fn();
const invite = vi.fn();
const markInvitationSent = vi.fn();
const removeRequest = vi.fn();
const sendInvitation = vi.fn();
const revalidatePath = vi.fn();
const verifyTurnstile = vi.fn();
const hit = vi.fn();
const pool = { query: vi.fn() };
const requestHeaders: Record<string, string> = { "x-real-ip": "203.0.113.9" };

vi.mock("@/lib/server/admin", () => ({ currentCaller: (...args: unknown[]) => currentCaller(...args) }));
vi.mock("@/lib/server/auth-config", () => ({ readAuthConfig: (...args: unknown[]) => readAuthConfig(...args) }));
vi.mock("@/lib/server/db", () => ({ getPool: () => pool }));
vi.mock("@/lib/server/waitlist", () => ({
  joinWaitlist: (...args: unknown[]) => joinWaitlist(...args),
  invite: (...args: unknown[]) => invite(...args),
  markInvitationSent: (...args: unknown[]) => markInvitationSent(...args),
  removeRequest: (...args: unknown[]) => removeRequest(...args),
}));
vi.mock("@/lib/server/send-invitation", () => ({ sendInvitation: (...args: unknown[]) => sendInvitation(...args) }));
vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));
vi.mock("next/headers", () => ({ headers: async () => new Headers(requestHeaders) }));
vi.mock("@/lib/server/turnstile", () => ({ verifyTurnstile: (...args: unknown[]) => verifyTurnstile(...args) }));
vi.mock("@/lib/server/rate-limit", () => ({ joinWindow: { hit: (...args: unknown[]) => hit(...args) } }));

const CONFIG = { databaseUrl: "postgresql://x", baseUrl: "https://atlas.test" };

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
}

beforeEach(() => {
  for (const mock of [currentCaller, readAuthConfig, joinWaitlist, invite, markInvitationSent, removeRequest, sendInvitation, revalidatePath, verifyTurnstile, hit]) mock.mockReset();
  readAuthConfig.mockReturnValue(CONFIG);
  verifyTurnstile.mockResolvedValue("off");
  hit.mockReturnValue({ allowed: true, retryAfterSeconds: 0 });
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

describe("joinWaitlistAction", () => {
  it("counts the address's window and checks the challenge before reading the input", async () => {
    hit.mockReturnValue({ allowed: false, retryAfterSeconds: 300 });
    const data = new FormData();
    data.set("email", "nobody@example.com");
    data.set("source", "landing");
    expect(await joinWaitlistAction(JOIN_IDLE, data)).toEqual({ status: "error", error: "too_many_requests" });
    expect(hit).toHaveBeenCalledWith("203.0.113.9");
    expect(verifyTurnstile).not.toHaveBeenCalled();
    expect(joinWaitlist).not.toHaveBeenCalled();

    hit.mockReturnValue({ allowed: true, retryAfterSeconds: 0 });
    verifyTurnstile.mockResolvedValue("failed");
    data.set("cf-turnstile-response", "tok-1");
    expect(await joinWaitlistAction(JOIN_IDLE, data)).toEqual({ status: "error", error: "challenge_failed" });
    expect(verifyTurnstile).toHaveBeenCalledWith("tok-1", "203.0.113.9");
    expect(joinWaitlist).not.toHaveBeenCalled();

    verifyTurnstile.mockResolvedValue("passed");
    joinWaitlist.mockResolvedValue("joined");
    expect(await joinWaitlistAction(JOIN_IDLE, data)).toEqual({ status: "joined", email: "nobody@example.com" });
  });

  it("validates before touching anything, and says when the accounts are not configured", async () => {
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: "nope", source: "landing" }))).toEqual({ status: "error", error: "invalid_email" });
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: "a@b.co", source: "elsewhere" }))).toEqual({ status: "error", error: "invalid_source" });
    expect(joinWaitlist).not.toHaveBeenCalled();
    readAuthConfig.mockReturnValue(null);
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: "a@b.co", source: "landing" }))).toEqual({ status: "error", error: "unavailable" });
  });

  it("answers the query's outcome with the normalized address, and a failure as such", async () => {
    joinWaitlist.mockResolvedValue("joined");
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: " Friend@Example.com ", note: " ciao ", source: "login" }))).toEqual({
      status: "joined",
      email: "friend@example.com",
    });
    expect(joinWaitlist).toHaveBeenCalledWith(pool, { email: "friend@example.com", note: "ciao", source: "login" });
    joinWaitlist.mockRejectedValue(new Error("connection refused"));
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: "a@b.co", source: "landing" }))).toEqual({ status: "error", error: "failed" });
  });
});

describe("inviteAction", () => {
  it("is for admins only, checked with the backend on every call", async () => {
    currentCaller.mockResolvedValue(null);
    expect(await inviteAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "error", error: "signed_out" });
    currentCaller.mockResolvedValue({ email: "someone@example.com", isAdmin: false });
    expect(await inviteAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "error", error: "forbidden" });
    currentCaller.mockRejectedValue(new Error("502"));
    expect(await inviteAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "error", error: "failed" });
    expect(invite).not.toHaveBeenCalled();
    expect(await inviteAction(INVITE_IDLE, form({ email: "nope" }))).toEqual({ status: "error", error: "invalid_email" });
  });

  it("invites, sends the email once, records it and refreshes the page", async () => {
    currentCaller.mockResolvedValue({ email: "Me@Example.com", isAdmin: true });
    invite.mockResolvedValue({ email: "a@b.co", invitationSentAt: null });

    const state = await inviteAction(INVITE_IDLE, form({ email: "A@b.co", note: "amico" }));

    expect(state).toEqual({ status: "invited", email: "a@b.co", emailSent: true, alreadyInvited: false });
    expect(invite).toHaveBeenCalledWith(pool, { email: "a@b.co", by: "me@example.com", note: "amico" });
    expect(sendInvitation).toHaveBeenCalledWith(CONFIG, { email: "a@b.co" });
    expect(markInvitationSent).toHaveBeenCalledWith(pool, "a@b.co");
    expect(revalidatePath).toHaveBeenCalledWith("/admin/waitlist");
  });

  it("sends nothing to an address already invited, and reports an email that did not leave", async () => {
    currentCaller.mockResolvedValue({ email: "me@example.com", isAdmin: true });
    invite.mockResolvedValue({ email: "a@b.co", invitationSentAt: "2026-10-16T10:00:00Z" });
    expect(await inviteAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "invited", email: "a@b.co", emailSent: false, alreadyInvited: true });
    expect(sendInvitation).not.toHaveBeenCalled();

    invite.mockResolvedValue({ email: "a@b.co", invitationSentAt: null });
    sendInvitation.mockRejectedValue(new Error("Resend refused"));
    expect(await inviteAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "invited", email: "a@b.co", emailSent: false, alreadyInvited: false });
    expect(markInvitationSent).not.toHaveBeenCalled();
  });
});

describe("removeRequestAction", () => {
  it("is for admins only and removes a pending request, refreshing the page", async () => {
    currentCaller.mockResolvedValue({ email: "someone@example.com", isAdmin: false });
    expect(await removeRequestAction(REMOVE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "error", error: "forbidden" });
    expect(removeRequest).not.toHaveBeenCalled();

    currentCaller.mockResolvedValue({ email: "me@example.com", isAdmin: true });
    removeRequest.mockResolvedValue(true);
    expect(await removeRequestAction(REMOVE_IDLE, form({ email: " A@b.co " }))).toEqual({ status: "removed", email: "a@b.co" });
    expect(removeRequest).toHaveBeenCalledWith(pool, "a@b.co");
    expect(revalidatePath).toHaveBeenCalledWith("/admin/waitlist");

    removeRequest.mockResolvedValue(false); // already invited, or gone
    expect(await removeRequestAction(REMOVE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "error", error: "failed" });
    expect(await removeRequestAction(REMOVE_IDLE, form({ email: "nope" }))).toEqual({ status: "error", error: "invalid_email" });
  });
});
