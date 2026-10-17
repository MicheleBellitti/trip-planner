import type { CSSProperties } from "react";

import { cx } from "@/components/ui/cx";
import { AGENT_LABELS } from "@/lib/plan-events/labels";

const LABEL = "Le cinque linee degli agenti convergono su Lisbona";
/** A line that draws in. Dash 720 is longer than any path here, so with no animation (reduced
 * motion) the line is simply whole. */
const LINE = "fill-none [stroke-dasharray:720] motion-safe:animate-pen";
const STATION = "fill-ground [transform-box:fill-box] origin-center motion-safe:animate-stamp";
const TEXT = "fill-ink-2 font-sans text-[12px] font-medium motion-safe:animate-reveal";
const STRONG = "fill-ink font-sans text-[12px] font-semibold motion-safe:animate-reveal";
/** A line's name at its head, like a transit diagram: no line is told apart by its colour alone. */
const NAME = "fill-ink font-cond text-micro font-semibold motion-safe:animate-reveal";
/** The destination's name, on the type ramp (the page title's size). */
const PLACE = "fill-ink font-cond text-display font-semibold motion-safe:animate-reveal";
const RING = "fill-none stroke-ink [stroke-dasharray:190] [--pen:190px] motion-safe:animate-ring";
const DESTINATION = "[transform-box:fill-box] origin-center motion-safe:animate-stamp";
/** The live tool's plate: it belongs to the run, not to its end, so its resting state is hidden and
 * it retires before the destination stamps "piano pronto". */
const PLATE = "opacity-0 motion-safe:animate-plate";

const at = (delay: number): CSSProperties => ({ animationDelay: `${delay}s` });

/** Each line's path and where the lines meet: `wide` from 768 px (560 × 420), `tall` below
 * (360 × 310). Like a transit diagram's hub, each line enters the destination from its own
 * direction, so none is drawn over another (line-geometry.test.ts). */
export const LINE_MAP = {
  wide: {
    destination: { cx: 430, cy: 230 },
    paths: {
      coordinator: "M20 230 H430",
      flights: "M20 70 H430 V230",
      lodging: "M20 150 H350 L430 230",
      activities: "M20 310 H350 L430 230",
      transport: "M130 390 H430 V230",
    },
  },
  tall: {
    destination: { cx: 180, cy: 230 },
    paths: {
      coordinator: "M180 30 V230",
      flights: "M32 30 V230 H180",
      lodging: "M106 30 V156 L180 230",
      activities: "M254 30 V156 L180 230",
      transport: "M328 30 V230 H180",
    },
  },
} as const;
const WIDE = LINE_MAP.wide.paths;
const TALL = LINE_MAP.tall.paths;

