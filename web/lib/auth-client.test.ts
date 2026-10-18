import { afterEach, describe, expect, it, vi } from "vitest";

import { forgetOnSignOut } from "./auth-client";
import { ADMIN_KEY, SIGNED_IN_KEY } from "./returning";

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

function remember(): void {
  localStorage.setItem(SIGNED_IN_KEY, "1");
  sessionStorage.setItem(ADMIN_KEY, "1");
}

describe("signing out", () => {
  it("forgets the browser's marks after a sign-out, and only then", () => {
    remember();
    forgetOnSignOut({ request: { url: "http://localhost:3000/api/auth/get-session" } });
    expect(sessionStorage.getItem(ADMIN_KEY)).toBe("1");

    forgetOnSignOut({ request: { url: new URL("http://localhost:3000/api/auth/sign-out") } });
    expect(sessionStorage.getItem(ADMIN_KEY)).toBeNull();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
  });

  it("is wired into the auth client: authClient.signOut() forgets the admin flag", async () => {
    remember();
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ success: true }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    // Better Auth's client keeps the fetch it finds when it is built: build it after the stub.
    vi.resetModules();
    const { authClient } = await import("./auth-client");

    await authClient.signOut();

    expect(fetchMock).toHaveBeenCalled();
    expect(String(fetchMock.mock.calls[0]![0])).toMatch(/\/sign-out$/);
    expect(sessionStorage.getItem(ADMIN_KEY)).toBeNull();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
  });
});
