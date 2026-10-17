import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ROUTES } from "@/lib/routes";

import {
  WAITLIST_CONSENT,
  WAITLIST_EMAIL_LABEL,
  WAITLIST_FAILED,
  WAITLIST_INVALID_EMAIL,
  WAITLIST_NOTE_LABEL,
  WAITLIST_OUTCOMES,
  WAITLIST_SUBMIT,
  WaitlistForm,
  WaitlistOutcome,
} from "./waitlist-form";

const join = vi.fn();

vi.mock("@/app/actions/waitlist", () => ({
  joinWaitlistAction: (...args: unknown[]) => join(...args),
}));

function submit(email: string, note = "") {
  fireEvent.change(screen.getByLabelText(WAITLIST_EMAIL_LABEL), { target: { value: email } });
  if (note) fireEvent.change(screen.getByLabelText(/Il prossimo viaggio/), { target: { value: note } });
  fireEvent.submit(screen.getByLabelText(WAITLIST_EMAIL_LABEL).closest("form")!);
}

describe("WaitlistForm", () => {
  beforeEach(() => join.mockReset());
  afterEach(cleanup);

  it("asks for the address and an optional note, says what the address is for, and names its source", () => {
    const { container } = render(<WaitlistForm source="landing" />);
    expect(screen.getByLabelText(WAITLIST_EMAIL_LABEL)).toHaveProperty("type", "email");
    expect(screen.getByLabelText(/Il prossimo viaggio/).tagName).toBe("TEXTAREA");
    expect(screen.getByText(WAITLIST_CONSENT)).toBeTruthy();
    expect(screen.getByRole("button", { name: WAITLIST_SUBMIT })).toBeTruthy();
    expect(container.querySelector('input[name="source"]')?.getAttribute("value")).toBe("landing");
    expect(WAITLIST_NOTE_LABEL).toBe("Il prossimo viaggio");
  });

  it("sends what was typed to the action and replaces itself with the answer, focused", async () => {
    join.mockResolvedValue({ status: "joined", email: "friend@example.com" });
    render(<WaitlistForm source="landing" />);

    submit(" Friend@Example.com ", "Lisbona ad aprile");

    const heading = await screen.findByRole("heading", { name: WAITLIST_OUTCOMES.joined.title });
    const data = join.mock.calls[0]?.[1] as FormData;
    expect(data.get("email")).toBe("Friend@Example.com"); // the email input trims; the action lower-cases
    expect(data.get("note")).toBe("Lisbona ad aprile");
    expect(data.get("source")).toBe("landing");
    expect(screen.getByRole("status").textContent).toBe("Ti scriviamo a friend@example.com quando c'è posto. Nessun altro messaggio da noi.");
    await waitFor(() => expect(document.activeElement?.contains(heading)).toBe(true));
    expect(screen.queryByRole("link", { name: "Accedi" })).toBeNull();
  });

  it("an address problem is an error on the field, which takes focus, and what was typed stays", async () => {
    join.mockResolvedValue({ status: "error", error: "invalid_email" });
    render(<WaitlistForm source="login" />);

    submit("friend@", "nota");

    const input = screen.getByLabelText(WAITLIST_EMAIL_LABEL) as HTMLInputElement;
    await waitFor(() => expect(input.getAttribute("aria-invalid")).toBe("true"));
    expect(screen.getByText(WAITLIST_INVALID_EMAIL)).toBeTruthy();
    expect(input.value).toBe("friend@");
    expect((screen.getByLabelText(/Il prossimo viaggio/) as HTMLTextAreaElement).value).toBe("nota");
    await waitFor(() => expect(document.activeElement).toBe(input));
  });

  it("a note too long is an error on the note, which takes focus", async () => {
    join.mockResolvedValue({ status: "error", error: "note_too_long" });
    render(<WaitlistForm source="landing" />);

    submit("friend@example.com", "x".repeat(10));

    const note = screen.getByLabelText(/Il prossimo viaggio/);
    await waitFor(() => expect(note.getAttribute("aria-invalid")).toBe("true"));
    await waitFor(() => expect(document.activeElement).toBe(note));
  });

  it("'Cambia indirizzo' brings the form back with the address kept and selected", async () => {
    join.mockResolvedValue({ status: "joined", email: "friend@example.com" });
    render(<WaitlistForm source="landing" signInHint />);
    submit("friend@example.com");
    await screen.findByRole("heading", { name: WAITLIST_OUTCOMES.joined.title });
    expect(screen.queryByRole("link", { name: "Accedi" })).toBeNull(); // the hint went with the form

    const select = vi.spyOn(HTMLInputElement.prototype, "select");
    fireEvent.click(screen.getByRole("button", { name: "Cambia indirizzo" }));

    const input = screen.getByLabelText(WAITLIST_EMAIL_LABEL) as HTMLInputElement;
    expect(input.value).toBe("friend@example.com");
    await waitFor(() => expect(document.activeElement).toBe(input));
    expect(select).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Accedi" })).toBeTruthy();
  });

  it("a failure is an alert above the form", async () => {
    join.mockResolvedValue({ status: "error", error: "failed" });
    render(<WaitlistForm source="landing" />);

    submit("friend@example.com");

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(WAITLIST_FAILED));
    expect(screen.getByRole("button", { name: WAITLIST_SUBMIT })).toBeTruthy();
  });

  it("an address that may already enter is told so, with the way in", () => {
    for (const outcome of ["already_invited", "already_registered"] as const) {
      render(<WaitlistOutcome outcome={outcome} email="friend@example.com" />);
      expect(screen.getByRole("heading", { name: WAITLIST_OUTCOMES[outcome].title })).toBeTruthy();
      expect(screen.getByRole("link", { name: "Accedi" }).getAttribute("href")).toBe(ROUTES.login);
      cleanup();
    }
    render(<WaitlistOutcome outcome="already_listed" email="friend@example.com" hint="Torna con lo stesso indirizzo." />);
    expect(screen.getByRole("status").textContent).toContain("Abbiamo già friend@example.com");
    expect(screen.getByText("Torna con lo stesso indirizzo.")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
    expect(WAITLIST_OUTCOMES.already_listed.icon).toBe("info"); // nothing was done: not a check
  });
});
