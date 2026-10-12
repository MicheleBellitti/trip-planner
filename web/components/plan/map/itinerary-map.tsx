"use client";

/**
 * The itinerary map of the finished plan (DESIGN.md, "Map"): each day's stops drawn as a line in
 * one of the five line hues, stations as rings, the lodging as a larger ink ring, with a legend
 * that doubles as the day picker. The list under it stays the primary content; the map is a
 * region of its own with a text summary.
 *
 * This file is the light part: the frame, the legend, the attribution, and the gate that loads
 * the heavy part (./itinerary-map-gl: maplibre, its worker and stylesheet) with `next/dynamic`
 * only when the finished plan is on screen and the frame is near the viewport, so `/plans/[id]`
 * does not pay for the library until a map is about to be seen. Until then, and while the chunk
 * loads, a skeleton of the same size holds the place.
 */

import dynamic from "next/dynamic";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { cx } from "@/components/ui/cx";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { VisuallyHidden } from "@/components/ui/visually-hidden";

import { buildMapModel, hueVariable, liveLine, mapSummary, type MapDay, type MapModel, type MapOutlier, type MapPlan } from "./model";

/** The frame: a fixed height, 16 rem on the phone and 18 rem from 1080 px (where it sits in the
 * sticky right column, 28 rem wide). The skeleton and the map share it, so nothing moves when the
 * map arrives. */
const FRAME = "relative h-64 overflow-hidden rounded-md border border-rule bg-ground lg:h-72";

/** How far below the viewport the frame may be before the map starts loading. */
const NEAR_VIEW = "400px";

function MapSkeleton() {
  return (
    <div className="absolute inset-0">
      <Skeleton shape="block" className="size-full rounded-none" />
      <VisuallyHidden>Caricamento della mappa…</VisuallyHidden>
    </div>
  );
}

const ItineraryMapGL = dynamic(() => import("./itinerary-map-gl"), { ssr: false, loading: () => <MapSkeleton /> });

type Near = "waiting" | "near";

const subscribeNothing = () => () => {};

/** Whether the element has come within `NEAR_VIEW` of the viewport (and stays true after).
 * `supported` is false in a browser with no IntersectionObserver: then the map is not loaded. */
function useNearView(ref: RefObject<HTMLElement | null>): { near: Near; supported: boolean } {
  const [near, setNear] = useState<Near>("waiting");
  // The server and the first client render assume support, so the markup agrees.
  const supported = useSyncExternalStore(
    subscribeNothing,
    () => typeof IntersectionObserver !== "undefined",
    () => true,
  );
  useEffect(() => {
    const element = ref.current;
    if (!element || !supported) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear("near");
          observer.disconnect();
        }
      },
      { rootMargin: NEAR_VIEW },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, supported]);
  return { near, supported };
}

// --- legend -----------------------------------------------------------------------------------

const PILL =
  "inline-flex h-10 items-center gap-2 rounded-full border-[1.5px] px-3 text-meta font-semibold lg:h-8 " +
  "transition-colors duration-(--duration-hover) hover:bg-notice-wash";

/** A day's line in miniature: solid, or dashed once the five hues are used up. */
function DaySwatch({ day }: { day: MapDay }) {
  const color = `var(${hueVariable(day.hue)})`;
  return (
    <span
      aria-hidden="true"
      className="block w-5 shrink-0"
      style={day.cycle > 0 ? { borderTop: `3.5px dashed ${color}` } : { height: 4, borderRadius: 2, backgroundColor: color }}
    />
  );
}

function Legend({
  model,
  selectedDay,
  onSelectDay,
}: {
  model: MapModel;
  selectedDay: number | null;
  onSelectDay: (index: number | null) => void;
}) {
  return (
    <div className="mt-3">
      <div role="group" aria-label="Giorni sulla mappa" className="flex flex-wrap gap-2">
        <button
          type="button"
          aria-pressed={selectedDay === null}
          onClick={() => onSelectDay(null)}
          className={cx(PILL, selectedDay === null ? "border-ink bg-notice-wash" : "border-rule-strong")}
        >
          Tutti i giorni
        </button>
        {model.days.map((day) => (
          <button
            key={day.index}
            type="button"
            aria-pressed={selectedDay === day.index}
            title={day.title ?? undefined}
            onClick={() => onSelectDay(selectedDay === day.index ? null : day.index)}
            className={cx(PILL, selectedDay === day.index ? "border-ink bg-notice-wash" : "border-rule-strong")}
          >
            <DaySwatch day={day} />
            {day.label}
          </button>
        ))}
      </div>
      {/* The base's ring in miniature, and the day trips that are off the first view. */}
      {model.hasLodging || model.outliers.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          {model.hasLodging ? (
            <p className="flex items-center gap-2 px-1 text-meta text-ink-2">
              <span
                aria-hidden="true"
                className="inline-grid size-4 shrink-0 place-items-center rounded-full border-[3px] border-ink bg-surface"
              >
                <span className="size-1.5 rounded-full bg-ink" />
              </span>
              Alloggio
            </p>
          ) : null}
          <OutlierChips outliers={model.outliers} selectedDay={selectedDay} onSelectDay={onSelectDay} />
        </div>
      ) : null}
    </div>
  );
}

