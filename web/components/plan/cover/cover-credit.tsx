"use client";

import { cx } from "@/components/ui/cx";
import { Disclosure } from "@/components/ui/disclosure";

import { useShownCovers } from "./cover-store";
import { CoverCredit, CreditText } from "./credit-line";

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
