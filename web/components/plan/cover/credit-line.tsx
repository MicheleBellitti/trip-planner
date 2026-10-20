/**
 * The words of a photo's credit, as the licenses ask for them: shared by the plan's cover, the
 * home list's note and the choice cards. No hooks and no store, so a card can show it without
 * pulling in the covers' reader.
 */

import { cx } from "@/components/ui/cx";
import type { Cover } from "@/lib/schemas/api";

import { coverCreditLine, type CreditPart } from "./cover-sources";

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
export function CreditText({ cover }: { cover: Cover }) {
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

/** The photo's credit: "Foto: Autore (CC BY-SA 4.0), Wikimedia Commons". This line is what CC BY
 * and CC BY-SA ask for, so it is never cut: under the plan's cover it is never hidden either, and
 * a choice card shows it from a button on its photo (DESIGN.md, "Choice cards"). */
export function CoverCredit({ cover, className }: { cover: Cover; className?: string }) {
  return (
    <p className={cx("text-micro text-ink-2 [overflow-wrap:anywhere]", className)}>
      Foto: <CreditText cover={cover} />
    </p>
  );
}
