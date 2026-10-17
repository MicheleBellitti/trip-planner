import { cx } from "@/components/ui/cx";

/** The five agent lines entering the destination: the landing's closing and the link preview's
 * drawing (app/opengraph-image.tsx draws the same paths in fixed colours). Decorative. */
export function ConvergingLines({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 1056 150" aria-hidden="true" className={cx("block h-auto w-full", className)}>
      <g fill="none" strokeLinecap="round" strokeLinejoin="round" strokeWidth={7}>
        <path d="M0 75 H990" strokeWidth={9} className="stroke-line-coordinator" />
        <path d="M0 15 H930 L990 75" className="stroke-line-flights" />
        <path d="M0 45 H960 L990 75" className="stroke-line-lodging" />
        <path d="M0 105 H960 L990 75" className="stroke-line-activities" />
        <path d="M120 135 H930 L990 75" className="stroke-line-transport" />
      </g>
      <circle cx={990} cy={75} r={26} strokeWidth={7} className="fill-ground stroke-ink" />
      <circle cx={990} cy={75} r={9} className="fill-ink" />
    </svg>
  );
}
