"use client";

/**
 * The home list's cover: a fixed-aspect thumbnail of the plan's destination (DESIGN.md, "Cover
 * photos"). It asks for the photo only when it comes near the viewport, and until the photo is
 * there, and for good when the destination has none, it is a quiet tinted tile with the
 * destination's initial, so the row is the same size and shape in every case and nothing moves
 * when a photo arrives. The photo has an empty alt text: the row's title names the place. The
 * credit is not here: the plan page carries it under the photo, and the list credits the photos it
 * shows, once each (`CoverCreditNote`).
 */

import { useState } from "react";

import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";

import { coverSources, destinationInitial } from "./cover-sources";
import { useCover, type CoverLoader } from "./cover-store";
import { useNearView } from "./use-near-view";

/** What the thumbnail asks for at 1x and 2x/3x: the list never draws it wider than 7 rem. */
const ASKED_WIDTHS = [250, 500] as const;
const THUMB_SIZES = "(min-width: 67.5rem) 6rem, 4.5rem";

interface CoverThumbProps {
  planId: string;
  /** The destination as the row names it: the tile's initial (the photo is decorative, the row's
   * title says where it is). */
  destination: string;
  /** Size and place (the caller sets the width; the aspect is fixed here, 4:3). */
  className?: string;
  /** Where the photo comes from (GET /plans/{id}/cover on the plans list); none, the tile. */
  loadCover?: CoverLoader;
}

export function CoverThumb({ planId, destination, className, loadCover }: CoverThumbProps) {
  const { ref, near } = useNearView<HTMLSpanElement>();
  const state = useCover(planId, near, loadCover);
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const initial = destinationInitial(destination);
  const cover = state.kind === "ready" && !broken ? state.cover : null;
  const sources = cover ? coverSources(cover, ASKED_WIDTHS) : null;

  return (
    <span
      ref={ref}
      data-cover={cover ? "photo" : "tile"}
      className={cx(
        "relative block aspect-[4/3] shrink-0 overflow-hidden rounded-sm border border-rule bg-notice-wash",
        className,
      )}
    >
      {/* The tile stays under the photo: it is what shows while the photo loads. */}
      <span aria-hidden="true" className="absolute inset-0 grid place-items-center text-ink-2">
        {initial ? (
          <span className="font-cond text-heading font-semibold">{initial}</span>
        ) : (
          <Icon name="map-pin" size={20} />
        )}
      </span>
      {cover && sources ? (
        // A plain <img>: the photo is already a sized thumbnail from Wikimedia's own cache, so
        // next/image's optimizer would only add a hop (and a bill) in front of it. No referrer: the
        // page's address carries a plan id.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={sources.src}
          srcSet={sources.srcSet}
          sizes={THUMB_SIZES}
          width={cover.width}
          height={cover.height}
          // Decorative: the row's title names the place, so a screen reader hears it once.
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={() => setLoaded(true)}
          onError={() => setBroken(true)}
          className={cx(
            "absolute inset-0 size-full object-cover transition-opacity duration-(--duration-arrive) ease-out motion-reduce:duration-(--duration-reduced)",
            loaded ? "opacity-100" : "opacity-0",
          )}
        />
      ) : null}
    </span>
  );
}
