"use client";

/**
 * One option of the traveller's choice (DESIGN.md, "Choice cards"): a native checkbox (several
 * picks) or radio (one) drawn as a card, photo on top, then the title, the reason and the facts.
 *
 * - The input is visually hidden and its label stretches over the whole card (the `after:inset-0`
 *   of AgentLane's header), so a tap anywhere on the card picks it; the reason and the facts
 *   describe the input, so a screen reader hears them on Tab too. The card draws the focus ring
 *   while the input has keyboard focus.
 * - Picked, the card gets a 2 px ink inset ring and its tick roundel fills: an overlay ring, so
 *   nothing moves. Nothing animates but the photo's slow zoom on hover (motion-safe only).
 * - The photo's credit sits behind its own button on the photo (decision 1 of the plan), named
 *   after the option ("Crediti della foto: Oceanário de Lisboa"): the button and the credit's
 *   links sit above the label's overlay and outside the label, so they never pick the card. The
 *   photo follows the label in the DOM and is drawn first (`order-first`), so Tab reaches the card,
 *   then its credit; the photo lets clicks through to the label, but for its credit. A photo that
 *   does not load leaves the tile, and its credit goes with it.
 * - Local state only for the credit and a broken photo: the selection is the caller's.
 */

import { useId, useState } from "react";

import { coverSources, destinationInitial, THUMB_WIDTHS } from "@/components/plan/cover/cover-sources";
import { CoverCredit } from "@/components/plan/cover/credit-line";
import type { ChoiceOptionView } from "@/lib/choices";
import { formatDuration, formatPrice } from "@/lib/format";

import { Chip } from "./chip";
import { cx } from "./cx";
import { Icon, type IconName } from "./icon";
import { IconButton } from "./icon-button";
import { VisuallyHidden } from "./visually-hidden";

/** What the photo is drawn at: at most a third of the panel's 64rem grid from 1080 px (three
 * columns), half the page below (two). */
const PHOTO_SIZES = "(min-width: 67.5rem) 21rem, 50vw";

const RATIOS = { "4/3": "aspect-[4/3]", "16/10": "aspect-[16/10]" } as const;

export type ChoiceCardMedia = keyof typeof RATIOS | "none";

interface ChoiceCardProps {
  option: ChoiceOptionView;
  /** `checkbox` (several picks) or `radio` (one); `name` groups the radios of one question. */
  control: "checkbox" | "radio";
  name: string;
  checked: boolean;
  /** Rests the card: the input is disabled and the photo does not zoom. The card keeps its full
   * opacity, so its words still read. */
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  /** The photo's frame, the same for every card of a question: 4:3, or 16:10 for food. `none`
   * when no option of the question has a photo: no photo area at all (a tile is not a photo). */
  media: ChoiceCardMedia;
  /** Layout only (grid placement, margins). */
  className?: string;
}

interface Fact {
  icon: IconName;
  /** Read before the value by screen readers only: the chip shows the value alone. */
  label: string;
  value: string;
}

/** The chips: duration, price for the party, area. An unknown value has no chip, and a missing
 * price is never "gratis" (it means "not checked" as often as "free"). */
function facts(option: ChoiceOptionView): Fact[] {
  const list: Fact[] = [];
  if (option.durationMin !== null) {
    list.push({ icon: "clock", label: "Durata: ", value: formatDuration(option.durationMin) });
  }
  if (option.price) {
    const { amountCents, currency } = option.price;
    list.push({ icon: "wallet", label: "Prezzo per il gruppo: ", value: formatPrice({ amount_cents: amountCents, currency }) });
  }
  if (option.area) list.push({ icon: "map-pin", label: "Zona: ", value: option.area });
  return list;
}

