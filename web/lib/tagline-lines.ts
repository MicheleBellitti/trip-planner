/**
 * The tagline in two lines for the link preview (app/opengraph-image.tsx). Apart from lib/brand.ts
 * so the pages that read the brand's words in the browser do not ship it.
 */

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
