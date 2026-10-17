import { describe, expect, it } from "vitest";

import { safeReturnTo } from "./return-to";

const ORIGIN = "https://atlas.bellittim.com";

describe("safeReturnTo", () => {
  it("keeps a same-origin page with its query and hash", () => {
    expect(safeReturnTo(`${ORIGIN}/plans/abc?tab=piano#giorno-2`, ORIGIN)).toBe("/plans/abc?tab=piano#giorno-2");
    expect(safeReturnTo("/new?esempio=1", ORIGIN)).toBe("/new?esempio=1");
    expect(safeReturnTo("/", ORIGIN)).toBe("/");
  });

  it("falls back to the plans list for anything that is not this origin", () => {
    for (const raw of [
      "https://evil.example/plans",
      "//evil.example/plans",
      "/\\evil.example",
      "https://atlas.bellittim.com.evil.example/",
      "javascript:alert(1)",
      "mailto:someone@example.com",
      "http://atlas.bellittim.com/plans", // the scheme matters: http is another origin
      "not a url at all \\",
      "",
      "   ",
      null,
      undefined,
    ]) {
      expect(safeReturnTo(raw, ORIGIN)).toBe("/");
    }
  });

  it("never loops back to the login page itself", () => {
    expect(safeReturnTo("/login?returnTo=%2Fplans", ORIGIN)).toBe("/");
  });

  it("accepts the origin with a trailing slash", () => {
    expect(safeReturnTo("/evals", `${ORIGIN}/`)).toBe("/evals");
  });
});
