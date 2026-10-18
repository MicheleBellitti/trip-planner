"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

import { AgentRoundel } from "@/components/ui/agent";
import { Button } from "@/components/ui/button";
import { ToolChip } from "@/components/ui/chip";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Timeline,
  TimelineEarlier,
  TimelineItem,
  TimelineNext,
  TimelineWaiting,
} from "@/components/ui/timeline";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { formatElapsed } from "@/lib/format";
import { AGENT_LABELS } from "@/lib/plan-events/labels";
import { shouldVirtualize } from "@/lib/plan-events/virtualization";

import { StationRow } from "./station-row";
import type { LaneView } from "./stations";

/** An open lane on the phone keeps its last stations and folds the older ones away. */
export const RECENT_STATIONS = 4;
/** Folding one or two stations would hide less than the button that unfolds them costs. */
const FOLD_FROM = RECENT_STATIONS + 2;

interface LaneProps {
  view: LaneView;
  /** When the plan started (ms): the time gutter counts from it. */
  startedAt: number | null;
  /** The shared clock (ms), frozen while the page is not up to date; null before the first tick. */
  now: number | null;
  /** Stations after this seq arrived live and draw in; null: none does. */
  freshAfterSeq: number | null;
  /** The plan is running: the line continues with a dashed "next stop". */
  running: boolean;
  /** The page shows its last known state (offline, signed out): no halo on the live node. */
  stale: boolean;
}

function gutter(ts: string, startedAt: number | null): string {
  if (startedAt === null) return "";
  const at = Date.parse(ts);
  return Number.isNaN(at) ? "" : formatElapsed(at - startedAt);
}

export const laneCardId = (agent: LaneView["agent"]) => `lane-${agent}`;
const ids = (agent: LaneView["agent"]) => ({ bodyId: `lane-${agent}-body`, nameId: `lane-${agent}-name` });

/** The roundel, the name and the state: two words and a glyph for screen readers. */
function HeadContent({ view, desktop }: { view: LaneView; desktop: boolean }) {
  const { agent } = view;
  return (
    <>
      <AgentRoundel agent={agent} size={desktop ? "lg" : "md"} className={desktop ? "row-span-2" : undefined} />
      <span id={ids(agent).nameId} className="min-w-0 font-cond text-title font-semibold">
        {AGENT_LABELS[agent]}
      </span>
      {/* Out of the grid's flow: keeps the name and the state two words for screen readers. */}
      <VisuallyHidden>, </VisuallyHidden>
      <StatusBadge state={view.badge} agent={agent} className={desktop ? "col-start-2" : undefined} />
    </>
  );
}

/** "1 fonte non risponde", "2 fonti non rispondono". */
export function sourcesLine(count: number): string {
  return count === 1 ? "1 fonte non risponde" : `${count} fonti non rispondono`;
}

/**
 * What the lane is doing now: the live tool, or how the lane ended. A dead source stays visible
 * when the lane's body is not (`withNotices`): on the phone card when it is closed, and in the
 * desktop head, as a quiet last line with the warning glyph (the phone's open body and the desktop
 * column carry no note of their own, so the lines stay level). `clamp` (the desktop head) keeps
 * the peek to two lines, so the sticky row of heads never grows with the longest tool title.
 */
function Peek({
  view,
  now,
  withNotices = false,
  clamp = false,
}: {
  view: LaneView;
  now: number | null;
  withNotices?: boolean;
  clamp?: boolean;
}) {
  const { live, agent } = view;
  const sources = withNotices ? view.notices.length : 0;
  return (
    <>
      {live ? (
        <ToolChip
          agent={agent}
          title={live.title}
          elapsed={now !== null ? formatElapsed(now - Date.parse(live.ts)) : null}
          variant="inline"
          clamp={clamp}
        />
      ) : (
        <span
          className={cx(
            "block text-meta",
            view.state === "error" ? "text-error" : "text-ink-2",
            (clamp || view.state === "working") && "line-clamp-2",
          )}
        >
          {view.summary}
        </span>
      )}
      {sources > 0 ? (
        <span className="mt-0.5 flex items-center gap-1 text-meta text-ink-2">
          <Icon name="warning" size={14} className="shrink-0 text-ink" />
          {sourcesLine(sources)}
          {clamp ? <VisuallyHidden>: il piano prosegue con le altre fonti</VisuallyHidden> : null}
        </span>
      ) : null}
    </>
  );
}

