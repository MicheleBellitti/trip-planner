import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { inviteAction, removeRequestAction } from "@/app/actions/waitlist";

import type { WaitlistRow } from "@/lib/server/waitlist";

import { formatDay, INVITE_ERRORS, inviteOutcome, removeOutcome, SOURCE_LABELS, WaitlistAdmin } from "./waitlist-admin";

vi.mock("@/app/actions/waitlist", () => ({ inviteAction: vi.fn(), removeRequestAction: vi.fn() }));

const row = (overrides: Partial<WaitlistRow>): WaitlistRow => ({
  email: "a@example.com",
  note: "",
  source: "landing",
  createdAt: "2026-10-17T16:00:00Z",
  invitedAt: null,
  invitedBy: null,
  invitationSentAt: null,
  registered: false,
  ...overrides,
});

afterEach(cleanup);

describe("WaitlistAdmin", () => {
  it("lists the requests with their facts and an Invita, and the invitations with their state", () => {
    render(
      <WaitlistAdmin
        rows={[
          row({ email: "pending@example.com", note: "Lisbona\nad aprile", source: "login" }),
          row({ email: "unsent@example.com", source: "admin", invitedAt: "2026-10-16T10:00:00Z", invitedBy: "me@example.com" }),
          row({ email: "done@example.com", invitedAt: "2026-10-15T10:00:00Z", invitedBy: "me@example.com", invitationSentAt: "2026-10-15T10:00:01Z", registered: true }),
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
    expect(screen.getAllByRole("status").length).toBeGreaterThanOrEqual(2); // the add form's line and the rows' line, mounted empty
    expect(screen.getByText("Nessuna richiesta in attesa.")).toBeTruthy();
    expect(screen.getByText(/Nessun invito ancora/)).toBeTruthy();
  });

  it("answers a row action in the page's status region, which takes focus once the answer is there", async () => {
    vi.mocked(removeRequestAction).mockResolvedValue({ status: "removed", email: "pending@example.com" });
    render(<WaitlistAdmin rows={[row({ email: "pending@example.com" })]} />);
    fireEvent.click(screen.getByRole("button", { name: "Togli pending@example.com" }));
    const line = await screen.findByText("pending@example.com è stato tolto dalla lista.");
    const region = line.closest("[role='status']");
    expect(region).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(region));
    expect(vi.mocked(removeRequestAction).mock.calls[0]?.[1].get("email")).toBe("pending@example.com");
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

    vi.mocked(inviteAction).mockResolvedValueOnce({ status: "invited", email: "cousin@example.com", alreadyInvited: false, emailSent: true });
    fireEvent.change(email, { target: { value: "cousin@example.com" } });
    fireEvent.click(within(add).getByRole("button", { name: "Invita" }));
    const sent = await within(add).findByText("Invito inviato a cousin@example.com.");
    expect((email as HTMLInputElement).value).toBe("");
    expect((note as HTMLTextAreaElement).value).toBe("");
    await waitFor(() => expect(document.activeElement).toBe(sent.closest("[role='status']")));
  });

  it("words each outcome of an invitation", () => {
    expect(inviteOutcome({ status: "idle" })).toBeNull();
    expect(inviteOutcome({ status: "invited", email: "a@b.co", emailSent: true, alreadyInvited: false })).toEqual({ tone: "info", text: "Invito inviato a a@b.co." });
    expect(inviteOutcome({ status: "invited", email: "a@b.co", emailSent: false, alreadyInvited: true })?.text).toContain("aveva già un invito");
    expect(inviteOutcome({ status: "invited", email: "a@b.co", emailSent: false, alreadyInvited: false })?.tone).toBe("warning");
    expect(inviteOutcome({ status: "error", error: "forbidden" })).toEqual({ tone: "error", text: INVITE_ERRORS.forbidden });
    expect(removeOutcome({ status: "removed", email: "a@b.co" })).toEqual({ tone: "info", text: "a@b.co è stato tolto dalla lista." });
    expect(removeOutcome({ status: "error", error: "signed_out" })?.text).toBe(INVITE_ERRORS.signed_out);
  });

  it("writes dates in the planner's home time zone, whatever the machine's", () => {
    expect(formatDay("2026-10-17T22:30:00Z")).toBe("18 ott 2026"); // 00:30 in Rome
  });
});
