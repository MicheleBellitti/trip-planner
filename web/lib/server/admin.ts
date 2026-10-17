import "server-only";

import { headers } from "next/headers";

import { getConfig } from "@/lib/config";
import { MeSchema } from "@/lib/schemas/api";

/** Who is making this request: signed out (null), or an account and whether it manages the planner. */
export type Caller = { email: string; isAdmin: boolean } | null;

/**
 * Asks the backend's `GET /me` with the request's own cookie. The backend is the authority on who
 * is signed in and on the admin role (ADMIN_EMAILS, backend/app/auth.py): this app never keeps a
 * second list. A 401 is "signed out"; any other failure throws, and the caller decides what the
 * page says. Server components call it inside a Suspense boundary (it reads the request).
 */
export async function currentCaller(): Promise<Caller> {
  const cookie = (await headers()).get("cookie") ?? "";
  const response = await fetch(`${getConfig().apiUrl}/me`, {
    headers: { cookie, accept: "application/json" },
    cache: "no-store",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`GET /me answered ${response.status}`);
  const me = MeSchema.parse(await response.json());
  return { email: me.email, isAdmin: me.is_admin };
}
