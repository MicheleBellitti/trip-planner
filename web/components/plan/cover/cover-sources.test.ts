import { describe, expect, it } from "vitest";

import type { Cover } from "@/lib/schemas/api";

import { coverCredit, coverCreditLine, coverSources, destinationFromTitle, destinationInitial, uniqueCovers } from "./cover-sources";

const COVER: Cover = {
  url: "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/Lisboa_-_Portugal_%2852597836992%29.jpg/1920px-Lisboa_-_Portugal_%2852597836992%29.jpg",
  width: 1920,
  height: 1231,
  author: "Vitor Oliveira from Torres Vedras, PORTUGAL",
  license: "CC BY-SA 2.0",
  license_url: "https://creativecommons.org/licenses/by-sa/2.0",
  source_page: "https://commons.wikimedia.org/wiki/File:Lisboa_-_Portugal_(52597836992).jpg",
  title: "Lisboa - Portugal (52597836992)",
};

describe("coverSources", () => {
  it("asks Wikimedia for the smaller sizes of the same thumbnail, smallest first", () => {
    const { src, srcSet } = coverSources(COVER, [250, 500]);
    const base = "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/Lisboa_-_Portugal_%2852597836992%29.jpg";
    expect(src).toBe(`${base}/250px-Lisboa_-_Portugal_%2852597836992%29.jpg`);
    expect(srcSet).toBe(
      `${base}/250px-Lisboa_-_Portugal_%2852597836992%29.jpg 250w, ` +
        `${base}/500px-Lisboa_-_Portugal_%2852597836992%29.jpg 500w, ${COVER.url} 1920w`,
    );
  });

  it("never asks for a width Wikimedia does not serve or the photo does not have", () => {
    const small = { ...COVER, width: 960 };
    const { srcSet } = coverSources(small, [250, 640, 960, 1280]);
    expect(srcSet).toContain("/250px-");
    expect(srcSet).not.toContain("/640px-");
    expect(srcSet).not.toContain("/1280px-");
    // 960 is the file the backend sent: it is the last entry, not a rewritten URL.
    expect(srcSet?.endsWith(`${small.url} 960w`)).toBe(true);
  });

  it("leaves an original file (not a thumbnail URL) alone", () => {
    const original = { ...COVER, url: "https://upload.wikimedia.org/wikipedia/commons/f/f2/Lisboa.jpg", width: 800 };
    expect(coverSources(original, [250, 500])).toEqual({ src: original.url, srcSet: undefined });
  });
});

describe("coverCredit", () => {
  it("names the author, links the license and the Commons page", () => {
    expect(coverCredit(COVER)).toEqual([
      { text: "Vitor Oliveira from Torres Vedras, PORTUGAL" },
      { text: "CC BY-SA 2.0", href: "https://creativecommons.org/licenses/by-sa/2.0" },
      { text: "Wikimedia Commons", href: COVER.source_page },
    ]);
  });

  it("copes with no author and no license link (public domain)", () => {
    const parts = coverCredit({ ...COVER, author: null, license: "Public domain", license_url: null });
    expect(parts).toEqual([{ text: "Public domain" }, { text: "Wikimedia Commons", href: COVER.source_page }]);
  });

  it("collapses the whitespace of an author's name", () => {
    expect(coverCredit({ ...COVER, author: "  Ana \n  Silva " })[0]).toEqual({ text: "Ana Silva" });
  });
});

describe("coverCreditLine", () => {
  it("keeps the author apart from the license and the source, so a screen can set them as it likes", () => {
    expect(coverCreditLine(COVER)).toEqual({
      author: "Vitor Oliveira from Torres Vedras, PORTUGAL",
      license: { text: "CC BY-SA 2.0", href: "https://creativecommons.org/licenses/by-sa/2.0" },
      source: { text: "Wikimedia Commons", href: COVER.source_page },
    });
    expect(coverCreditLine({ ...COVER, author: "  " }).author).toBeNull();
  });
});

describe("uniqueCovers", () => {
  it("keeps each photo once, by its Commons page, in the order it was first seen", () => {
    const other = { ...COVER, source_page: "https://commons.wikimedia.org/wiki/File:Other.jpg" };
    expect(uniqueCovers([COVER, other, { ...COVER }, other])).toEqual([COVER, other]);
    expect(uniqueCovers([])).toEqual([]);
  });
});

describe("destination names", () => {
  it("takes the title up to its first comma", () => {
    expect(destinationFromTitle("Lisbona in famiglia, 14–18 aprile 2027")).toBe("Lisbona in famiglia");
    expect(destinationFromTitle("Lisbona")).toBe("Lisbona");
    expect(destinationFromTitle(", 14–18 apr")).toBe(", 14–18 apr");
  });

  it("makes an initial, or nothing when the name has no letter", () => {
    expect(destinationInitial("lisbona")).toBe("L");
    expect(destinationInitial("  Èvora")).toBe("È");
    expect(destinationInitial("--")).toBeNull();
  });
});
