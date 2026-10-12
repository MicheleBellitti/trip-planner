/**
 * Pure helpers of a destination cover (GET /plans/{id}/cover): the image sizes to ask Wikimedia
 * for, the credit line the licenses require, and the destination names the screens print. No
 * React, no I/O.
 */

import type { Cover } from "@/lib/schemas/api";

/** `https://upload.wikimedia.org/.../thumb/a/ab/File.jpg/1920px-File.jpg`: the host, the path up to
 * the width, the width, the rest of the file name. */
const THUMB = /^(https:\/\/upload\.wikimedia\.org\/.+\/thumb\/.+\/)(\d+)(px-[^/?#]+)$/;

/** The widths Wikimedia serves from its thumbnail cache (anything else is an HTTP 400). */
export const THUMB_WIDTHS = [250, 330, 500, 960, 1280, 1920] as const;

export interface CoverSources {
  /** The `src`: the smallest size in the list, for a browser that ignores `srcset`. */
  src: string;
  /** `srcset`, or undefined when the cover is not a thumbnail URL (the original file, which the
   * backend returns for a small image: there is nothing else to ask for). */
  srcSet: string | undefined;
}

/** The cover at each of `widths` that the photo can give (never wider than the file the backend
 * sent). `widths` must come from THUMB_WIDTHS. */
export function coverSources(cover: Cover, widths: readonly number[]): CoverSources {
  const match = THUMB.exec(cover.url);
  if (!match) return { src: cover.url, srcSet: undefined };
  const [, base = "", , rest = ""] = match;
  const usable = widths.filter((width) => width < cover.width && THUMB_WIDTHS.some((known) => known === width));
  // Everything the photo can give: the sizes below its own width, then the file the backend sent.
  const entries = [...usable.map((width) => ({ url: `${base}${width}${rest}`, width })), { url: cover.url, width: cover.width }];
  return {
    src: entries[0]?.url ?? cover.url,
    srcSet: entries.map((entry) => `${entry.url} ${entry.width}w`).join(", "),
  };
}

/** The part of a plan's title before its first comma: "Lisbona in famiglia, 14–18 aprile 2027"
 * names the place first. It stands in for the destination where only the title is known (the home
 * list). */
export function destinationFromTitle(title: string): string {
  const head = title.split(",")[0]?.trim();
  return head || title.trim();
}

/** The initial of a destination, for the tile that stands in for a missing photo; null when the
 * name has no letter or digit to show. */
export function destinationInitial(name: string): string | null {
  const match = /[\p{L}\p{N}]/u.exec(name);
  return match ? match[0].toLocaleUpperCase("it-IT") : null;
}

export interface CreditPart {
  text: string;
  /** Present for the parts that link (the license text, the file page). */
  href?: string;
}

/** What the license asks to show next to the photo, kept apart so a screen can set it as it likes. */
export interface CreditLine {
  /** The author as plain text; null for a public-domain file with none. */
  author: string | null;
  /** The license's short name, linked to its text when there is one. */
  license: CreditPart;
  /** "Wikimedia Commons", linked to the file's page. */
  source: CreditPart;
}

export function coverCreditLine(cover: Cover): CreditLine {
  const author = cover.author?.replace(/\s+/g, " ").trim() || null;
  return {
    author,
    license: cover.license_url ? { text: cover.license, href: cover.license_url } : { text: cover.license },
    source: { text: "Wikimedia Commons", href: cover.source_page },
  };
}

/**
 * The same as a flat list, "Foto: " before it, which reads as a comma-separated line: the author,
 * the license (linked to its text when there is one) and the source (linked to the file's page on
 * Commons). A public-domain file can have no author.
 */
export function coverCredit(cover: Cover): CreditPart[] {
  const { author, license, source } = coverCreditLine(cover);
  return [...(author ? [{ text: author }] : []), license, source];
}

/** The credits of the photos a screen shows, each photo once (a destination planned five times
 * shows one photo five times: the credit is for the photo, not the row). Order of first sight. */
export function uniqueCovers(covers: readonly Cover[]): Cover[] {
  const seen = new Set<string>();
  const unique: Cover[] = [];
  for (const cover of covers) {
    if (seen.has(cover.source_page)) continue;
    seen.add(cover.source_page);
    unique.push(cover);
  }
  return unique;
}
