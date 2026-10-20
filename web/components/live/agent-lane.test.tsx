import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VIRTUALIZATION_THRESHOLD } from "@/lib/plan-events/virtualization";

import mcpFailure from "@/lib/plan-events/__fixtures__/backend/mcp-failure.json";
import { AGENTS } from "@/lib/plan-events/labels";
import { reducePlanEvents } from "@/lib/plan-events/reducer";
import { UIEventSchema } from "@/lib/schemas/generated/ui-event";

import { AgentLane, JumpToLatest, LaneBody, LaneColumn, LaneHead, RECENT_STATIONS } from "./agent-lane";
import { buildLaneViews, type LaneView, type Station } from "./stations";

afterEach(cleanup);

const START = Date.parse("2026-10-12T10:00:00+02:00");

function station(seq: number, extra: Partial<Station> = {}): Station {
  return {
    key: String(seq),
    seq,
    kind: "tool",
    ts: new Date(START + seq * 1000).toISOString(),
    title: `Ricerca web: passo ${seq}`,
    meta: "meno di 1 s",
    metaTone: "default",
    message: null,
    ...extra,
  };
}

function view(extra: Partial<LaneView> = {}): LaneView {
  return {
    agent: "activities",
    state: "working",
    badge: extra.state ?? "working",
    stations: [station(1)],
    live: null,
    asking: null,
    notices: [],
    summary: "Ragiona sul prossimo passo.",
    errorTitle: null,
    ...extra,
  };
}

const props = {
  open: true,
  desktop: false,
  onToggle: () => {},
  startedAt: START,
  now: START + 90_000,
  freshAfterSeq: null,
  running: true,
  stale: false,
};

