/**
 * The waitlist's rules (pure, so they are tested without a database): what a request must look
 * like, where it may come from, how long the note may be. The data lives in the `waitlist` table
 * (backend/app/db.py `WaitlistRecord`), written by lib/server/waitlist.ts.
 */

import { normalizeEmail } from "./auth-policy";

/** The note is two or three lines: enough to say which trip, not a form to fill. */
export const WAITLIST_NOTE_MAX = 280;
/** An address longer than this is not one (RFC 5321's path limit, minus the brackets). */
const EMAIL_MAX = 254;

/** Where a row came from: the landing's form, the login's refusal, or an admin adding an address. */
export const WAITLIST_SOURCES = ["landing", "login", "admin"] as const;
export type WaitlistSource = (typeof WAITLIST_SOURCES)[number];
/** The sources a public request may claim: "admin" is set only by the admin actions. */
export const PUBLIC_WAITLIST_SOURCES = ["landing", "login"] as const satisfies readonly WaitlistSource[];

export interface JoinInput {
  /** Trimmed and lower-cased. */
  email: string;
  /** Trimmed, control characters other than line breaks removed; may be empty. */
  note: string;
  source: WaitlistSource;
}

export type JoinInputError = "invalid_email" | "note_too_long" | "invalid_source";

export type JoinInputResult = { ok: true; value: JoinInput } | { ok: false; error: JoinInputError };

/** A shape check, not a validator: the magic link proves the address later. */
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const CONTROL_CHARACTERS = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Reads a join request from a form or a client call; every field is checked, none trusted. `sources`
 * are the ones this caller may claim: the public ones unless an admin action says otherwise. */
export function parseJoinInput(
  raw: { email?: unknown; note?: unknown; source?: unknown },
  sources: readonly WaitlistSource[] = PUBLIC_WAITLIST_SOURCES,
): JoinInputResult {
  const email = normalizeEmail(text(raw.email));
  if (!email || email.length > EMAIL_MAX || !EMAIL_SHAPE.test(email)) return { ok: false, error: "invalid_email" };
  const note = text(raw.note).replace(CONTROL_CHARACTERS, "").replace(/\r\n?/g, "\n").trim();
  if (note.length > WAITLIST_NOTE_MAX) return { ok: false, error: "note_too_long" };
  const source = text(raw.source);
  if (!(sources as readonly string[]).includes(source)) return { ok: false, error: "invalid_source" };
  return { ok: true, value: { email, note, source: source as WaitlistSource } };
}

/** What happened to a join request (lib/server/waitlist.ts `joinWaitlist`): for the server's logs
 * only, never for the caller (lib/waitlist-state.ts `JoinState`). */
export type JoinOutcome = "joined" | "already_listed" | "already_invited" | "already_registered";
