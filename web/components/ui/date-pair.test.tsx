import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DatePair, formatBookingInstant } from "./date-pair";

const NOW = Date.parse("2026-10-12T10:36:12+02:00");
const LISBON = "Europe/Lisbon";

afterEach(cleanup);

function dueSoonMarks(container: HTMLElement): number {
  return container.querySelectorAll("[data-due-soon]").length;
}

describe("DatePair", () => {
  it("always shows both labelled dates, separately", () => {
    render(
      <DatePair
        deadline={{ kind: "date", at: "2026-10-30T23:59:00+01:00" }}
        scheduledFor="2026-11-14T07:05:00+01:00"
        timeZone="Europe/Rome"
        now={NOW}
      />,
    );
    const terms = screen.getAllByRole("term").map((term) => term.textContent);
    expect(terms).toEqual(["Prenota entro", "Quando"]);
    const times = Array.from(document.querySelectorAll("time")).map((time) => time.getAttribute("datetime"));
    expect(times).toEqual(["2026-10-30T23:59:00+01:00", "2026-11-14T07:05:00+01:00"]);
  });

  it("turns amber, in words too, when dueAt is within 72 hours", () => {
    const { container } = render(
      <DatePair
        deadline={{ kind: "date", at: "2026-10-14T23:59:00+02:00" }}
        scheduledFor="2026-11-14T15:00:00+00:00"
        timeZone={LISBON}
        now={NOW}
      />,
    );
    expect(dueSoonMarks(container)).toBe(1);
    expect(screen.getByText("In scadenza · tra 2 giorni")).toBeTruthy();
  });

  it("stays neutral when dueAt is further than 72 hours", () => {
    const { container } = render(
      <DatePair
        deadline={{ kind: "date", at: "2026-10-30T23:59:00+01:00" }}
        scheduledFor="2026-11-14T07:05:00+01:00"
        timeZone={LISBON}
        now={NOW}
      />,
    );
    expect(dueSoonMarks(container)).toBe(0);
    expect(screen.getByText("tra 18 giorni")).toBeTruthy();
  });

  it("says a past deadline in words", () => {
    render(
      <DatePair
        deadline={{ kind: "date", at: "2026-10-11T18:00:00+02:00" }}
        scheduledFor="2026-11-15T10:00:00+00:00"
        timeZone={LISBON}
        now={NOW}
      />,
    );
    expect(screen.getByText("Scadenza passata")).toBeTruthy();
  });

  it("is never amber before the clock is known (server rendering)", () => {
    const { container } = render(
      <DatePair
        deadline={{ kind: "date", at: "2026-10-14T23:59:00+02:00" }}
        scheduledFor="2026-11-14T15:00:00+00:00"
        timeZone={LISBON}
        now={null}
      />,
    );
    expect(dueSoonMarks(container)).toBe(0);
  });

  it("is not amber without a dueAt, as in TripTracker, and says why in words", () => {
    const { container } = render(
      <DatePair deadline={{ kind: "book_now" }} scheduledFor="2026-10-13T09:00:00+02:00" timeZone={LISBON} now={NOW} />,
    );
    expect(dueSoonMarks(container)).toBe(0);
    expect(screen.getByText("Da prenotare subito")).toBeTruthy();
  });

  it.each([
    [{ kind: "none" } as const, "nessuna scadenza"],
    [{ kind: "pending" } as const, "in calcolo…"],
    [{ kind: "unknown" } as const, "non disponibile"],
  ])("writes the %o deadline as %s", (deadline, text) => {
    render(<DatePair deadline={deadline} scheduledFor={null} timeZone={LISBON} now={NOW} />);
    expect(screen.getByText(text)).toBeTruthy();
    expect(screen.getByText("da definire")).toBeTruthy();
  });

  it("keeps both labels in the compact variant and marks amber there too", () => {
    const { container } = render(
      <DatePair
        variant="compact"
        deadline={{ kind: "date", at: "2026-10-14T23:59:00+02:00" }}
        scheduledFor="2026-11-14T15:00:00+00:00"
        timeZone={LISBON}
        now={NOW}
      />,
    );
    expect(screen.getAllByRole("term").map((term) => term.textContent)).toEqual(["Prenota entro", "Quando"]);
    expect(dueSoonMarks(container)).toBe(1);
    expect(screen.getByText(", in scadenza")).toBeTruthy();
  });
});

describe("formatBookingInstant", () => {
  it("writes the instant in the trip's time zone, with the weekday", () => {
    expect(formatBookingInstant("2026-11-14T15:00:00+00:00", LISBON)).toBe("sab 14 nov, 15:00");
    expect(formatBookingInstant("2026-11-14T15:00:00+00:00", LISBON, false)).toBe("sab 14 nov");
  });

  it("returns an unreadable value unchanged", () => {
    expect(formatBookingInstant("domani", LISBON)).toBe("domani");
  });
});
