import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button, LinkButton } from "./button";
import { CostMeter, costValueText } from "./cost-meter";
import { Field, TextInput } from "./field";
import { PlanStatusBadge, StatusBadge } from "./status-badge";
import { Timeline, TimelineItem, TimelineTitle } from "./timeline";
import { dismissToast, toast, Toaster } from "./toast";

afterEach(() => {
  act(() => dismissToast());
  cleanup();
});

describe("CostMeter", () => {
  it("is a meter that speaks dollars", () => {
    render(<CostMeter costCents={162} budgetCents={400} />);
    const meter = screen.getByRole("meter", { name: "Costo della sessione" });
    expect(meter.getAttribute("aria-valuenow")).toBe("162");
    expect(meter.getAttribute("aria-valuemax")).toBe("400");
    expect(meter.getAttribute("aria-valuetext")).toBe(costValueText(162, 400));
    expect(meter.textContent).toContain("1,62 $");
    expect(meter.textContent).toContain("limite 4,00 $");
  });

  it("says it has no cost yet instead of showing a zero, and speaks of the turn's end", () => {
    render(<CostMeter costCents={0} budgetCents={60} pending />);
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.getByText("Costo non ancora aggiornato")).toBeTruthy();
    expect(screen.queryByText("0,00 $")).toBeNull();
    cleanup();
    render(<CostMeter costCents={38} budgetCents={60} />);
    expect(screen.getByRole("meter").getAttribute("aria-valuetext")).toContain("si aggiorna alla fine di ogni turno");
  });

  it("keeps the value in range over the budget and says the real figure", () => {
    render(<CostMeter costCents={431} budgetCents={400} />);
    const meter = screen.getByRole("meter");
    expect(meter.getAttribute("aria-valuenow")).toBe("400");
    expect(meter.getAttribute("aria-valuetext")).toBe(costValueText(431, 400));
    expect(meter.getAttribute("aria-valuetext")).toContain("4,31 dollari");
  });

  it("shows text only without a budget, and waits without a cost", () => {
    render(<CostMeter costCents={120} budgetCents={null} />);
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.getByText("1,20 $")).toBeTruthy();
    cleanup();
    render(<CostMeter costCents={null} budgetCents={400} />);
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.getByText("…")).toBeTruthy();
  });
});

describe("StatusBadge and PlanStatusBadge", () => {
  it.each([
    ["waiting", "In attesa"],
    ["working", "Al lavoro"],
    ["done", "Finito"],
    ["error", "Errore"],
    ["stopped", "Fermato"],
    ["not_started", "Non partita"],
  ] as const)("writes the lane state %s as a word", (state, word) => {
    render(<StatusBadge state={state} agent="flights" />);
    expect(screen.getByText(word)).toBeTruthy();
  });

  it("draws 'non partita' with the dashed ring, never the hourglass of 'in attesa'", () => {
    const { container, rerender } = render(<StatusBadge state="not_started" agent="flights" />);
    expect(container.querySelector("svg circle[stroke-dasharray]")).toBeTruthy();
    expect(container.querySelector("svg use")).toBeNull();
    rerender(<StatusBadge state="waiting" agent="flights" />);
    expect(container.querySelector("svg circle[stroke-dasharray]")).toBeNull();
    expect(container.querySelector("svg use")).toBeTruthy();
  });

  it("writes a plan status as a word", () => {
    render(<PlanStatusBadge status="budget_paused" />);
    expect(screen.getByText("Limite raggiunto")).toBeTruthy();
  });
});

describe("Button and LinkButton", () => {
  it("disables a busy button and says it is busy", () => {
    const onClick = vi.fn();
    render(
      <Button busy onClick={onClick}>
        Interrompo…
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Interrompo…" });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("opens another site in a new tab, safely, and says so", () => {
    render(
      <LinkButton href="https://www.expedia.it/x" external variant="primary">
        Prenota su Expedia
      </LinkButton>,
    );
    const link = screen.getByRole("link", { name: /^Prenota su Expedia\s*\(si apre in una nuova scheda\)$/ });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("draws a link to the current page with a 3 px ink edge, like the current station, not the hover wash", () => {
    render(
      <LinkButton href="/new" aria-current="page">
        Nuovo piano
      </LinkButton>,
    );
    const classes = screen.getByRole("link", { name: "Nuovo piano" }).className;
    expect(classes).toMatch(/aria-\[current=page\]:inset-ring-\[1\.5px\]/);
    expect(classes).toMatch(/aria-\[current=page\]:inset-ring-ink/);
    expect(classes).not.toMatch(/aria-\[current=page\]:bg-notice-wash/);
  });
});

describe("Field", () => {
  it("wires the label, the hint and the error to the control", () => {
    render(
      <Field label="Destinazione" hint="Una città" error="Scrivi una città.">
        {(control) => <TextInput {...control} />}
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "Destinazione" });
    expect(input.getAttribute("aria-invalid")).toBe("true");
    const describedBy = input.getAttribute("aria-describedby")?.split(" ") ?? [];
    expect(describedBy.map((id) => document.getElementById(id)?.textContent)).toEqual(["Una città", "Scrivi una città."]);
    expect(input.hasAttribute("required")).toBe(true);
  });
});

describe("Timeline", () => {
  it("is a named list whose live station is the current step", () => {
    render(
      <Timeline agent="flights" label="Eventi di voli">
        <TimelineItem kind="tool" time="0:44">
          <TimelineTitle>Kiwi · voli MXP→LIS · 14–18 nov</TimelineTitle>
        </TimelineItem>
        <TimelineItem kind="current" time="6:58">
          <TimelineTitle>Expedia · voli MXP→LIS · 14–18 nov</TimelineTitle>
        </TimelineItem>
      </Timeline>,
    );
    const list = screen.getByRole("list", { name: "Eventi di voli" });
    expect(list.getAttribute("data-agent")).toBe("flights");
    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.getAttribute("aria-current"))).toEqual([null, "step"]);
  });
});

describe("toast", () => {
  it("announces one message at a time and dismisses a neutral one after 5 s", () => {
    vi.useFakeTimers();
    try {
      render(<Toaster />);
      const region = screen.getByRole("status");
      act(() => toast("Link copiato."));
      expect(region.textContent).toBe("Link copiato.");
      act(() => toast("Interruzione richiesta."));
      expect(region.textContent).toBe("Interruzione richiesta.");
      act(() => vi.advanceTimersByTime(5000));
      expect(region.textContent).toBe("");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps an error until it is closed", () => {
    vi.useFakeTimers();
    try {
      render(<Toaster />);
      act(() => toast("Interruzione non riuscita.", { tone: "error" }));
      act(() => vi.advanceTimersByTime(20_000));
      expect(screen.getByRole("status").textContent).toContain("Interruzione non riuscita.");
      fireEvent.click(screen.getByRole("button", { name: "Chiudi il messaggio" }));
      expect(screen.getByRole("status").textContent).toBe("");
    } finally {
      vi.useRealTimers();
    }
  });
});
