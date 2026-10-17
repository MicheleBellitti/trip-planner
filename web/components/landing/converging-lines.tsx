import { cx } from "@/components/ui/cx";
import {
  CONVERGING_DESTINATION,
  CONVERGING_PATHS,
  CONVERGING_VIEWBOX,
  CONVERGING_VIEWBOX_NARROW,
} from "@/lib/brand-mark";

const { cx: hubX, cy: hubY } = CONVERGING_DESTINATION;

/** The five agent lines entering the destination: the landing's closing and the link preview's
 * drawing (app/opengraph-image.tsx draws the same paths in fixed colours). Decorative. Below 768 px
 * it shows only the last stretch before the destination, so the lines keep their weight. */
export function ConvergingLines({ className }: { className?: string }) {
  return (
    <div aria-hidden="true" className={className}>
      <Drawing viewBox={CONVERGING_VIEWBOX_NARROW} className="md:hidden" />
      <Drawing viewBox={CONVERGING_VIEWBOX} className="hidden md:block" />
    </div>
  );
}

function Drawing({ viewBox, className }: { viewBox: string; className: string }) {
  return (
    <svg viewBox={viewBox} className={cx("h-auto w-full", className)}>
      <g fill="none" strokeLinecap="round" strokeLinejoin="round" strokeWidth={7}>
        <path d={CONVERGING_PATHS.coordinator} strokeWidth={9} className="stroke-line-coordinator" />
        <path d={CONVERGING_PATHS.flights} className="stroke-line-flights" />
        <path d={CONVERGING_PATHS.lodging} className="stroke-line-lodging" />
        <path d={CONVERGING_PATHS.activities} className="stroke-line-activities" />
        <path d={CONVERGING_PATHS.transport} className="stroke-line-transport" />
      </g>
      <circle cx={hubX} cy={hubY} r={26} strokeWidth={7} className="fill-ground stroke-ink" />
      <circle cx={hubX} cy={hubY} r={9} className="fill-ink" />
    </svg>
  );
}
