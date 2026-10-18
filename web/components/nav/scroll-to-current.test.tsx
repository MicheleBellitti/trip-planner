import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScrollToCurrent } from "./scroll-to-current";

afterEach(() => {
  cleanup();
  // The tests shadow jsdom's Element.prototype.scrollLeft to see what the strip is told.
  delete (HTMLElement.prototype as { scrollLeft?: number }).scrollLeft;
});

function rect(left: number, width: number): DOMRect {
  return { left, right: left + width, width, top: 0, bottom: 44, height: 44, x: left, y: 0, toJSON: () => ({}) } as DOMRect;
}

/** The header's strip: two stations, the second one current. */
function strip() {
  render(
    <nav data-testid="strip">
      <ul>
        <li>
          <a href="#piani">Piani</a>
        </li>
        <li>
          <a href="#inviti" aria-current="page">
            Inviti
          </a>
        </li>
      </ul>
      <ScrollToCurrent />
    </nav>,
  );
}

describe("ScrollToCurrent", () => {
  it("scrolls only the strip sideways to the current station, never the window", () => {
    // A 200 px strip at x = 100; the current station is 80 px wide at x = 340 before scrolling.
    let scrollLeft = 0;
    const set = vi.fn((value: number) => (scrollLeft = value));
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.tagName === "NAV") return rect(100, 200);
      if (this.getAttribute("aria-current") === "page") return rect(340 - scrollLeft, 80);
      return rect(0, 0);
    });
    Object.defineProperty(HTMLElement.prototype, "scrollLeft", {
      configurable: true,
      get: () => scrollLeft,
      set,
    });
    const intoView = vi.fn();
    Element.prototype.scrollIntoView = intoView;
    const windowScroll = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);

    strip();

    // 340 + 80 = 420 is 120 px past the strip's right edge (300): the strip moves 120 px.
    expect(set).toHaveBeenCalledWith(120);
    expect(intoView).not.toHaveBeenCalled();
    expect(windowScroll).not.toHaveBeenCalled();
  });

  it("leaves the strip alone when the current station is already in view", () => {
    const set = vi.fn();
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.tagName === "NAV") return rect(100, 200);
      if (this.getAttribute("aria-current") === "page") return rect(150, 80);
      return rect(0, 0);
    });
    Object.defineProperty(HTMLElement.prototype, "scrollLeft", { configurable: true, get: () => 0, set });

    strip();

    expect(set).not.toHaveBeenCalled();
  });
});