/** "Fuori mappa: Sintra (Giorno 3)": a day trip is left out of the first view so the town is not
 * squeezed into a corner; this chip says so and takes the map there (it picks the day). */
function OutlierChips({
  outliers,
  selectedDay,
  onSelectDay,
}: {
  outliers: readonly MapOutlier[];
  selectedDay: number | null;
  onSelectDay: (index: number | null) => void;
}) {
  if (outliers.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-wrap gap-2">
      {outliers.map((outlier) => (
        <button
          key={outlier.dayIndex}
          type="button"
          aria-pressed={selectedDay === outlier.dayIndex}
          onClick={() => onSelectDay(selectedDay === outlier.dayIndex ? null : outlier.dayIndex)}
          className={cx(
            PILL,
            "max-w-full font-normal text-ink-2 hover:text-ink",
            selectedDay === outlier.dayIndex ? "border-ink bg-notice-wash text-ink" : "border-dashed border-rule-strong",
          )}
        >
          <span className="min-w-0 truncate">
            Fuori mappa: {outlier.name} ({outlier.dayLabel})
          </span>
        </button>
      ))}
    </div>
  );
}

function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="rounded-xs underline decoration-rule-strong underline-offset-[0.2em] hover:decoration-ink"
    >
      {children}
    </a>
  );
}

/** What OpenStreetMap's licence and OpenFreeMap's terms ask to be shown next to the map. */
export function Attribution() {
  return (
    <p className="mt-2 text-micro text-ink-2">
      © <ExternalLink href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</ExternalLink>,{" "}
      <ExternalLink href="https://openfreemap.org">OpenFreeMap</ExternalLink>,{" "}
      <ExternalLink href="https://www.openmaptiles.org/">© OpenMapTiles</ExternalLink>
    </p>
  );
}

// --- the map ----------------------------------------------------------------------------------

export interface ItineraryMapProps {
  model: MapModel;
  /** Itinerary index of the highlighted day, or null. */
  selectedDay: number | null;
  onSelectDay: (index: number | null) => void;
  /** "Vai alla tappa" on a station's card: bring that stop's row in the list into view. */
  onGoToStop?: (dayIndex: number, stopIndex: number) => void;
}

const noGoTo = () => {};

/** The region: frame (skeleton, then map), legend, a live line, attribution and a text summary. */
export function ItineraryMap({ model, selectedDay, onSelectDay, onGoToStop = noGoTo }: ItineraryMapProps) {
  const summaryId = useId();
  const frameRef = useRef<HTMLDivElement | null>(null);
  const { near, supported } = useNearView(frameRef);
  const [unavailable, setUnavailable] = useState(false);
  const [baseFailed, setBaseFailed] = useState(false);
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const summary = useMemo(() => mapSummary(model), [model]);

  const failed = unavailable || !supported;
  const loading = !failed && near !== "near";

  return (
    <div role="region" aria-label="Mappa delle tappe" aria-describedby={summaryId} className="min-w-0">
      <p id={summaryId} className="sr-only">
        {summary}
      </p>
      <div ref={frameRef} className={FRAME} aria-busy={loading || undefined}>
        {failed ? (
          <div className="absolute inset-0 grid place-items-center p-4">
            <Notice tone="info" className="max-w-sm">
              La mappa non si carica su questo dispositivo. Le tappe sono nell&apos;elenco qui sotto.
            </Notice>
          </div>
        ) : near === "near" ? (
          <ItineraryMapGL
            model={model}
            selectedDay={selectedDay}
            pickedKey={pickedKey}
            onPick={setPickedKey}
            onGoToStop={onGoToStop}
            onUnavailable={() => setUnavailable(true)}
            onBaseFailed={() => setBaseFailed(true)}
          />
        ) : (
          <MapSkeleton />
        )}
      </div>
      {baseFailed ? (
        <p className="mt-2 text-meta text-ink-2">La base della mappa non si carica. Restano le linee e le tappe.</p>
      ) : null}
      <Legend model={model} selectedDay={selectedDay} onSelectDay={onSelectDay} />
      {/* What the pick did, in words: heard on a phone, where the list is out of sight. */}
      <p role="status" className="mt-2 text-meta text-ink-2">
        {liveLine(model, selectedDay)}
      </p>
      <Attribution />
    </div>
  );
}

// --- the map and the list together ------------------------------------------------------------

/** The day (index in the itinerary) a click landed in: the top-level `li` of the list. */
function dayIndexOfClick(list: HTMLElement, target: Element): number | null {
  const top = list.querySelector(":scope > ol");
  if (!top) return null;
  let item = target.closest("li");
  while (item && item.parentElement !== top) item = item.parentElement?.closest("li") ?? null;
  return item ? Array.prototype.indexOf.call(top.children, item) : null;
}

