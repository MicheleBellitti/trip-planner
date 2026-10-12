import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Cover } from "@/lib/schemas/api";

import { CoverFeature } from "./cover-feature";
import { requestCover, resetCoverStore } from "./cover-store";

const COVER: Cover = {
  url: "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/Lisboa.jpg/1920px-Lisboa.jpg",
  width: 1920,
  height: 1231,
  author: null,
  license: "CC0",
  license_url: null,
  source_page: "https://commons.wikimedia.org/wiki/File:Lisboa.jpg",
  title: "Lisboa",
};

const mocks = vi.hoisted(() => ({ getCover: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { getCover: mocks.getCover } }));

beforeEach(() => {
  mocks.getCover.mockReset();
  mocks.getCover.mockResolvedValue(null);
  resetCoverStore();
});
afterEach(() => cleanup());

describe("CoverFeature", () => {
  it("is the band's shape, 11 rem and 14 rem from 1080 px, with a tile under the photo from the start", () => {
    const { container } = render(<CoverFeature planId="plan-1" destination="Lisbona" />);
    const frame = container.querySelector("[data-cover]") as HTMLElement;
    expect(frame.className).toContain("h-44");
    expect(frame.className).toContain("lg:h-56");
    expect(frame.getAttribute("data-cover")).toBe("tile");
    expect(frame.textContent).toBe("L");
  });

  it("draws the photo with its size, sized srcset and an empty alt text (the card's title names the place)", async () => {
    requestCover("plan-1", async () => COVER);
    const { container } = render(<CoverFeature planId="plan-1" destination="Lisbona" />);
    await act(async () => {});
    const image = container.querySelector("img") as HTMLImageElement;
    expect(image.getAttribute("alt")).toBe("");
    expect(image.getAttribute("width")).toBe("1920");
    expect(image.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(image.getAttribute("srcset")).toContain("/960px-Lisboa.jpg 960w");
    expect(image.className).toContain("object-[50%_42%]");
  });

  it("falls back to the tile when the file does not load", async () => {
    requestCover("plan-1", async () => COVER);
    const { container } = render(<CoverFeature planId="plan-1" destination="Lisbona" />);
    await act(async () => {});
    fireEvent.error(container.querySelector("img") as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-cover='tile']")).toBeTruthy();
  });
});
