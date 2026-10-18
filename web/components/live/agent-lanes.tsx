"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { cx } from "@/components/ui/cx";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { AGENTS } from "@/lib/plan-events/labels";
import type { PlanLiveState } from "@/lib/plan-events/reducer";
import type { AgentName } from "@/lib/schemas/generated/ui-event";

import { AgentRoundel } from "@/components/ui/agent";
import { Icon } from "@/components/ui/icon";
import { AGENT_LABELS } from "@/lib/plan-events/labels";

import { AgentLane, JumpToLatest, LaneColumn, LaneHead, laneBodyId, laneCardId } from "./agent-lane";
import { useLaneLayout } from "./hooks";
import { laneToOpen, type LaneView } from "./stations";

interface AgentLanesProps {
  state: PlanLiveState;
  views: Record<AgentName, LaneView>;
  now: number | null;
  freshAfterSeq: number | null;
  stale: boolean;
  /** The section's heading, for screen readers (the eye reads the lanes from their place). */
  heading?: string;
  /** How the phone's open card follows the work: `reader` (live) never swaps a card on screen;
   * `show` (the demo) follows the work until the viewer takes over. */
  follow?: LaneFollow;
}

export type LaneFollow = "reader" | "show";

/** Whether the phone's open card may move to where the work is now (see AgentLanes). */
export function mayFollowLane({
  caughtUp,
  layout,
  chosen,
  touched,
  followedOnScreen,
  follow,
}: {
  caughtUp: boolean;
  layout: string;
  chosen: ReadonlySet<AgentName> | null;
  touched: boolean;
  followedOnScreen: boolean;
  follow: LaneFollow;
}): boolean {
  if (!caughtUp) return true;
  if (layout !== "stack" || chosen !== null || touched) return false;
  return follow === "show" || !followedOnScreen;
}

const SUBAGENTS = AGENTS.filter((agent) => agent !== "coordinator");

/** The camera glides, unless the visitor asked for reduced motion. */
function cameraMotion(): ScrollBehavior {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
}

/** Under the live bar (LiveHeader measures it into `--live-bar-h`), above the lanes' own marks:
 * the one z-index besides the bar (10 < 20). The heads stay on screen while the lines scroll. */
const HEADS_STRIP =
  "sticky top-[var(--live-bar-h,5.75rem)] z-10 -mx-7 grid gap-x-3.5 bg-[color-mix(in_srgb,var(--ground)_92%,transparent)] px-7 backdrop-blur-[8px]";

/**
 * The five lanes in the spec's order (coordinatore, voli, alloggio, attività, spostamenti), in
 * three layouts (DESIGN.md, Layout):
 * - phone: stacked cards, the active lane open and the others one line each. While the history
 *   replays, the open lane follows the work. Once it has settled the open card is never swapped
 *   under a reader: it follows only while the viewer has not touched the page (scrolled, pressed a
 *   key, opened or closed a lane) and the open card is out of view; otherwise a quiet row above the
 *   cards says where the work is now ("Ora: Spostamenti") and takes the viewer there on a tap;
 * - from 1080 px: the coordinator's trunk line in a full-width row, the four subagents in a row of
 *   four columns under it, their heads sticking under the top bar;
 * - from 1280 px: five columns, the coordinator's trunk 1.3 times wider, one row of heads that
 *   sticks under the top bar.
 */
