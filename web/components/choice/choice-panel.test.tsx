import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CHOICE_PANEL_ID, readAskedChoice, type ChoiceView } from "@/lib/choices";
import choicesFixture from "@/lib/plan-events/__fixtures__/backend/choices.json";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import ChoicePanelDefault, { ChoicePanel, type ChoiceControls } from "./choice-panel";

afterEach(cleanup);

/** The recorded questions: seq 53 (activities, several picks, photos) and seq 77 (food, none). */
function askedChoice(seq: number): ChoiceView {
  const event = (choicesFixture.events as unknown as UIEvent[]).find((candidate) => candidate.seq === seq);
  const choice = event ? readAskedChoice(event.detail) : null;
  if (!choice) throw new Error(`choices.json lost its question at seq ${seq}`);
  return choice;
}

const activities = askedChoice(53);
const food = askedChoice(77);
/** A single-choice question, built by hand: the recording asks none. */
const destination: ChoiceView = {
  ...activities,
  id: "toolu_destination",
  kind: "destination",
  question: "Dove vuoi andare?",
  multiple: false,
};

const ASKED = Date.parse(activities.askedAt);
const DEADLINE = Date.parse(activities.deadlineAt);
const RULE = "Se non scegli entro 4 minuti, scelgo io.";

function controls(extra: Partial<ChoiceControls> = {}): ChoiceControls {
  return { answer: vi.fn(async () => null), ...extra };
}

function show(choice: ChoiceView, extra: Partial<ChoiceControls> = {}, now: number | null = ASKED + 12_000) {
  const panelControls = controls(extra);
  const view = render(<ChoicePanel choice={choice} controls={panelControls} now={now} destination="Lisbona" />);
  return { ...view, controls: panelControls };
}

const box = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;
const primary = () => screen.getByRole("button", { name: /^Continua con quest[ae]$/ }) as HTMLButtonElement;
const skip = () => screen.getByRole("button", { name: "Scegli tu" }) as HTMLButtonElement;
/** The countdown's time ("Tempo per scegliere: 3:48"), or null when it is not shown. */
const clock = () => screen.queryByText("Tempo per scegliere:", { exact: false })?.parentElement ?? null;

