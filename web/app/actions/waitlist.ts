"use server";

import { revalidatePath } from "next/cache";

import { normalizeEmail } from "@/lib/auth-policy";
import { ROUTES } from "@/lib/routes";
import { currentCaller } from "@/lib/server/admin";
import { readAuthConfig } from "@/lib/server/auth-config";
import { getPool } from "@/lib/server/db";
import { sendInvitation } from "@/lib/server/send-invitation";
import { invite, joinWaitlist, markInvitationSent, removeRequest } from "@/lib/server/waitlist";
import { parseJoinInput } from "@/lib/waitlist-policy";
import type { InviteState, JoinState, RemoveState } from "@/lib/waitlist-state";

/**
 * The waitlist's server actions (their states and initial values: lib/waitlist-state.ts).
 * `joinWaitlistAction` is public (the landing, the login's refusal); `inviteAction` is for admins,
 * checked here on every call with the backend's `GET /me` (lib/server/admin.ts), never trusted
 * from the page that rendered the button. Neither action ever puts an address in a log: failures
 * are logged by kind only.
 */

/** The public join: one answer, "received", whatever the address is (lib/waitlist-state.ts
 * `JoinState`); only the kind of outcome is logged. A public form may not claim the "admin" source. */
export async function joinWaitlistAction(_previous: JoinState, formData: FormData): Promise<JoinState> {
  const parsed = parseJoinInput({ email: formData.get("email"), note: formData.get("note"), source: formData.get("source") });
  if (!parsed.ok) return { status: "error", error: parsed.error };
  const config = readAuthConfig();
  if (!config) return { status: "error", error: "unavailable" };
  try {
    const outcome = await joinWaitlist(getPool(config.databaseUrl), parsed.value);
    console.info("[waitlist] join", outcome);
    return { status: "received", email: parsed.value.email };
  } catch (error) {
    console.error("[waitlist] join failed", error instanceof Error ? error.name : typeof error);
    return { status: "error", error: "failed" };
  }
}

/** The admin actions alone write the "admin" source. */
const ADMIN_SOURCE = ["admin"] as const;

type AdminGate =
  | { ok: true; email: string }
  | { ok: false; error: "signed_out" | "forbidden" | "failed" };

/** The backend's answer on who is calling, as the admin actions read it. */
async function admin(): Promise<AdminGate> {
  let caller;
  try {
    caller = await currentCaller();
  } catch (error) {
    console.error("[waitlist] admin check failed", error instanceof Error ? error.message : typeof error);
    return { ok: false, error: "failed" };
  }
  if (!caller) return { ok: false, error: "signed_out" };
  if (!caller.isAdmin) return { ok: false, error: "forbidden" };
  return { ok: true, email: normalizeEmail(caller.email) };
}

/** Invites the address in `email` (with an optional `note`), sends the invitation, refreshes the page. */
export async function inviteAction(_previous: InviteState, formData: FormData): Promise<InviteState> {
  const parsed = parseJoinInput({ email: formData.get("email"), note: formData.get("note") ?? "", source: "admin" }, ADMIN_SOURCE);
  if (!parsed.ok) return { status: "error", error: parsed.error === "invalid_source" ? "failed" : parsed.error };
  const config = readAuthConfig();
  if (!config) return { status: "error", error: "unavailable" };
  const gate = await admin();
  if (!gate.ok) return { status: "error", error: gate.error };
  const db = getPool(config.databaseUrl);
  try {
    const before = await invite(db, { email: parsed.value.email, by: gate.email, note: parsed.value.note });
    const alreadyInvited = before.invitationSentAt !== null;
    let emailSent = false;
    if (!alreadyInvited) {
      try {
        await sendInvitation(config, { email: parsed.value.email });
        await markInvitationSent(db, parsed.value.email);
        emailSent = true;
      } catch (error) {
        console.error("[waitlist] invitation email failed", error instanceof Error ? error.message : typeof error);
      }
    }
    revalidatePath(ROUTES.invites);
    return { status: "invited", email: parsed.value.email, emailSent, alreadyInvited };
  } catch (error) {
    console.error("[waitlist] invite failed", error instanceof Error ? error.name : typeof error);
    return { status: "error", error: "failed" };
  }
}

/** Removes a pending request (a typo, a stranger who should not wait); an invitation is never removed here. */
export async function removeRequestAction(_previous: RemoveState, formData: FormData): Promise<RemoveState> {
  const parsed = parseJoinInput({ email: formData.get("email"), note: "", source: "admin" }, ADMIN_SOURCE);
  if (!parsed.ok) return { status: "error", error: "invalid_email" };
  const config = readAuthConfig();
  if (!config) return { status: "error", error: "unavailable" };
  const gate = await admin();
  if (!gate.ok) return { status: "error", error: gate.error };
  try {
    const removed = await removeRequest(getPool(config.databaseUrl), parsed.value.email);
    revalidatePath(ROUTES.invites);
    return removed ? { status: "removed", email: parsed.value.email } : { status: "error", error: "failed" };
  } catch (error) {
    console.error("[waitlist] remove failed", error instanceof Error ? error.name : typeof error);
    return { status: "error", error: "failed" };
  }
}
