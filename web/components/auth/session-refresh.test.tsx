import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getSession = vi.fn();

vi.mock("@/lib/auth-client", () => ({ authClient: { getSession: (...args: unknown[]) => getSession(...args) } }));

/** A fresh module each time: the component asks once per page load. */
async function load() {
  vi.resetModules();
  return (await import("./session-refresh")).SessionRefresh;
}

describe("SessionRefresh", () => {
  beforeEach(() => {
    getSession.mockReset();
    getSession.mockResolvedValue({ data: null, error: null });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
  });

  it("asks for the session once per page load, from the browser and without disableRefresh, so Better Auth can extend it", async () => {
    vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "atlas");
    const SessionRefresh = await load();

    const { unmount } = render(<SessionRefresh />);
    render(<SessionRefresh />); // the plan page draws a second bar
    unmount();
    render(<SessionRefresh />); // the skeleton's bar gave way to the screen's

    expect(getSession).toHaveBeenCalledTimes(1);
    expect(getSession).toHaveBeenCalledWith(); // no query: a refresh is allowed
  });

  it("renders nothing, and a failure changes nothing", async () => {
    vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "atlas");
    getSession.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const SessionRefresh = await load();

    const { container } = render(<SessionRefresh />);

    expect(container.innerHTML).toBe("");
    await vi.waitFor(() => expect(getSession).toHaveBeenCalledTimes(1));
  });

  it("does nothing when TripTracker signs the user in: this app has no session then", async () => {
    vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "triptracker");
    const SessionRefresh = await load();

    render(<SessionRefresh />);

    expect(getSession).not.toHaveBeenCalled();
  });
});
