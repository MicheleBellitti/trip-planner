import type { CSSProperties } from "react";

import { cx } from "@/components/ui/cx";

const LABEL = "Le cinque linee degli agenti convergono su Lisbona";
/** A line that draws in. Dash 720 is longer than any path here, so with no animation (reduced
 * motion) the line is simply whole. */
const LINE = "fill-none [stroke-dasharray:720] motion-safe:animate-pen";
const STATION = "fill-ground [transform-box:fill-box] origin-center motion-safe:animate-stamp";
const TEXT = "fill-ink-2 font-sans text-[12px] font-medium motion-safe:animate-reveal";
const STRONG = "fill-ink font-sans text-[12px] font-semibold motion-safe:animate-reveal";
const RING = "fill-none stroke-ink [stroke-dasharray:190] [--pen:190px] motion-safe:animate-ring";
const DESTINATION = "[transform-box:fill-box] origin-center motion-safe:animate-stamp";

const at = (delay: number): CSSProperties => ({ animationDelay: `${delay}s` });

/**
 * The landing's line map (DESIGN.md, Landing): the five agent lines draw in, their stations stamp
 * on, the live tool's plate rises, and the lines converge on the sample destination, whose ring
 * draws once. It is the landing's one authored moment, `motion-safe:` only. Horizontal from 768 px;
 * below, vertical, converging at the bottom like the phone's lanes.
 */
