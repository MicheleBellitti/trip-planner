import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "@/lib/me";

import { MonthUsage, monthUsageWords } from "./month-usage";

const useMe = vi.fn<() => Identity | null>();
const useRememberedAdmin = vi.fn<() => boolean | null>(() => null);
vi.mock("@/lib/me", () => ({ useMe: () => useMe(), useRememberedAdmin: () => useRememberedAdmin() }));

afterEach(() => {
  cleanup();
  useRememberedAdmin.mockReturnValue(null);
});

const QUOTA = { plans_used: 3, plans_limit: 10, cents_used: 420, cents_limit: 1500, resets_at: "2026-11-01T00:00:00+01:00" };

describe("monthUsageWords", () => {
  it("counts the plans and the dollars committed, and says when the next plan can start", () => {
    expect(monthUsageWords(QUOTA)).toEqual({ summary: "Questo mese: 3 piani su 10 · 4,20 $ impegnati su 15,00 $", note: null });
    expect(monthUsageWords({ ...QUOTA, plans_used: 1 }).summary).toBe("Questo mese: 1 piano su 10 · 4,20 $ impegnati su 15,00 $");
    expect(monthUsageWords({ ...QUOTA, plans_used: 10 }).note).toBe("Il prossimo piano dal 1° novembre.");
    expect(monthUsageWords({ ...QUOTA, cents_used: 1500 }).note).not.toBeNull();
    // The backend's rule: the next plan's own budget must fit, not just a cent left.
    expect(monthUsageWords({ ...QUOTA, cents_used: 1200, next_plan_cents: 400 }).note).toBe("Il prossimo piano dal 1° novembre.");
    expect(monthUsageWords({ ...QUOTA, cents_used: 1100, next_plan_cents: 400 }).note).toBeNull();
  });
});

describe("MonthUsage", () => {
  it("reserves its line while the answer is on its way, unless the tab remembers an admin", () => {
    useMe.mockReturnValue(null);
    const { unmount } = render(<MonthUsage className="mt-2" />);
    const pending = screen.getByTestId("month-usage-pending");
    expect(pending.getAttribute("aria-hidden")).toBe("true");
    expect(pending.className).toContain("mt-2");
    expect(pending.className).toContain("text-small");
    expect(screen.queryByTestId("month-usage")).toBeNull();
    unmount();

    useRememberedAdmin.mockReturnValue(true);
    render(<MonthUsage />);
    expect(screen.queryByTestId("month-usage-pending")).toBeNull();
  });

  it("draws nothing for an exempt user, and the line for a plain one, the note on its own line", () => {
    useMe.mockReturnValue({ isAdmin: true, quota: null });
    const exempt = render(<MonthUsage />);
    expect(screen.queryByTestId("month-usage")).toBeNull();
    expect(screen.queryByTestId("month-usage-pending")).toBeNull();
    exempt.unmount();

    useMe.mockReturnValue({ isAdmin: false, quota: QUOTA });
    const plain = render(<MonthUsage className="mt-2" />);
    const line = screen.getByTestId("month-usage");
    expect(line.textContent).toBe("Questo mese: 3 piani su 10 · 4,20 $ impegnati su 15,00 $");
    expect(line.className).toContain("mt-2");
    expect(line.className).toContain("text-small");
    expect(line.querySelectorAll("p")).toHaveLength(1);
    plain.unmount();

    useMe.mockReturnValue({ isAdmin: false, quota: { ...QUOTA, plans_used: 10 } });
    render(<MonthUsage size="meta" />);
    const used = screen.getByTestId("month-usage");
    expect(used.className).toContain("text-meta");
    const lines = used.querySelectorAll("p");
    expect(lines).toHaveLength(2);
    expect(lines[0]?.textContent).toBe("Questo mese: 10 piani su 10 · 4,20 $ impegnati su 15,00 $");
    expect(lines[1]?.textContent).toBe("Il prossimo piano dal 1° novembre.");
    expect(lines[1]?.className).toContain("text-ink");
  });

  it("keeps the note for the form, which says it in its own notice", () => {
    useMe.mockReturnValue({ isAdmin: false, quota: { ...QUOTA, plans_used: 10 } });
    render(<MonthUsage withNote={false} />);
    expect(screen.getByTestId("month-usage").querySelectorAll("p")).toHaveLength(1);
  });
});
