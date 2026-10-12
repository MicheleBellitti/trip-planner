import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlanDetailSchema } from "@/lib/schemas/api";

import happyDetailJson from "../__fixtures__/happy-path.detail.json";
import { ItineraryDays, ItineraryMap, ItineraryMapPanel, ItineraryMapProvider } from "./itinerary-map";
import { buildMapModel, type MapPlan } from "./model";

// The heavy part is not run in jsdom (no WebGL): a stand-in that shows what it was given.
vi.mock("./itinerary-map-gl", () => ({
  default: (props: {
    selectedDay: number | null;
    pickedKey: string | null;
    onGoToStop: (dayIndex: number, stopIndex: number) => void;
  }) => (
    <div data-testid="gl" data-selected={String(props.selectedDay)} data-picked={String(props.pickedKey)}>
      <button type="button" onClick={() => props.onGoToStop(1, 2)}>
        go to day 2, stop 3
      </button>
    </div>
  ),
}));

function happyPlan() {
  const plan = PlanDetailSchema.parse(structuredClone(happyDetailJson)).plan;
  if (!plan) throw new Error("no plan");
  return plan;
}

type Callback = (entries: { isIntersecting: boolean }[]) => void;
let observers: { callback: Callback; options: IntersectionObserverInit | undefined; disconnected: boolean }[] = [];

beforeEach(() => {
  observers = [];
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      entry: (typeof observers)[number];
      constructor(callback: Callback, options?: IntersectionObserverInit) {
        this.entry = { callback, options, disconnected: false };
        observers.push(this.entry);
      }
      observe() {}
      disconnect() {
        this.entry.disconnected = true;
      }
    },
  );
});
afterEach(cleanup);

const nearView = () => act(() => observers.at(-1)?.callback([{ isIntersecting: true }]));

