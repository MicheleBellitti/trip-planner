import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "@/lib/me";
import { ROUTES } from "@/lib/routes";

import { AccountLine } from "./account-line";

const useMe = vi.fn<() => Identity | null>();
const signOut = vi.fn<() => Promise<unknown>>(() => Promise.resolve({}));
const authMode = vi.fn<() => string>(() => "atlas");

vi.mock("@/lib/me", () => ({ useMe: () => useMe() }));
vi.mock("@/lib/auth-client", () => ({ authClient: { signOut: () => signOut() } }));
vi.mock("@/lib/config", () => ({ getAuthMode: () => authMode() }));

afterEach(() => {
  cleanup();
  signOut.mockClear();
  authMode.mockReturnValue("atlas");
});

const ME: Identity = { email: "a@example.com", isAdmin: false, quota: null };

describe("AccountLine", () => {
  it("reserves its line until GET /me answers, then nothing for nobody", () => {
    useMe.mockReturnValue(null);
    const { unmount } = render(<AccountLine className="mt-1" />);
    expect(screen.getByTestId("account-line-pending").className).toContain("mt-1");
    unmount();
    useMe.mockReturnValue({ ...ME, email: null });
    render(<AccountLine />);
    expect(screen.queryByTestId("account-line")).toBeNull();
  });

  it("names the signed-in address and signs out to the login page", async () => {
    useMe.mockReturnValue(ME);
    const navigate = vi.fn<(url: string) => void>();
    render(<AccountLine navigate={navigate} />);
    expect(screen.getByTestId("account-line").textContent).toBe("Sei dentro come a@example.com · Esci");
    fireEvent.click(screen.getByRole("button", { name: "Esci" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(ROUTES.login));
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("with TripTracker's accounts only names the address: the sign-out is TripTracker's", () => {
    authMode.mockReturnValue("triptracker");
    useMe.mockReturnValue(ME);
    render(<AccountLine />);
    expect(screen.getByTestId("account-line").textContent).toBe("Sei dentro come a@example.com");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
