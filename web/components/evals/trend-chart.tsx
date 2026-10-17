"use client";

/**
 * The runs over time, drawn as a line of the map, oldest on the left. Two kinds:
 *
 * - `metric`: one figure (the judge's mean, the cost per plan, the accepted plans). The stations
 *   are plain ink rings, the newest one larger (the line's "you are here"), so their colour never
 *   competes with the figure they mark. A run without the figure breaks the line instead of
 *   inventing a value. The baseline the gate measures against, when there is one, is a dashed
 *   line across the plot, its value in a key under it ("riferimento 4,1"): a point on the wrong
 *   side of it is the alarm.
 * - `verdict`: the "Esito" line. Every run is a station carrying its verdict's glyph in its colour
 *   (green passed, red blocked, quiet otherwise), always with the word in the reading and the table.
 *
 * Reading it: the caption reads one run, the newest at rest. The pointer moves that reading to the
 * nearest run, with a crosshair, and a click opens the run; from the keyboard the chart is one tab
 * stop, ←/→, Home and End move between runs (each said once, politely: it answers the reader's own
 * key) and Enter opens one. On a touch screen the first tap reads a run and a second tap on it
 * opens it. Every value is also in a table for screen readers, so the reading never gates a number.
 *
 * Geometry: the line is an SVG stretched over the plot (`preserveAspectRatio="none"`, a
 * non-scaling 2 px stroke), the stations and the reference are HTML placed in percent, so they stay
 * round and crisp at every width with no measuring.
 */

import { useRouter } from "next/navigation";
import { useState, type KeyboardEvent, type PointerEvent } from "react";

import { cx } from "@/components/ui/cx";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { formatCreated, formatDateTime } from "@/lib/format";

import { axisDay, RUN_VERDICT_LABELS, type TrendPoint, type TrendReference } from "./eval-model";
import { RunVerdictGlyph, verdictTone } from "./marks";
import { evalRunPath } from "@/lib/routes";

/** The plot's inner height in the SVG's units: the viewBox is 100 by 100, stretched. */
const VIEW = 100;

