import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WaitlistRow } from "@/lib/server/waitlist";

import { formatDay, INVITE_ERRORS, inviteOutcome, SOURCE_LABELS, WaitlistAdmin } from "./waitlist-admin";

vi.mock("@/app/actions/waitlist", () => ({ inviteAction: vi.fn() }));

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
    expect(within(request).getByRole("button", { name: "Invita" })).toBeTruthy();

    const invited = screen.getByRole("region", { name: /Invitati/ });
    expect(within(invited).getByRole("heading").textContent).toBe("Invitati (2)");
    const [unsent, done] = within(invited).getAllByRole("listitem");
    expect(unsent!.textContent).toContain("invitato il 16 ott 2026 da me@example.com · email non inviata");
    expect(within(unsent!).getByRole("button", { name: "Invia l'email" })).toBeTruthy();
    expect(done!.textContent).toContain("email inviata · ha un account");
    expect(within(done!).queryByRole("button")).toBeNull();
  });

  it("has the add form first and says when a list is empty", () => {
    render(<WaitlistAdmin rows={[]} />);
    const add = screen.getByRole("region", { name: "Aggiungi un indirizzo" });
    expect(within(add).getByLabelText("Indirizzo email")).toBeTruthy();
    expect(within(add).getByLabelText(/Nota/)).toBeTruthy();
    expect(within(add).getByRole("button", { name: "Invita" })).toBeTruthy();
    expect(screen.getByText("Nessuna richiesta in attesa.")).toBeTruthy();
    expect(screen.getByText(/Nessun invito ancora/)).toBeTruthy();
  });

  it("words each outcome of an invitation", () => {
    expect(inviteOutcome({ status: "idle" })).toBeNull();
    expect(inviteOutcome({ status: "invited", email: "a@b.co", emailSent: true, alreadyInvited: false })).toEqual({ tone: "info", text: "Invito inviato a a@b.co." });
    expect(inviteOutcome({ status: "invited", email: "a@b.co", emailSent: false, alreadyInvited: true })?.text).toContain("aveva già un invito");
    expect(inviteOutcome({ status: "invited", email: "a@b.co", emailSent: false, alreadyInvited: false })?.tone).toBe("warning");
    expect(inviteOutcome({ status: "error", error: "forbidden" })).toEqual({ tone: "error", text: INVITE_ERRORS.forbidden });
  });

  it("writes dates in the planner's home time zone, whatever the machine's", () => {
    expect(formatDay("2026-10-17T22:30:00Z")).toBe("18 ott 2026"); // 00:30 in Rome
  });
});
