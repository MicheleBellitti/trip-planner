/**
 * Parsing of the plan's SSE messages (GET /plans/{id}/events, backend/app/routes.py):
 *
 * - default `message` events: `id: <seq>`, `data: <UIEvent JSON>`;
 * - one `event: end` with `data: {"status": "<terminal status>"}`, after which the server
 *   closes the stream;
 * - `: ping` comments every 15 s, which EventSource never surfaces.
 *
 * Every message is validated with Zod against schema/ui_event.json (generated schema). An
 * invalid message is dropped, never half-used, and warned about outside production builds
 * (the warning carries the validation issues, not the event's content).
 */

import * as z from "zod/mini";

import { StreamEndSchema, type PlanStatus } from "../schemas/api";
import { UIEventSchema, type UIEvent } from "../schemas/generated/ui-event";

/** Name of the SSE event that closes the stream (routes.END_EVENT). */
export const END_EVENT = "end";

function warnInDevelopment(message: string, detail?: string): void {
  if (process.env.NODE_ENV !== "production") {
    console.warn(`[plan-events] ${message}${detail ? `\n${detail}` : ""}`);
  }
}

function parseJson(data: unknown): { ok: true; value: unknown } | { ok: false } {
  if (typeof data !== "string") return { ok: false };
  try {
    return { ok: true, value: JSON.parse(data) as unknown };
  } catch {
    return { ok: false };
  }
}

/** The UIEvent in an SSE `message`'s data, or null (dropped) when it is not one. */
export function parseUIEvent(data: unknown): UIEvent | null {
  const json = parseJson(data);
  if (!json.ok) {
    warnInDevelopment("dropped a message that is not JSON");
    return null;
  }
  const result = UIEventSchema.safeParse(json.value);
  if (!result.success) {
    warnInDevelopment("dropped an event that does not match schema/ui_event.json", z.prettifyError(result.error));
    return null;
  }
  return result.data;
}

/** The terminal status in an `event: end` message's data, or null when unreadable. */
export function parseStreamEnd(data: unknown): PlanStatus | null {
  const json = parseJson(data);
  const result = json.ok ? StreamEndSchema.safeParse(json.value) : null;
  if (!result?.success) {
    warnInDevelopment("unreadable `end` event");
    return null;
  }
  return result.data.status;
}
