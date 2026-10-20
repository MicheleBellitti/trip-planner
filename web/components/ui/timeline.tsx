/*
 * Provenance: adapted from "Timeline" by Dice UI (Sadman Sakib), published on 21st.dev at
 * https://21st.dev/@diceui/components/timeline, source
 * https://github.com/sadmann7/diceui/blob/main/docs/registry/bases/base/ui/timeline.tsx,
 * licence MIT (21st.dev label "MIT", repository LICENSE checked), copied by hand on 2026-10-12.
 *
 * Kept from Dice UI: the anatomy (a list root, items with a dot on a connector, a time slot and
 * content), role list/listitem semantics, aria-current="step" on the active item, an
 * aria-hidden connector, item states completed / active / pending, dot size and connector
 * thickness as variables.
 * Changed for Atlas (web/DESIGN.md, "Lane line"): rewritten without @base-ui/react,
 * class-variance-authority, `cn` and the item-registration store (each item's kind comes from
 * the reducer, so no item needs to measure its siblings); vertical only, no alternate or RTL
 * layout; the dot is a Linee station glyph chosen by `kind`; colours, radii and motion re-mapped
 * to the Linee tokens.
 *
 * MIT License
 *
 * Copyright (c) 2024 Sadman Sakib
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

import type { ComponentPropsWithoutRef, ReactNode } from "react";

import type { AgentName } from "@/lib/schemas/generated/ui-event";

import { cx } from "./cx";
import { Icon } from "./icon";

/**
 * What a station is, which decides its glyph on the line:
 * - `tool`: a finished tool call, hollow ring in the line colour;
 * - `failed`: a tool call that failed (a source that did not answer), ring in error red;
 * - `status`: a lane status ("Al lavoro", "Finito"), a bar across the line;
 * - `wave`: a named stage of the run on the coordinator's line ("Ondata 1", "Scelta",
 *   "Ondata 2"), a large ink ring, the interchange station of a transit map;
 * - `message`: an inter-agent message, a lozenge with an ink edge (it shows on both lanes);
 * - `error`: the lane stopped on an error, a red cross that breaks the line above it;
 * - `current`: the tool running now, the "you are here" node (pair it with a ToolChip plate).
 */
export type StationKind = "tool" | "failed" | "status" | "wave" | "message" | "error" | "current";

/** Where the dot's centre sits from the top of a row: level with the first line of text. */
const DOT_TOP = "top-[0.78rem]";
const ROW = "grid grid-cols-[2.6rem_1.5rem_minmax(0,1fr)] gap-x-[0.45rem]";

interface TimelineProps extends ComponentPropsWithoutRef<"ol"> {
  /** The lane: sets the line colour (--line) for every station. */
  agent: AgentName;
  /** The list's accessible name, e.g. "Eventi di voli". */
  label: string;
}

/** A lane's line: an ordered list of stations, oldest at the top, the live one at the bottom. */
export function Timeline({ agent, label, className, children, ...props }: TimelineProps) {
  return (
    <ol data-agent={agent} aria-label={label} className={cx("m-0 list-none p-0", className)} {...props}>
      {children}
    </ol>
  );
}

const DOTS: Record<StationKind, string> = {
  tool: "size-[11px] rounded-full border-[2.5px] border-line bg-surface",
  failed: "size-[11px] rounded-full border-[2.5px] border-error bg-error-wash",
  status: "h-1.5 w-5 rounded-[3px] bg-line",
  wave: "size-4 rounded-full border-[3.5px] border-ink bg-surface",
  message: "h-3 w-[18px] rounded-[7px] border-[2.5px] border-ink bg-surface",
  error: "grid size-5 place-items-center rounded-full bg-surface text-error",
  current: "size-[18px] rounded-full border-4 border-line bg-surface",
};

/** The running node's halo (DESIGN.md gives it to "while running" only). */
const HALO =
  "after:absolute after:-inset-[9px] after:rounded-full after:border-2 after:border-line after:opacity-0 " +
  "motion-safe:after:animate-halo";

interface TimelineItemProps extends Omit<ComponentPropsWithoutRef<"li">, "children"> {
  kind: StationKind;
  /** The time gutter, elapsed since the session started ("7:12"). */
  time: string;
  /** The event's instant, for <time dateTime>. */
  dateTime?: string;
  /** Just arrived: the line draws down to it (320 ms, expo out), then it fades in. With reduced
   * motion it only fades in (120 ms). Set it for one render, on events that arrive live. */
  fresh?: boolean;
  /** `current` only: draw the halo around the node. Off for a plate that waits on the traveller,
   * where nothing runs. */
  halo?: boolean;
  children: ReactNode;
}

/** One station: time, the line with its glyph, and the content (TimelineTitle, TimelineMeta, a
 * message Disclosure, a ToolChip plate for `current`). */
