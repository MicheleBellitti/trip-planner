"use client";

/**
 * The cover at the top of the finished plan (DESIGN.md, "Cover photos"): the destination's photo
 * in a band of fixed height, a plate with the destination over its lower corner, and the credit
 * the license requires under it.
 *
 * - The band's height is fixed (8 rem on the phone, 18 rem from 1080 px), the photo fills it
 *   with `object-cover` kept on the skyline (a little above the middle, where a city photo has its
 *   roofs), and `width`/`height` of the file are on the `<img>`: nothing moves when
 *   the photo arrives. While the answer is on its way the band is a tinted block of the same
 *   size. When the destination has no photo, or the file does not load, the band is not drawn
 *   (the plan reads as it did before covers).
 * - The text over the photo sits on a plate, `surface` with `ink` text and a `rule` edge, so its
 *   contrast is the tokens' (measured in both themes) whatever the picture is; a scrim of the
 *   theme's own `--scrim` token darkens the foot of the photo so the plate sits on calmer ground.
 *   The plate is decorative for a screen reader: the picture's alt text names the place.
 * - The credit (author, license, source) is a caption under the photo, plain text with two links.
 */

import { useState } from "react";

import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { Skeleton } from "@/components/ui/skeleton";

import { coverSources } from "./cover-sources";
import { useCover, type CoverLoader } from "./cover-store";
import { CoverCredit } from "./credit-line";

/** The frame: also the loading block, so the photo's arrival moves nothing. 8 rem on the phone, so
 * "Da prenotare" stays in the first screen; 18 rem from 1080 px. */
const FRAME = "relative h-32 overflow-hidden rounded-md border border-rule bg-notice-wash lg:h-72";

/** What the band asks for: the phone (360 px at 3x), a laptop, a wide screen. */
const BAND_WIDTHS = [960, 1280, 1920] as const;
const BAND_SIZES = "(min-width: 67.5rem) 1426px, 100vw";

interface CoverBandProps {
  planId: string;
  /** The destination as the plan states it ("Lisbona, Portogallo"): the alt text and the plate. */
  destination: string;
  /** How to read the cover; defaults to the planner API. Pass a stable function. */
  loadCover?: CoverLoader;
  className?: string;
}

export function CoverBand({ planId, destination, loadCover, className }: CoverBandProps) {
  const state = useCover(planId, true, loadCover);
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);

  if (state.kind === "none" || broken) return null;

  if (state.kind !== "ready") {
    // Idle or loading: hold the place. Decorative, so nothing is announced.
    return (
      <div aria-hidden="true" className={cx(FRAME, className)}>
        <Skeleton shape="block" className="size-full rounded-none" />
      </div>
    );
  }

  const { cover } = state;
  const sources = coverSources(cover, BAND_WIDTHS);
  return (
    <figure data-cover="band" className={cx("m-0 min-w-0", className)}>
      <div className={FRAME}>
        {/* A plain <img>: a sized thumbnail from Wikimedia's own cache (see CoverThumb). */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={sources.src}
          srcSet={sources.srcSet}
          sizes={BAND_SIZES}
          width={cover.width}
          height={cover.height}
          alt={destination}
          decoding="async"
          fetchPriority="low"
          referrerPolicy="no-referrer"
          onLoad={() => setLoaded(true)}
          onError={() => setBroken(true)}
          className={cx(
            "absolute inset-0 size-full object-cover object-[50%_42%] transition-opacity duration-(--duration-arrive) ease-out motion-reduce:duration-(--duration-reduced)",
            loaded ? "opacity-100" : "opacity-0",
          )}
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 h-3/5 bg-linear-to-t from-(--scrim) to-transparent"
        />
        <span
          aria-hidden="true"
          className="absolute bottom-3 left-3 flex max-w-[calc(100%-1.5rem)] items-center gap-2 rounded-sm border border-rule bg-surface px-3 py-1.5 text-ink"
        >
          <Icon name="map-pin" size={17} className="shrink-0" />
          <span className="min-w-0 font-cond text-title font-semibold [overflow-wrap:anywhere]">{destination}</span>
        </span>
      </div>
      <figcaption className="mt-2">
        <CoverCredit cover={cover} />
      </figcaption>
    </figure>
  );
}
