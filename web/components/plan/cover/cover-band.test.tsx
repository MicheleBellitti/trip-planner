import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Cover } from "@/lib/schemas/api";

import { CoverBand } from "./cover-band";
import { resetCoverStore } from "./cover-store";

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

beforeEach(() => resetCoverStore());
afterEach(() => cleanup());

async function renderBand(load: () => Promise<Cover | null>) {
  await act(async () => {
    render(<CoverBand planId="plan-1" destination="Lisbona, Portogallo" loadCover={load} />);
  });
}

describe("CoverBand", () => {
  it("draws the photo with its size, alt text and the destination plate", async () => {
    await renderBand(async () => COVER);
    const image = screen.getByRole("img", { name: "Lisbona, Portogallo" });
    expect(image.getAttribute("width")).toBe("1920");
    expect(image.getAttribute("height")).toBe("1231");
    expect(image.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(image.getAttribute("srcset")).toContain("/960px-Lisboa.jpg 960w");
    // The plate repeats the place for sighted readers and is hidden from screen readers.
    const plate = screen.getByText("Lisbona, Portogallo", { selector: "span" });
    expect(plate.closest("[aria-hidden='true']")).toBeTruthy();
  });

  it("shows the required credit under the photo: author, license link, source link", async () => {
    await renderBand(async () => COVER);
    const caption = document.querySelector("figcaption");
    expect(caption?.textContent).toBe("Foto: Vitor Oliveira (CC BY-SA 2.0), Wikimedia Commons");
    const license = screen.getByRole("link", { name: "CC BY-SA 2.0" });
    expect(license.getAttribute("href")).toBe(COVER.license_url);
    const source = screen.getByRole("link", { name: "Wikimedia Commons" });
    expect(source.getAttribute("href")).toBe(COVER.source_page);
    for (const link of [license, source]) {
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    }
  });

  it("reserves the frame's size while the answer is on its way", () => {
    const html = renderToString(<CoverBand planId="plan-1" destination="Lisbona" loadCover={() => new Promise(() => {})} />);
    // 8 rem on the phone (so "Da prenotare" stays in the first screen), 18 rem from 1080 px.
    expect(html).toContain("h-32");
    expect(html).toContain("lg:h-72");
    expect(html).not.toContain("<img");
  });

  it("draws nothing when the destination has no photo", async () => {
    await renderBand(async () => null);
    expect(document.body.querySelector("figure")).toBeNull();
    expect(document.body.textContent).toBe("");
  });

  it("draws nothing when the read fails", async () => {
    await renderBand(async () => {
      throw new Error("offline");
    });
    expect(document.body.textContent).toBe("");
  });

  it("takes the band and the credit away when the file does not load", async () => {
    await renderBand(async () => COVER);
    fireEvent.error(screen.getByRole("img", { name: "Lisbona, Portogallo" }));
    expect(screen.queryByRole("img")).toBeNull();
    expect(document.querySelector("figcaption")).toBeNull();
  });
});
