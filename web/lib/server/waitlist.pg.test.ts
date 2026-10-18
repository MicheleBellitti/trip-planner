// @vitest-environment node
/**
 * The invitation claim against a real Postgres: only the database can show that two concurrent
 * claims never both win. Skipped unless WEB_TEST_DATABASE_URL names a scratch database (CI's web
 * job has none); the test works in its own schema and drops it.
 */
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { claimInvitation, invite, listWaitlist, reclaimInvitation, releaseInvitation, signInStanding } from "./waitlist";

const url = process.env.WEB_TEST_DATABASE_URL;
const SCHEMA = `waitlist_claim_${process.pid}`;

describe.skipIf(!url)("the invitation claim on Postgres", () => {
  let pool: Pool;

  beforeAll(async () => {
    pool = new Pool({ connectionString: url, max: 10, options: `-c search_path=${SCHEMA}` });
    await pool.query(`CREATE SCHEMA ${SCHEMA}`);
    // The columns of backend/migrations/versions/20261017_609ccf5bdc99_waitlist.py, and the
    // users table the queries join.
    await pool.query(`CREATE TABLE ${SCHEMA}.users (id text PRIMARY KEY, email text NOT NULL)`);
    await pool.query(`CREATE TABLE ${SCHEMA}.waitlist (
      email text PRIMARY KEY, note text NOT NULL DEFAULT '', source text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), invited_at timestamptz, invited_by text,
      invitation_sent_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now())`);
  });

  afterAll(async () => {
    await pool?.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await pool?.end();
  });

  it("hands the claim to exactly one of many concurrent invitations", async () => {
    await invite(pool, { email: "race@example.com", by: "me@example.com" });
    const claims = await Promise.all(Array.from({ length: 8 }, () => claimInvitation(pool, "race@example.com")));
    expect(claims.filter((claim) => claim !== null)).toHaveLength(1);
  });

  it("claims nothing for a pending request or an unknown address", async () => {
    await pool.query("INSERT INTO waitlist (email, source) VALUES ('pending@example.com', 'landing')");
    expect(await claimInvitation(pool, "pending@example.com")).toBeNull();
    expect(await claimInvitation(pool, "nobody@example.com")).toBeNull();
  });

  it("gives back its own claim exactly (microseconds included), never a later one", async () => {
    await invite(pool, { email: "retry@example.com", by: "me@example.com" });
    const claim = await claimInvitation(pool, "retry@example.com");
    expect(claim).not.toBeNull();
    await releaseInvitation(pool, "retry@example.com", claim!);
    const sent = async () =>
      (await pool.query<{ sent: Date | null }>("SELECT invitation_sent_at AS sent FROM waitlist WHERE email = 'retry@example.com'")).rows[0]?.sent;
    expect(await sent()).toBeNull();

    const retry = await claimInvitation(pool, "retry@example.com");
    expect(retry).not.toBeNull();
    await releaseInvitation(pool, "retry@example.com", claim!); // the first, stale claim
    expect(await sent()).not.toBeNull();
  });

  const stamp = async (email: string) =>
    (await pool.query<{ stamp: string | null }>("SELECT invitation_sent_at::text AS stamp FROM waitlist WHERE email = $1", [email])).rows[0]?.stamp ?? null;

  it("re-sends on a compare-and-swap: of many concurrent re-sends exactly one moves the stamp", async () => {
    await invite(pool, { email: "stuck@example.com", by: "me@example.com" });
    const first = await claimInvitation(pool, "stuck@example.com"); // the process died after this
    expect(first).not.toBeNull();
    // The page shows the exact stamp (listWaitlist), microseconds included.
    const shown = (await listWaitlist(pool)).rows.find((row) => row.email === "stuck@example.com")?.invitationSentClaim;
    expect(shown).toBe(first);
    const claims = await Promise.all(Array.from({ length: 8 }, () => reclaimInvitation(pool, "stuck@example.com", shown!)));
    const winners = claims.filter((claim) => claim !== null);
    expect(winners).toHaveLength(1);
    expect(await stamp("stuck@example.com")).toBe(winners[0]);
    expect(await reclaimInvitation(pool, "stuck@example.com", shown!)).toBeNull(); // a stale page sends nothing
  });

  it("a failed re-send puts the previous stamp back exactly", async () => {
    await invite(pool, { email: "flaky@example.com", by: "me@example.com" });
    const previous = (await claimInvitation(pool, "flaky@example.com"))!;
    const claim = (await reclaimInvitation(pool, "flaky@example.com", previous))!;
    expect(claim).not.toBe(previous);
    await releaseInvitation(pool, "flaky@example.com", claim, previous);
    expect(await stamp("flaky@example.com")).toBe(previous);
    expect(await reclaimInvitation(pool, "flaky@example.com", previous)).not.toBeNull(); // and it can be retried
  });

  it("never re-sends to an address that has an account, and reads the sign-in standing in one query", async () => {
    await invite(pool, { email: "member@example.com", by: "me@example.com" });
    const previous = (await claimInvitation(pool, "member@example.com"))!;
    await pool.query("INSERT INTO users (id, email) VALUES ('u1', 'Member@Example.com')");
    expect(await reclaimInvitation(pool, "member@example.com", previous)).toBeNull();
    expect(await signInStanding(pool, "member@example.com")).toEqual({ hasAccount: true, invited: true });
    expect(await signInStanding(pool, "pending@example.com")).toEqual({ hasAccount: false, invited: false });
    expect(await signInStanding(pool, "nobody@example.com")).toEqual({ hasAccount: false, invited: false });
  });
});
