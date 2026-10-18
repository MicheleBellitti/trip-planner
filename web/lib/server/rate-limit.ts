import "server-only";

/**
 * A sliding window per key, kept in the process: at most `limit` hits per `windowMs`. For the
 * public waitlist join (app/actions/waitlist.ts): ten joins per address in ten minutes. On Vercel
 * every function instance has its own window, so the limit is per instance and a redeploy starts
 * it over: it blunts a burst, Turnstile keeps the robots out, and the rows are the only thing at
 * stake. Keys are never logged.
 */

export interface Decision {
  allowed: boolean;
  /** Seconds until the oldest hit leaves the window, when refused. */
  retryAfterSeconds: number;
}

export class SlidingWindow {
  private readonly hits = new Map<string, number[]>();

  constructor(
    private readonly limit: number,
    private readonly windowMs: number,
    private readonly now: () => number = Date.now,
  ) {}

  hit(key: string): Decision {
    const moment = this.now();
    const horizon = moment - this.windowMs;
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

  /** Tests: start over. */
  clear(): void {
    this.hits.clear();
  }
}

export const JOIN_LIMIT = 10;
export const JOIN_WINDOW_MS = 10 * 60_000;

/** The waitlist join's window, shared by the process. */
export const joinWindow = new SlidingWindow(JOIN_LIMIT, JOIN_WINDOW_MS);
