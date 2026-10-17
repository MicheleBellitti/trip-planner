import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WAITLIST_FAILED } from "@/components/waitlist/waitlist-form";

import {
  GENERIC_SIGN_IN_ERROR,
  SEND_FAILED_ERROR,
  INVALID_EMAIL_ERROR,
  INVITE_ONLY_ERROR,
  INVITE_ONLY_HELP,
  LINK_VALIDITY,
  LISTED_HINT,
  LoginForm,
  SIGN_IN_ERRORS,
  TOO_MANY_REQUESTS_ERROR,
  UNCONFIGURED_MESSAGE,
  signInError,
} from "./login-form";

const magicLink = vi.fn();
const social = vi.fn();
const getSession = vi.fn();
const join = vi.fn();

vi.mock("@/lib/auth-client", () => ({
  authClient: {
    signIn: { magicLink: (...args: unknown[]) => magicLink(...args), social: (...args: unknown[]) => social(...args) },
    getSession: (...args: unknown[]) => getSession(...args),
  },
}));

vi.mock("@/app/actions/waitlist", () => ({
  joinWaitlistAction: (...args: unknown[]) => join(...args),
}));

const REFUSED = { data: null, error: { status: 403, code: "SIGNUP_NOT_ALLOWED", message: "x" } };

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
    getSession.mockReset();
    getSession.mockResolvedValue({ data: null, error: null });
    join.mockReset();
  });

  afterEach(cleanup);

  it("says what the link is, how long it lasts, which address to use, and offers Google only when configured", () => {
    renderForm();
    expect(screen.getByText(/Ti inviamo un link per entrare, senza password\./).textContent).toContain(LINK_VALIDITY);
    expect(screen.queryByText(/tornare dove eri/)).toBeNull();
    expect(screen.getByLabelText(LABEL)).toHaveProperty("type", "email");
    expect(screen.getByText("Quello invitato, o con cui sei già entrato.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Inviami il link" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continua con Google" })).toBeTruthy();
    expect(screen.queryByText(/su invito/)).toBeNull(); // the invite rule appears only when an address is refused
  });

  it("says why the user is here and promises the way back when it knows where they were", () => {
    renderForm({ returnTo: "/plans/abc" });
    const lede = screen.getByText(/Accedi per tornare dove eri/);
    expect(lede.textContent).toContain(LINK_VALIDITY);
    expect(lede.textContent!.length).toBeLessThanOrEqual(100); // two lines at 393 px, like the placeholder
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
      // A spent link lands here still knowing the way back.
      errorCallbackURL: "/login?returnTo=%2Fplans%2Fabc%3Ftab%3Dpiano",
    });
    expect(screen.getByText("Someone@Example.com")).toBeTruthy();
    expect(screen.getByText(/Abbiamo inviato un link a/).textContent).toContain(LINK_VALIDITY);
    expect(screen.getByText(/Guarda nella posta indesiderata/)).toBeTruthy();
    await waitFor(() => expect(document.activeElement?.contains(heading)).toBe(true));
  });

  it("a foreign returnTo goes back to the plans list", async () => {
    magicLink.mockResolvedValue(sent);
    renderForm({ returnTo: "https://evil.example/anywhere" });

    typeAndSubmit("a@example.com");

    await waitFor(() => expect(magicLink).toHaveBeenCalled());
    expect(magicLink.mock.calls[0]?.[0]).toMatchObject({ callbackURL: "/plans" });
  });

  it("'Inviane un altro' resends to the same address, says so and refocuses the news; 'Cambia indirizzo' keeps the address", async () => {
    magicLink.mockResolvedValue(sent);
    renderForm();
    typeAndSubmit("a@example.com");
    await screen.findByRole("heading", { name: "Controlla la posta" });

    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.click(screen.getByRole("button", { name: "Inviane un altro" }));
    await waitFor(() => expect(magicLink).toHaveBeenCalledTimes(2));
    expect(magicLink.mock.calls[1]?.[0]).toMatchObject({ email: "a@example.com" });
    const news = await screen.findByText(/Abbiamo inviato un altro link a/);
    expect(news.getAttribute("aria-live")).toBe("polite");
    await waitFor(() => expect(document.activeElement?.contains(news)).toBe(true));

    // `selectionStart` is null on type=email inputs (the spec excludes them), so the call is spied.
    const select = vi.spyOn(HTMLInputElement.prototype, "select");
    fireEvent.click(screen.getByRole("button", { name: "Cambia indirizzo" }));
    const input = screen.getByLabelText(LABEL) as HTMLInputElement;
    expect(input.value).toBe("a@example.com");
    await waitFor(() => expect(document.activeElement).toBe(input));
    expect(select).toHaveBeenCalledTimes(1); // typing replaces the kept address
  });

  it("a rate limit on the resend is an alert inside the sent panel", async () => {
    magicLink.mockResolvedValueOnce(sent).mockResolvedValueOnce({ data: null, error: { status: 429, message: "x" } });
    renderForm();
    typeAndSubmit("a@example.com");
    await screen.findByRole("heading", { name: "Controlla la posta" });

    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.click(screen.getByRole("button", { name: "Inviane un altro" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(TOO_MANY_REQUESTS_ERROR));
    const heading = screen.getByRole("heading", { name: "Controlla la posta" });
    await waitFor(() => expect(document.activeElement?.contains(heading)).toBe(true)); // focus never falls to the document
  });

  it("a refused address is an error on the field, with the invite rule and the way in, and focus goes back to it", async () => {
    magicLink.mockResolvedValue(REFUSED);
    renderForm();

    typeAndSubmit("nobody@example.com");

    const input = screen.getByLabelText(LABEL);
    await waitFor(() => expect(input.getAttribute("aria-invalid")).toBe("true"));
    const error = screen.getByText(INVITE_ONLY_ERROR).closest("p")!;
    expect(error.textContent).toContain(INVITE_ONLY_HELP);
    expect(input.getAttribute("aria-describedby")).toContain(error.id);
    expect(screen.queryByRole("alert")).toBeNull();
    // The way in is the primary now; the action that just failed steps back.
    expect(screen.getByRole("button", { name: "Mettimi in lista" }).className).toMatch(/\bbg-action\b/);
    expect(screen.getByRole("button", { name: "Inviami il link" }).className).not.toMatch(/\bbg-action\b/);
    await waitFor(() => expect(document.activeElement).toBe(input));

    fireEvent.change(input, { target: { value: "nobody2@example.com" } });
    expect(input.getAttribute("aria-invalid")).toBeNull();
    expect(screen.queryByRole("button", { name: "Mettimi in lista" })).toBeNull(); // another address: another try first
    expect(screen.getByRole("button", { name: "Inviami il link" }).className).toMatch(/\bbg-action\b/);
  });

  it("while an address stands refused, the way in comes first and Enter on the same address joins the list instead of another refusal", async () => {
    magicLink.mockResolvedValue(REFUSED);
    join.mockResolvedValue({ status: "joined", email: "nobody@example.com" });
    renderForm();
    typeAndSubmit("nobody@example.com");
    const offer = await screen.findByRole("button", { name: "Mettimi in lista" });
    const link = screen.getByRole("button", { name: "Inviami il link" });
    expect(offer.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(magicLink).toHaveBeenCalledTimes(1);

    fireEvent.submit(screen.getByLabelText(LABEL).closest("form")!);

    await screen.findByRole("heading", { name: "Sei in lista" });
    expect(magicLink).toHaveBeenCalledTimes(1); // no second refusal
    expect((join.mock.calls[0]?.[1] as FormData).get("email")).toBe("nobody@example.com");
  });

  it("'Mettimi in lista' joins the waitlist with the refused address, from the login, and shows the answer", async () => {
    magicLink.mockResolvedValue(REFUSED);
    join.mockResolvedValue({ status: "joined", email: "nobody@example.com" });
    renderForm({ returnTo: "/plans/abc" });
    typeAndSubmit("nobody@example.com");
    await screen.findByRole("button", { name: "Mettimi in lista" });

    fireEvent.click(screen.getByRole("button", { name: "Mettimi in lista" }));

    const heading = await screen.findByRole("heading", { name: "Sei in lista" });
    const data = join.mock.calls[0]?.[1] as FormData;
    expect(data.get("email")).toBe("nobody@example.com");
    expect(data.get("source")).toBe("login");
    expect(screen.getByRole("status").textContent).toContain("nobody@example.com");
    expect(screen.getByText(LISTED_HINT)).toBeTruthy(); // the h1 still says "Accedi": this says when
    await waitFor(() => expect(document.activeElement?.contains(heading)).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "Cambia indirizzo" }));
    const input = screen.getByLabelText(LABEL) as HTMLInputElement;
    expect(input.value).toBe("nobody@example.com");
    expect(input.getAttribute("aria-invalid")).toBeNull();
  });

  it("an address the list already knows as invited gets its link after all", async () => {
    magicLink.mockResolvedValueOnce(REFUSED).mockResolvedValueOnce(sent);
    join.mockResolvedValue({ status: "already_invited", email: "late@example.com" });
    renderForm();
    typeAndSubmit("late@example.com");
    fireEvent.click(await screen.findByRole("button", { name: "Mettimi in lista" }));

    await screen.findByRole("heading", { name: "Controlla la posta" });
    expect(magicLink).toHaveBeenCalledTimes(2);
  });

  it("a failed join is an alert, and the form stays", async () => {
    magicLink.mockResolvedValue(REFUSED);
    join.mockResolvedValue({ status: "error", error: "failed" });
    renderForm();
    typeAndSubmit("nobody@example.com");
    fireEvent.click(await screen.findByRole("button", { name: "Mettimi in lista" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(WAITLIST_FAILED));
    expect(screen.getByRole("button", { name: "Mettimi in lista" })).toBeTruthy();
  });

  it("the sent tab heals itself: back in view with a session, it goes where the user was headed", async () => {
    magicLink.mockResolvedValue(sent);
    const navigate = vi.fn();
    renderForm({ returnTo: "/plans/abc?tab=piano", navigate });
    typeAndSubmit("a@example.com");
    await screen.findByRole("heading", { name: "Controlla la posta" });

    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(getSession).toHaveBeenCalledTimes(1));
    expect(navigate).not.toHaveBeenCalled(); // no session yet: the link was not used

    getSession.mockResolvedValue({ data: { session: { id: "ses_1" }, user: { email: "a@example.com" } }, error: null });
    window.dispatchEvent(new Event("focus"));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/plans/abc?tab=piano"));

    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(getSession).toHaveBeenCalledTimes(2); // hidden: nothing to ask
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
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(SEND_FAILED_ERROR));
    expect(SEND_FAILED_ERROR).not.toBe(GENERIC_SIGN_IN_ERROR); // the link failed to leave; access did not fail
  });

  it("shows Better Auth's callback error codes in Italian, with what to do", () => {
    renderForm({ errorCode: "INVALID_TOKEN" });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(SIGN_IN_ERRORS.INVALID_TOKEN!.title);
    expect(alert.textContent).toContain("Chiedine un altro qui sotto.");
    expect(alert.textContent).not.toContain(LINK_VALIDITY); // the lede already says it
    expect(signInError("something_else")).toEqual({ title: GENERIC_SIGN_IN_ERROR });
    expect(signInError(null)).toBeNull();
  });

  it("Google goes through the social sign-in with the same return path", async () => {
    social.mockResolvedValue({ data: { url: "https://accounts.google.com/x", redirect: true }, error: null });
    renderForm({ returnTo: "/evals" });

    fireEvent.click(screen.getByRole("button", { name: "Continua con Google" }));

    await waitFor(() =>
      expect(social).toHaveBeenCalledWith({
        provider: "google",
        callbackURL: "/evals",
        errorCallbackURL: "/login?returnTo=%2Fevals",
      }),
    );
    expect(screen.getByRole("button", { name: "Apro Google…" })).toHaveProperty("disabled", true);
  });

  it("without accounts on the server there is the lede and the reason, no form", () => {
    renderForm({ configured: false });
    expect(screen.getByText(UNCONFIGURED_MESSAGE)).toBeTruthy();
    expect(screen.queryByText(/env\.example/)).toBeNull();
    expect(screen.queryByLabelText(LABEL)).toBeNull();
    expect(screen.queryByRole("button", { name: "Inviami il link" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Continua con Google" })).toBeNull();
  });

  it("drops a shown ?error= from the address bar and keeps returnTo", () => {
    window.history.replaceState(null, "", "/login?returnTo=%2Fplans%2Fabc&error=INVALID_TOKEN");
    renderForm({ errorCode: "INVALID_TOKEN", returnTo: "/plans/abc" });
    expect(window.location.search).toBe("?returnTo=%2Fplans%2Fabc");
    window.history.replaceState(null, "", "/");
  });
});
