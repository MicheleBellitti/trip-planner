import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ROUTES } from "@/lib/routes";

import {
  WAITLIST_CONSENT,
  WAITLIST_EMAIL_LABEL,
  WAITLIST_FAILED,
  WAITLIST_INVALID_EMAIL,
  WAITLIST_NOTE_LABEL,
  WAITLIST_RECEIVED_TITLE,
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
    join.mockResolvedValue({ status: "received", email: "friend@example.com" });
    render(<WaitlistForm source="landing" />);

    submit(" Friend@Example.com ", "Lisbona ad aprile");

    const heading = await screen.findByRole("heading", { name: WAITLIST_RECEIVED_TITLE });
    const data = join.mock.calls[0]?.[1] as FormData;
    expect(data.get("email")).toBe("Friend@Example.com"); // the email input trims; the action lower-cases
    expect(data.get("note")).toBe("Lisbona ad aprile");
    expect(data.get("source")).toBe("landing");
    expect(screen.getByRole("status").textContent).toBe(
      "Se friend@example.com è già abilitato puoi accedere subito; altrimenti ti scriviamo lì quando c'è posto.",
    );
    await waitFor(() => expect(document.activeElement?.contains(heading)).toBe(true));
    expect(screen.queryByRole("link", { name: "Accedi" })).toBeNull(); // no sign-in hint asked for
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

  it("'Cambia indirizzo' brings the form back with the address kept and selected, and the note as it was", async () => {
    join.mockResolvedValue({ status: "received", email: "friend@example.com" });
    render(<WaitlistForm source="landing" signInHint />);
    submit("friend@example.com", "Lisbona ad aprile");
    await screen.findByRole("heading", { name: WAITLIST_RECEIVED_TITLE });
    // The hint went with the form; the answer offers "Accedi" in its place, once.
    expect(screen.getAllByRole("link", { name: "Accedi" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Accedi" }).getAttribute("href")).toBe(ROUTES.login);

    const select = vi.spyOn(HTMLInputElement.prototype, "select");
    fireEvent.click(screen.getByRole("button", { name: "Cambia indirizzo" }));

    const input = screen.getByLabelText(WAITLIST_EMAIL_LABEL) as HTMLInputElement;
    expect(input.value).toBe("friend@example.com");
    expect((screen.getByLabelText(/Il prossimo viaggio/) as HTMLTextAreaElement).value).toBe("Lisbona ad aprile");
    await waitFor(() => expect(document.activeElement).toBe(input));
    expect(select).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Accedi" }).getAttribute("href")).toBe("/login");
  });

  it("a field's error clears as soon as the field is edited", async () => {
    join.mockResolvedValue({ status: "error", error: "invalid_email" });
    render(<WaitlistForm source="landing" />);
    submit("nope");
    const input = screen.getByLabelText(WAITLIST_EMAIL_LABEL) as HTMLInputElement;
    await waitFor(() => expect(input.getAttribute("aria-invalid")).toBe("true"));

    fireEvent.change(input, { target: { value: "nope@" } });

    expect(input.getAttribute("aria-invalid")).toBeNull();
    expect(screen.queryByText(WAITLIST_INVALID_EMAIL)).toBeNull();
  });

  it("a failure is an alert above the form", async () => {
    join.mockResolvedValue({ status: "error", error: "failed" });
    render(<WaitlistForm source="landing" />);

    submit("friend@example.com");

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(WAITLIST_FAILED));
    expect(screen.getByRole("button", { name: WAITLIST_SUBMIT })).toBeTruthy();
  });

  it("a rejected action (a dropped connection, a redeploy) is the same alert, and the form works again", async () => {
    join.mockRejectedValueOnce(new Error("Failed to find Server Action"));
    render(<WaitlistForm source="landing" />);

    submit("friend@example.com");

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(WAITLIST_FAILED));
    expect((screen.getByLabelText(WAITLIST_EMAIL_LABEL) as HTMLInputElement).value).toBe("friend@example.com");
    join.mockResolvedValueOnce({ status: "received", email: "friend@example.com" });
    fireEvent.submit(screen.getByLabelText(WAITLIST_EMAIL_LABEL).closest("form")!);
    await screen.findByRole("heading", { name: WAITLIST_RECEIVED_TITLE });
  });

  it("says the same thing for every address: the panel takes only the address, never an outcome", () => {
    render(<WaitlistOutcome email="friend@example.com" hint="Torna con lo stesso indirizzo." />);
    expect(screen.getByRole("heading", { name: WAITLIST_RECEIVED_TITLE })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Se friend@example.com è già abilitato");
    expect(screen.getByText("Torna con lo stesso indirizzo.")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
    cleanup();
    render(<WaitlistOutcome email="friend@example.com" signIn />);
    expect(screen.getByRole("link", { name: "Accedi" }).getAttribute("href")).toBe(ROUTES.login);
  });
});
