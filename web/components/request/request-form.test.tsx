import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, MonthlyLimitError, RequestValidationError } from "@/lib/api";
import { emptyRequestForm, exampleRequestForm } from "@/lib/request-form";

import { RequestForm } from "./request-form";

const TODAY = "2026-10-12";
const PLAN_ID = "6f1c2a7e-3b4d-4e5f-8a9b-0c1d2e3f4a5b";

const mocks = vi.hoisted(() => ({ createPlan: vi.fn(), push: vi.fn(), me: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));

vi.mock("@/lib/me", () => ({ useMe: () => mocks.me(), useRememberedAdmin: () => null }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { createPlan: mocks.createPlan } };
});

beforeEach(() => {
  mocks.createPlan.mockReset();
  mocks.push.mockReset();
  mocks.me.mockReset();
  mocks.me.mockReturnValue(null);
});

afterEach(cleanup);

function submitButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /Pianifica il viaggio|Avvio il piano/ });
}

async function submit() {
  await act(async () => {
    fireEvent.click(submitButton());
  });
}

describe("RequestForm", () => {
  it("labels every control and shows the cost estimate under the button", () => {
    render(<RequestForm today={TODAY} initialValues={emptyRequestForm()} />);

    for (const name of ["Da dove parti", "Dove vuoi andare", "Partenza", "Ritorno", "Budget totale", "Preferenze (facoltativo)"]) {
      expect(screen.getByLabelText(name)).toBeTruthy();
    }
    expect(screen.getByRole("radio", { name: "Suggeriscimi tu" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Mese e notti" })).toBeTruthy();
    expect(screen.getByRole("spinbutton", { name: "Adulti" })).toBeTruthy();
    expect(submitButton().getAttribute("aria-describedby")).toBe("submit-plan-estimate");
    expect(document.getElementById("submit-plan-estimate")?.textContent).toBe("Il planner costa circa 2–4 $ per piano");
    expect((screen.getByLabelText("Partenza") as HTMLInputElement).min).toBe("2026-10-13");
    expect(screen.queryByLabelText(/Scenario demo/)).toBeNull();
  });

  it("does not send an invalid request: errors on the fields, and a summary with the focus from three up", async () => {
    render(<RequestForm today={TODAY} initialValues={emptyRequestForm()} />);

    await submit();

    expect(mocks.createPlan).not.toHaveBeenCalled();
    const origin = screen.getByLabelText("Da dove parti");
    expect(origin.getAttribute("aria-invalid")).toBe("true");
    const described = (origin.getAttribute("aria-describedby") ?? "").split(" ");
    expect(described.map((id) => document.getElementById(id)?.textContent)).toContain(
      "Indica da dove parti: una città o un aeroporto.",
    );
    expect(screen.getByLabelText("Partenza").getAttribute("aria-invalid")).toBe("true");
    // Five problems: the summary takes the focus, counts them, and links to the fields by name only.
    const summary = screen.getByText("5 campi da sistemare").closest("[data-tone]") as HTMLElement;
    expect(document.activeElement).toBe(summary);
    expect(within(summary).getByRole("link", { name: "Budget totale" }).getAttribute("href")).toBe("#field-budget_eur");
    expect(summary.textContent).not.toContain("Indica da dove parti");
    // On the phone it sits above the first section, not beside the button.
    const form = screen.getByRole("form", { name: "Richiesta di viaggio" });
    expect(form.firstElementChild?.firstElementChild).toBe(summary);
    // A link goes to its field.
    fireEvent.click(within(summary).getByRole("link", { name: "Da dove parti" }));
    expect(document.activeElement).toBe(origin);
  });

  it("keeps the focus on the field, and shows no summary, with one or two problems", async () => {
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} />);
    fireEvent.change(screen.getByLabelText("Da dove parti"), { target: { value: "" } });
    await submit();
    expect(document.activeElement).toBe(screen.getByLabelText("Da dove parti"));
    expect(screen.queryByText(/da sistemare/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Budget totale"), { target: { value: "" } });
    await submit();
    expect(document.activeElement).toBe(screen.getByLabelText("Da dove parti"));
    expect(screen.queryByText(/da sistemare/)).toBeNull();
    expect(screen.getByLabelText("Budget totale").getAttribute("aria-invalid")).toBe("true");
  });

  it("clears a field's error as soon as it is edited", async () => {
    render(<RequestForm today={TODAY} initialValues={emptyRequestForm()} />);
    await submit();

    fireEvent.change(screen.getByLabelText("Da dove parti"), { target: { value: "Milano" } });

    expect(screen.getByLabelText("Da dove parti").getAttribute("aria-invalid")).toBeNull();
    expect(screen.getByText("4 campi da sistemare")).toBeTruthy();
  });

  it("moves to the next field on Enter and sends the request only from the last single-line field", async () => {
    mocks.createPlan.mockResolvedValue({ id: PLAN_ID });
    render(<RequestForm today={TODAY} initialValues={emptyRequestForm()} />);
    const origin = screen.getByLabelText("Da dove parti");
    origin.focus();
    fireEvent.change(origin, { target: { value: "Milano" } });
    // "Avanti" on the phone: no submit, no errors, the destination gets the focus.
    await act(async () => {
      fireEvent.keyDown(origin, { key: "Enter" });
    });
    expect(document.activeElement).toBe(screen.getByLabelText("Dove vuoi andare"));
    expect(screen.queryByText(/da sistemare/)).toBeNull();
    expect(origin.getAttribute("aria-invalid")).toBeNull();

    // From the destination to the date (the radios are skipped), and so on down the form.
    await act(async () => {
      fireEvent.keyDown(screen.getByLabelText("Dove vuoi andare"), { key: "Enter" });
    });
    expect(document.activeElement).toBe(screen.getByLabelText("Partenza"));
    await act(async () => {
      fireEvent.keyDown(screen.getByLabelText("Ritorno"), { key: "Enter" });
    });
    expect(document.activeElement).toBe(screen.getByRole("spinbutton", { name: "Adulti" }));
    await act(async () => {
      fireEvent.keyDown(screen.getByRole("spinbutton", { name: "Adulti" }), { key: "Enter" });
    });
    expect(document.activeElement).toBe(screen.getByRole("spinbutton", { name: "Bambini" }));
    await act(async () => {
      fireEvent.keyDown(screen.getByRole("spinbutton", { name: "Bambini" }), { key: "Enter" });
    });
    expect(document.activeElement).toBe(screen.getByLabelText("Budget totale"));
    expect(screen.getByLabelText("Budget totale").getAttribute("enterkeyhint")).toBe("go");

    // The budget is the last single-line field: Enter there sends the form (here, with errors).
    const sent = fireEvent.keyDown(screen.getByLabelText("Budget totale"), { key: "Enter" });
    expect(sent).toBe(true);
    // A text area keeps its new line.
    const preferences = screen.getByLabelText("Preferenze (facoltativo)");
    expect(fireEvent.keyDown(preferences, { key: "Enter" })).toBe(true);
  });

  it("sends a complete request with Enter from the budget", async () => {
    mocks.createPlan.mockResolvedValue({ id: PLAN_ID });
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} />);
    const form = screen.getByRole("form", { name: "Richiesta di viaggio" });
    const budget = screen.getByLabelText("Budget totale");
    budget.focus();
    // Enter is not intercepted here: the browser's implicit submission follows.
    expect(fireEvent.keyDown(budget, { key: "Enter" })).toBe(true);
    await act(async () => {
      fireEvent.submit(form);
    });
    expect(mocks.createPlan).toHaveBeenCalledTimes(1);
  });

  it("remembers the origin, the adults and the number of children for the next plan, never their ages or the budget", async () => {
    window.localStorage.clear();
    mocks.createPlan.mockResolvedValue({ id: PLAN_ID });
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} />);
    await submit();
    const stored = JSON.parse(window.localStorage.getItem("atlas:last-request") ?? "null");
    expect(stored).toEqual({ origin: "Milano", adults: 2, childAges: ["8", "11"] });
    cleanup();

    render(<RequestForm today={TODAY} initialValues={emptyRequestForm()} restoreLast />);
    expect((screen.getByLabelText("Da dove parti") as HTMLInputElement).value).toBe("Milano");
    expect((screen.getByRole("spinbutton", { name: "Adulti" }) as HTMLInputElement).value).toBe("2");
    // Ages go stale and the party sets the price: the count comes back, each age is a new choice.
    expect((screen.getByLabelText("Età del bambino 1") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Età del bambino 2") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Budget totale") as HTMLInputElement).value).toBe("");
    cleanup();

    // The home page's example is a request of its own.
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} />);
    expect((screen.getByLabelText("Da dove parti") as HTMLInputElement).value).toBe("Milano");
    window.localStorage.clear();
  });

  it("works without storage", async () => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new Error("blocked");
      },
      configurable: true,
    });
    try {
      mocks.createPlan.mockResolvedValue({ id: PLAN_ID });
      render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} restoreLast />);
      await submit();
      expect(mocks.push).toHaveBeenCalledWith(`/plans/${PLAN_ID}`);
    } finally {
      if (original) Object.defineProperty(window, "localStorage", original);
    }
  });

  it("starts the plan and opens it", async () => {
    mocks.createPlan.mockResolvedValue({ id: PLAN_ID });
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} />);

    await submit();

    expect(mocks.createPlan).toHaveBeenCalledWith(
      {
        origin: "Milano",
        destination: "Lisbona",
        suggest_destination: false,
        dates: { exact_start: "2027-04-14", exact_end: "2027-04-18", month: null, nights: null },
        travelers: [
          { kind: "adult", age: null },
          { kind: "adult", age: null },
          { kind: "child", age: 8 },
          { kind: "child", age: 11 },
        ],
        budget_eur: 2400,
        preferences: "Quartieri tranquilli, cucina locale.",
        destination_idea: null,
      },
      { demoScenario: null },
    );
    expect(mocks.push).toHaveBeenCalledWith(`/plans/${PLAN_ID}`);
    expect(submitButton().textContent).toContain("Avvio il piano…");
    expect(submitButton().disabled).toBe(true);
  });

  it("sends the month and the nights, and the idea instead of a destination", async () => {
    mocks.createPlan.mockResolvedValue({ id: PLAN_ID });
    render(<RequestForm today={TODAY} initialValues={{ ...emptyRequestForm(), origin: "MXP", budgetEur: "900" }} />);

    fireEvent.click(screen.getByRole("radio", { name: "Suggeriscimi tu" }));
    fireEvent.change(screen.getByLabelText("Che viaggio vorresti (facoltativo)"), {
      target: { value: "Mare a novembre, volo diretto" },
    });
    fireEvent.click(screen.getByRole("radio", { name: "Mese e notti" }));
    fireEvent.change(screen.getByLabelText("Mese di partenza"), { target: { value: "2026-11" } });
    fireEvent.click(screen.getByRole("button", { name: "Una notte in meno" }));
    await submit();

    const [request] = mocks.createPlan.mock.calls[0] ?? [];
    expect(request).toMatchObject({
      suggest_destination: true,
      destination_idea: "Mare a novembre, volo diretto",
      dates: { month: "2026-11", nights: 6 },
      budget_eur: 900,
    });
    expect((request as { destination?: string | null }).destination ?? null).toBeNull();
  });

  it("asks each child's age and keeps the count within nine travellers", async () => {
    render(<RequestForm today={TODAY} initialValues={emptyRequestForm()} />);

    fireEvent.click(screen.getByRole("button", { name: "Aggiungi un bambino" }));
    fireEvent.click(screen.getByRole("button", { name: "Aggiungi un bambino" }));
    expect(screen.getByLabelText("Età del bambino 2")).toBeTruthy();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Adulti" }), { target: { value: "12" } });
    expect((screen.getByRole("spinbutton", { name: "Adulti" }) as HTMLInputElement).value).toBe("7");
    expect((screen.getByRole("button", { name: "Aggiungi un bambino" }) as HTMLButtonElement).disabled).toBe(true);

    await submit();
    expect(screen.getByLabelText("Età del bambino 1").getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById("field-travelers-7-age-error")?.textContent).toBe(
      "Indica l'età del bambino (da 0 a 17 anni).",
    );
  });

  it("puts the backend's 422 issues on the same fields", async () => {
    mocks.createPlan.mockRejectedValue(
      new RequestValidationError(422, [
        { type: "start_not_in_future", loc: ["body", "dates", "exact_start"], msg: "start must be after today" },
      ]),
    );
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} />);

    await submit();

    const start = screen.getByLabelText("Partenza");
    expect(start.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(start);
    expect(document.getElementById("field-dates-exact_start-error")?.textContent).toBe(
      "La partenza deve essere da domani in poi.",
    );
    expect(submitButton().disabled).toBe(false);
  });

  it.each([
    [
      new MonthlyLimitError({
        status: 429,
        code: "monthly_limit_reached",
        message: "Questo mese sono già stati spesi 98,40 $ su 100,00 $: il prossimo piano si potrà creare il mese prossimo.",
        data: { spent_cents: 9840, limit_cents: 10000 },
      }),
      "Limite di spesa del mese raggiunto",
      "98,40 $ su 100,00 $",
      "warning",
    ],
    [
      new ApiError({
        kind: "planner_unavailable",
        status: 503,
        code: "planner_unavailable",
        message: "Il planner non è pronto in questo momento: nessun costo è stato addebitato. Riprova più tardi.",
      }),
      "Il planner non è pronto",
      "nessun costo è stato addebitato",
      "error",
    ],
  ])("says clearly why the plan did not start (%#)", async (error, title, figure, tone) => {
    mocks.createPlan.mockRejectedValue(error);
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} />);

    await submit();

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(title);
    expect(alert.textContent).toContain(figure);
    // A refusal by rule is a warning, a failure an error; the button is described by the notice,
    // and the cost estimate makes room for it.
    expect(alert.getAttribute("data-tone")).toBe(tone);
    expect(submitButton().getAttribute("aria-describedby")).toBe("submit-plan-failure");
    expect(document.getElementById("submit-plan-estimate")).toBeNull();
    expect(mocks.push).not.toHaveBeenCalled();
    expect(submitButton().disabled).toBe(false);
    expect(document.activeElement).toBe(submitButton());
    expect((screen.getByLabelText("Da dove parti") as HTMLInputElement).value).toBe("Milano");
  });

  it("says the month is used up before the press, keeps the form editable and the estimate out of the way", () => {
    mocks.me.mockReturnValue({
      isAdmin: false,
      quota: { plans_used: 2, plans_limit: 2, cents_used: 200, cents_limit: 1500, resets_at: "2026-11-01T00:00:00+01:00" },
    });
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} />);

    const notice = document.getElementById("submit-plan-quota");
    expect(notice?.getAttribute("data-tone")).toBe("warning");
    expect(notice?.getAttribute("role")).toBeNull();
    expect(notice?.textContent).toContain("Hai usato i piani di questo mese");
    expect(notice?.textContent).toContain("Questo mese hai creato 2 piani su 2. Il prossimo si potrà creare dal 1° novembre.");
    expect(submitButton().getAttribute("aria-describedby")).toBe("submit-plan-quota");
    expect(submitButton().disabled).toBe(false);
    expect((screen.getByLabelText("Da dove parti") as HTMLInputElement).disabled).toBe(false);
    expect(document.getElementById("submit-plan-estimate")).toBeNull();
    expect(screen.queryByTestId("month-usage")).toBeNull();
  });

  it("offers the demo scenarios in development and sends the chosen one", async () => {
    mocks.createPlan.mockResolvedValue({ id: PLAN_ID });
    render(
      <RequestForm
        today={TODAY}
        initialValues={exampleRequestForm(TODAY)}
        demoScenarios={["happy_path", "budget_reached"]}
      />,
    );

    const select = screen.getByLabelText("Scenario demo (facoltativo)") as HTMLSelectElement;
    expect([...select.options].map((option) => option.textContent)).toEqual(["Nessuno", "happy_path", "budget_reached"]);
    fireEvent.change(select, { target: { value: "budget_reached" } });
    await submit();

    expect(mocks.createPlan).toHaveBeenCalledWith(expect.any(Object), { demoScenario: "budget_reached" });
  });

  it("shows a refused demo scenario on its select", async () => {
    mocks.createPlan.mockRejectedValue(
      new RequestValidationError(422, [
        {
          type: "literal_error",
          loc: ["query", "demo_scenario"],
          msg: "Input should be one of: happy_path",
          ctx: { expected: "happy_path" },
        },
      ]),
    );
    render(<RequestForm today={TODAY} initialValues={exampleRequestForm(TODAY)} demoScenarios={["gone"]} />);

    fireEvent.change(screen.getByLabelText("Scenario demo (facoltativo)"), { target: { value: "gone" } });
    await submit();

    const select = screen.getByLabelText("Scenario demo (facoltativo)");
    expect(select.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(select);
  });
});