const INTERACTIVE = "a, button, summary, input, select, textarea, label";

interface MapLink {
  model: MapModel;
  /** Itinerary index of the picked day, or null. */
  selected: number | null;
  select: (index: number | null) => void;
  listRef: RefObject<HTMLDivElement | null>;
  goToStop: (dayIndex: number, stopIndex: number) => void;
}

const MapLinkContext = createContext<MapLink | null>(null);

const reducedMotion = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * What the map and the day-by-day list share: the model, the picked day, and the way from a
 * station to its row. The map (`ItineraryMapPanel`) and the list (`ItineraryDays`) can then sit
 * in different places of the page: the phone stacks them, desktop puts the map in the sticky right
 * column, in view while the list is read. A plan with no coordinates has no model, no panel, and
 * the list alone.
 */
export function ItineraryMapProvider({ plan, children }: { plan: MapPlan; children: ReactNode }) {
  const model = useMemo(() => buildMapModel(plan), [plan]);
  const [picked, setPicked] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const selected = model && picked !== null && model.days.some((day) => day.index === picked) ? picked : null;

  const goToStop = useCallback((dayIndex: number, stopIndex: number) => {
    const day = listRef.current?.querySelector(":scope > ol")?.children[dayIndex];
    const row = day?.querySelector(":scope > ol")?.children[stopIndex];
    if (!(row instanceof HTMLElement)) return;
    row.setAttribute("tabindex", "-1");
    row.setAttribute("data-stop-found", "");
    row.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
    row.focus({ preventScroll: true });
    window.setTimeout(() => {
      row.removeAttribute("data-stop-found");
      row.removeAttribute("tabindex");
    }, 2400);
  }, []);

  const value = useMemo<MapLink | null>(
    () => (model ? { model, selected, select: setPicked, listRef, goToStop } : null),
    [model, selected, goToStop],
  );
  return <MapLinkContext.Provider value={value}>{children}</MapLinkContext.Provider>;
}

/** The map, where the page puts it; nothing when the plan has no located stop. */
export function ItineraryMapPanel({ className }: { className?: string }) {
  const link = useContext(MapLinkContext);
  if (!link) return null;
  return (
    <div className={className}>
      <ItineraryMap model={link.model} selectedDay={link.selected} onSelectDay={link.select} onGoToStop={link.goToStop} />
    </div>
  );
}

/**
 * The day-by-day list, wired to the map: clicking inside a day (not on a link or a button) picks
 * it on the map, and the day in the list is marked (`data-day-selected`) with its title underlined
 * in the day's hue. The list itself is not changed: clicks are read from the wrapper, so the
 * keyboard way to a day is the legend, whose buttons are real buttons.
 */
export function ItineraryDays({ children, className }: { children: ReactNode; className?: string }) {
  const link = useContext(MapLinkContext);
  const model = link?.model ?? null;
  const active = link?.selected ?? null;
  const select = link?.select;
  const listRef = link?.listRef;

  const onListClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      if (!model || !select || event.defaultPrevented || !(event.target instanceof Element)) return;
      if (event.target.closest(INTERACTIVE)) return;
      if (window.getSelection()?.toString()) return;
      const index = listRef?.current ? dayIndexOfClick(listRef.current, event.target) : null;
      if (index === null || !model.days.some((day) => day.index === index)) return;
      select(active === index ? null : index);
    },
    [model, select, listRef, active],
  );

  // Mark the selected day in the list. The attributes are ours (React does not render them), so
  // they survive the list's own renders; running after every render keeps them current.
  useEffect(() => {
    const top = listRef?.current?.querySelector(":scope > ol");
    if (!top || !model) return;
    Array.from(top.children).forEach((item, index) => {
      if (!(item instanceof HTMLElement)) return;
      const day = model.days.find((candidate) => candidate.index === index);
      if (active === index && day) {
        item.setAttribute("data-day-selected", "");
        item.style.setProperty("--day-line", `var(${hueVariable(day.hue)})`);
      } else {
        item.removeAttribute("data-day-selected");
        item.style.removeProperty("--day-line");
      }
    });
  });

  if (!model) return <div className={className}>{children}</div>;
  return (
    <div
      ref={listRef}
      onClick={onListClick}
      className={cx(
        className,
        "[&_h3]:cursor-pointer",
        "[&_li[data-day-selected]_h3>span:last-child]:underline [&_li[data-day-selected]_h3>span:last-child]:decoration-(--day-line)",
        "[&_li[data-day-selected]_h3>span:last-child]:decoration-[3px] [&_li[data-day-selected]_h3>span:last-child]:underline-offset-4",
        // The row "Vai alla tappa" arrived at: a wash for a moment, so the eye finds it.
        "[&_li[data-stop-found]]:rounded-sm [&_li[data-stop-found]]:bg-notice-wash [&_li[data-stop-found]]:outline-none",
      )}
    >
      {children}
    </div>
  );
}