/** A promise the test settles by hand, to look at the panel while the answer is on its way. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

describe("ChoicePanel", () => {
  it("names whose findings these are, asks the question, states the rule once", () => {
    expect(ChoicePanelDefault).toBe(ChoicePanel);
    const { container } = show(activities);

    const panel = screen.getByRole("region", { name: "Cosa ti va di vedere?" });
    expect(panel.id).toBe(CHOICE_PANEL_ID);
    const heading = screen.getByRole("heading", { level: 2, name: "Cosa ti va di vedere?" });
    expect(heading.id).toBe(`${CHOICE_PANEL_ID}-domanda`);
    expect(heading.getAttribute("tabindex")).toBe("-1");

    // The eyebrow: the activities line found these, with its roundel.
    const eyebrow = screen.getByText("Attività ha trovato 3 idee per Lisbona");
    expect(eyebrow.closest("p")?.querySelector("[data-agent]")?.getAttribute("data-agent")).toBe("activities");

    // The intro states the rule once, and nothing else on the panel repeats it.
    const intro = screen.getByText(`Scegli quelle che ti piacciono, anche più di una. ${RULE}`);
    expect(container.textContent?.split("Se non scegli").length).toBe(2);

    // The cards: checkboxes in a group named by the heading, with their photos (4:3).
    const group = screen.getByRole("group", { name: "Cosa ti va di vedere?" });
    expect(within(group).getAllByRole("checkbox")).toHaveLength(3);
    expect(container.querySelectorAll('[data-media="photo"]')).toHaveLength(3);
    expect(container.querySelector(".aspect-\\[4\\/3\\]")).not.toBeNull();

    const countdown = clock();
    expect(countdown?.textContent).toBe("Tempo per scegliere: 3:48");
    const count = screen.getByText("Nessuna scelta");

    // In order: eyebrow, question, intro, cards, countdown, the action row.
    const order = [eyebrow, heading, intro, group, countdown!, count, skip(), primary()];
    for (let index = 1; index < order.length; index += 1) {
      expect(order[index - 1]!.compareDocumentPosition(order[index]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    cleanup();

    // Food: the coordinator proposes; no option has a photo, so no photo area; four across.
    const food_ = show(food);
    const eyebrowFood = screen.getByText("Il coordinatore propone 3 modi di mangiare a Lisbona");
    expect(eyebrowFood.closest("p")?.querySelector("[data-agent]")?.getAttribute("data-agent")).toBe("coordinator");
    expect(food_.container.querySelectorAll('[data-media="none"]')).toHaveLength(3);
    expect(screen.getByRole("group", { name: "Che cucina cerchi?" }).className).toContain("lg:grid-cols-4");
  });

  it("multiple: picks two, the count says '2 scelte', 'Continua con queste' sends them in the order offered", async () => {
    const { controls: panel } = show(activities);
    expect(primary().textContent).toBe("Continua con queste");

    fireEvent.click(box("Torre di Belém e Mosteiro dos Jerónimos"));
    expect(screen.getByText("1 scelta")).toBeTruthy();
    expect(primary().textContent).toBe("Continua con questa");

    fireEvent.click(box("Oceanário de Lisboa"));
    expect(screen.getByText("2 scelte")).toBeTruthy();
    expect(primary().textContent).toBe("Continua con queste");
    expect(box("Oceanário de Lisboa").checked).toBe(true);
    expect(box("Palácio da Pena a Sintra").checked).toBe(false);

    await act(async () => {
      fireEvent.click(primary());
    });
    // a3 was picked first, but the answer keeps the order the cards were offered in.
    expect(panel.answer).toHaveBeenCalledTimes(1);
    expect(panel.answer).toHaveBeenCalledWith(activities.id, { selected: ["a1", "a3"] });
    // It went: everything rests until the parent hides the panel, and nothing turns.
    expect(primary().disabled).toBe(true);
    expect(primary().getAttribute("aria-busy")).toBeNull();
    expect(skip().disabled).toBe(true);
    expect(box("Oceanário de Lisboa").disabled).toBe(true);
  });

  it("single: radios, 'Continua con questa', exactly one pick", async () => {
    const { controls: panel } = show(destination);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    const group = screen.getByRole("radiogroup", { name: "Dove vuoi andare?" });
    const radios = within(group).getAllByRole("radio") as HTMLInputElement[];
    expect(radios).toHaveLength(3);
    expect(screen.getByText(`Scegline una. ${RULE}`)).toBeTruthy();
    expect(screen.getByText("Il coordinatore propone 3 mete")).toBeTruthy();
    // No count on a single choice.
    expect(screen.queryByText(/^(Nessuna scelta|1 scelta|\d+ scelte)$/)).toBeNull();
    expect(primary().textContent).toBe("Continua con questa");

    fireEvent.click(radios[0]!);
    fireEvent.click(radios[1]!);
    expect(radios.map((radio) => radio.checked)).toEqual([false, true, false]);
    expect(primary().textContent).toBe("Continua con questa");

    await act(async () => {
      fireEvent.click(primary());
    });
    expect(panel.answer).toHaveBeenCalledWith(destination.id, { selected: ["a2"] });
  });

  it("'Continua' is disabled with no pick; 'Scegli tu' sends a skip", async () => {
    const { controls: panel } = show(activities);
    expect(primary().disabled).toBe(true);
    expect(skip().disabled).toBe(false);
    fireEvent.click(primary());
    expect(panel.answer).not.toHaveBeenCalled();

    const sent = deferred<null>();
    vi.mocked(panel.answer).mockReturnValueOnce(sent.promise);
    fireEvent.click(skip());
    expect(panel.answer).toHaveBeenCalledWith(activities.id, { skip: true });
    // The pressed button turns; the other one rests.
    expect(skip().getAttribute("aria-busy")).toBe("true");
    expect(primary().getAttribute("aria-busy")).toBeNull();
    expect(primary().disabled).toBe(true);
    await act(async () => {
      sent.resolve(null);
    });
  });

  it("focuses its heading when it appears", () => {
    const panel = controls();
    const { rerender } = render(
      <>
        <button type="button">Altrove</button>
        <ChoicePanel choice={activities} controls={panel} now={ASKED} destination="Lisbona" />
      </>,
    );
    expect(document.activeElement?.id).toBe(`${CHOICE_PANEL_ID}-domanda`);
    fireEvent.click(box("Oceanário de Lisboa"));

    // The same question as a new object (the reducer derives it again): the focus stays where it
    // went, and so do the picks.
    screen.getByRole("button", { name: "Altrove" }).focus();
    rerender(
      <>
        <button type="button">Altrove</button>
        <ChoicePanel choice={{ ...activities }} controls={panel} now={ASKED + 1_000} destination="Lisbona" />
      </>,
    );
    expect(document.activeElement?.textContent).toBe("Altrove");
    expect(box("Oceanário de Lisboa").checked).toBe(true);

    // The next question takes the focus again, and starts with no pick.
    rerender(
      <>
        <button type="button">Altrove</button>
        <ChoicePanel choice={food} controls={panel} now={ASKED + 30_000} destination="Lisbona" />
      </>,
    );
    expect(document.activeElement?.textContent).toBe("Che cucina cerchi?");
    expect(screen.getAllByRole("checkbox").some((input) => (input as HTMLInputElement).checked)).toBe(false);
    expect(screen.getByText("Nessuna scelta")).toBeTruthy();
  });

  it("a failed send shows the error and keeps the picks; a closed answer shows the backend's words and no buttons", async () => {
    const first = deferred<null | string | { closed: string }>();
    const answer = vi.fn<ChoiceControls["answer"]>(() => first.promise);
    show(activities, { answer });

    fireEvent.click(box("Oceanário de Lisboa"));
    fireEvent.click(box("Palácio da Pena a Sintra"));
    fireEvent.click(primary());

    // Sending: the primary turns, and nothing else can be touched.
    expect(primary().getAttribute("aria-busy")).toBe("true");
    expect(primary().disabled).toBe(true);
    expect(skip().disabled).toBe(true);
    expect(skip().getAttribute("aria-busy")).toBeNull();
    expect(screen.getAllByRole("checkbox").every((input) => (input as HTMLInputElement).disabled)).toBe(true);

    await act(async () => {
      first.resolve("Il planner ha avuto un problema. Riprova più tardi.");
    });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Scelta non inviata");
    expect(alert.textContent).toContain("Il planner ha avuto un problema. Riprova più tardi.");
    // The picks are kept, and everything can be touched again.
    expect(box("Oceanário de Lisboa").checked).toBe(true);
    expect(box("Palácio da Pena a Sintra").checked).toBe(true);
    expect(box("Oceanário de Lisboa").disabled).toBe(false);
    expect(primary().disabled).toBe(false);
    expect(primary().getAttribute("aria-busy")).toBeNull();
    expect(skip().disabled).toBe(false);

    // A send that throws (it should not) still says something, and keeps the picks.
    answer.mockRejectedValueOnce(new Error("boom"));
    await act(async () => {
      fireEvent.click(primary());
    });
    expect(screen.getByRole("alert").textContent).toContain("Scelta non inviata");
    expect(screen.getByRole("alert").textContent).not.toContain("boom");
    expect(box("Palácio da Pena a Sintra").checked).toBe(true);

    // The backend says the question closed: its words, no buttons, the cards rest.
    answer.mockResolvedValueOnce({ closed: "Questa scelta è già chiusa: il piano va avanti." });
    await act(async () => {
      fireEvent.click(primary());
    });
    expect(answer).toHaveBeenLastCalledWith(activities.id, { selected: ["a1", "a2"] });
    expect(screen.getByText("Questa scelta è già chiusa: il piano va avanti.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Continua/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Scegli tu" })).toBeNull();
    expect(screen.getAllByRole("checkbox").every((input) => (input as HTMLInputElement).disabled)).toBe(true);
    expect(clock()).toBeNull();
  });

  it("at zero the buttons rest and it says 'Tempo scaduto: scelgo io.'", () => {
    const panel = controls();
    const { rerender } = render(<ChoicePanel choice={activities} controls={panel} now={DEADLINE - 2_000} destination={null} />);
    fireEvent.click(box("Oceanário de Lisboa"));
    expect(primary().disabled).toBe(false);

    rerender(<ChoicePanel choice={activities} controls={panel} now={DEADLINE} destination={null} />);
    expect(screen.getByText("Tempo scaduto: scelgo io.")).toBeTruthy();
    expect(primary().disabled).toBe(true);
    expect(skip().disabled).toBe(true);
    expect(screen.getAllByRole("checkbox").every((input) => (input as HTMLInputElement).disabled)).toBe(true);
    // Without a destination the eyebrow drops its place.
    expect(screen.getByText("Attività ha trovato 3 idee")).toBeTruthy();
  });

  it("autoPick shows those cards selected and rests every control", () => {
    const onTouch = vi.fn();
    const { container } = show(activities, { autoPick: ["a1", "a3"], onTouch });
    expect(screen.getAllByRole("checkbox").map((input) => (input as HTMLInputElement).checked)).toEqual([true, false, true]);
    expect(screen.getAllByRole("checkbox").every((input) => (input as HTMLInputElement).disabled)).toBe(true);
    expect(primary().disabled).toBe(true);
    expect(skip().disabled).toBe(true);
    // The countdown is hidden while the demo picks.
    expect(clock()).toBeNull();
    expect(container.querySelector("[data-countdown-bar]")).toBeNull();
    expect(screen.getByText("2 scelte")).toBeTruthy();
    fireEvent.click(box("Palácio da Pena a Sintra"));
    expect(onTouch).not.toHaveBeenCalled();
  });

  it("no rule and no countdown when deadlineAt is null", async () => {
    const { container, controls: panel } = show(activities, { deadlineAt: null });
    expect(screen.getByText("Scegli quelle che ti piacciono, anche più di una.")).toBeTruthy();
    expect(container.textContent).not.toContain("Se non scegli");
    expect(container.querySelector("[data-countdown-bar]")).toBeNull();
    // Nothing runs out: the buttons still work.
    fireEvent.click(box("Oceanário de Lisboa"));
    await act(async () => {
      fireEvent.click(primary());
    });
    expect(panel.answer).toHaveBeenCalledWith(activities.id, { selected: ["a1"] });
    cleanup();

    // The demo's own window and rule.
    const demoRule = "Se non scegli entro 15 secondi, la corsa prosegue con le scelte registrate.";
    const now = 1_000_000;
    show(activities, { deadlineAt: now + 15_000, windowMs: 15_000, rule: demoRule }, now);
    expect(screen.getByText(`Scegli quelle che ti piacciono, anche più di una. ${demoRule}`)).toBeTruthy();
    expect(clock()?.textContent).toBe("Tempo per scegliere: 0:15");
    cleanup();

    // `rule: null` leaves the countdown alone.
    show(activities, { rule: null });
    expect(screen.getByText("Scegli quelle che ti piacciono, anche più di una.")).toBeTruthy();
    expect(clock()).not.toBeNull();
  });

  it("onTouch fires on the first change of a pick", () => {
    const onTouch = vi.fn();
    show(activities, { onTouch });
    expect(onTouch).not.toHaveBeenCalled();
    fireEvent.click(box("Oceanário de Lisboa"));
    expect(onTouch).toHaveBeenCalledTimes(1);
    fireEvent.click(box("Palácio da Pena a Sintra"));
    fireEvent.click(box("Oceanário de Lisboa"));
    expect(onTouch).toHaveBeenCalledTimes(1);
  });
});
