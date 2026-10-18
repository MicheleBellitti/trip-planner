import { toNextJsHandler } from "better-auth/next-js";

import { auth } from "@/lib/auth";

/** Better Auth's endpoints (sign-in, magic-link verify, Google callback, get-session, sign-out).
 * Without a configured database every call answers 503 with the API's error envelope shape. */
const UNCONFIGURED = {
  detail: {
    code: "auth_unavailable",
    message: "Gli account non sono configurati su questo server.",
    data: null,
  },
};

async function unavailable(): Promise<Response> {
  return Response.json(UNCONFIGURED, { status: 503, headers: { "Cache-Control": "no-store" } });
}

const handler = auth ? toNextJsHandler(auth) : { GET: unavailable, POST: unavailable };

export const GET = handler.GET;
export const POST = handler.POST;
