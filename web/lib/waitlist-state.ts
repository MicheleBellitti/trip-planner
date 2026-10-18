/**
 * The states of the waitlist's server actions (app/actions/waitlist.ts), kept apart from them: a
 * "use server" module may export only its actions, and the components need the initial states
 * and the types on both sides.
 */

import type { JoinInputError } from "./waitlist-policy";

/**
 * A public join answers "received" whatever happened to the address (new, already listed, already
 * invited, already registered, on AUTH_ALLOWED_EMAILS): the page never tells a stranger whether an
 * address has an account or an invitation (Michele, 2026-10-18: "uguale per tutti"). The query's
 * own outcome (lib/waitlist-policy.ts `JoinOutcome`) stays on the server, for the logs.
 */
/** Why a join was refused besides the input: the challenge was not passed (Turnstile), too many
 * joins from this address or this client in a short time (the server's windows), no accounts
 * configured, or a failure. None of them depends on what the list holds. */
export type JoinRefusal = "challenge_failed" | "too_many_requests" | "unavailable" | "failed";

export type JoinState =
  | { status: "idle" }
  | { status: "received"; email: string }
  | { status: "error"; error: JoinInputError | JoinRefusal };

export const JOIN_IDLE: JoinState = { status: "idle" };

export type InviteError = "invalid_email" | "note_too_long" | "signed_out" | "forbidden" | "unavailable" | "failed";

/**
 * What happened to the invitation's email: it left; it had already left (or another admin is
 * sending it right now); the address already has an account, so nothing is sent; or it did not
 * leave (the claim is given back, "Invia l'email" tries again). The `resend_*` three answer
 * "Invia di nuovo": sent again; not sent, because the stamp had moved (another click or admin, or
 * an account meanwhile); not sent, the previous stamp restored.
 */
export type InviteDelivery = "sent" | "already_sent" | "has_account" | "failed" | "resent" | "resend_skipped" | "resend_failed";

export type InviteState =
  | { status: "idle" }
  | { status: "invited"; email: string; delivery: InviteDelivery }
  | { status: "error"; error: InviteError };

export const INVITE_IDLE: InviteState = { status: "idle" };

export type RemoveState =
  | { status: "idle" }
  | { status: "removed"; email: string }
  | { status: "error"; error: Exclude<InviteError, "note_too_long"> };

export const REMOVE_IDLE: RemoveState = { status: "idle" };
