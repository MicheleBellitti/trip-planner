/**
 * The brand's words, decided by Michele (web/PRODUCT.md, "Decisions"): the name on 2026-10-12, the
 * tagline on 2026-10-14. Each is spelled here and nowhere else (components/ui/invariants.test.ts):
 * page metadata, the header lockup, the link preview and the landing read them. The repo and the
 * spec keep their own names.
 */
export const BRAND_NAME = "Atlas";

/** The line of the brand: the landing hero, the metadata, the link preview, the empty plans list. */
export const BRAND_TAGLINE = "Ogni viaggio ha il suo atlante.";

/** Italian articles: a line never ends on one, away from its noun. */
const ARTICLES = new Set(["il", "lo", "la", "i", "gli", "le", "l'", "un", "uno", "una", "un'"]);

/** A line in two, for a fixed-width image (the link preview): before its last article, so "il" stays
 * with "suo atlante." ("Ogni viaggio ha / il suo atlante."); without one, in the middle. */
export function taglineLines(text: string): [string, string] {
  const words = text.split(" ");
  let cut = -1;
  words.forEach((word, index) => {
    if (index > 0 && ARTICLES.has(word.toLocaleLowerCase("it"))) cut = index;
  });
  if (cut < 0) cut = Math.ceil(words.length / 2);
  return [words.slice(0, cut).join(" "), words.slice(cut).join(" ")];
}

/** The page description and the landing's lede (Italian, sentence case). */
export const BRAND_DESCRIPTION =
  "Da Milano a Lisbona in un pomeriggio di lavoro, fatto da altri. Cinque agenti AI tracciano voli, alloggio, attività e spostamenti, e ti lasciano un piano con le date entro cui prenotare.";

/** The production origin: absolute URLs in metadata (the link preview image) start here. */
export const BRAND_URL = "https://atlas.bellittim.com";
