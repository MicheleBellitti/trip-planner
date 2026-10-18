import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, QuotaReachedError } from "@/lib/api";

import { BudgetPausedPanel } from "./budget-paused";

afterEach(cleanup);

describe("BudgetPausedPanel and the economics", () => {
  it("offers 'Continua' below the cap and nothing at it, saying why", () => {
    const { unmount } = render(<BudgetPausedPanel costCents={60} budgetCents={60} continues={1} continuesLimit={2} onContinue={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Continua con 2 \$/ })).toBeTruthy();
    expect(screen.getByText(/Aggiungi 2 \$ al budget/)).toBeTruthy();
    unmount();

    render(<BudgetPausedPanel costCents={460} budgetCents={460} continues={2} continuesLimit={2} onContinue={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Continua/ })).toBeNull();
    expect(screen.getByText(/ha già usato le sue 2 proroghe/).textContent).toContain("Puoi interromperlo, o creare un nuovo piano.");
  });

  it("a backend without the cap (limit 0) still offers the button", () => {
    render(<BudgetPausedPanel costCents={60} budgetCents={60} onContinue={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Continua/ })).toBeTruthy();
  });

  it("a quota refusal and the cap's 409 are final: the button stays off", async () => {
    const quota = { plans_used: 3, plans_limit: 10, cents_used: 1480, cents_limit: 1500, resets_at: "2026-11-01T00:00:00+01:00" };
    const refuse = vi.fn(async () => {
      throw new QuotaReachedError({ status: 429, code: "quota_cents_reached", message: "x", data: quota });
    });
    const { unmount } = render(<BudgetPausedPanel costCents={60} budgetCents={60} onContinue={refuse} />);
    fireEvent.click(screen.getByRole("button", { name: /Continua/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Hai usato il budget di questo mese");
    expect(alert.textContent).toContain("Il piano resta in pausa e puoi interromperlo.");
    await waitFor(() => expect((screen.getByRole("button", { name: /Continua/ }) as HTMLButtonElement).disabled).toBe(true));
    unmount();

    const capped = vi.fn(async () => {
      throw new ApiError({ kind: "continue_limit", status: 409, code: "continue_limit_reached", message: "Questo piano ha già usato le sue 2 proroghe: il budget non si può aumentare ancora. Puoi interromperlo, o creare un nuovo piano." });
    });
    render(<BudgetPausedPanel costCents={60} budgetCents={60} onContinue={capped} />);
    fireEvent.click(screen.getByRole("button", { name: /Continua/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("Proroghe esaurite");
  });
});
