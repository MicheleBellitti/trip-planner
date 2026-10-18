import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { inviteAction, removeRequestAction, resendInvitationAction } from "@/app/actions/waitlist";

import type { WaitlistRow } from "@/lib/server/waitlist";

import { formatDay, INVITE_ERRORS, inviteOutcome, REMOVE_ERRORS, removeOutcome, SOURCE_LABELS, WaitlistAdmin } from "./waitlist-admin";

vi.mock("@/app/actions/waitlist", () => ({ inviteAction: vi.fn(), removeRequestAction: vi.fn(), resendInvitationAction: vi.fn() }));

const row = (overrides: Partial<WaitlistRow>): WaitlistRow => ({
  email: "a@example.com",
  note: "",
  source: "landing",
  createdAt: "2026-10-17T16:00:00Z",
  invitedAt: null,
  invitedBy: null,
  invitationSentAt: null,
  invitationSentClaim: null,
  registered: false,
  ...overrides,
});

afterEach(cleanup);

/** The visible answer to a row action: the one line drawn under the row (or in its place). */
async function rowAnswer(text: string): Promise<HTMLElement> {
  return waitFor(() => {
    const line = screen
      .getAllByText(text)
      .map((element) => element.closest<HTMLElement>("[data-row-status]"))
      .find((element) => element !== null);
    if (!line) throw new Error(`no row answer "${text}"`);
    return line;
  });
}

/** What the page's one (visually hidden) region reads aloud. */
const announced = () => screen.getByRole("status").textContent;

