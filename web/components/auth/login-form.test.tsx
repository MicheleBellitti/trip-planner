import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  GENERIC_SIGN_IN_ERROR,
  INVALID_EMAIL_ERROR,
  INVITE_ONLY_ERROR,
  INVITE_ONLY_HELP,
  LINK_VALIDITY,
  LoginForm,
  SIGN_IN_ERRORS,
  TOO_MANY_REQUESTS_ERROR,
  UNCONFIGURED_MESSAGE,
  signInError,
} from "./login-form";

const magicLink = vi.fn();
const social = vi.fn();

vi.mock("@/lib/auth-client", () => ({
  authClient: { signIn: { magicLink: (...args: unknown[]) => magicLink(...args), social: (...args: unknown[]) => social(...args) } },
}));

const LABEL = "Indirizzo email";

function renderForm(props: Partial<Parameters<typeof LoginForm>[0]> = {}) {
  return render(<LoginForm returnTo={null} errorCode={null} configured googleEnabled {...props} />);
}

function typeAndSubmit(address: string) {
  fireEvent.change(screen.getByLabelText(LABEL), { target: { value: address } });
  fireEvent.submit(screen.getByLabelText(LABEL).closest("form")!);
}

const sent = { data: { status: true }, error: null };

describe("LoginForm", () => {
  beforeEach(() => {
    magicLink.mockReset();
    social.mockReset();
  });

  afterEach(cleanup);

  it("says what the link is, how long it lasts, which address to use, and offers Google only when configured", () => {
    renderForm();
    expect(screen.getByText(/Ti mandiamo un link per entrare, senza password\./).textContent).toContain(LINK_VALIDITY);
    expect(screen.queryByText(/Poi torni dove eri/)).toBeNull();
    expect(screen.getByLabelText(LABEL)).toHaveProperty("type", "email");
    expect(screen.getByText("Quello a cui è arrivato l'invito.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Inviami il link" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continua con Google" })).toBeTruthy();
    expect(screen.queryByText(/su invito/)).toBeNull(); // the invite rule appears only when an address is refused
  });

  it("promises the way back when it knows where the user was", () => {
    renderForm({ returnTo: "/plans/abc" });
    expect(screen.getByText(/Poi torni dove eri\./)).toBeTruthy();
  });

  it("hides Google when the server has no client", () => {
    renderForm({ googleEnabled: false });
    expect(screen.queryByRole("button", { name: "Continua con Google" })).toBeNull();
  });

  it("sends the magic link back to the interrupted page, reduced to a same-origin path, and lands focus on the news", async () => {
    magicLink.mockResolvedValue(sent);
    renderForm({ returnTo: `${window.location.origin}/plans/abc?tab=piano` });

    typeAndSubmit(" Someone@Example.com ");

    const heading = await screen.findByRole("heading", { name: "Controlla la posta" });
    expect(magicLink).toHaveBeenCalledWith({
      email: "Someone@Example.com",
      callbackURL: "/plans/abc?tab=piano",
      errorCallbackURL: "/login",
    });
    expect(screen.getByText("Someone@Example.com")).toBeTruthy();
    expect(screen.getByText(/Abbiamo mandato un link a/).textContent).toContain(LINK_VALIDITY);
    expect(screen.getByText(/Guarda nella posta indesiderata/)).toBeTruthy();
    await waitFor(() => expect(document.activeElement?.contains(heading)).toBe(true));
  });

  it("a foreign returnTo goes back to the plans list", async () => {
    magicLink.mockResolvedValue(sent);
    renderForm({ returnTo: "https://evil.example/anywhere" });

    typeAndSubmit("a@example.com");

    await waitFor(() => expect(magicLink).toHaveBeenCalled());
    expect(magicLink.mock.calls[0]?.[0]).toMatchObject({ callbackURL: "/" });
  });

  it("'Mandane un altro' resends to the same address and says so; 'Cambia indirizzo' keeps it in the field", async () => {
    magicLink.mockResolvedValue(sent);
    renderForm();
    typeAndSubmit("a@example.com");
    await screen.findByRole("heading", { name: "Controlla la posta" });

    fireEvent.click(screen.getByRole("button", { name: "Mandane un altro" }));
    await waitFor(() => expect(magicLink).toHaveBeenCalledTimes(2));
    expect(magicLink.mock.calls[1]?.[0]).toMatchObject({ email: "a@example.com" });
    await screen.findByText(/Abbiamo mandato un altro link a/);

    fireEvent.click(screen.getByRole("button", { name: "Cambia indirizzo" }));
    expect(screen.getByLabelText(LABEL)).toHaveProperty("value", "a@example.com");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText(LABEL)));
  });

  it("a rate limit on the resend is an alert inside the sent panel", async () => {
    magicLink.mockResolvedValueOnce(sent).mockResolvedValueOnce({ data: null, error: { status: 429, message: "x" } });
    renderForm();
    typeAndSubmit("a@example.com");
    await screen.findByRole("heading", { name: "Controlla la posta" });

    fireEvent.click(screen.getByRole("button", { name: "Mandane un altro" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(TOO_MANY_REQUESTS_ERROR));
    expect(screen.getByRole("heading", { name: "Controlla la posta" })).toBeTruthy();
  });

  it("a refused address is an error on the field, with the invite rule and what to do, and focus goes back to it", async () => {
    magicLink.mockResolvedValue({ data: null, error: { status: 403, code: "SIGNUP_NOT_ALLOWED", message: "x" } });
    renderForm();

    typeAndSubmit("nobody@example.com");

    const input = screen.getByLabelText(LABEL);
    await waitFor(() => expect(input.getAttribute("aria-invalid")).toBe("true"));
    expect(screen.getByText(new RegExp(INVITE_ONLY_ERROR)).textContent).toContain(INVITE_ONLY_HELP);
    expect(screen.queryByRole("alert")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(input));

    fireEvent.change(input, { target: { value: "nobody2@example.com" } });
    expect(input.getAttribute("aria-invalid")).toBeNull();
  });

  it("an address without a shape never leaves the browser", () => {
    renderForm();

    typeAndSubmit("not-an-address");

    expect(magicLink).not.toHaveBeenCalled();
    expect(screen.getByText(INVALID_EMAIL_ERROR)).toBeTruthy();
    expect(screen.getByLabelText(LABEL).getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText(LABEL));
  });

  it("a rate limit and anything else are alerts with their own words", async () => {
    magicLink.mockResolvedValueOnce({ data: null, error: { status: 429, message: "x" } });
    renderForm();
    typeAndSubmit("a@example.com");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(TOO_MANY_REQUESTS_ERROR));

    magicLink.mockResolvedValueOnce({ data: null, error: { status: 500, message: "x" } });
    fireEvent.submit(screen.getByLabelText(LABEL).closest("form")!);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(GENERIC_SIGN_IN_ERROR));
  });

  it("shows Better Auth's callback error codes in Italian, with what to do", () => {
    renderForm({ errorCode: "INVALID_TOKEN" });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(SIGN_IN_ERRORS.INVALID_TOKEN!.title);
    expect(alert.textContent).toContain(LINK_VALIDITY);
    expect(signInError("something_else")).toEqual({ title: GENERIC_SIGN_IN_ERROR });
    expect(signInError(null)).toBeNull();
  });

  it("Google goes through the social sign-in with the same return path", async () => {
    social.mockResolvedValue({ data: { url: "https://accounts.google.com/x", redirect: true }, error: null });
    renderForm({ returnTo: "/evals" });

    fireEvent.click(screen.getByRole("button", { name: "Continua con Google" }));

    await waitFor(() => expect(social).toHaveBeenCalledWith({ provider: "google", callbackURL: "/evals", errorCallbackURL: "/login" }));
    expect(screen.getByRole("button", { name: "Apro Google…" })).toHaveProperty("disabled", true);
  });

  it("without accounts on the server the form is disabled and says why", () => {
    renderForm({ configured: false });
    expect(screen.getByText(UNCONFIGURED_MESSAGE)).toBeTruthy();
    expect(screen.queryByText(/env\.example/)).toBeNull();
    expect(screen.getByLabelText(LABEL)).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Inviami il link" })).toHaveProperty("disabled", true);
  });
});