export function ChoiceCard({
  option,
  control,
  name,
  checked,
  disabled = false,
  onChange,
  media,
  className,
}: ChoiceCardProps) {
  const [broken, setBroken] = useState(false);
  const [creditOpen, setCreditOpen] = useState(false);
  const id = useId();
  const detailsId = `${id}-dettagli`;
  const creditId = `${id}-crediti`;
  const photo = media !== "none" && !broken ? option.photo : null;
  const sources = photo ? coverSources(photo, THUMB_WIDTHS) : null;
  const initial = destinationInitial(option.title);
  const list = facts(option);

  return (
    <div
      data-media={media === "none" ? "none" : photo ? "photo" : "tile"}
      className={cx(
        "group relative isolate flex flex-col overflow-hidden rounded-md bg-surface text-ink",
        // The edge and the picked ring, one overlay drawn over the photo: a 1 px rule hairline, or a
        // 2 px ink inset ring. A ring, not a border, so nothing moves when the card is picked.
        "after:pointer-events-none after:absolute after:inset-0 after:z-10 after:rounded-md",
        checked ? "after:inset-ring-2 after:inset-ring-ink" : "after:inset-ring-1 after:inset-ring-rule",
        // The controls' focus ring, around the whole card, while its input has keyboard focus.
        "has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-3 has-[input:focus-visible]:outline-focus",
        className,
      )}
    >
      <div className="flex flex-1 flex-col gap-1 px-3.5 pt-3 pb-3.5">
        <label
          className={cx(
            "font-cond text-title font-semibold [overflow-wrap:anywhere]",
            // The label covers the card: a tap anywhere on it picks the option.
            "after:absolute after:inset-0",
            disabled ? "cursor-not-allowed" : "cursor-pointer",
            // Without a photo the tick sits beside the title.
            media === "none" && "pr-8",
          )}
        >
          <input
            type={control}
            name={name}
            value={option.id}
            checked={checked}
            disabled={disabled}
            aria-describedby={detailsId}
            onChange={(event) => onChange(event.currentTarget.checked)}
            className="sr-only"
          />
          {option.title}
        </label>
        <div id={detailsId} className="flex flex-1 flex-col gap-2">
          <p className="text-small text-ink-2">{option.reason}</p>
          {list.length > 0 ? (
            <ul className="mt-auto flex list-none flex-wrap gap-1.5 p-0">
              {list.map((fact) => (
                <li key={fact.icon}>
                  <Chip tone="quiet">
                    <Icon name={fact.icon} size={13} className="text-ink-2" />
                    <VisuallyHidden>{fact.label}</VisuallyHidden>
                    {fact.value}
                  </Chip>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>

      {/* The photo: drawn first (`order-first`) but after the label in the DOM, so Tab reaches the
          card, then its credit. Clicks go through to the label's overlay, but for the credit. */}
      {media !== "none" ? (
        <div className={cx("pointer-events-none relative order-first shrink-0 overflow-hidden bg-notice-wash", RATIOS[media])}>
          {/* The tile: under the photo while it loads, alone when the option has none. */}
          <span data-tile="" aria-hidden="true" className="absolute inset-0 grid place-items-center text-ink-2">
            {initial ? (
              <span className="font-cond text-display font-semibold">{initial}</span>
            ) : (
              <Icon name="map-pin" size={20} />
            )}
          </span>
          {photo && sources ? (
            <>
              {/* A plain <img>, as the covers: Wikimedia serves sized thumbnails from its own cache.
                  Decorative: the title names the place. No referrer: the page's address holds a
                  plan id. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={sources.src}
                srcSet={sources.srcSet}
                sizes={PHOTO_SIZES}
                width={photo.width}
                height={photo.height}
                alt=""
                loading="lazy"
                decoding="async"
                referrerPolicy="no-referrer"
                onError={() => setBroken(true)}
                className={cx(
                  "absolute inset-0 size-full object-cover",
                  !disabled &&
                    "motion-safe:transition-[scale] motion-safe:duration-(--duration-zoom) motion-safe:ease-out motion-safe:group-hover:scale-[1.04]",
                )}
              />
              {/* The credit, on demand: a solid strip across the photo's foot. Above the label's
                  overlay, so its links never pick the card. */}
              <div
                id={creditId}
                hidden={!creditOpen}
                className="pointer-events-auto absolute inset-x-0 bottom-0 z-10 max-h-full overflow-y-auto bg-surface py-2 pr-12 pl-3 pointer-coarse:pr-15"
              >
                <CoverCredit cover={photo} />
              </div>
              <span className="pointer-events-auto absolute right-2 bottom-2 z-10 grid rounded-full bg-surface">
                <IconButton
                  icon="info"
                  label={`Crediti della foto: ${option.title}`}
                  size="sm"
                  aria-expanded={creditOpen}
                  aria-controls={creditId}
                  onClick={() => setCreditOpen((open) => !open)}
                  className="pointer-coarse:size-11"
                />
              </span>
            </>
          ) : null}
        </div>
      ) : null}

      {/* The tick: hollow, or filled ink with a check when picked; on a surface disc, so it reads on
          any photo. The input carries the state for assistive tech. */}
      <span aria-hidden="true" className="pointer-events-none absolute top-2 right-2 z-10 grid rounded-full bg-surface p-0.5">
        <span
          className={cx(
            "grid size-6 place-items-center rounded-full border-[1.5px]",
            checked
              ? "border-ink bg-ink text-on-action"
              : cx("border-rule-strong bg-surface", !disabled && "group-hover:border-ink"),
          )}
        >
          {checked ? <Icon name="check" size={14} /> : null}
        </span>
      </span>
    </div>
  );
}
