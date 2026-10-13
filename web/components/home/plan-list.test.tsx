import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { PlanSummary } from "@/lib/schemas/api";

import { resetCoverStore } from "@/components/plan/cover/cover-store";
import type { Cover } from "@/lib/schemas/api";

import { PlanList, POLL_MS, RECENT_ROWS } from "./plan-list";

const mocks = vi.hoisted(() => ({ listPlans: vi.fn(), getCover: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { listPlans: mocks.listPlans, getCover: mocks.getCover } };
});

beforeEach(() => {
  mocks.listPlans.mockReset();
  mocks.getCover.mockReset();
  // No photo unless a test gives one: every row is a tile.
  mocks.getCover.mockResolvedValue(null);
  resetCoverStore();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const PLANS: PlanSummary[] = [
  {
    id: "6f1c2a7e-3b4d-4e5f-8a9b-0c1d2e3f4a5b",
    title: "Lisbona in famiglia, 14–18 aprile 2027",
    status: "ready",
    cost_cents: 162,
    created_at: "2026-10-12T09:18:41Z",
  },
  {
    id: "0b9d8c7e-6f5a-4b3c-8d2e-1f0a9b8c7d6e",
    title: "Lisbona, 14–18 apr",
    status: "running",
    cost_cents: 48,
    created_at: "2026-10-12T10:02:00Z",
  },
];

async function renderList() {
  await act(async () => {
    render(<PlanList />);
  });
}

describe("PlanList", () => {
  it("shows placeholder rows while loading", () => {
    mocks.listPlans.mockReturnValue(new Promise(() => {}));
    render(<PlanList />);
    expect(screen.getByText("Carico i piani…")).toBeTruthy();
    expect(document.querySelector("[aria-busy='true']")).toBeTruthy();
  });

  it("lists each plan with its title, status word, cost in dollars and date, linking to it", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse("2026-10-12T15:00:00Z"));
    mocks.listPlans.mockResolvedValue(PLANS);
    await renderList();

    const first = screen.getByRole("link", { name: /Lisbona in famiglia/ });
    expect(first.getAttribute("href")).toBe(`/plans/${PLANS[0]?.id}`);
    expect(first.textContent).toContain("Pronto");
    expect(first.textContent).toContain("Costo 1,62 $");
    // Relative to today, in Rome: no year on a plan from this week.
    expect(first.textContent).toContain("Creato Oggi, 11:18");
    expect(screen.getByRole("link", { name: /Lisbona, 14–18 apr/ }).textContent).toContain("In corso");
  });

  it("reads no clock while rendering: the server path draws the placeholder rows", () => {
    // With Cache Components the route is prerendered; a Date.now() in render would be frozen into
    // the static shell (and fails the build). Only effects and callbacks may read the clock.
    const now = vi.spyOn(Date, "now").mockImplementation(() => {
      throw new Error("Date.now() was read while rendering");
    });
    try {
      mocks.listPlans.mockReturnValue(new Promise(() => {}));
      const html = renderToString(<PlanList />);
      expect(html).toContain("Carico i piani…");
      expect(now).not.toHaveBeenCalled();
    } finally {
      now.mockRestore();
    }
  });

  it("draws each plan as a station on the rail, with its status glyph, and the word for the quiet ones", async () => {
    mocks.listPlans.mockResolvedValue([
      ...PLANS,
      { ...PLANS[0]!, id: "11111111-3b4d-4e5f-8a9b-0c1d2e3f4a5b", title: "Porto", status: "failed" as const },
      { ...PLANS[0]!, id: "22222222-3b4d-4e5f-8a9b-0c1d2e3f4a5b", title: "Roma", status: "interrupted" as const },
    ]);
    await renderList();
    const rows = screen.getAllByRole("link");
    expect(rows).toHaveLength(4);
    // One node per row, aria-hidden: the status is a word in the row, never the glyph alone.
    for (const row of rows) expect(row.querySelector("span[aria-hidden='true'].rounded-full")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Porto/ }).textContent).toContain("Non riuscito");
    expect(screen.getByRole("link", { name: /Roma/ }).textContent).toContain("Interrotto");
    // Finished rows keep the cost; the running one drops it.
    expect(screen.getByRole("link", { name: /Roma/ }).textContent).toContain("Costo 1,62 $");
    expect(screen.getByRole("link", { name: /Lisbona, 14–18 apr/ }).textContent).not.toContain("Costo");
  });

  it("tells plans of the same trip apart by their creation time, in the meta line and not on the title", async () => {
    // The same day as the plans: "Oggi, 11:18" (the clock is frozen, so the test never depends on today).
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse("2026-10-12T17:00:00Z"));
    mocks.listPlans.mockResolvedValue([
      { ...PLANS[0]!, id: "11111111-3b4d-4e5f-8a9b-0c1d2e3f4a5b", created_at: "2026-10-12T09:18:41Z" },
      { ...PLANS[0]!, id: "22222222-3b4d-4e5f-8a9b-0c1d2e3f4a5b", created_at: "2026-10-12T14:02:00Z" },
      { ...PLANS[0]!, id: "33333333-3b4d-4e5f-8a9b-0c1d2e3f4a5b", created_at: "2026-10-12T16:30:00Z" },
    ]);
    await renderList();
    // The first is featured; the other two are rows, and each says when it was created.
    const rows = screen.getAllByRole("link").filter((link) => !link.hasAttribute("data-featured"));
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      const title = row.querySelector("[data-plan-title]") as HTMLElement;
      expect(title.textContent).toBe("Lisbona in famiglia, 14–18 aprile 2027");
      expect(row.textContent).toMatch(/Creato\s*Oggi, \d\d:\d\d|Creato\s*\d+ \w+/);
    }
  });

  it("keeps a date range in one piece, so a line never breaks inside '14–18 aprile'", async () => {
    mocks.listPlans.mockResolvedValue([PLANS[0], { ...PLANS[0]!, id: "44444444-3b4d-4e5f-8a9b-0c1d2e3f4a5b" }]);
    await renderList();
    const row = screen.getAllByRole("link").find((link) => !link.hasAttribute("data-featured")) as HTMLElement;
    const kept = row.querySelector("[data-plan-title] .whitespace-nowrap");
    expect(kept?.textContent).toBe("14–18 aprile");
  });

  it("puts the running plans first under 'In corso' and the rest under 'Recenti'", async () => {
    mocks.listPlans.mockResolvedValue([PLANS[0], PLANS[1]]);
    await renderList();
    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual(["In corso", "Recenti"]);
    const links = screen.getAllByRole("link").map((link) => link.textContent ?? "");
    expect(links[0]).toContain("Lisbona, 14–18 apr");
    expect(links[1]).toContain("Lisbona in famiglia");
  });

  it("shows eight finished plans and keeps the rest behind 'Mostra gli altri N'", async () => {
    const many: PlanSummary[] = Array.from({ length: RECENT_ROWS + 3 }, (_, index) => ({
      id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      title: `Viaggio ${index + 1}`,
      status: "ready" as const,
      cost_cents: 100,
      created_at: "2026-09-01T09:00:00Z",
    }));
    mocks.listPlans.mockResolvedValue(many);
    await renderList();
    // The newest is featured, so it is not a row: eight recent rows and the other two folded.
    const more = screen.getByText("Mostra gli altri 2").closest("details") as HTMLDetailsElement;
    expect(more.open).toBe(false);
    expect(more.querySelectorAll("a")).toHaveLength(2);
    expect(screen.queryByRole("heading", { name: "In corso" })).toBeNull();
  });

  it("invites to start from the example when there is no plan", async () => {
    mocks.listPlans.mockResolvedValue([]);
    await renderList();

    expect(screen.getByRole("heading", { name: "Il primo viaggio parte da qui" })).toBeTruthy();
    expect(screen.getByText(/Lisbona a metà aprile, 2 adulti e 2 bambini, 2\.400 €/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Parti da questo esempio" }).getAttribute("href")).toBe("/new?esempio=1");
  });

  it("says the list did not load and tries again", async () => {
    mocks.listPlans.mockRejectedValueOnce(new ApiError({ kind: "network", status: 0 }));
    mocks.listPlans.mockResolvedValueOnce(PLANS);
    await renderList();

    expect(screen.getByText("I piani non si sono caricati")).toBeTruthy();
    expect(screen.getByText(/Non riesco a raggiungere il planner/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Riprova" }));
    });
    expect(mocks.listPlans).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("link", { name: /Lisbona in famiglia/ })).toBeTruthy();
  });

  it("says how long a running plan has been going, where the others say when they began", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    try {
      vi.setSystemTime(Date.parse("2026-10-12T10:05:30Z"));
      mocks.listPlans.mockResolvedValue(PLANS);
      await renderList();
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
      const running = screen.getByRole("link", { name: /Lisbona, 14–18 apr/ });
      // The group heading says "In corso"; the row adds only how long ("da 3 min"), at heading size.
      expect(running.textContent).toContain("da 3 min");
      expect(running.textContent).not.toContain("in corso da");
      expect(running.textContent).not.toContain("Creato");
      expect(running.textContent).not.toContain("Costo");
      // Finished plans keep their timestamp.
      expect(screen.getByRole("link", { name: /Lisbona in famiglia/ }).textContent).toContain("Creato Oggi, 11:18");
    } finally {
      vi.useRealTimers();
    }
  });

  it("reads the list again, quietly, while a plan is running, and stops when none is", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      mocks.listPlans.mockResolvedValueOnce(PLANS);
      await renderList();
      expect(mocks.listPlans).toHaveBeenCalledTimes(1);
      const done = PLANS.map((plan) => ({ ...plan, status: "ready" as const, cost_cents: 51 }));
      mocks.listPlans.mockResolvedValue(done);
      await act(async () => {
        vi.advanceTimersByTime(POLL_MS);
      });
      expect(mocks.listPlans).toHaveBeenCalledTimes(2);
      // No skeleton, no announcement; the running row became a finished one.
      expect(screen.queryByText("Carico i piani…")).toBeNull();
      expect(document.querySelector("[aria-live]")).toBeNull();
      expect(screen.getByRole("link", { name: /Lisbona, 14–18 apr/ }).textContent).toContain("Pronto");
      await act(async () => {
        vi.advanceTimersByTime(POLL_MS * 3);
      });
      expect(mocks.listPlans).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps what it shows when a quiet read fails", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      mocks.listPlans.mockResolvedValueOnce(PLANS);
      await renderList();
      mocks.listPlans.mockRejectedValue(new ApiError({ kind: "network", status: 0 }));
      await act(async () => {
        vi.advanceTimersByTime(POLL_MS);
      });
      expect(screen.queryByText("I piani non si sono caricati")).toBeNull();
      expect(screen.getByRole("link", { name: /Lisbona in famiglia/ })).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });
  describe("the featured plan", () => {
    const featuredOf = () => document.querySelector("[data-featured]") as HTMLElement | null;

    it("is the plan that is running, under 'In corso', and is not repeated in the rows", async () => {
      mocks.listPlans.mockResolvedValue([PLANS[0], PLANS[1]]);
      await renderList();
      const featured = featuredOf();
      expect(featured?.getAttribute("href")).toBe(`/plans/${PLANS[1]?.id}`);
      expect(featured?.textContent).toContain("Lisbona, 14–18 apr");
      expect(screen.getByRole("heading", { level: 2, name: "In corso" })).toBeTruthy();
      expect(screen.getAllByRole("link")).toHaveLength(2);
      expect(featured?.querySelector("[data-plan-title]")?.className).toContain("text-heading");
    });

    it("is the newest ready plan when nothing runs, under 'Ultimo piano pronto'", async () => {
      mocks.listPlans.mockResolvedValue([
        { ...PLANS[0]!, id: "66666666-3b4d-4e5f-8a9b-0c1d2e3f4a5b", status: "failed" },
        PLANS[0],
        { ...PLANS[0]!, id: "77777777-3b4d-4e5f-8a9b-0c1d2e3f4a5b" },
      ]);
      await renderList();
      expect(featuredOf()?.getAttribute("href")).toBe(`/plans/${PLANS[0]?.id}`);
      expect(screen.getByRole("heading", { level: 2, name: "Ultimo piano pronto" })).toBeTruthy();
    });

    it("is not drawn when no plan is running or ready", async () => {
      mocks.listPlans.mockResolvedValue([{ ...PLANS[0]!, status: "failed" }]);
      await renderList();
      expect(featuredOf()).toBeNull();
      expect(screen.getByRole("heading", { level: 2, name: "Recenti" })).toBeTruthy();
    });

    it("leaves no empty list card when it is the only plan", async () => {
      mocks.listPlans.mockResolvedValue([PLANS[0]]);
      await renderList();
      expect(featuredOf()).toBeTruthy();
      expect(screen.queryByRole("heading", { name: "Recenti" })).toBeNull();
    });

    it("has the band's shape (11 rem, 14 rem from 1080 px), a tile while there is no photo, and an empty alt when there is", async () => {
      mocks.getCover.mockResolvedValue(null);
      mocks.listPlans.mockResolvedValue([PLANS[0]]);
      await renderList();
      const frame = featuredOf()?.querySelector("[data-cover]");
      expect(frame?.className).toContain("h-44");
      expect(frame?.className).toContain("lg:h-56");
      expect(frame?.getAttribute("data-cover")).toBe("tile");
      cleanup();
      resetCoverStore();
      mocks.getCover.mockResolvedValue({
        url: "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/Lisboa.jpg/1920px-Lisboa.jpg",
        width: 1920,
        height: 1231,
        author: null,
        license: "CC0",
        license_url: null,
        source_page: "https://commons.wikimedia.org/wiki/File:Lisboa.jpg",
        title: "Lisboa",
      });
      await renderList();
      expect(featuredOf()?.querySelector("img")?.getAttribute("alt")).toBe("");
      // No author: the license stands first.
      expect(screen.getByText(/^Foto:/).textContent).toBe("Foto: CC0, Wikimedia Commons");
    });
  });

  describe("cover photos", () => {
    const COVER: Cover = {
      url: "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/Lisboa.jpg/1920px-Lisboa.jpg",
      width: 1920,
      height: 1231,
      author: "Vitor Oliveira",
      license: "CC BY-SA 2.0",
      license_url: "https://creativecommons.org/licenses/by-sa/2.0",
      source_page: "https://commons.wikimedia.org/wiki/File:Lisboa.jpg",
      title: "Lisboa",
    };

    it("shows a tile with the destination's initial when there is no photo, and no credit note", async () => {
      mocks.listPlans.mockResolvedValue(PLANS);
      await renderList();
      expect(mocks.getCover).toHaveBeenCalledWith(PLANS[0]?.id);
      const tiles = document.querySelectorAll("[data-cover='tile']");
      expect(tiles).toHaveLength(2);
      expect(tiles[0]?.textContent).toBe("L");
      expect(document.querySelector("img")).toBeNull();
      expect(screen.queryByText(/Wikimedia Commons/)).toBeNull();
    });

    it("draws a row's photo as a lazy 4:3 thumbnail with an empty alt text, since the title names the place", async () => {
      mocks.getCover.mockResolvedValue(COVER);
      mocks.listPlans.mockResolvedValue([PLANS[0], { ...PLANS[0]!, id: "55555555-3b4d-4e5f-8a9b-0c1d2e3f4a5b" }]);
      await renderList();
      const thumb = document.querySelector("[data-cover='photo'].aspect-\\[4\\/3\\]");
      const image = thumb?.querySelector("img");
      expect(image?.getAttribute("alt")).toBe("");
      expect(image?.getAttribute("loading")).toBe("lazy");
      expect(image?.getAttribute("referrerpolicy")).toBe("no-referrer");
      expect(image?.getAttribute("src")).toContain("/250px-Lisboa.jpg");
      expect(image?.getAttribute("srcset")).toContain("/500px-Lisboa.jpg 500w");
    });

    it("credits the photos it shows, once each, with the license and the source as links", async () => {
      mocks.getCover.mockResolvedValue(COVER);
      mocks.listPlans.mockResolvedValue([PLANS[0], { ...PLANS[0]!, id: "55555555-3b4d-4e5f-8a9b-0c1d2e3f4a5b" }]);
      await renderList();
      // Two plans, one photo: one credit, written from the cover that was read.
      const credits = screen.getAllByText(/^Foto:/);
      expect(credits).toHaveLength(1);
      expect(credits[0]?.textContent).toBe("Foto: Vitor Oliveira (CC BY-SA 2.0), Wikimedia Commons");
      const license = screen.getByRole("link", { name: "CC BY-SA 2.0" });
      expect(license.getAttribute("href")).toBe(COVER.license_url);
      expect(license.getAttribute("rel")).toBe("noopener noreferrer");
      expect(screen.getByRole("link", { name: "Wikimedia Commons" }).getAttribute("href")).toBe(COVER.source_page);
    });

    it("puts the credits of many different photos in a closed 'Crediti delle foto'", async () => {
      const covers = ["A", "B", "C"].map(
        (name): Cover => ({ ...COVER, author: `Autore ${name}`, source_page: `https://commons.wikimedia.org/wiki/File:${name}.jpg` }),
      );
      mocks.getCover.mockImplementation(async (id: string) => covers[Number(id.slice(0, 1)) - 1] ?? null);
      mocks.listPlans.mockResolvedValue(
        [1, 2, 3].map((n) => ({ ...PLANS[0]!, id: `${n}1111111-3b4d-4e5f-8a9b-0c1d2e3f4a5b` })),
      );
      await renderList();
      const disclosure = screen.getByText("Crediti delle foto (3)").closest("details") as HTMLDetailsElement;
      expect(disclosure.open).toBe(false);
      expect(disclosure.querySelectorAll("li")).toHaveLength(3);
      expect(disclosure.textContent).toContain("Autore B (CC BY-SA 2.0), Wikimedia Commons");
    });

    it("keeps the tile when the photo cannot be read", async () => {
      mocks.getCover.mockRejectedValue(new ApiError({ kind: "network", status: 0 }));
      mocks.listPlans.mockResolvedValue([PLANS[0]]);
      await renderList();
      expect(document.querySelector("[data-cover='tile']")).toBeTruthy();
      expect(screen.getByRole("link", { name: /Lisbona in famiglia/ })).toBeTruthy();
    });

    it("asks for a plan's cover once, however often the list is read again", async () => {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
      try {
        mocks.listPlans.mockResolvedValue(PLANS);
        await renderList();
        await act(async () => {
          vi.advanceTimersByTime(POLL_MS * 2);
        });
        expect(mocks.listPlans.mock.calls.length).toBeGreaterThan(1);
        expect(mocks.getCover).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
