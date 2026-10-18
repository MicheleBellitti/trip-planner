import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN_KEY, fetchIsAdmin, resetMeCache, useIsAdmin } from "./me";

const ME = { email: "michele@example.com", is_admin: true };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function envelope(code: string): { detail: { code: string; message: string; data: null } } {
  return { detail: { code, message: "Accedi per usare il planner.", data: null } };
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000");
  vi.stubEnv("NEXT_PUBLIC_TRIPTRACKER_URL", "http://localhost:3001");
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "atlas");
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  resetMeCache();
  sessionStorage.clear();
  localStorage.clear();
});

describe("fetchIsAdmin", () => {
  it("shares the request in flight and remembers the answer for the tab", async () => {
    fetchMock.mockResolvedValue(json(200, ME));

    expect(await Promise.all([fetchIsAdmin(), fetchIsAdmin()])).toEqual([true, true]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(ADMIN_KEY)).toBe("1");
  });

  it("neither shares nor stores a failure: the next caller asks again, and the tab's flag stands", async () => {
    sessionStorage.setItem(ADMIN_KEY, "1");
    fetchMock.mockResolvedValueOnce(json(503, envelope("auth_unavailable")));
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    fetchMock.mockResolvedValueOnce(json(200, { ...ME, is_admin: false }));

    expect(await fetchIsAdmin()).toBeNull(); // unknown, not "no admin"
    expect(sessionStorage.getItem(ADMIN_KEY)).toBe("1");
    expect(await fetchIsAdmin()).toBeNull();
    expect(sessionStorage.getItem(ADMIN_KEY)).toBe("1");
    expect(await fetchIsAdmin()).toBe(false);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(sessionStorage.getItem(ADMIN_KEY)).toBe("0");
  });

  it("takes a 401 as no admin, forgets the tab's flag, and asks again next time", async () => {
    sessionStorage.setItem(ADMIN_KEY, "1");
    fetchMock.mockResolvedValueOnce(json(401, envelope("not_authenticated")));
    fetchMock.mockResolvedValueOnce(json(200, ME));

    expect(await fetchIsAdmin()).toBe(false);
    expect(sessionStorage.getItem(ADMIN_KEY)).toBeNull();
    expect(await fetchIsAdmin()).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("useIsAdmin", () => {
  it("keeps what the tab remembered when this page's request fails", async () => {
    sessionStorage.setItem(ADMIN_KEY, "1");
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useIsAdmin());
    expect(result.current).toBe(true);
    await act(async () => {
      await fetchIsAdmin(); // the hook's own request has failed by now
    });

    expect(fetchMock).toHaveBeenCalled();
    expect(result.current).toBe(true);
  });

  it("drops the station's flag once the session turns out to be gone", async () => {
    sessionStorage.setItem(ADMIN_KEY, "1");
    fetchMock.mockResolvedValue(json(401, envelope("not_authenticated")));

    const { result } = renderHook(() => useIsAdmin());

    await waitFor(() => expect(result.current).toBe(false));
    expect(sessionStorage.getItem(ADMIN_KEY)).toBeNull();
  });
});
