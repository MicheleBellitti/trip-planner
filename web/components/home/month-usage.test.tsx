import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "@/lib/me";

import { MonthUsage, monthUsageWords } from "./month-usage";

const useMe = vi.fn<() => Identity | null>();
vi.mock("@/lib/me", () => ({ useMe: () => useMe() }));

afterEach(cleanup);

const QUOTA = { plans_used: 3, plans_limit: 10, cents_used: 420, cents_limit: 1500, resets_at: "2026-11-01T00:00:00+01:00" };

describe("monthUsageWords", () => {
  it("counts the plans and the dollars, and says when a limit is reached", () => {
    expect(monthUsageWords(QUOTA)).toEqual({ summary: "Questo mese: 3 piani su 10 · 4,20 $ su 15,00 $", note: null });
    expect(monthUsageWords({ ...QUOTA, plans_used: 1 }).summary).toBe("Questo mese: 1 piano su 10 · 4,20 $ su 15,00 $");
    expect(monthUsageWords({ ...QUOTA, plans_used: 10 }).note).toBe(
      "Hai usato quanto previsto per questo mese: il prossimo piano dal 1° novembre.",
    );
    expect(monthUsageWords({ ...QUOTA, cents_used: 1500 }).note).not.toBeNull();
  });
});

describe("MonthUsage", () => {
  it("draws nothing while unknown or for an exempt user, and the line for a plain one", () => {
    useMe.mockReturnValue(null);
    const { unmount, rerender } = render(<MonthUsage />);
    expect(screen.queryByTestId("month-usage")).toBeNull();
    useMe.mockReturnValue({ isAdmin: true, quota: null });
    rerender(<MonthUsage />);
    expect(screen.queryByTestId("month-usage")).toBeNull();
    unmount();

    useMe.mockReturnValue({ isAdmin: false, quota: QUOTA });
    render(<MonthUsage className="mt-2" />);
    const line = screen.getByTestId("month-usage");
    expect(line.textContent).toBe("Questo mese: 3 piani su 10 · 4,20 $ su 15,00 $");
    expect(line.className).toContain("mt-2");
  });
});
