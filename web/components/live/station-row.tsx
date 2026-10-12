import { memo } from "react";

import { Disclosure } from "@/components/ui/disclosure";
import { TimelineItem, TimelineMeta, TimelineTitle } from "@/components/ui/timeline";

import type { Station, StationMessage } from "./stations";

/**
 * Past DESIGN.md's 300-station threshold a lane's rows use `content-visibility: auto`: the
 * browser skips layout and paint of the rows out of view (virtualization by the engine), while
 * every station stays in the DOM, in the tab order, in find-in-page and for screen readers, so
 * keyboard access is untouched. 2.75rem is a one-line station's height, the placeholder size of
 * a row not laid out yet.
 */
const VIRTUAL_ROW = "[content-visibility:auto] [contain-intrinsic-size:auto_2.75rem]";

function MessageSummary({ message }: { message: StationMessage }) {
  return (
    <span className="line-clamp-2 [overflow-wrap:anywhere]">
      {message.route}
      {message.firstLine ? (
        <>
          {": "}
          <span lang={message.firstLineLang ?? undefined}>{message.firstLine}</span>
        </>
      ) : null}
    </span>
  );
}

function MessageStation({ message }: { message: StationMessage }) {
  if (!message.text) {
    return (
      <TimelineTitle>
        <MessageSummary message={message} />
      </TimelineTitle>
    );
  }
  return (
    <Disclosure summary={<MessageSummary message={message} />} contentLang={message.lang ?? undefined}>
      <p className="whitespace-pre-line [overflow-wrap:anywhere]">{message.text}</p>
    </Disclosure>
  );
}

interface StationRowProps {
  station: Station;
  /** The time gutter: elapsed since the plan started ("2:14"). */
  time: string;
  fresh: boolean;
  virtual: boolean;
}

function StationRowBase({ station, time, fresh, virtual }: StationRowProps) {
  return (
    <TimelineItem
      kind={station.kind}
      time={time}
      dateTime={station.ts}
      fresh={fresh}
      className={virtual ? VIRTUAL_ROW : undefined}
    >
      {station.message ? <MessageStation message={station.message} /> : <TimelineTitle>{station.title}</TimelineTitle>}
      {station.meta ? <TimelineMeta tone={station.metaTone}>{station.meta}</TimelineMeta> : null}
    </TimelineItem>
  );
}

function sameStation(a: Station, b: Station): boolean {
  return (
    a.key === b.key &&
    a.kind === b.kind &&
    a.ts === b.ts &&
    a.title === b.title &&
    a.meta === b.meta &&
    a.metaTone === b.metaTone &&
    a.message?.text === b.message?.text &&
    a.message?.lang === b.message?.lang &&
    a.message?.firstLineLang === b.message?.firstLineLang
  );
}

/** One station of a lane. Memoized on its content: the builder makes new objects on every
 * event, and a long lane must not re-render rows that did not change. */
export const StationRow = memo(
  StationRowBase,
  (previous, next) =>
    previous.time === next.time &&
    previous.fresh === next.fresh &&
    previous.virtual === next.virtual &&
    sameStation(previous.station, next.station),
);