describe("WaitlistAdmin", () => {
  it("lists the requests with their facts and an Invita, and the invitations with their state", () => {
    render(
      <WaitlistAdmin
        rows={[
          row({ email: "pending@example.com", note: "Lisbona\nad aprile", source: "login" }),
          row({ email: "unsent@example.com", source: "admin", invitedAt: "2026-10-16T10:00:00Z", invitedBy: "me@example.com" }),
          row({ email: "done@example.com", invitedAt: "2026-10-15T10:00:00Z", invitedBy: "me@example.com", invitationSentAt: "2026-10-15T10:00:01Z", invitationSentClaim: "2026-10-15 10:00:01.000042+00", registered: true }),
        ]}
      />,
    );
    const pending = screen.getByRole("region", { name: /In attesa/ });
    expect(within(pending).getByRole("heading").textContent).toBe("In attesa (1)");
    const request = within(pending).getByRole("listitem");
    expect(request.textContent).toContain("pending@example.com");
    expect(request.textContent).toContain("Lisbona\nad aprile");
    expect(request.textContent).toContain(`${SOURCE_LABELS.login}, 17 ott 2026`);
    // Each row's buttons are named with the address: fourteen "Invita" would tell a screen reader nothing.
    const invite = within(request).getByRole("button", { name: "Invita pending@example.com" });
    expect(invite.className).not.toMatch(/\bbg-action\b/); // the view's one primary is the add form's
    expect(within(request).getByRole("button", { name: "Togli pending@example.com" })).toBeTruthy();

    const invited = screen.getByRole("region", { name: /Invitati/ });
    expect(within(invited).getByRole("heading").textContent).toBe("Invitati (2)");
    const [unsent, done] = within(invited).getAllByRole("listitem");
    expect(unsent!.textContent).toContain("invitato il 16 ott 2026 da me@example.com · email non inviata");
    expect(within(unsent!).getByRole("button", { name: "Invia l'email a unsent@example.com" })).toBeTruthy();
    expect(within(unsent!).queryByRole("button", { name: /Togli/ })).toBeNull(); // an invitation is not removed here
    expect(done!.textContent).toContain("email inviata · ha un account");
    expect(within(done!).queryByRole("button")).toBeNull();
  });

  it("has the invite form first, one primary, a status region from the start, and says when a list is empty", () => {
    render(<WaitlistAdmin rows={[]} />);
    const add = screen.getByRole("region", { name: "Invita un indirizzo" });
    expect(within(add).getByLabelText("Indirizzo email")).toBeTruthy();
    expect(within(add).getByLabelText(/Nota/)).toBeTruthy();
    const primaries = screen.getAllByRole("button").filter((button) => /\bbg-action\b/.test(button.className));
    expect(primaries.map((button) => button.textContent)).toEqual(["Invita"]);
    expect(screen.getAllByRole("status").length).toBe(1); // one region for the whole view, mounted empty
    expect(screen.getByText("Nessuna richiesta in attesa.")).toBeTruthy();
    expect(screen.getByText(/Nessun invito ancora/)).toBeTruthy();
  });

  it("'Togli' asks once: the question takes focus, 'Annulla' gives it back, 'Sì, togli' removes and its answer takes focus when no request is left", async () => {
    vi.mocked(removeRequestAction).mockResolvedValue({ status: "removed", email: "pending@example.com" });
    render(<WaitlistAdmin rows={[row({ email: "pending@example.com" })]} />);
    fireEvent.click(screen.getByRole("button", { name: "Togli pending@example.com" }));
    expect(vi.mocked(removeRequestAction)).not.toHaveBeenCalled();
    const yes = screen.getByRole("button", { name: "Sì, togli pending@example.com" });
    await waitFor(() => expect(document.activeElement).toBe(yes));

    fireEvent.click(screen.getByRole("button", { name: "Annulla" }));
    const remove = screen.getByRole("button", { name: "Togli pending@example.com" });
    await waitFor(() => expect(document.activeElement).toBe(remove));
    expect(screen.queryByRole("button", { name: /Sì, togli/ })).toBeNull();

    fireEvent.click(remove);
    fireEvent.click(screen.getByRole("button", { name: "Sì, togli pending@example.com" }));
    const line = await rowAnswer("pending@example.com è stato tolto dalla lista.");
    await waitFor(() => expect(document.activeElement).toBe(line));
    expect(announced()).toBe("pending@example.com è stato tolto dalla lista.");
    expect(vi.mocked(removeRequestAction).mock.calls[0]?.[1].get("email")).toBe("pending@example.com");
  });

  it("after a row action focus moves to the next request's button, not up to the status line", async () => {
    vi.mocked(inviteAction).mockResolvedValue({ status: "invited", email: "first@example.com", delivery: "sent" });
    render(<WaitlistAdmin rows={[row({ email: "first@example.com" }), row({ email: "second@example.com" })]} />);
    fireEvent.click(screen.getByRole("button", { name: "Invita first@example.com" }));
    await rowAnswer("Invito inviato a first@example.com.");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Invita second@example.com" })));
  });

  it("draws a row action's answer where the row was, even once the row has left the list", async () => {
    vi.mocked(inviteAction).mockResolvedValue({ status: "invited", email: "second@example.com", delivery: "sent" });
    const rows = [row({ email: "first@example.com" }), row({ email: "second@example.com" }), row({ email: "third@example.com" })];
    const { rerender } = render(<WaitlistAdmin rows={rows} />);
    fireEvent.click(screen.getByRole("button", { name: "Invita second@example.com" }));
    const line = await rowAnswer("Invito inviato a second@example.com.");
    expect(line.closest("li")?.textContent).toContain("second@example.com"); // under its own row
    expect(line.className).not.toMatch(/\bbg-|\bborder\b/); // one surface: the line has no frame

    // The page re-reads the rows: the invitation moved to "Invitati", its place keeps the answer.
    rerender(<WaitlistAdmin rows={[rows[0]!, { ...rows[1]!, invitedAt: "2026-10-18T10:00:00Z", invitationSentAt: "2026-10-18T10:00:01Z", invitationSentClaim: "2026-10-18 10:00:01.5+00" }, rows[2]!]} />);
    const pending = within(screen.getByRole("region", { name: /In attesa/ })).getAllByRole("listitem");
    expect(pending.map((item) => item.textContent?.split("@")[0])).toEqual(["first", "second", "third"]);
    expect(pending[1]!.textContent).toContain("Invito inviato a second@example.com.");
    expect(within(pending[1]!).queryByRole("button")).toBeNull();
    expect(announced()).toBe("Invito inviato a second@example.com.");
  });

  it("keeps the typing and focuses the field after a refused add, and clears both after a success", async () => {
    vi.mocked(inviteAction).mockResolvedValueOnce({ status: "error", error: "invalid_email" });
    render(<WaitlistAdmin rows={[]} />);
    const add = screen.getByRole("region", { name: "Invita un indirizzo" });
    const email = within(add).getByLabelText("Indirizzo email");
    const note = within(add).getByLabelText(/Nota/);
    fireEvent.change(email, { target: { value: "not-an-address" } });
    fireEvent.change(note, { target: { value: "la cugina" } });
    fireEvent.click(within(add).getByRole("button", { name: "Invita" }));
    await within(add).findByText(INVITE_ERRORS.invalid_email);
    expect((email as HTMLInputElement).value).toBe("not-an-address");
    expect((note as HTMLTextAreaElement).value).toBe("la cugina");
    await waitFor(() => expect(document.activeElement).toBe(email));

    vi.mocked(inviteAction).mockResolvedValueOnce({ status: "invited", email: "cousin@example.com", delivery: "sent" });
    fireEvent.change(email, { target: { value: "cousin@example.com" } });
    fireEvent.click(within(add).getByRole("button", { name: "Invita" }));
    const sent = await within(add).findByText("Invito inviato a cousin@example.com."); // under the form
    expect((email as HTMLInputElement).value).toBe("");
    expect((note as HTMLTextAreaElement).value).toBe("");
    await waitFor(() => expect(document.activeElement?.contains(sent)).toBe(true));
    expect(announced()).toBe("Invito inviato a cousin@example.com.");
  });

  it("words each outcome of an invitation", () => {
    expect(inviteOutcome({ status: "idle" })).toBeNull();
    expect(inviteOutcome({ status: "invited", email: "a@b.co", delivery: "sent" })).toEqual({ tone: "info", text: "Invito inviato a a@b.co." });
    expect(inviteOutcome({ status: "invited", email: "a@b.co", delivery: "already_sent" })?.text).toContain("aveva già un invito");
    expect(inviteOutcome({ status: "invited", email: "a@b.co", delivery: "has_account" })).toEqual({
      tone: "info",
      text: "a@b.co ha già un account: nessuna email.",
    });
    expect(inviteOutcome({ status: "invited", email: "a@b.co", delivery: "failed" })?.tone).toBe("warning");
    expect(inviteOutcome({ status: "error", error: "forbidden" })).toEqual({ tone: "error", text: INVITE_ERRORS.forbidden });
    expect(removeOutcome({ status: "removed", email: "a@b.co" })).toEqual({ tone: "info", text: "a@b.co è stato tolto dalla lista." });
    expect(removeOutcome({ status: "error", error: "signed_out" })?.text).toBe(INVITE_ERRORS.signed_out);
    expect(removeOutcome({ status: "error", error: "failed" })?.text).toBe(REMOVE_ERRORS.failed);
    expect(REMOVE_ERRORS.failed).toContain("togliere");
  });

  it("a row action that never answers (a dropped connection, a redeploy) is an error in the status line, not the error page", async () => {
    vi.mocked(inviteAction).mockRejectedValueOnce(new Error("Failed to find Server Action"));
    vi.mocked(removeRequestAction).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<WaitlistAdmin rows={[row({ email: "first@example.com" }), row({ email: "second@example.com" })]} />);

    fireEvent.click(screen.getByRole("button", { name: "Invita first@example.com" }));
    const line = await rowAnswer(INVITE_ERRORS.failed);
    expect(line.closest("li")?.textContent).toContain("first@example.com");
    await waitFor(() => expect(document.activeElement).toBe(line));
    const invite = screen.getByRole("button", { name: "Invita first@example.com" });
    expect(invite).toHaveProperty("disabled", false); // the transition ended: the rows work again

    fireEvent.click(screen.getByRole("button", { name: "Togli second@example.com" }));
    fireEvent.click(screen.getByRole("button", { name: "Sì, togli second@example.com" }));
    expect((await rowAnswer(REMOVE_ERRORS.failed)).closest("li")?.textContent).toContain("second@example.com");
  });

  it("the add form survives an action that never answers: an error in the status line, the typing kept", async () => {
    vi.mocked(inviteAction).mockRejectedValueOnce(new Error("Failed to find Server Action"));
    render(<WaitlistAdmin rows={[]} />);
    const add = screen.getByRole("region", { name: "Invita un indirizzo" });
    const email = within(add).getByLabelText("Indirizzo email") as HTMLInputElement;
    fireEvent.change(email, { target: { value: "cousin@example.com" } });
    fireEvent.click(within(add).getByRole("button", { name: "Invita" }));

    await within(add).findByText(INVITE_ERRORS.failed);
    expect(email.value).toBe("cousin@example.com");
    await waitFor(() => expect(email).toHaveProperty("disabled", false));
  });

  it("says the list is cut when the page read only its first rows", () => {
    const { unmount } = render(<WaitlistAdmin rows={[row({})]} />);
    expect(screen.queryByText(/le prime/)).toBeNull();
    unmount();
    render(<WaitlistAdmin rows={[row({})]} truncatedAt={500} />);
    expect(screen.getByText("Qui ci sono le prime 500 voci, le richieste in attesa per prime: le altre restano salvate.")).toBeTruthy();
  });

  it("marks a pending request whose address already has an account", () => {
    render(<WaitlistAdmin rows={[row({ email: "member@example.com", registered: true })]} />);
    expect(screen.getByRole("listitem").textContent).toContain("ha un account");
  });

  it("offers a quiet \"Invia di nuovo\" on a sent invitation, sending the stamp it shows", async () => {
    vi.mocked(resendInvitationAction).mockResolvedValue({ status: "invited", email: "sent@example.com", delivery: "resent" });
    render(
      <WaitlistAdmin
        rows={[
          row({ email: "sent@example.com", invitedAt: "2026-10-15T10:00:00Z", invitationSentAt: "2026-10-15T10:00:01Z", invitationSentClaim: "2026-10-15 10:00:01.000042+00" }),
          row({ email: "member@example.com", invitedAt: "2026-10-15T10:00:00Z", invitationSentAt: "2026-10-15T10:00:01Z", invitationSentClaim: "2026-10-15 10:00:02.5+00", registered: true }),
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: /member@example\.com/ })).toBeNull(); // an account: nothing to resend
    const again = screen.getByRole("button", { name: "Invia di nuovo l'invito a sent@example.com" });
    expect(again.textContent).toBe("Invia di nuovo");
    expect(again.className).not.toMatch(/\bbg-action\b|amber|due/); // quiet, never the deadline colour
    fireEvent.click(again);
    const line = await rowAnswer("Invito inviato di nuovo a sent@example.com.");
    expect(line.closest("li")?.textContent).toContain("sent@example.com");
    const data = vi.mocked(resendInvitationAction).mock.calls[0]?.[1] as FormData;
    expect(data.get("email")).toBe("sent@example.com");
    expect(data.get("sent")).toBe("2026-10-15 10:00:01.000042+00");
  });

  it("words each outcome of a re-send", () => {
    expect(inviteOutcome({ status: "invited", email: "a@b.co", delivery: "resend_skipped" })?.text).toContain("Nessuna nuova email a a@b.co");
    expect(inviteOutcome({ status: "invited", email: "a@b.co", delivery: "resend_failed" })).toEqual({
      tone: "warning",
      text: "L'email per a@b.co non è partita di nuovo: riprova con «Invia di nuovo».",
    });
  });

  it("writes dates in the planner's home time zone, whatever the machine's", () => {
    expect(formatDay("2026-10-17T22:30:00Z")).toBe("18 ott 2026"); // 00:30 in Rome
  });
});
