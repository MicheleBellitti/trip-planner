import "server-only";

/**
 * A sliding window per key, kept in the process: at most `limit` hits per `windowMs`. For the
 * public waitlist join (app/actions/waitlist.ts): ten joins per client IP (lib/server/request-ip.ts)
 * in ten minutes, checked before the challenge and the input, and answered with the same words for
 * every address (no enumeration). On Vercel every function instance has its own window, so the
 * limit is per instance and a redeploy starts it over: it blunts a burst, Turnstile keeps the
 * robots out, and the rows are the only thing at stake. Keys whose hits all left the window are
 * dropped (a key on every hit, and every key at most once per window), so the map holds only the
 * clients of the last two windows. Keys are never logged.
 */

export interface Decision {
  allowed: boolean;
  /** Seconds until the oldest hit leaves the window, when refused. */
  retryAfterSeconds: number;
}

export class SlidingWindow {
  private readonly hits = new Map<string, number[]>();
  private sweptAt: number | null = null;

  constructor(
    private readonly limit: number,
    private readonly windowMs: number,
    private readonly now: () => number = Date.now,
  ) {}

  hit(key: string): Decision {
    const moment = this.now();
    const horizon = moment - this.windowMs;
    if (this.sweptAt === null || moment - this.sweptAt >= this.windowMs) {
      this.sweep(horizon);
      this.sweptAt = moment;
    }
    const recent = (this.hits.get(key) ?? []).filter((at) => at > horizon);
    if (recent.length >= this.limit) {
      this.hits.set(key, recent);
      const oldest = recent[0] ?? moment;
      return { allowed: false, retryAfterSeconds: Math.max(1, Math.ceil((oldest + this.windowMs - moment) / 1000)) };
    }
    recent.push(moment);
    this.hits.set(key, recent);
    return { allowed: true, retryAfterSeconds: 0 };
  }

  /** How many keys the window holds (tests: it stays bounded). */
  get size(): number {
    return this.hits.size;
  }

  private sweep(horizon: number): void {
    for (const [key, hits] of this.hits) {
      const recent = hits.filter((at) => at > horizon);
      if (recent.length === 0) this.hits.delete(key);
      else if (recent.length !== hits.length) this.hits.set(key, recent);
    }
  }

  /** Tests: start over. */
  clear(): void {
    this.hits.clear();
    this.sweptAt = null;
  }
}

export const JOIN_LIMIT = 10;
export const JOIN_WINDOW_MS = 10 * 60_000;

/** The waitlist join's window, shared by the process. */
export const joinWindow = new SlidingWindow(JOIN_LIMIT, JOIN_WINDOW_MS);
