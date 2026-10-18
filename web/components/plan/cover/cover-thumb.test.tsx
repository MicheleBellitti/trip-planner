import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Cover } from "@/lib/schemas/api";

import { requestCover, resetCoverStore } from "./cover-store";
import { CoverThumb } from "./cover-thumb";

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

beforeEach(() => {
  mocks.getCover.mockReset();
  resetCoverStore();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CoverThumb", () => {
  it("does not ask for the photo until it comes near the viewport", async () => {
    let callback: IntersectionObserverCallback = () => {};
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: IntersectionObserverCallback) {
          callback = cb;
        }
        observe() {}
        disconnect() {}
      },
    );
    mocks.getCover.mockResolvedValue(COVER);
    const { container } = render(<CoverThumb planId="plan-1" destination="Lisbona" loadCover={mocks.getCover} />);
    expect(mocks.getCover).not.toHaveBeenCalled();
    expect(container.querySelector("[data-cover='tile']")?.textContent).toBe("L");
    expect(container.querySelector("img")).toBeNull();

    await act(async () => {
      callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    });
    expect(mocks.getCover).toHaveBeenCalledWith("plan-1");
    expect(container.querySelector("img")).toBeTruthy();
  });

  it("is decorative: an empty alt text, because the row's title names the place", async () => {
    requestCover("plan-1", async () => COVER);
    const { container } = render(<CoverThumb planId="plan-1" destination="Lisbona" loadCover={mocks.getCover} />);
    await act(async () => {});
    expect(container.querySelector("img")?.getAttribute("alt")).toBe("");
  });

  it("falls back to the tile when the file does not load", async () => {
    requestCover("plan-1", async () => COVER);
    const { container } = render(<CoverThumb planId="plan-1" destination="Lisbona" loadCover={mocks.getCover} />);
    await act(async () => {});
    const image = container.querySelector("img");
    expect(image).toBeTruthy();
    fireEvent.error(image as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-cover='tile']")?.textContent).toBe("L");
  });

  it("shows a pin instead of an initial when the name has no letter", () => {
    const { container } = render(<CoverThumb planId="plan-1" destination="--" loadCover={mocks.getCover} />);
    expect(container.querySelector("svg")).toBeTruthy();
  });
});
