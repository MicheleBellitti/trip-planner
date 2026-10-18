import "server-only";

import { Pool } from "pg";

/**
 * One connection pool per database URL for everything the web app reads and writes itself:
 * Better Auth's tables through Better Auth (lib/auth.ts) and the waitlist directly
 * (lib/server/waitlist.ts). The runtime keeps a process alive across requests, so a pool per
 * request would leak connections; a pool per URL is one pool in practice.
 */
const pools = new Map<string, Pool>();

/** Connections per pool: each serverless instance has its own pool, and Railway's Postgres has a
 * small connection limit shared with the backend, so a few per instance (pg's default is 10). */
export const POOL_MAX = 3;

export function getPool(connectionString: string): Pool {
  let pool = pools.get(connectionString);
  if (!pool) {
    pool = new Pool({ connectionString, max: POOL_MAX });
    // An idle client dropped by the server or Railway's proxy emits 'error' on the pool; without a
    // listener Node treats it as unhandled and the process dies. The pool discards that client and
    // the next query opens another. Log the kind and code only: the message can carry the host.
    pool.on("error", (error: Error & { code?: string }) => {
      console.error("[db] idle connection failed", error.name, error.code ?? "");
    });
    pools.set(connectionString, pool);
  }
  return pool;
}