/**
 * The landing's line map (DESIGN.md, Landing): the five agent lines draw in, named at their heads,
 * their stations stamp on, the live tool's plate rises and retires, and the lines converge on the
 * sample destination, whose ring draws once. It is the landing's one authored moment,
 * `motion-safe:` only. Horizontal from 768 px; below, vertical and short enough that the
 * destination lands in a phone's first screen.
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
          <path d={WIDE.coordinator} strokeWidth={8} className={cx(LINE, "stroke-line-coordinator")} style={at(0)} />
          <path d={WIDE.flights} className={cx(LINE, "stroke-line-flights")} style={at(0.15)} />
          <path d={WIDE.lodging} className={cx(LINE, "stroke-line-lodging")} style={at(0.3)} />
          <path d={WIDE.activities} className={cx(LINE, "stroke-line-activities")} style={at(0.45)} />
          <path d={WIDE.transport} className={cx(LINE, "stroke-line-transport")} style={at(1)} />
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
        <text x={20} y={52} className={NAME} style={at(0.25)}>
          {AGENT_LABELS.flights}
        </text>
        <text x={20} y={132} className={NAME} style={at(0.4)}>
          {AGENT_LABELS.lodging}
        </text>
        <text x={20} y={212} className={NAME} style={at(0.1)}>
          {AGENT_LABELS.coordinator}
        </text>
        <text x={20} y={292} className={NAME} style={at(0.55)}>
          {AGENT_LABELS.activities}
        </text>
        <text x={130} y={372} className={NAME} style={at(1.1)}>
          {AGENT_LABELS.transport}
        </text>
        <g className={PLATE} style={at(0.8)}>
          <rect x={196} y={84} width={200} height={30} rx={8} className="fill-line-flights" />
          <text x={208} y={103.5} className="fill-on-line font-sans text-micro font-semibold">
            Expedia · voli MXP→LIS · 0:14
          </text>
        </g>
        <circle cx={430} cy={230} r={30} strokeWidth={1.5} className={RING} style={at(2.4)} />
        <g className={DESTINATION} style={at(2.1)}>
          <circle cx={430} cy={230} r={20} strokeWidth={5} className="fill-ground stroke-ink" />
          <circle cx={430} cy={230} r={6} className="fill-ink" />
        </g>
        <text x={472} y={226} className={PLACE} style={at(2.3)}>
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
        viewBox="0 0 360 310"
        role="img"
        aria-label={LABEL}
        className="mx-auto block h-auto w-full max-w-[26rem] overflow-visible md:hidden"
      >
        <g strokeLinecap="round" strokeLinejoin="round" strokeWidth={6}>
          <path d={TALL.coordinator} strokeWidth={8} className={cx(LINE, "stroke-line-coordinator")} style={at(0)} />
          <path d={TALL.flights} className={cx(LINE, "stroke-line-flights")} style={at(0.15)} />
          <path d={TALL.lodging} className={cx(LINE, "stroke-line-lodging")} style={at(0.3)} />
          <path d={TALL.activities} className={cx(LINE, "stroke-line-activities")} style={at(0.45)} />
          <path d={TALL.transport} className={cx(LINE, "stroke-line-transport")} style={at(1)} />
        </g>
        <g strokeWidth={3}>
          <circle cx={32} cy={56} r={7} className={cx(STATION, "stroke-line-flights")} style={at(0.7)} />
          <circle cx={106} cy={112} r={7} className={cx(STATION, "stroke-line-lodging")} style={at(0.85)} />
          <rect x={171} y={57} width={18} height={26} rx={9} className={cx(STATION, "stroke-ink")} style={at(0.6)} />
          <rect x={171} y={133} width={18} height={26} rx={9} className={cx(STATION, "stroke-ink")} style={at(1.3)} />
          <circle cx={254} cy={110} r={7} className={cx(STATION, "stroke-line-activities")} style={at(1)} />
          <circle cx={328} cy={62} r={7} className={cx(STATION, "stroke-line-transport")} style={at(1.6)} />
        </g>
        <text x={32} y={13} textAnchor="middle" className={NAME} style={at(0.25)}>
          {AGENT_LABELS.flights}
        </text>
        <text x={106} y={13} textAnchor="middle" className={NAME} style={at(0.4)}>
          {AGENT_LABELS.lodging}
        </text>
        <text x={180} y={13} textAnchor="middle" className={NAME} style={at(0.1)}>
          {AGENT_LABELS.coordinator}
        </text>
        <text x={254} y={13} textAnchor="middle" className={NAME} style={at(0.55)}>
          {AGENT_LABELS.activities}
        </text>
        <text x={328} y={13} textAnchor="middle" className={NAME} style={at(1.1)}>
          {AGENT_LABELS.transport}
        </text>
        <text x={44} y={60} className={TEXT} style={at(0.75)}>
          Expedia
        </text>
        <text x={118} y={116} className={TEXT} style={at(0.9)}>
          Booking
        </text>
        <text x={194} y={74} className={STRONG} style={at(0.65)}>
          Ondata 1
        </text>
        <text x={194} y={150} className={STRONG} style={at(1.35)}>
          Scelta
        </text>
        <text x={240} y={114} textAnchor="end" className={TEXT} style={at(1.05)}>
          Sintra
        </text>
        <text x={314} y={66} textAnchor="end" className={TEXT} style={at(1.65)}>
          Aerobus
        </text>
        <g className={PLATE} style={at(0.8)}>
          <rect x={110} y={268} width={140} height={28} rx={8} className="fill-line-flights" />
          <text x={180} y={286.5} textAnchor="middle" className="fill-on-line font-sans text-micro font-semibold">
            Expedia · voli · 0:14
          </text>
        </g>
        <circle cx={180} cy={230} r={30} strokeWidth={1.5} className={RING} style={at(2.4)} />
        <g className={DESTINATION} style={at(2.1)}>
          <circle cx={180} cy={230} r={20} strokeWidth={5} className="fill-ground stroke-ink" />
          <circle cx={180} cy={230} r={6} className="fill-ink" />
        </g>
        <text x={180} y={288} textAnchor="middle" className={PLACE} style={at(2.3)}>
          Lisbona
        </text>
        <text x={180} y={306} textAnchor="middle" className={TEXT} style={at(2.4)}>
          14–18 aprile, piano pronto
        </text>
      </svg>
    </>
  );
}