export function TimelineItem({ kind, time, dateTime, fresh = false, halo = true, className, children, ...props }: TimelineItemProps) {
  return (
    <li
      data-kind={kind}
      aria-current={kind === "current" ? "step" : undefined}
      className={cx("group/station relative", ROW, className)}
      {...props}
    >
      <span className="pt-[0.2rem] text-right text-micro text-ink-2">
        {dateTime ? <time dateTime={dateTime}>{time}</time> : time}
      </span>
      <span aria-hidden="true" className="relative">
        <span
          className={cx(
            "absolute inset-y-0 left-1/2 -ml-[2.5px] w-[5px] bg-line",
            "group-first/station:top-[0.78rem]",
            kind === "error"
              ? "bottom-[calc(100%-0.78rem+13px)]"
              : kind !== "current" && "group-last/station:bottom-[calc(100%-0.78rem)]",
            fresh && "origin-top motion-safe:animate-draw",
          )}
        />
        <span
          className={cx(
            "absolute left-1/2 -translate-x-1/2 -translate-y-1/2",
            DOT_TOP,
            DOTS[kind],
            kind === "current" && halo && HALO,
            fresh && "motion-safe:animate-arrive motion-reduce:animate-fade-in",
          )}
        >
          {kind === "error" ? <Icon name="x-circle" size={20} /> : null}
        </span>
      </span>
      <div
        className={cx(
          "min-w-0 pt-[0.12rem] pb-[0.9rem]",
          fresh && "motion-safe:animate-arrive motion-reduce:animate-fade-in",
        )}
      >
        {children}
      </div>
    </li>
  );
}

/** A station's main line: 14.5 px; condensed semibold on status and wave stations, semibold
 * error red on an error station. */
export function TimelineTitle({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      className={cx(
        "text-small leading-[1.35] [overflow-wrap:anywhere]",
        "group-data-[kind=status]/station:font-cond group-data-[kind=status]/station:font-semibold",
        "group-data-[kind=wave]/station:font-cond group-data-[kind=wave]/station:text-body group-data-[kind=wave]/station:font-semibold",
        "group-data-[kind=error]/station:font-semibold group-data-[kind=error]/station:text-error",
        className,
      )}
    >
      {children}
    </p>
  );
}

/** A station's second line in ink-2 (a duration, "meno di 1 s"); `error` puts a warning glyph
 * and error red on it ("Nessuna risposta in 30 s"). */
export function TimelineMeta({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode;
  tone?: "default" | "error";
  className?: string;
}) {
  return (
    <p
      className={cx(
        "mt-px text-meta",
        tone === "error" ? "flex items-center gap-[5px] text-error" : "text-ink-2",
        className,
      )}
    >
      {tone === "error" ? <Icon name="warning" size={14} /> : null}
      {children}
    </p>
  );
}

/** The folded start of a long line (the phone's open lane keeps its last stations): a dashed
 * stretch of line and one button, "12 passaggi precedenti", that unfolds the rest. */
export function TimelineEarlier({
  count,
  expanded,
  onToggle,
}: {
  count: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <li className={ROW}>
      <span />
      <span aria-hidden="true" className="relative">
        <span className="absolute inset-y-0 left-1/2 -ml-[1.5px] border-l-[3px] border-dashed border-line opacity-70" />
      </span>
      <div className="min-w-0 pb-1.5">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={onToggle}
          className="-my-2 inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-xs text-small font-medium underline-offset-[0.2em] hover:underline"
        >
          {expanded ? "Nascondi i passaggi precedenti" : `${count} ${count === 1 ? "passaggio precedente" : "passaggi precedenti"}`}
          <Icon
            name="caret-down"
            size={12}
            className={cx(
              "shrink-0 text-ink-2 transition-[rotate] duration-(--duration-toggle) ease-expo motion-reduce:transition-none",
              expanded && "rotate-180",
            )}
          />
        </button>
      </div>
    </li>
  );
}

/** The dashed stub under the live station: the next stop, not reached yet. */
export function TimelineNext() {
  return (
    <li aria-hidden="true" className={cx(ROW, "h-[22px]")}>
      <span />
      <span className="relative">
        <span className="absolute inset-y-0 left-1/2 -ml-[1.5px] border-l-[3px] border-dashed border-line opacity-70" />
      </span>
      <span />
    </li>
  );
}

/** A lane with no events yet: a dashed line with an empty ring at its head, and why it waits
 * ("Parte dopo la scelta di volo e alloggio."). */
export function TimelineWaiting({
  agent,
  children,
  className,
}: {
  agent: AgentName;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div data-agent={agent} className={cx(ROW, "min-h-16", className)}>
      <span />
      <span aria-hidden="true" className="relative">
        <span className="absolute top-1.5 bottom-1 left-1/2 -ml-[1.5px] border-l-[3px] border-dashed border-line opacity-70" />
        <span className="absolute top-0 left-1/2 size-[11px] -translate-x-1/2 rounded-full border-[2.5px] border-line bg-surface" />
      </span>
      <p className="text-meta text-ink-2">{children}</p>
    </div>
  );
}
