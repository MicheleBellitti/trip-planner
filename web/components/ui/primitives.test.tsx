import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { readAskedChoice, type ChoiceOptionView, type ChoiceView } from "@/lib/choices";
import choicesFixture from "@/lib/plan-events/__fixtures__/backend/choices.json";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { Button, LinkButton } from "./button";
import { ChoiceCard } from "./choice-card";
import { CostMeter, costValueText } from "./cost-meter";
import { Countdown } from "./countdown";
import { Field, TextInput } from "./field";
import { PlanStatusBadge, StatusBadge } from "./status-badge";
import { Timeline, TimelineItem, TimelineTitle } from "./timeline";
import { dismissToast, toast, Toaster } from "./toast";

afterEach(() => {
  act(() => dismissToast());
  cleanup();
});

/** The recorded questions: seq 53 (activities, with photos) and seq 77 (food, none). */
function askedChoice(seq: number): ChoiceView {
  const event = (choicesFixture.events as unknown as UIEvent[]).find((candidate) => candidate.seq === seq);
  const choice = event ? readAskedChoice(event.detail) : null;
  if (!choice) throw new Error(`choices.json lost its question at seq ${seq}`);
  return choice;
}

function option(choice: ChoiceView, id: string): ChoiceOptionView {
  const found = choice.options.find((candidate) => candidate.id === id);
  if (!found) throw new Error(`no option ${id}`);
  return found;
}

const activities = askedChoice(53);
const food = askedChoice(77);
const oceanario = option(activities, "a1");
const pena = option(activities, "a2");
const belem = option(activities, "a3");
const tascas = option(food, "c1");
const grill = option(food, "c2");

describe("ChoiceCard", () => {
  it("is a checkbox or a radio named by its title, checked state on the input", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ChoiceCard option={oceanario} control="checkbox" name="q" checked={false} onChange={onChange} media="4/3" />,
    );
    const box = screen.getByRole("checkbox", { name: "Oceanário de Lisboa" }) as HTMLInputElement;
    expect(box.checked).toBe(false);
    // The label is the card's target: a click on its words picks it.
    fireEvent.click(screen.getByText("Oceanário de Lisboa"));
    expect(onChange).toHaveBeenLastCalledWith(true);
    rerender(<ChoiceCard option={oceanario} control="checkbox" name="q" checked onChange={onChange} media="4/3" />);
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(onChange).toHaveBeenLastCalledWith(false);
    // The reason and the facts describe the input, so a screen reader hears them on Tab too.
    const description = document.getElementById(box.getAttribute("aria-describedby") ?? "")?.textContent ?? "";
    expect(description).toContain(oceanario.reason);
    expect(description).toContain("Durata: 2 h 30 min");
    cleanup();

    const pick = vi.fn();
    render(
      <>
        <ChoiceCard option={tascas} control="radio" name="cucina" checked={false} onChange={pick} media="none" />
        <ChoiceCard option={grill} control="radio" name="cucina" checked onChange={vi.fn()} media="none" />
      </>,
    );
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios.map((radio) => [radio.name, radio.checked])).toEqual([
      ["cucina", false],
      ["cucina", true],
    ]);
    expect(screen.getByRole("radio", { name: "Tascas di quartiere" })).toBe(radios[0]);
    fireEvent.click(radios[0]!);
    expect(pick).toHaveBeenCalledWith(true);
    cleanup();

    const never = vi.fn();
    render(<ChoiceCard option={pena} control="checkbox" name="q" checked={false} disabled onChange={never} media="4/3" />);
    const rested = screen.getByRole("checkbox", { name: "Palácio da Pena a Sintra" }) as HTMLInputElement;
    expect(rested.disabled).toBe(true);
    fireEvent.click(screen.getByText("Palácio da Pena a Sintra"));
    expect(never).not.toHaveBeenCalled();
  });

  it("shows duration, price and area chips, and leaves out the unknown ones", () => {
    const facts = () => screen.queryAllByRole("listitem").map((item) => item.textContent);
    render(
      <ChoiceCard
        option={{ ...oceanario, area: "Parque das Nações" }}
        control="checkbox"
        name="q"
        checked={false}
        onChange={vi.fn()}
        media="4/3"
      />,
    );
    expect(facts()).toEqual(["Durata: 2 h 30 min", "Prezzo per il gruppo: 60,00 €", "Zona: Parque das Nações"]);
    // The words before each value are for screen readers: the chip shows the value alone.
    for (const prefix of ["Durata:", "Prezzo per il gruppo:", "Zona:"]) {
      expect(screen.getByText(prefix).className).toContain("sr-only");
    }
    cleanup();

    // No price: no chip, and never "gratis" (a null price is as often "not checked" as "free").
    render(<ChoiceCard option={belem} control="checkbox" name="q" checked={false} onChange={vi.fn()} media="4/3" />);
    expect(facts()).toEqual(["Durata: 3 h 30 min"]);
    cleanup();

    const { container } = render(
      <ChoiceCard option={tascas} control="checkbox" name="q" checked={false} onChange={vi.fn()} media="none" />,
    );
    expect(screen.queryByRole("list")).toBeNull();
    expect(container.textContent).not.toMatch(/gratis/i);
  });

  it("opens the photo's credit on its own button, never toggling the card, with new-tab links", () => {
    const onChange = vi.fn();
    render(<ChoiceCard option={oceanario} control="checkbox" name="q" checked={false} onChange={onChange} media="4/3" />);
    expect(screen.queryByRole("link")).toBeNull();

    const credit = screen.getByRole("button", { name: "Crediti della foto" });
    expect(credit.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(credit);
    expect(credit.getAttribute("aria-expanded")).toBe("true");
    const strip = document.getElementById(credit.getAttribute("aria-controls") ?? "");
    expect(strip?.textContent).toBe("Foto: Jose Manuel (CC BY 2.5), Wikimedia Commons");

    const links = screen.getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["CC BY 2.5", "https://creativecommons.org/licenses/by/2.5"],
      ["Wikimedia Commons", "https://commons.wikimedia.org/wiki/File:Lisboa-Oceanario.jpg"],
    ]);
    for (const link of links) {
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
      // jsdom does not navigate; the click still bubbles as in a browser.
      link.addEventListener("click", (event) => event.preventDefault());
      fireEvent.click(link);
    }
    expect(onChange).not.toHaveBeenCalled();
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);

    fireEvent.click(credit);
    expect(credit.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("link")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("without a photo: the tile with the initial, or no media at all", () => {
    const card = (container: HTMLElement) => container.firstElementChild as HTMLElement;
    const { container } = render(
      <ChoiceCard option={oceanario} control="checkbox" name="q" checked={false} onChange={vi.fn()} media="4/3" />,
    );
    expect(card(container).getAttribute("data-media")).toBe("photo");
    const photo = container.querySelector("img");
    expect(photo?.getAttribute("alt")).toBe("");
    expect(photo?.getAttribute("loading")).toBe("lazy");
    expect(photo?.getAttribute("srcset")).toContain("/500px-Lisboa-Oceanario.jpg 500w");
    expect(photo?.getAttribute("sizes")).toBe("(min-width: 67.5rem) 33vw, 50vw");
    // A photo that does not load leaves the tile, and its credit goes with it.
    fireEvent.error(photo!);
    expect(card(container).getAttribute("data-media")).toBe("tile");
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryByRole("button", { name: "Crediti della foto" })).toBeNull();
    cleanup();

    // Some options of the question have a photo: the others keep the frame, with their initial.
    const tile = render(
      <ChoiceCard option={tascas} control="checkbox" name="q" checked={false} onChange={vi.fn()} media="16/10" />,
    ).container;
    expect(card(tile).getAttribute("data-media")).toBe("tile");
    expect(tile.querySelector("img")).toBeNull();
    expect(tile.querySelector("[data-tile]")?.textContent).toBe("T");
    expect(screen.queryByRole("button", { name: "Crediti della foto" })).toBeNull();
    cleanup();

    // None has one: no photo area at all (a tile is not a photo).
    const none = render(
      <ChoiceCard option={oceanario} control="checkbox" name="q" checked={false} onChange={vi.fn()} media="none" />,
    ).container;
    expect(card(none).getAttribute("data-media")).toBe("none");
    expect(none.querySelector("img, [data-tile]")).toBeNull();
    expect(screen.queryByRole("button", { name: "Crediti della foto" })).toBeNull();
  });
});

