import type { ReactNode } from "react";

import { cx } from "@/components/ui/cx";
import { Icon, type IconName } from "@/components/ui/icon";

interface Stop {
  /** The place ("Milano"), or what is still missing ("Partenza da scegliere"). */
  text: ReactNode;
  /** A second line under the place (the idea behind "Suggeriscimi tu"). */
  note?: ReactNode;
  /** Not filled in yet: the text stands alone, in ink-2, without "Da" / "A" before it. */
  missing?: boolean;
  /** Not a place ("Meta suggerita dal planner"): no "Da" / "A" before it. */
  bare?: boolean;
}

/**
 * A request's route as a short line between two stations: a ring where it starts, the larger
 * ring where it ends (the "Ondata" station's form), joined by an ink line. Ink only: line colours
 * belong to the agents.
 */
export function RouteLine({ origin, destination, className }: { origin: Stop; destination: Stop; className?: string }) {
  return (
    <ol aria-label="Percorso" className={cx("relative grid content-start gap-3.5 self-start text-small", className)}>
      <span
        aria-hidden="true"
        className="absolute top-[0.62rem] bottom-[0.62rem] left-[calc(0.75rem-1.5px)] w-[3px] rounded-full bg-ink"
      />
      <Station label="Da" stop={origin} glyph="size-[13px] border-[2.5px]" />
      <Station label="A" stop={destination} glyph="size-4 border-[3.5px]" />
    </ol>
  );
}

function Station({ label, stop, glyph }: { label: string; stop: Stop; glyph: string }) {
  return (
    <li className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-2">
      <span className="grid h-[1.38em] place-items-center">
        <span aria-hidden="true" className={cx("rounded-full border-ink bg-surface", glyph)} />
      </span>
      <span className="min-w-0">
        {stop.missing || stop.bare ? null : <span className="text-ink-2">{label} </span>}
        <span className={stop.missing ? "text-ink-2" : "font-semibold text-ink"}>{stop.text}</span>
        {stop.note ? <span className="block text-meta text-ink-2">{stop.note}</span> : null}
      </span>
    </li>
  );
}

/** One fact of the request with its icon: dates, travellers, budget. */
export function TripFact({ icon, missing = false, children }: { icon: IconName; missing?: boolean; children: ReactNode }) {
  return (
    <li className={cx("flex items-start gap-2", missing ? "text-ink-2" : "text-ink")}>
      <Icon name={icon} size={16} className="mt-0.5 text-ink-2" />
      <span className="min-w-0">{children}</span>
    </li>
  );
}
