/**
 * The states of the waitlist's server actions (app/actions/waitlist.ts), kept apart from them: a
 * "use server" module may export only its actions, and the components need the initial states
 * and the types on both sides.
 */

import type { JoinInputError, JoinOutcome } from "./waitlist-policy";

export type JoinState =
  | { status: "idle" }
  | { status: JoinOutcome; email: string }
  | { status: "error"; error: JoinInputError | "unavailable" | "failed" };

export const JOIN_IDLE: JoinState = { status: "idle" };

export type InviteError = "invalid_email" | "note_too_long" | "signed_out" | "forbidden" | "unavailable" | "failed";

export type InviteState =
  | { status: "idle" }
  | { status: "invited"; email: string; emailSent: boolean; alreadyInvited: boolean }
  | { status: "error"; error: InviteError };

export const INVITE_IDLE: InviteState = { status: "idle" };