describe("Countdown", () => {
  const DEADLINE = Date.parse("2026-10-12T10:04:27.461Z");
  const WINDOW = 240_000;
  const bar = (container: HTMLElement) => (container.querySelector("[data-countdown-bar]") as HTMLElement).style.transform;

  it("shows m:ss and the bar's share of the window", () => {
    const { container, rerender } = render(<Countdown deadlineAt={DEADLINE} windowMs={WINDOW} now={DEADLINE - 120_000} />);
    expect(container.textContent).toBe("Tempo per scegliere: 2:00");
    expect(screen.getByText("Tempo per scegliere:").className).toContain("sr-only");
    expect(bar(container)).toBe("scaleX(0.5)");

    rerender(<Countdown deadlineAt={DEADLINE} windowMs={WINDOW} now={DEADLINE - 45_000} />);
    expect(container.textContent).toBe("Tempo per scegliere: 0:45");
    expect(bar(container)).toBe("scaleX(0.1875)");
    // A second that has begun still counts: 44.2 s left reads 0:45, and the last second 0:01.
    rerender(<Countdown deadlineAt={DEADLINE} windowMs={WINDOW} now={DEADLINE - 44_200} />);
    expect(container.textContent).toBe("Tempo per scegliere: 0:45");
    rerender(<Countdown deadlineAt={DEADLINE} windowMs={WINDOW} now={DEADLINE - 300} />);
    expect(container.textContent).toBe("Tempo per scegliere: 0:01");

    // It reports the time, it does not announce it: the page has one live region.
    expect(container.querySelector("[aria-live], [role=status], [role=timer], [role=alert]")).toBeNull();
  });

  it("clamps to the window and to zero", () => {
    // A browser clock five minutes early never shows more than the question's own window.
    const { container, rerender } = render(
      <Countdown deadlineAt={DEADLINE} windowMs={WINDOW} now={DEADLINE - WINDOW - 300_000} />,
    );
    expect(container.textContent).toBe("Tempo per scegliere: 4:00");
    expect(bar(container)).toBe("scaleX(1)");
    // Before the first tick: the whole window.
    rerender(<Countdown deadlineAt={DEADLINE} windowMs={WINDOW} now={null} />);
    expect(container.textContent).toBe("Tempo per scegliere: 4:00");
    expect(bar(container)).toBe("scaleX(1)");
    // At the deadline, and a clock running late: the expired copy and an empty bar, never below 0:00.
    for (const now of [DEADLINE, DEADLINE + 90_000]) {
      rerender(<Countdown deadlineAt={DEADLINE} windowMs={WINDOW} now={now} />);
      expect(container.textContent).toBe("Tempo scaduto: scelgo io.");
      expect(bar(container)).toBe("scaleX(0)");
    }
  });
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
