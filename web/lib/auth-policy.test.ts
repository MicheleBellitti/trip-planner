import { describe, expect, it } from "vitest";

import { isSignupAllowed, normalizeEmail, parseAllowedEmails } from "./auth-policy";

describe("the sign-up allowlist", () => {
  it("an empty list lets nobody sign up", () => {
    for (const raw of [undefined, "", " , ,"]) {
      const list = parseAllowedEmails(raw);
      expect(isSignupAllowed("someone@example.com", list)).toBe(false);
    }
  });

  it("compares trimmed and lower-cased, with no wildcard but the whole-list star", () => {
    const list = parseAllowedEmails(" Michele@Example.com, friend@example.com ");
    expect(isSignupAllowed("michele@example.com", list)).toBe(true);
    expect(isSignupAllowed("  FRIEND@example.com ", list)).toBe(true);
    expect(isSignupAllowed("other@example.com", list)).toBe(false);
    expect(isSignupAllowed("*@example.com", list)).toBe(false);
  });

  it("a star opens sign-up to everybody with an address", () => {
    const list = parseAllowedEmails("*");
    expect(list.everyone).toBe(true);
    expect(isSignupAllowed("anyone@example.com", list)).toBe(true);
    expect(isSignupAllowed("not-an-email", list)).toBe(false);
    expect(isSignupAllowed("", list)).toBe(false);
    expect(isSignupAllowed(null, list)).toBe(false);
  });

  it("normalizes like the backend's PLANNER_ALLOWED_EMAILS", () => {
    expect(normalizeEmail("  Test@Example.COM ")).toBe("test@example.com");
  });
});