export function LineMap() {
  return (
    <>
      <svg
        viewBox="0 0 560 420"
        role="img"
        aria-label={LABEL}
        className="hidden h-auto w-full overflow-visible md:block"
      >
        <g strokeLinecap="round" strokeLinejoin="round" strokeWidth={6}>
          <path d="M20 230 H430" strokeWidth={8} className={cx(LINE, "stroke-line-coordinator")} style={at(0)} />
          <path d="M20 70 H250 L410 230" className={cx(LINE, "stroke-line-flights")} style={at(0.15)} />
          <path d="M20 150 H330 L410 230" className={cx(LINE, "stroke-line-lodging")} style={at(0.3)} />
          <path d="M20 310 H330 L410 230" className={cx(LINE, "stroke-line-activities")} style={at(0.45)} />
          <path d="M130 390 H250 L410 230" className={cx(LINE, "stroke-line-transport")} style={at(1)} />
        </g>
        <g strokeWidth={3}>
          <circle cx={90} cy={70} r={7} className={cx(STATION, "stroke-line-flights")} style={at(0.7)} />
          <circle cx={175} cy={70} r={7} className={cx(STATION, "stroke-line-flights")} style={at(0.9)} />
          <circle cx={110} cy={150} r={7} className={cx(STATION, "stroke-line-lodging")} style={at(0.85)} />
          <circle cx={230} cy={150} r={7} className={cx(STATION, "stroke-line-lodging")} style={at(1.1)} />
          <rect x={140} y={221} width={26} height={18} rx={9} className={cx(STATION, "stroke-ink")} style={at(0.6)} />
          <rect x={268} y={221} width={26} height={18} rx={9} className={cx(STATION, "stroke-ink")} style={at(1.3)} />
          <circle cx={100} cy={310} r={7} className={cx(STATION, "stroke-line-activities")} style={at(1)} />
          <circle cx={220} cy={310} r={7} className={cx(STATION, "stroke-line-activities")} style={at(1.2)} />
          <circle cx={200} cy={390} r={7} className={cx(STATION, "stroke-line-transport")} style={at(1.6)} />
        </g>
        <text x={76} y={52} className={TEXT} style={at(0.75)}>
          Expedia
        </text>
        <text x={152} y={52} className={TEXT} style={at(0.95)}>
          Google Flights
        </text>
        <text x={88} y={132} className={TEXT} style={at(0.9)}>
          Booking.com
        </text>
        <text x={206} y={132} className={TEXT} style={at(1.15)}>
          Lisboa Plaza
        </text>
        <text x={130} y={258} className={STRONG} style={at(0.65)}>
          Ondata 1
        </text>
        <text x={264} y={258} className={STRONG} style={at(1.35)}>
          Scelta
        </text>
        <text x={80} y={336} className={TEXT} style={at(1.05)}>
          Oceanário
        </text>
        <text x={204} y={336} className={TEXT} style={at(1.25)}>
          Sintra
        </text>
        <text x={180} y={414} className={TEXT} style={at(1.65)}>
          Aerobus
        </text>
        <g className="motion-safe:animate-rise" style={at(1.6)}>
          <rect x={196} y={84} width={200} height={30} rx={8} className="fill-line-flights" />
          <text x={208} y={103.5} className="fill-on-line font-sans text-[12.5px] font-semibold">
            Expedia · voli MXP→LIS · 0:14
          </text>
        </g>
        <circle cx={430} cy={230} r={30} strokeWidth={1.5} className={RING} style={at(2.4)} />
        <g className={DESTINATION} style={at(2.1)}>
          <circle cx={430} cy={230} r={20} strokeWidth={5} className="fill-ground stroke-ink" />
          <circle cx={430} cy={230} r={6} className="fill-ink" />
        </g>
        <text x={472} y={226} className={cx(STRONG, "font-cond text-[22px]")} style={at(2.3)}>
          Lisbona
        </text>
        <text x={472} y={246} className={TEXT} style={at(2.4)}>
          14–18 aprile
        </text>
        <text x={472} y={262} className={TEXT} style={at(2.5)}>
          piano pronto
        </text>
      </svg>

      <svg
        viewBox="0 0 360 480"
        role="img"
        aria-label={LABEL}
        className="mx-auto block h-auto w-full max-w-[26rem] overflow-visible md:hidden"
      >
        <g strokeLinecap="round" strokeLinejoin="round" strokeWidth={6}>
          <path d="M180 10 V400" strokeWidth={8} className={cx(LINE, "stroke-line-coordinator")} style={at(0)} />
          <path d="M40 10 V260 L180 400" className={cx(LINE, "stroke-line-flights")} style={at(0.15)} />
          <path d="M110 10 V330 L180 400" className={cx(LINE, "stroke-line-lodging")} style={at(0.3)} />
          <path d="M250 10 V330 L180 400" className={cx(LINE, "stroke-line-activities")} style={at(0.45)} />
          <path d="M320 100 V260 L180 400" className={cx(LINE, "stroke-line-transport")} style={at(1)} />
        </g>
        <g strokeWidth={3}>
          <circle cx={40} cy={70} r={7} className={cx(STATION, "stroke-line-flights")} style={at(0.7)} />
          <circle cx={110} cy={130} r={7} className={cx(STATION, "stroke-line-lodging")} style={at(0.85)} />
          <rect x={167} y={166} width={26} height={18} rx={9} className={cx(STATION, "stroke-ink")} style={at(0.6)} />
          <rect x={167} y={266} width={26} height={18} rx={9} className={cx(STATION, "stroke-ink")} style={at(1.3)} />
          <circle cx={250} cy={100} r={7} className={cx(STATION, "stroke-line-activities")} style={at(1)} />
          <circle cx={320} cy={190} r={7} className={cx(STATION, "stroke-line-transport")} style={at(1.6)} />
        </g>
        <text x={52} y={74} className={TEXT} style={at(0.75)}>
          Expedia
        </text>
        <text x={122} y={134} className={TEXT} style={at(0.9)}>
          Booking
        </text>
        <text x={200} y={179} className={STRONG} style={at(0.65)}>
          Ondata 1
        </text>
        <text x={200} y={279} className={STRONG} style={at(1.35)}>
          Scelta
        </text>
        <text x={262} y={104} className={TEXT} style={at(1.05)}>
          Oceanário
        </text>
        <text x={308} y={216} textAnchor="end" className={TEXT} style={at(1.65)}>
          Aerobus
        </text>
        <circle cx={180} cy={400} r={30} strokeWidth={1.5} className={RING} style={at(2.4)} />
        <g className={DESTINATION} style={at(2.1)}>
          <circle cx={180} cy={400} r={20} strokeWidth={5} className="fill-ground stroke-ink" />
          <circle cx={180} cy={400} r={6} className="fill-ink" />
        </g>
        <text x={180} y={456} textAnchor="middle" className={cx(STRONG, "font-cond text-[22px]")} style={at(2.3)}>
          Lisbona
        </text>
        <text x={180} y={474} textAnchor="middle" className={TEXT} style={at(2.4)}>
          14–18 aprile, piano pronto
        </text>
      </svg>
    </>
  );
}
