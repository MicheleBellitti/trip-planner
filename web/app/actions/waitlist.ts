"use server";

import { revalidatePath } from "next/cache";
import { headers } from "next/headers";

import { normalizeEmail } from "@/lib/auth-policy";
import { ROUTES } from "@/lib/routes";
import { currentCaller } from "@/lib/server/admin";
import { readAuthConfig, type AuthServerConfig } from "@/lib/server/auth-config";
import { getPool } from "@/lib/server/db";
import { joinWindow } from "@/lib/server/rate-limit";
import { clientIp } from "@/lib/server/request-ip";
import { sendInvitation } from "@/lib/server/send-invitation";
import { verifyTurnstile } from "@/lib/server/turnstile";
import { claimInvitation, invite, joinWaitlist, releaseInvitation, removeRequest, type Queryable } from "@/lib/server/waitlist";
import { TURNSTILE_ACTIONS, TURNSTILE_FIELD } from "@/lib/turnstile";
import { parseJoinInput } from "@/lib/waitlist-policy";
import type { InviteDelivery, InviteState, JoinState, RemoveState } from "@/lib/waitlist-state";

/**
 * The waitlist's server actions (their states and initial values: lib/waitlist-state.ts).
 * `joinWaitlistAction` is public (the landing, the login's sent state): the client IP's window
 * (lib/server/rate-limit.ts) and the Turnstile token (lib/server/turnstile.ts) are checked before
 * the input, so a robot learns nothing about the shape check or the list. `inviteAction` is for
 * admins, checked here on every call with the backend's `GET /me` (lib/server/admin.ts), never
 * trusted from the page that rendered the button. No action ever puts an address in a log:
 * failures are logged by kind only.
 */

/** The public join: one answer, "received", whatever the address is (lib/waitlist-state.ts
 * `JoinState`); only the kind of outcome is logged. A public form may not claim the "admin" source. */
export async function joinWaitlistAction(_previous: JoinState, formData: FormData): Promise<JoinState> {
  const ip = clientIp(await headers());
  if (!joinWindow.hit(ip ?? "unknown").allowed) return { status: "error", error: "too_many_requests" };
  const token = formData.get(TURNSTILE_FIELD);
  if ((await verifyTurnstile(typeof token === "string" ? token : null, ip, TURNSTILE_ACTIONS.waitlist)) === "failed") {
    return { status: "error", error: "challenge_failed" };
  }
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

/**
 * Invites the address in `email` (with an optional `note`), sends the invitation, refreshes the
 * page. An address that already has an account gets no email. Otherwise the sending is claimed
 * first (lib/server/waitlist.ts `claimInvitation`): only the claimer sends, so two admins never
 * send it twice, and a send that fails gives the claim back for a retry.
 */
export async function inviteAction(_previous: InviteState, formData: FormData): Promise<InviteState> {
  const parsed = parseJoinInput({ email: formData.get("email"), note: formData.get("note") ?? "", source: "admin" }, ADMIN_SOURCE);
  if (!parsed.ok) return { status: "error", error: parsed.error === "invalid_source" ? "failed" : parsed.error };
  const config = readAuthConfig();
  if (!config) return { status: "error", error: "unavailable" };
  const gate = await admin();
  if (!gate.ok) return { status: "error", error: gate.error };
  const db = getPool(config.databaseUrl);
  const { email } = parsed.value;
  try {
    const before = await invite(db, { email, by: gate.email, note: parsed.value.note });
    const delivery = before.registered ? "has_account" : await deliver(db, config, email);
    revalidatePath(ROUTES.invites);
    return { status: "invited", email, delivery };
  } catch (error) {
    console.error("[waitlist] invite failed", error instanceof Error ? error.name : typeof error);
    return { status: "error", error: "failed" };
  }
}

/** Claims, sends, and gives the claim back when the email did not leave. */
async function deliver(db: Queryable, config: AuthServerConfig, email: string): Promise<InviteDelivery> {
  const claim = await claimInvitation(db, email);
  if (claim === null) return "already_sent";
  try {
    await sendInvitation(config, { email });
    return "sent";
  } catch (error) {
    console.error("[waitlist] invitation email failed", error instanceof Error ? error.message : typeof error);
    await releaseInvitation(db, email, claim);
    return "failed";
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
