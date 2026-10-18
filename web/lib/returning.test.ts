import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN_KEY, markSignedIn, markSignedOut, SIGNED_IN_KEY } from "./returning";
import { SKIP_LANDING_BOOTSTRAP, SKIP_LANDING_DECISION } from "./skip-landing";

type Decide = (storage: Pick<Storage, "getItem">, referrer: string, origin: string, hash?: string) => string | null;
// The same source the inline script runs.
const decide = new Function(`return (${SKIP_LANDING_DECISION})`)() as Decide;
const ORIGIN = "https://atlas.bellittim.com";
const marked = { getItem: () => "1" };
const unmarked = { getItem: () => null };

afterEach(() => localStorage.clear());

describe("the landing skip", () => {
  it("sends a signed-in browser arriving from outside to the plans", () => {
    expect(decide(marked, "", ORIGIN)).toBe("/plans");
    expect(decide(marked, "https://viaggi.bellittim.com/accedi", ORIGIN)).toBe("/plans");
  });

  it("shows the landing to a signed-in browser that came from a page of this site", () => {
    expect(decide(marked, `${ORIGIN}/plans/6f1c2a7e`, ORIGIN)).toBeNull();
  });

  it("shows the landing without the mark", () => {
    expect(decide(unmarked, "", ORIGIN)).toBeNull();
  });

  it("fails safe to the landing when storage throws", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
    };
    expect(decide(blocked, "", ORIGIN)).toBeNull();
  });

  it("shows the landing to anyone who links to a part of it, so a signed-in browser can still reach it", () => {
    expect(decide(marked, "", ORIGIN, "#come-funziona")).toBeNull();
    expect(decide(marked, "", ORIGIN, "")).toBe("/plans");
  });

  it("reads the fragment in the inline script", () => {
    expect(SKIP_LANDING_BOOTSTRAP).toContain("location.hash");
  });

  it("treats an unreadable referrer as outside", () => {
    expect(decide(marked, "not a url", ORIGIN)).toBe("/plans");
  });

  it("runs the decision inside a script that never throws", () => {
    expect(SKIP_LANDING_BOOTSTRAP).toContain(SKIP_LANDING_DECISION);
    expect(SKIP_LANDING_BOOTSTRAP.startsWith("(function(){try{")).toBe(true);
  });
});

describe("the mark", () => {
  it("is set and cleared", () => {
    markSignedIn();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBe("1");
    markSignedOut();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
  });

  it("stays silent when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(markSignedIn).not.toThrow();
    expect(markSignedOut).not.toThrow();
  });
});

describe("signing out", () => {
  afterEach(() => sessionStorage.clear());

  it("forgets the tab's admin flag with the mark, so the next account never inherits it", () => {
    markSignedIn();
    sessionStorage.setItem(ADMIN_KEY, "1");
    markSignedOut();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
    expect(sessionStorage.getItem(ADMIN_KEY)).toBeNull();
  });
});