export function AgentLanes({
  state,
  views,
  now,
  freshAfterSeq,
  stale,
  heading = "Corsie degli agenti",
  follow = "reader",
}: AgentLanesProps) {
  const layout = useLaneLayout();
  const coordinatorEnd = useRef<HTMLDivElement>(null);
  const headsStrip = useRef<HTMLDivElement>(null);
  const preferred = laneToOpen(views, state);
  // Where the work is: the lane stays the focus while it works (the busiest lane changes every
  // second early in a run), then the next one takes over. The open card (`followed`) trails it.
  const [focusState, setFocus] = useState<AgentName>(preferred);
  const handOver = focusState !== preferred && (focusState === "coordinator" || views[focusState].state !== "working");
  if (handOver) setFocus(preferred);
  const focus = handOver ? preferred : focusState;
  const [followed, setFollowed] = useState<AgentName>(focus);
  const [chosen, setChosen] = useState<ReadonlySet<AgentName> | null>(null);
  // The viewer has taken control of the page: the first scroll gesture, key press or lane toggle.
  const [touched, setTouched] = useState(false);
  // The phone's cards that touch the screen right now.
  const [onScreen, setOnScreen] = useState<ReadonlySet<AgentName>>(new Set());
  const settled = freshAfterSeq !== null;
  const followedIsStale = followed !== focus;
  // The open card has caught up with the history: from here on it is a reader's card.
  const [caughtUp, setCaughtUp] = useState(false);
  if (!caughtUp && settled && !followedIsStale) setCaughtUp(true);

  // While the history replays, and until the open card has caught up with it, nobody is reading
  // yet: follow the work freely (the coordinator gives way as soon as a subagent is at work). Live,
  // swap the open lane only when nobody is looking at it: a card that touches the screen is never
  // closed, and once the viewer has scrolled or chosen, the row below is the only pointer.
  // In the demo (`show`) the open card keeps following the work on screen: a visitor who only
  // watches sees each agent at work, until they scroll or choose.
  const mayFollow = mayFollowLane({
    caughtUp,
    layout,
    chosen,
    touched,
    followedOnScreen: onScreen.has(followed),
    follow,
  });
  if (followedIsStale && mayFollow) setFollowed(focus);

  // The demo's camera (`show`): while the visitor only watches, the work stays on screen. On the
  // phone the open card's newest station stays in view as the work moves and grows; on wider
  // layouts the coordinator's newest station does. "nearest" moves the page only when the thing is out of view; a scroll, a key or
  // a toggle (`touched`) hands the page back to the visitor.
  // What the camera keeps in view: the open card's end, where its newest station is (the card
  // itself before it opens), or the coordinator's newest station on wider layouts.
  const cameraTarget = useCallback((): HTMLElement | null => {
    if (layout !== "stack") return coordinatorEnd.current;
    // The end marker lives in the card's collapsible body, which is in the DOM even closed: aim at
    // it only once the body shows (open and grown past 0 px), else at the card, still opening.
    const body = document.getElementById(laneBodyId(followed));
    const shown = body !== null && !body.hasAttribute("inert") && body.getBoundingClientRect().height > 0;
    const end = shown ? body.querySelector<HTMLElement>("[data-lane-end]") : null;
    return end ?? document.getElementById(laneCardId(followed));
  }, [layout, followed]);
  // Until when a scroll is the camera's own (a smooth move takes a few hundred ms).
  const cameraUntil = useRef(0);
  const followedStations = views[followed].stations.length;
  const coordinatorStations = views.coordinator.stations.length;
  useEffect(() => {
    if (follow !== "show" || touched) return;
    cameraUntil.current = Date.now() + 1_000;
    cameraTarget()?.scrollIntoView?.({ block: "nearest", behavior: cameraMotion() });
  }, [follow, touched, cameraTarget, followedStations, coordinatorStations]);
  // Any other scroll that takes the work out of view is the visitor's (the scrollbar, a screen
  // reader, a magnifier, an anchor: none of them sends a wheel or a key), and hands the page back.
  useEffect(() => {
    if (follow !== "show" || touched) return;
    const onScroll = () => {
      if (Date.now() < cameraUntil.current) return;
      const box = cameraTarget()?.getBoundingClientRect();
      if (box && (box.bottom < 0 || box.top > window.innerHeight)) setTouched(true);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [follow, touched, cameraTarget]);

  useEffect(() => {
    const mark = () => setTouched(true);
    window.addEventListener("wheel", mark, { passive: true });
    window.addEventListener("touchmove", mark, { passive: true });
    window.addEventListener("keydown", mark);
    return () => {
      window.removeEventListener("wheel", mark);
      window.removeEventListener("touchmove", mark);
      window.removeEventListener("keydown", mark);
    };
  }, []);

  useEffect(() => {
    if (layout !== "stack" || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      setOnScreen((current) => {
        const next = new Set(current);
        for (const entry of entries) {
          const agent = (entry.target as HTMLElement).dataset.agent as AgentName;
          if (entry.isIntersecting) next.add(agent);
          else next.delete(agent);
        }
        return next;
      });
    });
    for (const agent of AGENTS) {
      const card = document.getElementById(laneCardId(agent));
      if (card) observer.observe(card);
    }
    return () => observer.disconnect();
  }, [layout]);

  // The sticky strip of heads (desktop) covers the top of the page like the bar does: publish its
  // height so scrolled-to and focused things stay clear of both (`scroll-padding-top`).
  useEffect(() => {
    const strip = headsStrip.current;
    if (!strip) return;
    const root = document.documentElement;
    const publish = () => root.style.setProperty("--live-heads-h", `${Math.round(strip.getBoundingClientRect().height)}px`);
    publish();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    observer?.observe(strip);
    return () => {
      observer?.disconnect();
      root.style.removeProperty("--live-heads-h");
    };
  }, [layout]);

  const openLanes = chosen ?? new Set([followed]);
  const toggle = (agent: AgentName) => {
    setTouched(true);
    const next = new Set(openLanes);
    if (next.has(agent)) next.delete(agent);
    else next.add(agent);
    setChosen(next);
  };
  /** "Ora: Spostamenti": open the lane where the work is and bring it into view. */
  const goToWork = () => {
    setTouched(true);
    if (chosen === null) setFollowed(focus);
    else if (!chosen.has(focus)) setChosen(new Set([...chosen, focus]));
    requestAnimationFrame(() =>
      document.getElementById(laneCardId(focus))?.scrollIntoView({
        block: "start",
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      }),
    );
  };

  const startedAt = state.startedAt ? Date.parse(state.startedAt) : Number.NaN;
  const running = state.status === null || state.status === "running";
  const laneProps = (agent: AgentName) => ({
    view: views[agent],
    startedAt: Number.isNaN(startedAt) ? null : startedAt,
    now,
    freshAfterSeq,
    running,
    stale,
  });
  const heads = (agents: readonly AgentName[]) =>
    agents.map((agent) => <LaneHead key={agent} view={views[agent]} now={now} />);
  const columns = (agents: readonly AgentName[]) =>
    agents.map((agent) => <LaneColumn key={agent} {...laneProps(agent)} />);

  let content;
  if (layout === "stack") {
    content = (
      <div className="grid gap-2.5">
        {running || !openLanes.has(focus) ? (
          <WorkNow agent={focus} running={running} onGo={goToWork} />
        ) : null}
        {AGENTS.map((agent) => (
          <AgentLane key={agent} {...laneProps(agent)} open={openLanes.has(agent)} onToggle={toggle} />
        ))}
      </div>
    );
  } else if (layout === "rows") {
    content = (
      <div className="grid gap-y-8">
        {/* The trunk line's text keeps a readable measure; the width beside it is left empty. */}
        <div className="max-w-[52rem]">
          <LaneHead view={views.coordinator} now={now} />
          <div className="pt-3.5">
            <LaneColumn {...laneProps("coordinator")} endRef={coordinatorEnd} />
          </div>
        </div>
        <div>
          <div ref={headsStrip} className={cx(HEADS_STRIP, "grid-cols-4")}>{heads(SUBAGENTS)}</div>
          <div className="grid grid-cols-4 gap-x-3.5 pt-3.5">{columns(SUBAGENTS)}</div>
        </div>
      </div>
    );
  } else {
    const grid = "grid-cols-[minmax(0,1.3fr)_repeat(4,minmax(0,1fr))]";
    const withEnd = (agent: AgentName) =>
      agent === "coordinator" ? <LaneColumn key={agent} {...laneProps(agent)} endRef={coordinatorEnd} /> : <LaneColumn key={agent} {...laneProps(agent)} />;
    content = (
      <div>
        <div ref={headsStrip} className={cx(HEADS_STRIP, grid)}>{heads(AGENTS)}</div>
        <div className={cx("grid gap-x-3.5 pt-3.5", grid)}>{AGENTS.map(withEnd)}</div>
      </div>
    );
  }

  return (
    <section aria-labelledby="lanes-heading">
      <VisuallyHidden as="h2" id="lanes-heading">
        {heading}
      </VisuallyHidden>
      {content}
      {layout === "stack" ? null : <JumpToLatest key={layout} target={coordinatorEnd} label={"Vai all\u2019ultimo del coordinatore"} />}
    </section>
  );
}

/**
 * The quiet row above the phone's cards: where the work is now ("Ora: Spostamenti"), a tap away
 * from opening it. It stands in for moving the open card under a reader. Not a live region: the
 * lanes' own state changes are the announcements. A plan that stopped says where instead ("Si è
 * fermato qui: Voli") and shows only while that lane is closed.
 */
function WorkNow({ agent, running, onGo }: { agent: AgentName; running: boolean; onGo: () => void }) {
  return (
    <button
      type="button"
      data-agent={agent}
      onClick={onGo}
      className={cx(
        "flex min-h-11 w-full cursor-pointer items-center gap-2.5 rounded-sm px-3.5 text-left text-small",
        "transition-[background-color] duration-(--duration-hover) ease-out hover:bg-notice-wash",
      )}
    >
      <AgentRoundel agent={agent} size="sm" />
      <span className="min-w-0 flex-1">
        <span className="text-ink-2">{running ? "Ora:" : "Si è fermato qui:"}</span>{" "}
        <span className="font-semibold text-ink">{AGENT_LABELS[agent]}</span>
      </span>
      <Icon name="caret-down" size={14} className="shrink-0 text-ink-2" />
    </button>
  );
}
