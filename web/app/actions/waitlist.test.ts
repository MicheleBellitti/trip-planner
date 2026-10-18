import { beforeEach, describe, expect, it, vi } from "vitest";

import { INVITE_IDLE, JOIN_IDLE, REMOVE_IDLE } from "@/lib/waitlist-state";

import { inviteAction, joinWaitlistAction, removeRequestAction, resendInvitationAction } from "./waitlist";

const currentCaller = vi.fn();
const readAuthConfig = vi.fn();
const joinWaitlist = vi.fn();
const invite = vi.fn();
const claimInvitation = vi.fn();
const releaseInvitation = vi.fn();
const reclaimInvitation = vi.fn();
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
  claimInvitation: (...args: unknown[]) => claimInvitation(...args),
  releaseInvitation: (...args: unknown[]) => releaseInvitation(...args),
  reclaimInvitation: (...args: unknown[]) => reclaimInvitation(...args),
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
  for (const mock of [currentCaller, readAuthConfig, joinWaitlist, invite, claimInvitation, releaseInvitation, reclaimInvitation, removeRequest, sendInvitation, revalidatePath, verifyTurnstile, hit]) mock.mockReset();
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
    expect(verifyTurnstile).toHaveBeenCalledWith("tok-1", "203.0.113.9", "waitlist");
    expect(joinWaitlist).not.toHaveBeenCalled();

    verifyTurnstile.mockResolvedValue("passed");
    joinWaitlist.mockResolvedValue("joined");
    expect(await joinWaitlistAction(JOIN_IDLE, data)).toEqual({ status: "received", email: "nobody@example.com" });
  });

  it("keys the window on the client, never on the address, and a request without an IP shares one bucket", async () => {
    hit.mockReturnValue({ allowed: false, retryAfterSeconds: 300 });
    // Two addresses from one connection: the same key, the same answer, whatever the list holds.
    for (const email of ["listed@example.com", "stranger@example.com"]) {
      expect(await joinWaitlistAction(JOIN_IDLE, form({ email, source: "landing" }))).toEqual({ status: "error", error: "too_many_requests" });
    }
    expect(hit.mock.calls).toEqual([["203.0.113.9"], ["203.0.113.9"]]);

    const ip = requestHeaders["x-real-ip"];
    delete requestHeaders["x-real-ip"];
    try {
      await joinWaitlistAction(JOIN_IDLE, form({ email: "a@b.co", source: "landing" }));
    } finally {
      if (ip) requestHeaders["x-real-ip"] = ip;
    }
    expect(hit).toHaveBeenLastCalledWith("unknown");
    expect(joinWaitlist).not.toHaveBeenCalled();
  });

  it("validates before touching anything, and says when the accounts are not configured", async () => {
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: "nope", source: "landing" }))).toEqual({ status: "error", error: "invalid_email" });
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: "a@b.co", source: "elsewhere" }))).toEqual({ status: "error", error: "invalid_source" });
    // Only the admin actions write the "admin" source: a public form may not claim it.
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: "a@b.co", source: "admin" }))).toEqual({ status: "error", error: "invalid_source" });
    expect(joinWaitlist).not.toHaveBeenCalled();
    readAuthConfig.mockReturnValue(null);
    expect(await joinWaitlistAction(JOIN_IDLE, form({ email: "a@b.co", source: "landing" }))).toEqual({ status: "error", error: "unavailable" });
  });

  it("answers \"received\" with the normalized address whatever the query found, and a failure as such", async () => {
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    for (const outcome of ["joined", "already_listed", "already_invited", "already_registered"]) {
      joinWaitlist.mockResolvedValueOnce(outcome);
      expect(await joinWaitlistAction(JOIN_IDLE, form({ email: " Friend@Example.com ", note: " ciao ", source: "login" }))).toEqual({
        status: "received",
        email: "friend@example.com",
      });
    }
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

  it("invites, claims the sending, sends the email once and refreshes the page", async () => {
    currentCaller.mockResolvedValue({ email: "Me@Example.com", isAdmin: true });
    invite.mockResolvedValue({ email: "a@b.co", invitationSentAt: null, registered: false });
    claimInvitation.mockResolvedValue("2026-10-18 10:00:00.123456+00");

    const state = await inviteAction(INVITE_IDLE, form({ email: "A@b.co", note: "amico" }));

    expect(state).toEqual({ status: "invited", email: "a@b.co", delivery: "sent" });
    expect(invite).toHaveBeenCalledWith(pool, { email: "a@b.co", by: "me@example.com", note: "amico" });
    expect(claimInvitation).toHaveBeenCalledWith(pool, "a@b.co");
    expect(claimInvitation.mock.invocationCallOrder[0]).toBeLessThan(sendInvitation.mock.invocationCallOrder[0]!); // claim first
    expect(sendInvitation).toHaveBeenCalledWith(CONFIG, { email: "a@b.co" });
    expect(releaseInvitation).not.toHaveBeenCalled();
    expect(revalidatePath).toHaveBeenCalledWith("/admin/waitlist");
  });

  it("sends nothing when the claim is taken: already sent, or another admin sending it right now", async () => {
    currentCaller.mockResolvedValue({ email: "me@example.com", isAdmin: true });
    invite.mockResolvedValue({ email: "a@b.co", invitationSentAt: null, registered: false });
    // Two admins at once: the database hands the claim to one of them only.
    claimInvitation.mockResolvedValueOnce("2026-10-18 10:00:00.123456+00").mockResolvedValueOnce(null);
    let finishSend: () => void = () => undefined;
    sendInvitation.mockImplementationOnce(() => new Promise<void>((resolve) => (finishSend = resolve)));

    const first = inviteAction(INVITE_IDLE, form({ email: "a@b.co" }));
    const second = inviteAction(INVITE_IDLE, form({ email: "a@b.co" }));
    await vi.waitFor(() => expect(claimInvitation).toHaveBeenCalledTimes(2));
    finishSend();

    expect(await first).toEqual({ status: "invited", email: "a@b.co", delivery: "sent" });
    expect(await second).toEqual({ status: "invited", email: "a@b.co", delivery: "already_sent" });
    expect(sendInvitation).toHaveBeenCalledTimes(1);
  });

  it("gives the claim back when the email did not leave, so the admin can retry", async () => {
    currentCaller.mockResolvedValue({ email: "me@example.com", isAdmin: true });
    invite.mockResolvedValue({ email: "a@b.co", invitationSentAt: null, registered: false });
    claimInvitation.mockResolvedValue("2026-10-18 10:00:00.123456+00");
    sendInvitation.mockRejectedValueOnce(new Error("Resend refused"));

    expect(await inviteAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "invited", email: "a@b.co", delivery: "failed" });
    expect(releaseInvitation).toHaveBeenCalledWith(pool, "a@b.co", "2026-10-18 10:00:00.123456+00");

    // The retry claims again and sends.
    expect(await inviteAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "invited", email: "a@b.co", delivery: "sent" });
    expect(sendInvitation).toHaveBeenCalledTimes(2);
  });

  it("emails no address that already has an account, and says so", async () => {
    currentCaller.mockResolvedValue({ email: "me@example.com", isAdmin: true });
    invite.mockResolvedValue({ email: "a@b.co", invitationSentAt: null, registered: true });

    expect(await inviteAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "invited", email: "a@b.co", delivery: "has_account" });
    expect(claimInvitation).not.toHaveBeenCalled();
    expect(sendInvitation).not.toHaveBeenCalled();
  });
});