export function TrendChart({
  title,
  points,
  openedAt,
  kind = "metric",
  domain = [-1, 1],
  tick,
  empty = "",
  reference = null,
}: {
  title: string;
  points: TrendPoint[];
  /** When the page read the runs: the time axis says "Oggi" and "Ieri" against it. */
  openedAt: number;
  kind?: "metric" | "verdict";
  /** The vertical bounds, bottom and top (a metric chart). */
  domain?: [number, number];
  /** An axis bound as written: "5", "0,50 $" (a metric chart). */
  tick?: (value: number) => string;
  /** What a run without the figure reads: "nessun voto". */
  empty?: string;
  /** The baseline to read the figure against. */
  reference?: TrendReference | null;
}) {
  const router = useRouter();
  const [active, setActive] = useState<number | null>(null);
  /** What a keyboard move says: set only by the reader's own keys, never by the pointer. */
  const [spoken, setSpoken] = useState("");
  const verdicts = kind === "verdict";
  const [low, high] = domain;
  const span = high - low || 1;
  const last = points.length - 1;
  const xOf = (index: number) => (last === 0 ? 50 : (index / last) * 100);
  const yOf = (value: number) => ((high - Math.min(high, Math.max(low, value))) / span) * VIEW;

  const summary = verdicts ? verdictSummary(title, points) : metricSummary(title, points, reference);
  const reading = (point: TrendPoint) =>
    verdicts
      ? `${RUN_VERDICT_LABELS[point.verdict].toLocaleLowerCase("it")}, ${formatDateTime(point.startedAt)}`
      : `${point.label ?? empty}, ${formatDateTime(point.startedAt)}, ${RUN_VERDICT_LABELS[point.verdict].toLocaleLowerCase("it")}`;

  const open = (index: number) => {
    const point = points[index];
    if (point) router.push(evalRunPath(point.id));
  };

  const nearest = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const share = box.width > 0 ? (event.clientX - box.left) / box.width : 0;
    return Math.min(last, Math.max(0, Math.round(share * last)));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const from = active ?? last;
    const to =
      event.key === "ArrowLeft"
        ? Math.max(0, from - 1)
        : event.key === "ArrowRight"
          ? Math.min(last, from + 1)
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (to !== null) {
      event.preventDefault();
      setActive(to);
      if (points[to]) setSpoken(reading(points[to]));
    } else if (event.key === "Enter") {
      event.preventDefault();
      open(from);
    } else if (event.key === "Escape") {
      setActive(null);
    }
  };

  // The line: one path, broken where a run has no figure.
  let path = "";
  points.forEach((point, index) => {
    if (point.value === null) return;
    const joined = index > 0 && points[index - 1]?.value !== null;
    path += `${joined ? "L" : "M"}${xOf(index)} ${yOf(point.value)} `;
  });

  const shown = active === null ? null : points[active];
  const read = shown ?? points[last];
  const plotHeight = verdicts ? "h-8" : "h-20 lg:h-24";

  return (
    <figure className="min-w-0 px-4 py-4 lg:px-5">
      <figcaption className="flex items-start justify-between gap-3">
        <h3 className="text-small font-semibold text-ink">{title}</h3>
        {read ? (
          <div data-readout="" className="text-right">
            {verdicts ? (
              <span className={cx("inline-flex items-center gap-1.5 font-cond text-title font-semibold", verdictTone(read.verdict))}>
                <RunVerdictGlyph verdict={read.verdict} size={16} />
                {RUN_VERDICT_LABELS[read.verdict]}
              </span>
            ) : (
              <span className="block font-cond text-title font-semibold text-ink">{read.label ?? empty}</span>
            )}
            <span className="mt-0.5 flex flex-wrap items-center justify-end gap-x-2 text-micro">
              <span className="text-ink-2">{formatCreated(read.startedAt, openedAt)}</span>
              {verdicts ? null : (
                <span className={cx("inline-flex items-center gap-1 font-semibold", verdictTone(read.verdict))}>
                  <RunVerdictGlyph verdict={read.verdict} size={12} />
                  {RUN_VERDICT_LABELS[read.verdict]}
                </span>
              )}
            </span>
          </div>
        ) : null}
      </figcaption>
      <VisuallyHidden aria-live="polite">{spoken}</VisuallyHidden>

      <div className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2.5">
        {/* The axis: the two bounds only, the line carries the rest. The verdict line has no scale. */}
        <div
          aria-hidden="true"
          className={cx("flex w-11 flex-col justify-between text-right text-micro whitespace-nowrap text-ink-2", plotHeight)}
        >
          {!verdicts && tick ? (
            <>
              <span className="-translate-y-1/2">{tick(high)}</span>
              <span className="translate-y-1/2">{tick(low)}</span>
            </>
          ) : null}
        </div>

        <div
          role="group"
          tabIndex={0}
          aria-label={summary}
          onFocus={() => setActive((current) => current ?? last)}
          onBlur={() => {
            setActive(null);
            setSpoken("");
          }}
          onKeyDown={onKeyDown}
          onPointerMove={(event) => {
            if (event.pointerType === "mouse") setActive(nearest(event));
          }}
          onPointerLeave={(event) => {
            if (event.pointerType === "mouse") setActive(null);
          }}
          onPointerUp={(event) => {
            const index = nearest(event);
            if (event.pointerType === "mouse" || active === index) open(index);
            else setActive(index);
          }}
          className={cx(
            "relative mx-2 cursor-pointer touch-manipulation rounded-xs",
            "focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus",
            plotHeight,
          )}
        >
          <svg
            aria-hidden="true"
            viewBox={`0 0 100 ${VIEW}`}
            preserveAspectRatio="none"
            className="absolute inset-0 size-full overflow-visible"
          >
            {verdicts ? null : (
              <>
                <line x1="0" x2="100" y1="0" y2="0" className="stroke-rule" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                <line
                  x1="0"
                  x2="100"
                  y1={VIEW}
                  y2={VIEW}
                  className="stroke-rule-strong"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                />
              </>
            )}
            {shown ? (
              <line
                x1={xOf(active!)}
                x2={xOf(active!)}
                y1="0"
                y2={VIEW}
                className="stroke-rule-strong"
                strokeWidth="1"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
            <path
              d={path}
              fill="none"
              className="stroke-ink"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          </svg>

          {reference && !verdicts ? (
            // The baseline: a dashed hairline under the stations; its value is in the key below.
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 border-t border-dashed border-rule-strong"
              style={{ top: `${yOf(reference.value)}%` }}
            />
          ) : null}

          {points.map((point, index) =>
            point.value === null ? null : verdicts ? (
              <span
                key={point.id}
                aria-hidden="true"
                data-station=""
                data-verdict={point.verdict}
                className={cx(
                  "absolute grid -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-surface",
                  "transition-[scale] duration-(--duration-hover) ease-out",
                  // Twenty runs on a phone's width: smaller glyphs, so neighbours never touch.
                  index === last ? "[&_svg]:size-4 sm:[&_svg]:size-5" : "[&_svg]:size-3 sm:[&_svg]:size-4",
                  active === index && "scale-125",
                  verdictTone(point.verdict),
                )}
                style={{ left: `${xOf(index)}%`, top: "50%" }}
              >
                <RunVerdictGlyph verdict={point.verdict} size={index === last ? 20 : 16} />
              </span>
            ) : (
              <span
                key={point.id}
                aria-hidden="true"
                data-station=""
                data-verdict={point.verdict}
                className={cx(
                  "absolute -translate-x-1/2 -translate-y-1/2 rounded-full bg-surface transition-[scale] duration-(--duration-hover) ease-out",
                  index === last ? "size-3.5 border-[3px] border-ink" : "size-2.5 border-[2.5px] border-ink-2",
                  active === index && "scale-125",
                )}
                style={{ left: `${xOf(index)}%`, top: `${yOf(point.value)}%` }}
              />
            ),
          )}
        </div>
        {/* The time axis: its two ends, by the day. */}
        <p
          aria-hidden="true"
          data-axis="time"
          className="col-start-2 mx-2 mt-1.5 flex justify-between gap-3 text-micro text-ink-2"
        >
          <span>{points[0] ? axisDay(points[0].startedAt, openedAt) : null}</span>
          {reference && !verdicts ? (
            // The reference's key: a short dashed stroke and its value, between the two days.
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
              <span className="w-3.5 border-t border-dashed border-rule-strong" />
              <span data-reference="">{reference.label}</span>
            </span>
          ) : null}
          <span>{points.length > 1 ? axisDay(points[last]!.startedAt, openedAt) : null}</span>
        </p>
      </div>

      {/* A table ignores the 1 px box of sr-only: the box is on a div around it, so it never widens
          the page. */}
      <div className="sr-only">
        <table>
          <caption>{title}, una riga per valutazione, dalla meno recente</caption>
          <thead>
            <tr>
              <th scope="col">Valutazione</th>
              {verdicts ? null : <th scope="col">{title}</th>}
              <th scope="col">Esito</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.id}>
                <th scope="row">{formatDateTime(point.startedAt)}</th>
                {verdicts ? null : <td>{point.label ?? empty}</td>}
                <td>{RUN_VERDICT_LABELS[point.verdict]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}

/** "Voto medio nelle ultime 5 valutazioni: da 4,0 a 4,6, l'ultima 4,0. Riferimento 4,1." The runs'
 * own figures, as the caption writes them. */
function metricSummary(title: string, points: TrendPoint[], reference: TrendReference | null): string {
  const valued = points.filter((point) => point.value !== null);
  const head = `${title} nelle ultime ${points.length} valutazioni`;
  if (valued.length === 0) return `${head}: nessun valore.`;
  const lowest = valued.reduce((min, point) => (min.value! <= point.value! ? min : point));
  const highest = valued.reduce((max, point) => (max.value! >= point.value! ? max : point));
  const body = `${head}: da ${lowest.label} a ${highest.label}, l'ultima ${valued.at(-1)!.label}.`;
  return reference ? `${body} ${reference.label.charAt(0).toLocaleUpperCase("it")}${reference.label.slice(1)}.` : body;
}

/** "Esito nelle ultime 5 valutazioni, dalla meno recente: solo report, interrotto, superato." */
function verdictSummary(title: string, points: TrendPoint[]): string {
  const words = points.map((point) => RUN_VERDICT_LABELS[point.verdict].toLocaleLowerCase("it"));
  return `${title} nelle ultime ${points.length} valutazioni, dalla meno recente: ${words.join(", ")}.`;
}
