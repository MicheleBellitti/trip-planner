"use client";

/**
 * The photo of the home list's featured plan (DESIGN.md, "Cover photos"): the plan page's band
 * shape, 11 rem tall on the phone and 14 rem from 1080 px, filling the top of its card. As in the
 * thumbnails, a `notice-wash` tile with the destination's initial is under the photo from the
 * start, so the card is the same size while the answer is on its way and when there is none, and
 * the photo only fades in over it. The photo is decorative (empty alt): the card's title names the
 * place. The credit is the list's (`CoverCreditNote`).
 */

import { useState } from "react";

import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";

import { coverSources, destinationInitial } from "./cover-sources";
import { useCover } from "./cover-store";

/** The card's width is the phone's (up to 24 rem) or the right column's (22 rem). */
const WIDTHS = [500, 960, 1280] as const;
const SIZES = "(min-width: 80rem) 22rem, (min-width: 67.5rem) 64rem, 100vw";

export function CoverFeature({
  planId,
  destination,
  className,
}: {
  planId: string;
  destination: string;
  className?: string;
}) {
  const state = useCover(planId, true);
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const cover = state.kind === "ready" && !broken ? state.cover : null;
  const sources = cover ? coverSources(cover, WIDTHS) : null;
  const initial = destinationInitial(destination);

  return (
    <span
      data-cover={cover ? "photo" : "tile"}
      className={cx("relative block h-44 overflow-hidden bg-notice-wash lg:h-56", className)}
    >
      <span aria-hidden="true" className="absolute inset-0 grid place-items-center text-ink-2">
        {initial ? (
          <span className="font-cond text-display font-semibold">{initial}</span>
        ) : (
          <Icon name="map-pin" size={20} />
        )}
      </span>
      {cover && sources ? (
        // A plain <img>, as the other covers: Wikimedia serves the sizes from its own cache.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={sources.src}
          srcSet={sources.srcSet}
          sizes={SIZES}
          width={cover.width}
          height={cover.height}
          alt=""
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={() => setLoaded(true)}
          onError={() => setBroken(true)}
          className={cx(
            "absolute inset-0 size-full object-cover object-[50%_42%] transition-opacity duration-(--duration-arrive) ease-out motion-reduce:duration-(--duration-reduced)",
            loaded ? "opacity-100" : "opacity-0",
          )}
        />
      ) : null}
    </span>
  );
}
