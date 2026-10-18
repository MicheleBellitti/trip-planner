import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, QuotaReachedError } from "@/lib/api";

import { BudgetPausedPanel } from "./budget-paused";

afterEach(cleanup);

describe("BudgetPausedPanel and the economics", () => {
  it("offers 'Continua' below the cap, and at the cap a new plan instead, saying why", () => {
    const { unmount } = render(<BudgetPausedPanel costCents={61} budgetCents={100} continues={1} continuesLimit={2} onContinue={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Budget della sessione raggiunto" })).toBeTruthy();
    expect(screen.getByText(/ha speso 0,61 \$: il passo successivo non stava nel budget di 1,00 \$/)).toBeTruthy();
    const resume = screen.getByRole("button", { name: /Continua con 2 \$/ });
    expect(resume.className).toContain("min-h-11");
    expect(screen.getByText(/Aggiungi 2 \$ al budget/).textContent).toContain("«Interrompi» qui sopra");
    expect(screen.getByText(/con 2 \$ in più gli agenti riprendono da lì/)).toBeTruthy();
    unmount();

    render(<BudgetPausedPanel costCents={460} budgetCents={460} continues={2} continuesLimit={2} onContinue={vi.fn()} />);
    expect(screen.getByText(/ha speso 4,60 \$: il budget di 4,60 \$ è finito/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Continua/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Crea un nuovo piano" }).getAttribute("href")).toBe("/new");
    expect(screen.getByText(/ha già avuto 2 volte i suoi 2 \$ in più/).textContent).toContain(
      "Puoi interromperlo con «Interrompi» qui sopra, o creare un nuovo piano.",
    );
    expect(screen.queryByText(/riprendono da lì/)).toBeNull();
  });

  it("says it in the singular with one 'Continua' allowed; a backend without the cap (limit 0) still offers the button", () => {
    const { unmount } = render(<BudgetPausedPanel costCents={60} budgetCents={60} continues={1} continuesLimit={1} onContinue={vi.fn()} />);
    expect(screen.getByText(/ha già avuto i suoi 2 \$ in più:/)).toBeTruthy();
    unmount();

    render(<BudgetPausedPanel costCents={60} budgetCents={60} onContinue={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Continua/ })).toBeTruthy();
  });

  it("a quota refusal and the cap's 409 are final and not red: the button stays off", async () => {
    const quota = { plans_used: 3, plans_limit: 10, cents_used: 1480, cents_limit: 1500, resets_at: "2026-11-01T00:00:00+01:00" };
    const refuse = vi.fn(async () => {
      throw new QuotaReachedError({ status: 429, code: "quota_cents_reached", message: "x", data: quota });
    });
    const { unmount } = render(<BudgetPausedPanel costCents={60} budgetCents={60} onContinue={refuse} />);
    fireEvent.click(screen.getByRole("button", { name: /Continua/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.getAttribute("data-tone")).toBe("warning");
    expect(alert.textContent).toContain("Hai usato il budget di questo mese");
    expect(alert.textContent).toContain("Il piano resta in pausa e puoi interromperlo.");
    await waitFor(() => expect((screen.getByRole("button", { name: /Continua/ }) as HTMLButtonElement).disabled).toBe(true));
    unmount();

    const message =
      "Questo piano ha già avuto tutti gli aumenti di budget previsti (2 su 2): il budget non si può aumentare ancora. Puoi interromperlo, o creare un nuovo piano.";
    const capped = vi.fn(async () => {
      throw new ApiError({ kind: "continue_limit", status: 409, code: "continue_limit_reached", message });
    });
    render(<BudgetPausedPanel costCents={60} budgetCents={60} onContinue={capped} />);
    fireEvent.click(screen.getByRole("button", { name: /Continua/ }));
    const cap = await screen.findByRole("alert");
    expect(cap.getAttribute("data-tone")).toBe("warning");
    expect(cap.textContent).toContain("Il budget non si può aumentare ancora");
    expect(cap.textContent).toContain(message);
  });

  it("anything else is an error, in red, and the button can be tried again", async () => {
    const fail = vi.fn(async () => {
      throw new ApiError({ kind: "server", status: 500 });
    });
    render(<BudgetPausedPanel costCents={60} budgetCents={60} onContinue={fail} />);
    fireEvent.click(screen.getByRole("button", { name: /Continua/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.getAttribute("data-tone")).toBe("error");
    expect(alert.textContent).toContain("Il piano non è ripartito");
    await waitFor(() => expect((screen.getByRole("button", { name: /Continua/ }) as HTMLButtonElement).disabled).toBe(false));
  });
});
