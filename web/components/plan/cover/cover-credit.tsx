"use client";

import { cx } from "@/components/ui/cx";
import { Disclosure } from "@/components/ui/disclosure";
import type { Cover } from "@/lib/schemas/api";

import { coverCreditLine, type CreditPart } from "./cover-sources";
import { useShownCovers } from "./cover-store";

function CreditPartText({ part }: { part: CreditPart }) {
  return part.href ? (
    <a href={part.href} target="_blank" rel="noopener noreferrer" className="underline hover:text-ink">
      {part.text}
    </a>
  ) : (
    <>{part.text}</>
  );
}

/** "Autore (CC BY-SA 2.0), Wikimedia Commons", without "Foto: ": the license and the source are
 * links (new tab, no referrer). Without an author the license stands first: "CC0, Wikimedia
 * Commons". */
function CreditText({ cover }: { cover: Cover }) {
  const { author, license, source } = coverCreditLine(cover);
  return (
    <>
      {author ? (
        <>
          {author} (<CreditPartText part={license} />)
        </>
      ) : (
        <CreditPartText part={license} />
      )}
      , <CreditPartText part={source} />
    </>
  );
}

/** The photo's credit, under it: "Foto: Autore (CC BY-SA 4.0), Wikimedia Commons". This line is
 * what CC BY and CC BY-SA ask for, so it is never cut and never hidden. */
export function CoverCredit({ cover, className }: { cover: Cover; className?: string }) {
  return (
    <p className={cx("text-micro text-ink-2 [overflow-wrap:anywhere]", className)}>
      Foto: <CreditText cover={cover} />
    </p>
  );
}

/** Up to this many different photos on the home list are credited in plain sight; more are
 * credited in a disclosure, closed, so a long list does not grow a paragraph of names. */
const INLINE_CREDITS = 2;

/**
 * The credit of the photos the home list shows (thumbnails are too small to carry it), written
 * from the covers actually on screen, each photo once: "Foto: Vitor Oliveira (CC BY-SA 2.0),
 * Wikimedia Commons". With more than two different photos the lines sit in a closed "Crediti
 * delle foto". Nothing while no row has a photo.
 */
export function CoverCreditNote({ planIds, className }: { planIds: readonly string[]; className?: string }) {
  const covers = useShownCovers(planIds);
  if (covers.length === 0) return null;
  if (covers.length <= INLINE_CREDITS) {
    return (
      <div className={cx("space-y-0.5", className)}>
        {covers.map((cover) => (
          <CoverCredit key={cover.source_page} cover={cover} />
        ))}
      </div>
    );
  }
  return (
    <Disclosure summary={`Crediti delle foto (${covers.length})`} className={cx("text-micro", className)}>
      <ul className="m-0 list-none space-y-1 p-0 text-micro">
        {covers.map((cover) => (
          <li key={cover.source_page} className="[overflow-wrap:anywhere]">
            <CreditText cover={cover} />
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}
