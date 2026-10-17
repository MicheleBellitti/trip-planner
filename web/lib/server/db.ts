import "server-only";

import { Pool } from "pg";

/**
 * One connection pool per database URL for everything the web app reads and writes itself:
 * Better Auth's tables through Better Auth (lib/auth.ts) and the waitlist directly
 * (lib/server/waitlist.ts). The runtime keeps a process alive across requests, so a pool per
 * request would leak connections; a pool per URL is one pool in practice.
 */
const pools = new Map<string, Pool>();

export function getPool(connectionString: string): Pool {
  let pool = pools.get(connectionString);
  if (!pool) {
    pool = new Pool({ connectionString });
    pools.set(connectionString, pool);
  }
  return pool;
}