describe("AgentLane", () => {
  it("keeps a dead source visible on the card's second line, closed or open", () => {
    const notices = [{ key: "source:kiwi.com", source: "Kiwi.com", title: "Kiwi.com non ha risposto" }];
    render(<AgentLane {...props} open={false} view={view({ state: "done", summary: "Esito consegnato al coordinatore.", notices })} />);
    const card = screen.getByRole("region");
    expect(within(card).getByText("Esito consegnato al coordinatore.")).toBeTruthy();
    expect(within(card).getByText("1 fonte non risponde")).toBeTruthy();
    cleanup();
    render(<AgentLane {...props} open={false} view={view({ state: "done", notices: [...notices, { ...notices[0]!, key: "source:b" }] })} />);
    expect(screen.getByText("2 fonti non rispondono")).toBeTruthy();
    cleanup();
    render(<AgentLane {...props} open={false} view={view({ state: "done" })} />);
    expect(screen.queryByText(/fonte|fonti/)).toBeNull();
  });

  it("draws the stations with the elapsed time in the gutter and the live plate at the end", () => {
    render(
      <AgentLane
        {...props}
        view={view({
          stations: [station(5), station(65)],
          live: {
            seq: 80,
            ts: new Date(START + 80_000).toISOString(),
            title: "Expedia · voli MXP→LIS · 14–18 nov",
            tool: "search_flights",
            server: "expedia",
            params: null,
            toolUseId: "t",
          },
        })}
      />,
    );
    const list = screen.getByRole("list", { name: "Eventi di attività" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((item) => item.querySelector("time")?.textContent)).toEqual(["0:05", "1:05", "1:20"]);
    const current = items.at(-1);
    expect(current?.getAttribute("aria-current")).toBe("step");
    expect(current?.textContent).toContain("in corso da 0:10");
  });

  it("says on the lane that a subagent stopped on an error while the coordinator goes on", () => {
    render(
      <AgentLane
        {...props}
        view={view({
          state: "error",
          errorTitle: "Errore: ricerca interrotta",
          stations: [station(1), station(2, { kind: "error", title: "Errore: ricerca interrotta", meta: null })],
        })}
      />,
    );
    const notice = screen.getByText("Il coordinatore prosegue con le altre corsie.").closest("[data-tone]");
    expect(notice?.getAttribute("data-tone")).toBe("error");
    expect(notice?.textContent).toContain("Errore: ricerca interrotta");
  });

  it(`hands rows to the browser's virtualization past ${VIRTUALIZATION_THRESHOLD} stations, keeping them all in the DOM`, () => {
    const many = Array.from({ length: VIRTUALIZATION_THRESHOLD + 1 }, (_, index) => station(index + 1));
    const { rerender } = render(<LaneBody {...props} view={view({ stations: many.slice(0, VIRTUALIZATION_THRESHOLD) })} />);
    const rows = () => within(screen.getByRole("list")).getAllByRole("listitem");
    expect(rows()[0]?.className).not.toContain("content-visibility");
    rerender(<LaneBody {...props} view={view({ stations: many })} />);
    expect(rows()).toHaveLength(VIRTUALIZATION_THRESHOLD + 1);
    expect(rows().every((row) => row.className.includes("[content-visibility:auto]"))).toBe(true);
  });

  it("keeps a closed lane's body out of the tab order, and the one line that says what it does", () => {
    render(<AgentLane {...props} open={false} view={view({ summary: "Esito consegnato al coordinatore.", state: "done" })} />);
    const toggle = screen.getByRole("button", { name: /^Attivit\S+,\s?Finito$/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.getElementById(toggle.getAttribute("aria-controls") ?? "")?.hasAttribute("inert")).toBe(true);
    expect(screen.getAllByText("Esito consegnato al coordinatore.")).toHaveLength(1);
  });

  it("keeps the live tool's line under the header of an open lane, and makes it part of the tap target", () => {
    const onToggle = vi.fn();
    render(
      <AgentLane
        {...props}
        onToggle={onToggle}
        view={view({
          live: {
            seq: 9,
            ts: new Date(START + 80_000).toISOString(),
            title: "Expedia · hotel Lisbona · 14–18 apr",
            tool: "search_hotels",
            server: "expedia",
            params: null,
            toolUseId: "t",
          },
        })}
      />,
    );
    const toggle = screen.getByRole("button", { name: /^Attivit\S+,\s?Al lavoro$/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    // The same title shows twice: the line under the header and the plate at the end of the line.
    expect(screen.getAllByText("Expedia · hotel Lisbona · 14–18 apr")).toHaveLength(2);
    // The header and the line sit in one box, and the button stretches over it.
    const peek = screen.getAllByText(/Expedia · hotel Lisbona/)[0]?.closest("div.relative");
    expect(peek?.contains(toggle)).toBe(true);
    expect(toggle.className).toContain("after:inset-0");
  });

  it("folds an open lane's older stations away and unfolds them on request", () => {
    const many = Array.from({ length: 12 }, (_, index) => station(index + 1));
    render(<AgentLane {...props} view={view({ stations: many })} />);
    const rows = () => within(screen.getByRole("list", { name: "Eventi di attività" })).getAllByRole("listitem");
    // The fold row and the last stations.
    expect(rows()).toHaveLength(1 + RECENT_STATIONS);
    const button = screen.getByRole("button", { name: /^8 passaggi precedenti$/ });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Nascondi i passaggi precedenti" }).getAttribute("aria-expanded")).toBe("true");
    expect(rows()).toHaveLength(1 + 12);
  });

  it("does not fold a short line", () => {
    render(<AgentLane {...props} view={view({ stations: Array.from({ length: RECENT_STATIONS + 1 }, (_, index) => station(index + 1)) })} />);
    expect(screen.queryByRole("button", { name: /passagg/ })).toBeNull();
  });
});

describe("the desktop heads", () => {
  const events = mcpFailure.events.map((event) => UIEventSchema.parse(event));
  const views = buildLaneViews(reducePlanEvents(events, { end: "ready" }));

  it("share one height for the five rules, however long each peek is (mcp_failure)", () => {
    // jsdom has no layout, so this reads the structure that makes the rules level: every head is a
    // flex column whose rule row grows (flex-1) to the height of the grid row the heads share.
    // The Voli lane has a dead source: its peek is the longest.
    expect(views.flights.notices).toHaveLength(1);
    const { container } = render(
      <div className="grid grid-cols-5">
        {AGENTS.map((agent) => (
          <LaneHead key={agent} view={views[agent]} now={START} />
        ))}
      </div>,
    );
    const rules = container.querySelectorAll("[data-lane-rule]");
    expect(rules).toHaveLength(5);
    for (const rule of rules) {
      expect(rule.className).toContain("flex-1");
      expect(rule.className).toContain("border-b");
      expect(rule.parentElement?.className).toContain("flex-col");
    }
  });

  it("keep the peek to two lines and say a dead source in the head, not above the line", () => {
    const { container } = render(
      <>
        <LaneHead view={views.flights} now={START} />
        <LaneColumn view={views.flights} startedAt={START} now={START} freshAfterSeq={null} running={false} stale={false} />
      </>,
    );
    const head = container.querySelector("[data-lane-rule]") as HTMLElement;
    expect(head.textContent).toContain("1 fonte non risponde");
    expect(head.textContent).toContain("il piano prosegue con le altre fonti");
    expect(head.querySelector(".line-clamp-2")).toBeTruthy();
    // The dashed note would push this lane's first station below the others'.
    expect(container.querySelector("[role=group] .border-dashed")).toBeNull();
  });
});

describe("the waiting plate", () => {
  it("has no halo and links to #scelta", () => {
    const asking = { title: "Tocca a te: scegli cosa vedere", seq: 53, ts: new Date(START + 53_000).toISOString() };
    const { container } = render(
      <LaneBody {...props} view={view({ agent: "coordinator", state: "waiting", asking, summary: asking.title })} />,
    );
    const link = screen.getByRole("link", { name: "Tocca a te: scegli cosa vedere" });
    expect(link.getAttribute("href")).toBe("#scelta");
    const item = link.closest("li") as HTMLElement;
    expect(item.getAttribute("data-kind")).toBe("current");
    expect(item.getAttribute("aria-current")).toBe("step");
    expect(container.innerHTML).not.toContain("animate-halo");
    expect(container.innerHTML).not.toContain("after:border-2");
  });

  it("keeps the halo on a running tool's plate", () => {
    const live = { seq: 2, ts: new Date(START + 2000).toISOString(), title: "Ricerca web", tool: "web_search", server: null, params: null, toolUseId: "t" };
    const { container } = render(<LaneBody {...props} view={view({ live })} />);
    expect(container.innerHTML).toContain("animate-halo");
  });
});

describe("JumpToLatest", () => {
  it("is an opaque pill over the lane's text (its surface wins over the button's transparent ground)", () => {
    // The lane's end is below the screen: the pill shows.
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(private readonly callback: IntersectionObserverCallback) {}
        observe() {
          this.callback([{ isIntersecting: false, boundingClientRect: { top: 400 } } as IntersectionObserverEntry], this as never);
        }
        disconnect() {}
      },
    );
    const target = { current: document.createElement("div") };
    render(<JumpToLatest target={target} />);
    expect(screen.getByRole("button").className).toMatch(/(^|\s)bg-surface!(\s|$)/);
    vi.unstubAllGlobals();
  });
});