interface LaneBodyProps extends LaneProps {
  /** The phone's open lane: fold the older stations into "N passaggi precedenti". */
  fold?: boolean;
  /** The phone: a marker after the line, for "Vai all'ultimo". */
  endRef?: RefObject<HTMLDivElement | null>;
  /** The column's head already says a source did not answer: no dashed note above the line, so
   * the first stations of the five columns start level. */
  noticesInHead?: boolean;
}

/** The lane's notices and its line of stations, oldest at the top, the live plate at the end. */
export function LaneBody({ view, startedAt, now, freshAfterSeq, running, stale, fold = false, endRef, noticesInHead = false }: LaneBodyProps) {
  const { agent, live } = view;
  const name = AGENT_LABELS[agent];
  const [unfolded, setUnfolded] = useState(false);
  const virtual = shouldVirtualize(view.stations.length);
  const liveElapsed = live && now !== null ? formatElapsed(now - Date.parse(live.ts)) : null;
  const isFresh = (seq: number) => freshAfterSeq !== null && seq > freshAfterSeq;

  const foldable = fold && view.stations.length >= FOLD_FROM;
  const earlier = foldable ? view.stations.length - RECENT_STATIONS : 0;
  const stations = foldable && !unfolded ? view.stations.slice(earlier) : view.stations;

  const showError = view.state === "error" && agent !== "coordinator" && view.errorTitle !== null && running;
  const empty = view.stations.length === 0 && !live;

  return (
    <>
      {(view.notices.length > 0 && !noticesInHead) || showError ? (
        <div className="mb-3 grid gap-2">
          {showError ? (
            <Notice tone="error" title={view.errorTitle}>
              Il coordinatore prosegue con le altre corsie.
            </Notice>
          ) : null}
          {noticesInHead
            ? null
            : view.notices.map((notice) => (
                <Notice key={notice.key} tone="warning">
                  {notice.title}
                </Notice>
              ))}
        </div>
      ) : null}

      {empty ? (
        <TimelineWaiting agent={agent}>{view.summary}</TimelineWaiting>
      ) : (
        <Timeline
          agent={agent}
          label={`Eventi di ${name.toLocaleLowerCase("it")}`}
          className={stale ? "[&_*::after]:animate-none!" : undefined}
        >
          {foldable ? <TimelineEarlier count={earlier} expanded={unfolded} onToggle={() => setUnfolded((value) => !value)} /> : null}
          {stations.map((station) => (
            <StationRow
              key={station.key}
              station={station}
              time={gutter(station.ts, startedAt)}
              fresh={isFresh(station.seq)}
              virtual={virtual}
            />
          ))}
          {live ? (
            <TimelineItem kind="current" time={gutter(live.ts, startedAt)} dateTime={live.ts} fresh={isFresh(live.seq)}>
              <ToolChip agent={agent} title={live.title} elapsed={liveElapsed} />
            </TimelineItem>
          ) : null}
          {running && (live || view.state === "working" || view.state === "waiting") ? <TimelineNext /> : null}
        </Timeline>
      )}
      {endRef ? <div ref={endRef} data-lane-end="" aria-hidden="true" /> : null}
    </>
  );
}

/**
 * From 1080 px: a lane's head, a bare column's header (roundel, name and state, then the live tool
 * or the ending under the name, the Sala borrowing) over a `rule` line. The lanes' heads share one
 * row, so they stay level and stick under the top bar together (AgentLanes); each head is a
 * column whose peek grows to the row's height, so the five `rule` lines sit at one height however
 * long each lane's peek is, and the first stations below them start level.
 */
export function LaneHead({ view, now }: { view: LaneView; now: number | null }) {
  const { agent } = view;
  const empty = view.stations.length === 0 && !view.live;
  return (
    <div data-agent={agent} data-state={view.state} className="flex min-w-0 flex-col">
      <h3 className="m-0">
        <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2.5 pt-1">
          <HeadContent view={view} desktop />
        </div>
      </h3>
      <div data-lane-rule className="flex-1 border-b border-rule pt-1.5 pb-3 text-small">
        {/* An empty lane says it on its waiting line; the row keeps the heads level. */}
        {empty ? null : <Peek view={view} now={now} withNotices clamp />}
      </div>
    </div>
  );
}

