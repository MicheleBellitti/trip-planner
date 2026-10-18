import { describe, expect, it } from "vitest";

import { safeReturnTo } from "./return-to";
import { ROUTES } from "./routes";

const ORIGIN = "https://atlas.bellittim.com";

describe("safeReturnTo", () => {
  it("keeps a same-origin page with its query and hash", () => {
    expect(safeReturnTo(`${ORIGIN}/plans/abc?tab=piano#giorno-2`, ORIGIN)).toBe("/plans/abc?tab=piano#giorno-2");
    expect(safeReturnTo("/new?esempio=1", ORIGIN)).toBe("/new?esempio=1");
    expect(safeReturnTo("/", ORIGIN)).toBe("/"); // the landing is a page of this origin too
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
      expect(safeReturnTo(raw, ORIGIN)).toBe(ROUTES.plans);
    }
  });

  it("falls back when the parsed path would start with `//`, however the input spells it", () => {
    for (const raw of [
      "/.//evil.com",
      "/a/..//evil.com",
      "/%2e//evil.com",
      "/%2E//evil.com",
      "/././/evil.com",
      `${ORIGIN}//evil.com`,
      `${ORIGIN}/.//evil.com`,
      `${ORIGIN}/a/..//evil.com`,
      `${ORIGIN}/%2e//evil.com`,
    ]) {
      expect(new URL(raw, ORIGIN).pathname.startsWith("//")).toBe(true); // the case is real
      expect(safeReturnTo(raw, ORIGIN)).toBe(ROUTES.plans);
    }
  });

  it("still keeps an ordinary path that merely contains dot segments", () => {
    expect(safeReturnTo("/plans/./abc", ORIGIN)).toBe("/plans/abc");
    expect(safeReturnTo("/a/../plans", ORIGIN)).toBe("/plans");
  });

  it("never loops back to the login page itself", () => {
    expect(safeReturnTo("/login?returnTo=%2Fplans", ORIGIN)).toBe(ROUTES.plans);
  });

  it("accepts the origin with a trailing slash", () => {
    expect(safeReturnTo("/evals", `${ORIGIN}/`)).toBe("/evals");
  });
});