describe("ItineraryMap", () => {
  const model = buildMapModel(happyPlan());
  if (!model) throw new Error("no model");

  it("is a labelled region with a text summary", () => {
    render(<ItineraryMap model={model} selectedDay={null} onSelectDay={() => {}} />);
    const region = screen.getByRole("region", { name: "Mappa delle tappe" });
    const summary = document.getElementById(region.getAttribute("aria-describedby") ?? "");
    expect(summary?.textContent).toMatch(/^Mappa di \d+ tappe su 19, in 5 giorni\./);
  });

  it("holds a skeleton of the same frame until the map is near, then loads it", async () => {
    render(<ItineraryMap model={model} selectedDay={null} onSelectDay={() => {}} />);
    const region = screen.getByRole("region", { name: "Mappa delle tappe" });
    expect(screen.queryByTestId("gl")).toBeNull();
    expect(within(region).getByText("Caricamento della mappa…")).toBeTruthy();
    expect(observers.at(-1)?.options?.rootMargin).toBe("400px");
    nearView();
    expect(await screen.findByTestId("gl")).toBeTruthy();
    expect(observers.at(-1)?.disconnected).toBe(true);
  });

  it("says so, and loads nothing, in a browser with no IntersectionObserver", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    render(<ItineraryMap model={model} selectedDay={null} onSelectDay={() => {}} />);
    expect(screen.getByText(/La mappa non si carica su questo dispositivo/)).toBeTruthy();
    expect(screen.queryByTestId("gl")).toBeNull();
  });

  it("shows OpenStreetMap's and OpenFreeMap's attribution, with safe links", () => {
    render(<ItineraryMap model={model} selectedDay={null} onSelectDay={() => {}} />);
    const osm = screen.getByRole("link", { name: "OpenStreetMap contributors" });
    expect(osm.getAttribute("href")).toBe("https://www.openstreetmap.org/copyright");
    expect(screen.getByRole("link", { name: "OpenFreeMap" })).toBeTruthy();
    for (const link of screen.getAllByRole("link")) expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("lists the days in the legend as toggle buttons", () => {
    const picked: (number | null)[] = [];
    render(<ItineraryMap model={model} selectedDay={1} onSelectDay={(index) => picked.push(index)} />);
    const group = screen.getByRole("group", { name: "Giorni sulla mappa" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Tutti i giorni",
      "Giorno 1",
      "Giorno 2",
      "Giorno 3",
      "Giorno 4",
      "Giorno 5",
    ]);
    expect(buttons.map((button) => button.getAttribute("aria-pressed"))).toEqual([
      "false",
      "false",
      "true",
      "false",
      "false",
      "false",
    ]);
    fireEvent.click(buttons[3] as HTMLElement);
    fireEvent.click(buttons[2] as HTMLElement);
    fireEvent.click(buttons[0] as HTMLElement);
    expect(picked).toEqual([2, null, null]);
    expect(screen.getByText("Alloggio")).toBeTruthy();
  });

  it("offers the day trip as a quiet chip that picks its day", () => {
    const picked: (number | null)[] = [];
    const { rerender } = render(<ItineraryMap model={model} selectedDay={null} onSelectDay={(index) => picked.push(index)} />);
    const chip = screen.getByRole("button", { name: "Fuori mappa: Sintra (Giorno 3)" });
    expect(chip.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(chip);
    expect(picked).toEqual([2]);
    rerender(<ItineraryMap model={model} selectedDay={2} onSelectDay={(index) => picked.push(index)} />);
    fireEvent.click(screen.getByRole("button", { name: "Fuori mappa: Sintra (Giorno 3)" }));
    expect(picked).toEqual([2, null]);
  });

  it("says in a polite live line how much of the plan is on the map, and what a picked day has", () => {
    const { rerender } = render(<ItineraryMap model={model} selectedDay={null} onSelectDay={() => {}} />);
    const line = screen.getByRole("status");
    expect(line.textContent).toBe(`${model.located} tappe su 19 sono sulla mappa, le altre solo nell'elenco.`);
    rerender(<ItineraryMap model={model} selectedDay={2} onSelectDay={() => {}} />);
    expect(screen.getByRole("status").textContent).toBe("Giorno 3: 2 tappe sulla mappa, altre 2 solo nell'elenco.");
  });
});

/** The map above the list, the phone's order (the page puts the map elsewhere from 1080 px). */
function ItineraryWithMap({ plan, children }: { plan: MapPlan; children: ReactNode }) {
  return (
    <ItineraryMapProvider plan={plan}>
      <ItineraryMapPanel />
      <ItineraryDays className="mt-8">{children}</ItineraryDays>
    </ItineraryMapProvider>
  );
}

describe("ItineraryWithMap", () => {
  function list() {
    return (
      <ol>
        {["Uno", "Due", "Tre"].map((name) => (
          <li key={name} data-testid={`day-${name}`}>
            <h3>
              <span>Giorno</span>
              <span>{name}</span>
            </h3>
            <ol>
              <li>
                <p>{`stop ${name}`}</p>
                <a href="#x">{`link ${name}`}</a>
              </li>
            </ol>
          </li>
        ))}
      </ol>
    );
  }
  const base = happyPlan();
  const plan = { ...base, days: base.days.slice(0, 3) };

  it("renders the list alone when the plan has no coordinates", () => {
    const bare = {
      ...plan,
      days: plan.days.map((day) => ({ ...day, stops: day.stops.map((stop) => ({ ...stop, lat: null, lon: null })) })),
    };
    render(<ItineraryWithMap plan={bare}>{list()}</ItineraryWithMap>);
    expect(screen.queryByRole("region", { name: "Mappa delle tappe" })).toBeNull();
    expect(screen.getByTestId("day-Uno")).toBeTruthy();
  });

  it("puts the map above the list", () => {
    render(<ItineraryWithMap plan={plan}>{list()}</ItineraryWithMap>);
    const region = screen.getByRole("region", { name: "Mappa delle tappe" });
    const day = screen.getByTestId("day-Uno");
    expect(region.compareDocumentPosition(day) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("highlights a day clicked in the list, and clears it on a second click", async () => {
    render(<ItineraryWithMap plan={plan}>{list()}</ItineraryWithMap>);
    nearView();
    const gl = await screen.findByTestId("gl");
    expect(gl.dataset.selected).toBe("null");
    fireEvent.click(screen.getByText("Due"));
    expect(screen.getByTestId("gl").dataset.selected).toBe("1");
    expect(screen.getByTestId("day-Due").hasAttribute("data-day-selected")).toBe(true);
    expect(screen.getByTestId("day-Uno").hasAttribute("data-day-selected")).toBe(false);
    expect(screen.getByRole("button", { name: "Giorno 2" }).getAttribute("aria-pressed")).toBe("true");
    // A click in one of the day's stops is a click in that day.
    fireEvent.click(screen.getByText("stop Uno"));
    expect(screen.getByTestId("gl").dataset.selected).toBe("0");
    fireEvent.click(screen.getByText("stop Uno"));
    expect(screen.getByTestId("gl").dataset.selected).toBe("null");
  });

  it("leaves links in the list alone", async () => {
    render(<ItineraryWithMap plan={plan}>{list()}</ItineraryWithMap>);
    nearView();
    await screen.findByTestId("gl");
    const link = screen.getByText("link Uno");
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    expect(screen.getByTestId("gl").dataset.selected).toBe("null");
  });

  it("selects from the legend too", async () => {
    render(<ItineraryWithMap plan={plan}>{list()}</ItineraryWithMap>);
    nearView();
    await screen.findByTestId("gl");
    fireEvent.click(screen.getByRole("button", { name: "Giorno 3" }));
    expect(screen.getByTestId("gl").dataset.selected).toBe("2");
    expect(screen.getByTestId("day-Tre").hasAttribute("data-day-selected")).toBe(true);
  });

  it("takes the way from a station to its row in the list: 'Vai alla tappa'", async () => {
    render(
      <ItineraryWithMap plan={plan}>
        {list()}
      </ItineraryWithMap>,
    );
    nearView();
    await screen.findByTestId("gl");
    const row = screen.getByTestId("day-Due").querySelector("ol > li") as HTMLElement;
    const scroll = vi.fn();
    row.scrollIntoView = scroll;
    fireEvent.click(screen.getByText("go to day 2, stop 3"));
    // The list's second day has one stop, so stop 3 is not there: nothing moves, nothing throws.
    expect(scroll).not.toHaveBeenCalled();
    const list2 = screen.getByTestId("day-Due").querySelector("ol") as HTMLElement;
    const stops = [row, row.cloneNode(true) as HTMLElement, row.cloneNode(true) as HTMLElement];
    for (const extra of stops.slice(1)) list2.append(extra);
    const third = stops[2] as HTMLElement;
    third.scrollIntoView = scroll;
    fireEvent.click(screen.getByText("go to day 2, stop 3"));
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(third.hasAttribute("data-stop-found")).toBe(true);
    expect(document.activeElement).toBe(third);
  });

  it("lets the page put the map somewhere else than above the list", () => {
    render(
      <ItineraryMapProvider plan={plan}>
        <aside>
          <ItineraryMapPanel />
        </aside>
        <main>
          <ItineraryDays>{list()}</ItineraryDays>
        </main>
      </ItineraryMapProvider>,
    );
    const region = screen.getByRole("region", { name: "Mappa delle tappe" });
    expect(region.closest("aside")).toBeTruthy();
    fireEvent.click(screen.getByText("Tre"));
    expect(screen.getByRole("button", { name: "Giorno 3" }).getAttribute("aria-pressed")).toBe("true");
  });
});
