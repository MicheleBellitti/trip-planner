import { describe, expect, it, vi } from "vitest";

import {
  claimInvitation,
  invite,
  isInvited,
  joinWaitlist,
  listWaitlist,
  releaseInvitation,
  removeRequest,
  WAITLIST_LIST_LIMIT,
  type Queryable,
} from "./waitlist";

/** A database that answers each query in turn and records what it was asked. */
function fakeDb(...answers: unknown[][]): Queryable & { calls: { text: string; values: unknown[] | undefined }[] } {
  const calls: { text: string; values: unknown[] | undefined }[] = [];
  const queue = [...answers];
  return {
    calls,
    query: vi.fn(async (text: string, values?: unknown[]) => {
      calls.push({ text: text.replace(/\s+/g, " ").trim(), values });
      return { rows: (queue.shift() ?? []) as never[] };
    }) as Queryable["query"],
  };
}

const NOW = new Date("2026-10-17T18:00:00Z");

describe("the waitlist queries", () => {
  it("isInvited asks for a row with invited_at", async () => {
    const db = fakeDb([{ "?column?": 1 }]);
    expect(await isInvited(db, "friend@example.com")).toBe(true);
    expect(db.calls[0]).toEqual({ text: "SELECT 1 FROM waitlist WHERE email = $1 AND invited_at IS NOT NULL", values: ["friend@example.com"] });
    expect(await isInvited(fakeDb([]), "nobody@example.com")).toBe(false);
  });

  it("joinWaitlist inserts a new request, keeps a repeat and tells an invited or registered address apart", async () => {
    const joined = fakeDb([], [{ invited_at: null, inserted: true }]);
    expect(await joinWaitlist(joined, { email: "friend@example.com", note: "Lisbona", source: "landing" })).toBe("joined");
    expect(joined.calls[0]).toEqual({ text: "SELECT 1 FROM users WHERE lower(email) = $1", values: ["friend@example.com"] });
    expect(joined.calls[1]?.text).toContain("INSERT INTO waitlist (email, note, source) VALUES ($1, $2, $3) ON CONFLICT (email) DO UPDATE");
    expect(joined.calls[1]?.text).toContain("CASE WHEN waitlist.note = '' THEN EXCLUDED.note ELSE waitlist.note END"); // the first note stays
    expect(joined.calls[1]?.values).toEqual(["friend@example.com", "Lisbona", "landing"]);

    expect(await joinWaitlist(fakeDb([], [{ invited_at: null, inserted: false }]), { email: "a@b.co", note: "", source: "login" })).toBe("already_listed");
    expect(await joinWaitlist(fakeDb([], [{ invited_at: NOW, inserted: false }]), { email: "a@b.co", note: "", source: "login" })).toBe("already_invited");
    const registered = fakeDb([{ "?column?": 1 }]);
    expect(await joinWaitlist(registered, { email: "a@b.co", note: "", source: "login" })).toBe("already_registered");
    expect(registered.calls).toHaveLength(1); // never written
  });

  it("listWaitlist maps the rows, pending first, with the account flag", async () => {
    const db = fakeDb([
      { email: "a@b.co", note: "", source: "landing", created_at: NOW, invited_at: null, invited_by: null, invitation_sent_at: null, registered: false },
      { email: "c@d.co", note: "ciao", source: "admin", created_at: NOW, invited_at: NOW, invited_by: "me@x.it", invitation_sent_at: NOW, registered: true },
    ]);
    const { rows, truncated } = await listWaitlist(db);
    expect(truncated).toBe(false);
    expect(rows).toEqual([
      { email: "a@b.co", note: "", source: "landing", createdAt: NOW.toISOString(), invitedAt: null, invitedBy: null, invitationSentAt: null, registered: false },
      { email: "c@d.co", note: "ciao", source: "admin", createdAt: NOW.toISOString(), invitedAt: NOW.toISOString(), invitedBy: "me@x.it", invitationSentAt: NOW.toISOString(), registered: true },
    ]);
    expect(db.calls[0]?.text).toContain("ORDER BY (w.invited_at IS NULL) DESC, w.created_at DESC");
    expect(db.calls[0]?.text).toContain("LEFT JOIN users u ON lower(u.email) = w.email");
  });

  it("listWaitlist reads at most the limit, one more to know the list is cut", async () => {
    expect(WAITLIST_LIST_LIMIT).toBe(500);
    const raw = (email: string) => ({ email, note: "", source: "landing", created_at: NOW, invited_at: null, invited_by: null, invitation_sent_at: null, registered: false });
    const db = fakeDb([raw("a@b.co"), raw("c@d.co"), raw("e@f.co")]);
    const { rows, truncated } = await listWaitlist(db, 2);
    expect(rows.map((item) => item.email)).toEqual(["a@b.co", "c@d.co"]);
    expect(truncated).toBe(true);
    expect(db.calls[0]?.text).toMatch(/LIMIT \$1$/);
    expect(db.calls[0]?.values).toEqual([3]);
    expect((await listWaitlist(fakeDb([raw("a@b.co"), raw("c@d.co")]), 2)).truncated).toBe(false);
    expect((await listWaitlist(fakeDb([]))).rows).toEqual([]);
  });

  it("invite upserts the row, keeping a first invitation, and reports it", async () => {
    const db = fakeDb([{ email: "a@b.co", note: "", source: "admin", created_at: NOW, invited_at: NOW, invited_by: "me@x.it", invitation_sent_at: null, registered: false }]);
    const row = await invite(db, { email: "a@b.co", by: "me@x.it" });
    expect(row).toMatchObject({ email: "a@b.co", invitedAt: NOW.toISOString(), invitedBy: "me@x.it", invitationSentAt: null });
    expect(db.calls[0]?.text).toContain("VALUES ($1, $2, 'admin', now(), $3)");
    expect(db.calls[0]?.text).toContain("invited_at = COALESCE(waitlist.invited_at, now())");
    expect(db.calls[0]?.values).toEqual(["a@b.co", "", "me@x.it"]);
    await expect(invite(fakeDb([]), { email: "a@b.co", by: "me@x.it" })).rejects.toThrow(/no row/);
  });

  it("removeRequest deletes a pending row only, and says whether one went", async () => {
    const db = fakeDb([{ email: "a@b.co" }]);
    expect(await removeRequest(db, "a@b.co")).toBe(true);
    expect(db.calls[0]).toEqual({ text: "DELETE FROM waitlist WHERE email = $1 AND invited_at IS NULL RETURNING email", values: ["a@b.co"] });
    expect(await removeRequest(fakeDb([]), "invited@b.co")).toBe(false);
  });

  it("claimInvitation stamps an unsent invitation only, and hands back the exact stamp", async () => {
    const db = fakeDb([{ claim: "2026-10-18 10:00:00.123456+00" }]);
    expect(await claimInvitation(db, "a@b.co")).toBe("2026-10-18 10:00:00.123456+00");
    expect(db.calls[0]?.text).toBe(
      "UPDATE waitlist SET invitation_sent_at = now(), updated_at = now() WHERE email = $1 AND invited_at IS NOT NULL AND invitation_sent_at IS NULL RETURNING invitation_sent_at::text AS claim",
    );
    expect(await claimInvitation(fakeDb([]), "a@b.co")).toBeNull();
  });

  it("releaseInvitation gives back only its own claim", async () => {
    const db = fakeDb([]);
    await releaseInvitation(db, "a@b.co", "2026-10-18 10:00:00.123456+00");
    expect(db.calls[0]).toEqual({
      text: "UPDATE waitlist SET invitation_sent_at = NULL, updated_at = now() WHERE email = $1 AND invitation_sent_at = $2::timestamptz",
      values: ["a@b.co", "2026-10-18 10:00:00.123456+00"],
    });
  });
});
