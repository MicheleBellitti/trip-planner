import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/** A fresh module each time: `readAuthConfig` caches its first answer. */
async function read() {
  vi.resetModules();
  const { readAuthConfig } = await import("./auth-config");
  return readAuthConfig();
}

const PRODUCTION = {
  NODE_ENV: "production",
  DATABASE_URL: "postgresql://atlas:x@db.example:5432/atlas",
  BETTER_AUTH_SECRET: "a".repeat(32),
  BETTER_AUTH_URL: "https://atlas.bellittim.com",
  AUTH_COOKIE_DOMAIN: "bellittim.com",
  AUTH_ALLOWED_EMAILS: "a@example.com",
  RESEND_API_KEY: "re_x",
  AUTH_EMAIL_FROM: "Atlas <accedi@example.com>",
  GOOGLE_CLIENT_ID: "",
  GOOGLE_CLIENT_SECRET: "",
};

function stub(values: Record<string, string>) {
  for (const [name, value] of Object.entries(values)) vi.stubEnv(name, value);
}

describe("readAuthConfig", () => {
  beforeEach(() => stub(PRODUCTION));
  afterEach(() => vi.unstubAllEnvs());

  it("reads a complete production setup", async () => {
    const config = await read();
    expect(config).toMatchObject({ cookieDomain: "bellittim.com", baseUrl: "https://atlas.bellittim.com", production: true });
  });

  it("refuses to start in production without AUTH_COOKIE_DOMAIN: a host-only cookie never reaches the API", async () => {
    for (const empty of ["", "   "]) {
      vi.stubEnv("AUTH_COOKIE_DOMAIN", empty);
      await expect(read()).rejects.toThrow(/AUTH_COOKIE_DOMAIN/);
    }
  });

  it("keeps a host-only cookie in development, where localhost needs one", async () => {
    stub({ NODE_ENV: "development", AUTH_COOKIE_DOMAIN: "", RESEND_API_KEY: "", AUTH_EMAIL_FROM: "" });
    expect((await read())?.cookieDomain).toBeNull();
    vi.stubEnv("AUTH_COOKIE_DOMAIN", "bellittim.com");
    expect((await read())?.cookieDomain).toBe("bellittim.com");
  });

  it("without a database the accounts are not configured, whatever else is missing", async () => {
    stub({ DATABASE_URL: "", AUTH_COOKIE_DOMAIN: "" });
    expect(await read()).toBeNull();
  });
});
