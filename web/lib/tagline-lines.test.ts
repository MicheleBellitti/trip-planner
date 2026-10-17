import { describe, expect, it } from "vitest";

import { BRAND_TAGLINE } from "./brand";
import { taglineLines } from "./tagline-lines";

describe("taglineLines", () => {
  it("breaks the tagline before its article, never between the article and its noun", () => {
    expect(taglineLines(BRAND_TAGLINE)).toEqual(["Ogni viaggio ha", "il suo atlante."]);
  });

  it("splits a line without an article in the middle", () => {
    expect(taglineLines("Una frase senza articoli qui")).toEqual(["Una frase senza", "articoli qui"]);
  });
});
