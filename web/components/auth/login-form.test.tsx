import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  GENERIC_SIGN_IN_ERROR,
  INVITE_ONLY_ERROR,
  LoginForm,
  SIGN_IN_ERRORS,
  TOO_MANY_REQUESTS_ERROR,
  UNCONFIGURED_MESSAGE,
  signInErrorMessage,
} from "./login-form";

const magicLink = vi.fn();
const social = vi.fn();

vi.mock("@/lib/auth-client", () => ({
  authClient: { signIn: { magicLink: (...args: unknown[]) => magicLink(...args), social: (...args: unknown[]) => social(...args) } },
}));

function renderForm(props: Partial<Parameters<typeof LoginForm>[0]> = {}) {
  return render(<LoginForm returnTo={null} errorCode={null} configured googleEnabled {...props} />);
}

describe("LoginForm", () => {
  beforeEach(() => {
    magicLink.mockReset();
    social.mockReset();
  });

  afterEach(cleanup);

  it("asks for the email, says what happens, and offers Google only when configured", () => {
    renderForm();
    expect(screen.getByLabelText("Email")).toHaveProperty("type", "email");
    expect(screen.getByText("Ti mandiamo un link per entrare, senza password.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Inviami il link" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continua con Google" })).toBeTruthy();
    expect(screen.getByText(/L'accesso è su invito/)).toBeTruthy();
  });

  it("hides Google when the server has no client", () => {
    renderForm({ googleEnabled: false });
    expect(screen.queryByRole("button", { name: "Continua con Google" })).toBeNull();
  });

  it("sends the magic link back to the interrupted page, reduced to a same-origin path", async () => {
    magicLink.mockResolvedValue({ data: { status: true }, error: null });
    renderForm({ returnTo: `${window.location.origin}/plans/abc?tab=piano` });

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: " Someone@Example.com " } });
    fireEvent.submit(screen.getByRole("button", { name: "Inviami il link" }).closest("form")!);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Controlla la posta" })).toBeTruthy());
    expect(magicLink).toHaveBeenCalledWith({
      email: "Someone@Example.com",
      callbackURL: "/plans/abc?tab=piano",
      errorCallbackURL: "/login",
    });
    expect(screen.getByText("Someone@Example.com")).toBeTruthy();
    expect(screen.getByText(/Vale cinque minuti e funziona una volta sola/)).toBeTruthy();
  });

  it("a foreign returnTo goes back to the plans list", async () => {
    magicLink.mockResolvedValue({ data: { status: true }, error: null });
    renderForm({ returnTo: "https://evil.example/anywhere" });

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);

    await waitFor(() => expect(magicLink).toHaveBeenCalled());
    expect(magicLink.mock.calls[0]?.[0]).toMatchObject({ callbackURL: "/" });
  });

  it("'Usa un altro indirizzo' returns to the form", async () => {
    magicLink.mockResolvedValue({ data: { status: true }, error: null });
    renderForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Controlla la posta" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Usa un altro indirizzo" }));

    expect(screen.getByLabelText("Email")).toBeTruthy();
  });

  it("a refused address says the beta is by invitation, as an alert", async () => {
    magicLink.mockResolvedValue({ data: null, error: { status: 403, code: "SIGNUP_NOT_ALLOWED", message: "x" } });
    renderForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toContain(INVITE_ONLY_ERROR);
  });

  it("maps a rate limit and anything else to their own words", async () => {
    magicLink.mockResolvedValueOnce({ data: null, error: { status: 429, message: "x" } });
    renderForm();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(TOO_MANY_REQUESTS_ERROR));

    magicLink.mockResolvedValueOnce({ data: null, error: { status: 500, message: "x" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(GENERIC_SIGN_IN_ERROR));
  });

  it("shows Better Auth's callback error codes in Italian", () => {
    renderForm({ errorCode: "INVALID_TOKEN" });
    expect(screen.getByRole("alert").textContent).toContain(SIGN_IN_ERRORS.INVALID_TOKEN);
    expect(signInErrorMessage("something_else")).toBe(GENERIC_SIGN_IN_ERROR);
    expect(signInErrorMessage(null)).toBeNull();
  });

  it("Google goes through the social sign-in with the same return path", async () => {
    social.mockResolvedValue({ data: { url: "https://accounts.google.com/x", redirect: true }, error: null });
    renderForm({ returnTo: "/evals" });

    fireEvent.click(screen.getByRole("button", { name: "Continua con Google" }));

    await waitFor(() => expect(social).toHaveBeenCalledWith({ provider: "google", callbackURL: "/evals", errorCallbackURL: "/login" }));
    expect(screen.getByRole("button", { name: "Vado su Google…" })).toHaveProperty("disabled", true);
  });

  it("without accounts on the server the form is disabled and says why", () => {
    renderForm({ configured: false });
    expect(screen.getByText(UNCONFIGURED_MESSAGE)).toBeTruthy();
    expect(screen.getByLabelText("Email")).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Inviami il link" })).toHaveProperty("disabled", true);
  });
});