describe("resendInvitationAction", () => {
  const SENT = "2026-10-17 09:00:00.654321+00";
  const NEW = "2026-10-18 10:00:00.123456+00";
  beforeEach(() => currentCaller.mockResolvedValue({ email: "me@example.com", isAdmin: true }));

  it("re-claims on the stamp the page showed, and only the winner sends, once", async () => {
    reclaimInvitation.mockResolvedValue(NEW);
    expect(await resendInvitationAction(INVITE_IDLE, form({ email: "A@b.co", sent: SENT }))).toEqual({ status: "invited", email: "a@b.co", delivery: "resent" });
    expect(reclaimInvitation).toHaveBeenCalledWith(pool, "a@b.co", SENT);
    expect(sendInvitation).toHaveBeenCalledTimes(1);
    expect(releaseInvitation).not.toHaveBeenCalled();
    expect(revalidatePath).toHaveBeenCalledWith("/admin/waitlist");
  });

  it("a double click or two admins send one email: the stamp moves once", async () => {
    reclaimInvitation.mockResolvedValueOnce(NEW).mockResolvedValueOnce(null);
    const [first, second] = await Promise.all([
      resendInvitationAction(INVITE_IDLE, form({ email: "a@b.co", sent: SENT })),
      resendInvitationAction(INVITE_IDLE, form({ email: "a@b.co", sent: SENT })),
    ]);
    expect([first, second].map((state) => (state.status === "invited" ? state.delivery : state.status)).sort()).toEqual(["resend_skipped", "resent"]);
    expect(sendInvitation).toHaveBeenCalledTimes(1);
  });

  it("a re-send that fails puts the previous stamp back exactly", async () => {
    reclaimInvitation.mockResolvedValue(NEW);
    sendInvitation.mockRejectedValueOnce(new Error("Resend refused"));
    expect(await resendInvitationAction(INVITE_IDLE, form({ email: "a@b.co", sent: SENT }))).toEqual({ status: "invited", email: "a@b.co", delivery: "resend_failed" });
    expect(releaseInvitation).toHaveBeenCalledWith(pool, "a@b.co", NEW, SENT);
  });

  it("needs the stamp, an address and an admin", async () => {
    expect(await resendInvitationAction(INVITE_IDLE, form({ email: "a@b.co" }))).toEqual({ status: "error", error: "failed" });
    expect(await resendInvitationAction(INVITE_IDLE, form({ email: "nope", sent: SENT }))).toEqual({ status: "error", error: "failed" });
    currentCaller.mockResolvedValue({ email: "someone@example.com", isAdmin: false });
    expect(await resendInvitationAction(INVITE_IDLE, form({ email: "a@b.co", sent: SENT }))).toEqual({ status: "error", error: "forbidden" });
    expect(reclaimInvitation).not.toHaveBeenCalled();
    expect(sendInvitation).not.toHaveBeenCalled();
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
