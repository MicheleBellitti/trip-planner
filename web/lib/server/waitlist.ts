import type { QueryResultRow } from "pg";

import type { JoinInput, JoinOutcome, WaitlistSource } from "@/lib/waitlist-policy";

/**
 * The waitlist's queries (the `waitlist` table, backend/app/db.py `WaitlistRecord`; Alembic owns
 * it, this file only reads and writes rows). Every function takes the connection it should use,
 * so the tests pass a fake and the app passes the shared pool (lib/server/db.ts).
 *
 * The rules: one row per address; a row with `invited_at` is an invitation, and the sign-up
 * policy (lib/auth.ts) lets that address create an account; `note` keeps the first thing the
 * person wrote; an address that already has an account is never added.
 */
export interface Queryable {
  query<R extends QueryResultRow = QueryResultRow>(text: string, values?: unknown[]): Promise<{ rows: R[] }>;
}

export interface WaitlistRow {
  email: string;
  note: string;
  source: WaitlistSource;
  createdAt: string;
  invitedAt: string | null;
  invitedBy: string | null;
  invitationSentAt: string | null;
  /** The address already has an account (a `users` row). */
  registered: boolean;
}

interface RawRow extends QueryResultRow {
  email: string;
  note: string;
  source: string;
  created_at: Date;
  invited_at: Date | null;
  invited_by: string | null;
  invitation_sent_at: Date | null;
  registered: boolean;
}

function iso(value: Date | null): string | null {
  return value ? value.toISOString() : null;
}

function row(raw: RawRow): WaitlistRow {
  return {
    email: raw.email,
    note: raw.note,
    source: raw.source as WaitlistSource,
    createdAt: raw.created_at.toISOString(),
    invitedAt: iso(raw.invited_at),
    invitedBy: raw.invited_by,
    invitationSentAt: iso(raw.invitation_sent_at),
    registered: raw.registered,
  };
}

/** True when `email` (normalized) was invited: it may create an account. */
export async function isInvited(db: Queryable, email: string): Promise<boolean> {
  const { rows } = await db.query("SELECT 1 FROM waitlist WHERE email = $1 AND invited_at IS NOT NULL", [email]);
  return rows.length > 0;
}

/**
 * Adds a request. An address with an account is not added ("already_registered"); an address
 * already invited is not added either ("already_invited": the person should sign in); a repeat
 * request keeps its row and its first note ("already_listed", the note filled in if it was empty).
 */
export async function joinWaitlist(db: Queryable, input: JoinInput): Promise<JoinOutcome> {
  const registered = await db.query("SELECT 1 FROM users WHERE lower(email) = $1", [input.email]);
  if (registered.rows.length > 0) return "already_registered";
  const { rows } = await db.query<{ invited_at: Date | null; inserted: boolean }>(
    `INSERT INTO waitlist (email, note, source)
     VALUES ($1, $2, $3)
     ON CONFLICT (email) DO UPDATE
       SET note = CASE WHEN waitlist.note = '' THEN EXCLUDED.note ELSE waitlist.note END,
           updated_at = now()
     RETURNING invited_at, (xmax = 0) AS inserted`,
    [input.email, input.note, input.source],
  );
  const result = rows[0];
  if (!result) throw new Error("the waitlist insert returned no row");
  if (result.invited_at) return "already_invited";
  return result.inserted ? "joined" : "already_listed";
}

/** Every row, the pending requests first (newest first), then the invitations (newest first). */
export async function listWaitlist(db: Queryable): Promise<WaitlistRow[]> {
  const { rows } = await db.query<RawRow>(
    `SELECT w.email, w.note, w.source, w.created_at, w.invited_at, w.invited_by, w.invitation_sent_at,
            (u.id IS NOT NULL) AS registered
       FROM waitlist w
       LEFT JOIN users u ON lower(u.email) = w.email
      ORDER BY (w.invited_at IS NULL) DESC, w.created_at DESC`,
  );
  return rows.map(row);
}

/**
 * Invites `email`: a pending request becomes an invitation, an unknown address gets a row with
 * source "admin", an address already invited keeps its first invitation. Returns the row.
 */
export async function invite(
  db: Queryable,
  { email, by, note = "" }: { email: string; by: string; note?: string },
): Promise<WaitlistRow> {
  const { rows } = await db.query<RawRow>(
    `INSERT INTO waitlist (email, note, source, invited_at, invited_by)
     VALUES ($1, $2, 'admin', now(), $3)
     ON CONFLICT (email) DO UPDATE
       SET invited_at = COALESCE(waitlist.invited_at, now()),
           invited_by = COALESCE(waitlist.invited_by, EXCLUDED.invited_by),
           note = CASE WHEN waitlist.note = '' THEN EXCLUDED.note ELSE waitlist.note END,
           updated_at = now()
     RETURNING email, note, source, created_at, invited_at, invited_by, invitation_sent_at,
               EXISTS (SELECT 1 FROM users u WHERE lower(u.email) = waitlist.email) AS registered`,
    [email, note, by],
  );
  const result = rows[0];
  if (!result) throw new Error("the invitation upsert returned no row");
  return row(result);
}

/** Records that the invitation email left for `email` (the admin page shows it). */
export async function markInvitationSent(db: Queryable, email: string): Promise<void> {
  await db.query("UPDATE waitlist SET invitation_sent_at = now(), updated_at = now() WHERE email = $1", [email]);
}
