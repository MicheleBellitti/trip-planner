import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchMe, resetMeCache, useMe } from "./me";

const me = vi.fn<() => Promise<unknown>>();

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, createApiClient: () => ({ me: () => me() }) };
});

beforeEach(() => {
  resetMeCache();
  me.mockReset();
  sessionStorage.clear();
});

afterEach(cleanup);

const USER = { email: "a@example.com", is_admin: false, quota: null };
const ADMIN = { ...USER, is_admin: true };

describe("fetchMe", () => {
  it("shares one request while it is in flight and asks again once it answered", async () => {
    let answer!: (value: unknown) => void;
    me.mockReturnValueOnce(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    const first = fetchMe();
    const second = fetchMe();
    expect(me).toHaveBeenCalledTimes(1);
    answer(USER);
    await expect(first).resolves.toEqual({ email: "a@example.com", isAdmin: false, quota: null });
    await second;

    me.mockResolvedValueOnce(ADMIN);
    await expect(fetchMe()).resolves.toEqual({ email: "a@example.com", isAdmin: true, quota: null });
    expect(me).toHaveBeenCalledTimes(2);
    expect(sessionStorage.getItem("atlas-admin")).toBe("1");
  });

  it("reads a failure as unknown and keeps the last answer", async () => {
    me.mockResolvedValueOnce(ADMIN);
    await fetchMe();
    me.mockRejectedValueOnce(new Error("down"));
    await expect(fetchMe()).resolves.toBeNull();
    expect(sessionStorage.getItem("atlas-admin")).toBe("1");
  });
});

describe("useMe", () => {
  function Probe() {
    const identity = useMe();
    return <output>{identity === null ? "pending" : identity.isAdmin ? "admin" : "user"}</output>;
  }

  it("draws the last answer at once and the fresh one when it lands", async () => {
    me.mockResolvedValueOnce(USER);
    const first = render(<Probe />);
    expect(screen.getByRole("status").textContent).toBe("pending");
    await screen.findByText("user");
    first.unmount();

    me.mockResolvedValueOnce(ADMIN);
    render(<Probe />);
    expect(screen.getByRole("status").textContent).toBe("user");
    await screen.findByText("admin");
    expect(me).toHaveBeenCalledTimes(2);
  });
});
