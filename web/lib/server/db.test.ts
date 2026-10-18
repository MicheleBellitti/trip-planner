// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { getPool, POOL_MAX } from "./db";

describe("getPool", () => {
  it("keeps one small pool per URL, and an idle connection's failure is logged, never thrown", () => {
    const url = "postgresql://nobody@127.0.0.1:1/never";
    const pool = getPool(url);
    expect(getPool(url)).toBe(pool);
    expect(pool.options.max).toBe(POOL_MAX);
    expect(POOL_MAX).toBeLessThanOrEqual(5);
    expect(pool.listenerCount("error")).toBe(1);

    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const dropped = Object.assign(new Error("Connection terminated unexpectedly at db.internal:5432"), { code: "ECONNRESET" });
    expect(() => pool.emit("error", dropped)).not.toThrow();
    expect(log).toHaveBeenCalledWith("[db] idle connection failed", "Error", "ECONNRESET");
    expect(JSON.stringify(log.mock.calls)).not.toContain("db.internal"); // no host, no URL
  });
});