/** The body of a lane in the desktop layouts: named by its head for screen readers. */
export function LaneColumn({ endRef, ...props }: LaneProps & { endRef?: RefObject<HTMLDivElement | null> }) {
  const { agent, state } = props.view;
  return (
    <div data-agent={agent} data-state={state} role="group" aria-labelledby={ids(agent).nameId} className="min-w-0">
      <LaneBody {...props} endRef={endRef} noticesInHead />
    </div>
  );
}

/** "Vai all'ultimo": while a lane's live end is below the fold, a button that goes there. The
 * phone points at the open lane's end; from 1080 px at the coordinator's (the lane that decides),
 * whose end can be a screen below the heads. */
export function JumpToLatest({ target, label = "Vai all\u2019ultimo" }: { target: RefObject<HTMLDivElement | null>; label?: string }) {
  const [below, setBelow] = useState(false);

  useEffect(() => {
    const element = target.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry) setBelow(!entry.isIntersecting && entry.boundingClientRect.top > 0);
      },
      { threshold: 0 },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [target]);

  if (!below) return null;
  return (
    // Zero height, so it takes no room in the card; it sticks to the bottom of the screen while
    // the card's end is still below it.
    <div className="pointer-events-none sticky bottom-3 z-10 h-0">
      <div className="pointer-events-auto absolute right-3 bottom-0 motion-safe:animate-toast-in motion-reduce:animate-fade-in">
        <Button
          size="sm"
          icon="caret-down"
          // `!`: the secondary button's transparent ground would win over the surface (classes are
          // concatenated, not merged), and the pill sits over the lane's text.
          className="min-h-11 bg-surface! shadow-pop"
          onClick={() =>
            target.current?.scrollIntoView({
              block: "end",
              behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
            })
          }
        >
          {label}
        </Button>
      </div>
    </div>
  );
}

interface AgentLaneProps extends LaneProps {
  /** The lane's body is shown. */
  open: boolean;
  onToggle: (agent: LaneView["agent"]) => void;
}

/**
 * The phone's lane (spec: AgentLane): a card whose header opens and closes it. Header and the
 * line under it (the live tool, or how the lane ended) are one tap target. Open, the lane keeps
 * that line, folds all but its last stations into "N passaggi precedenti" and offers "Vai
 * all'ultimo" while the end of its line is below the fold: the present first, history on request.
 */
export function AgentLane({ open, onToggle, ...lane }: AgentLaneProps) {
  const { view, now } = lane;
  const { agent } = view;
  const { bodyId, nameId } = ids(agent);
  const endRef = useRef<HTMLDivElement>(null);

  return (
    <section
      id={laneCardId(agent)}
      data-agent={agent}
      data-state={view.state}
      aria-labelledby={nameId}
      className="rounded-md border border-rule bg-surface"
    >
      <div className="relative">
        <h3 className="m-0">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => onToggle(agent)}
            className={cx(
              "grid w-full cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-2.5 rounded-md px-3.5 py-3 text-left",
              "focus-visible:-outline-offset-2",
              // The card's second line is part of the target: the tap lands on the whole header.
              "after:absolute after:inset-0 after:rounded-md",
            )}
          >
            <HeadContent view={view} desktop={false} />
            <Icon
              name="caret-down"
              size={16}
              className={cx(
                "text-ink-2 transition-[rotate] duration-(--duration-toggle) ease-expo motion-reduce:transition-none",
                open && "rotate-180",
              )}
            />
          </button>
        </h3>
        <div className="-mt-1 pr-3.5 pb-3 pl-[3.375rem] text-small">
          <Peek view={view} now={now} withNotices />
        </div>
      </div>

      <div
        id={bodyId}
        inert={!open}
        className={cx(
          "grid transition-[grid-template-rows] duration-(--duration-expand) ease-expo motion-reduce:transition-none",
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="px-3.5 pb-4">
            <LaneBody {...lane} fold endRef={endRef} />
          </div>
        </div>
      </div>
      {open ? <JumpToLatest target={endRef} /> : null}
    </section>
  );
}
