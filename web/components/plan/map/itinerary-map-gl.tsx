"use client";

/**
 * The map itself, on maplibre-gl (BSD-3) and OpenFreeMap's tiles. This module is the heavy part
 * (the library, its worker and its stylesheet), so it is only ever loaded through `next/dynamic`
 * by ./itinerary-map.tsx, once the map is near the screen.
 *
 * It draws what the model says and reports two things upward: the station a person clicked, and
 * that the map cannot run here (no WebGL). It never moves the page: the wheel scrolls the page
 * (zoom needs Ctrl or two fingers), and nothing here takes the focus away from the list.
 */

import { Map as MapLibreMap, setWorkerUrl, type LngLatBoundsLike, type MapLayerMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef } from "react";

import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";

import {
  dayBounds,
  findStop,
  isPointBounds,
  lineFeatures,
  modelBounds,
  stationCaption,
  stopFeatures,
  type Bounds,
  type MapModel,
} from "./model";
import {
  buildStyle,
  CLICKABLE_LAYERS,
  LAYER_IDS,
  pickedFilter,
  readPalette,
  selectionPaint,
  type MapData,
} from "./style";

let workerConfigured = false;

/** maplibre starts its worker from a file next to its own module; once bundled that path is gone,
 * so the worker file is shipped as an asset and its URL given here. */
function configureWorker() {
  if (workerConfigured) return;
  workerConfigured = true;
  setWorkerUrl(new URL("../../../node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).href);
}

/** What a fit leaves free: the zoom buttons sit at the right (40 px and a margin, so 60), the rest
 * is a margin that keeps the rings and their numbers whole. An open station card takes the bottom
 * (`fit` adds its height). */
const PADDING = { top: 36, right: 60, bottom: 36, left: 36 };
const MAX_ZOOM = 15.5;
/** Room kept around a station that a card or a button would cover. */
const CLEAR = 16;

const reducedMotion = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** maplibre throws while a style is loading; run the change once it is not. */
function whenStyleReady(map: MapLibreMap, apply: () => void) {
  try {
    apply();
  } catch {
    map.once("style.load", () => {
      try {
        apply();
      } catch {
        /* the next change will apply it */
      }
    });
  }
}

/** Fits the map to a box; a single point gets the closest zoom a street map is still useful at.
 * `cardHeight` is the open station card's height: the box is fitted above it. */
function fit(map: MapLibreMap, bounds: Bounds, animate: boolean, cardHeight = 0) {
  const box = bounds as unknown as LngLatBoundsLike;
  const padding = { ...PADDING, bottom: PADDING.bottom + (cardHeight > 0 ? cardHeight + CLEAR / 2 : 0) };
  // A frame too short for the card still has to leave something to draw in.
  const room = map.getContainer().clientHeight - padding.top - padding.bottom;
  const options = {
    padding: room < 80 ? PADDING : padding,
    maxZoom: isPointBounds(bounds) ? 14 : MAX_ZOOM,
    duration: animate && !reducedMotion() ? 500 : 0,
  };
  map.fitBounds(box, options);
}

export interface ItineraryMapGLProps {
  model: MapModel;
  /** Itinerary index of the highlighted day, or null. */
  selectedDay: number | null;
  /** Key of the station whose card is open, or null. */
  pickedKey: string | null;
  onPick: (key: string | null) => void;
  /** "Vai alla tappa": brings the station's row in the list into view. */
  onGoToStop: (dayIndex: number, stopIndex: number) => void;
  /** The map could not start (no WebGL): the parent says so and the list carries on. */
  onUnavailable: () => void;
  /** The tiles' source could not be reached: the lines and stations still draw. */
  onBaseFailed: () => void;
}

export default function ItineraryMapGL({
  model,
  selectedDay,
  pickedKey,
  onPick,
  onGoToStop,
  onUnavailable,
  onBaseFailed,
}: ItineraryMapGLProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const controlsRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const data = useMemo<MapData>(() => ({ lines: lineFeatures(model), stops: stopFeatures(model) }), [model]);

  // The latest of everything the long-lived map handlers read, without recreating the map.
  const live = useRef({ model, selectedDay, pickedKey, onPick, onUnavailable, onBaseFailed });
  useEffect(() => {
    live.current = { model, selectedDay, pickedKey, onPick, onUnavailable, onBaseFailed };
  });

  // The map is created for a model and lives until the model changes or the page leaves.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let map: MapLibreMap;
    const palette = readPalette(container);
    const bounds = modelBounds(model);
    try {
      configureWorker();
      map = new MapLibreMap({
        container,
        style: buildStyle(palette, data, { selected: live.current.selectedDay, picked: live.current.pickedKey }),
        bounds: (bounds ?? [[-9.2, 38.7], [-9.1, 38.8]]) as unknown as LngLatBoundsLike,
        fitBoundsOptions: { padding: PADDING, maxZoom: bounds && isPointBounds(bounds) ? 14 : MAX_ZOOM },
        attributionControl: false,
        // The page scrolls under a finger or a wheel; the map zooms with Ctrl + wheel or two fingers.
        cooperativeGestures: true,
        dragRotate: false,
        pitchWithRotate: false,
        maxPitch: 0,
        fadeDuration: reducedMotion() ? 0 : 200,
        locale: {
          "Map.Title": "Mappa delle tappe",
          "CooperativeGesturesHandler.WindowsHelpText": "Usa Ctrl + rotella per ingrandire la mappa",
          "CooperativeGesturesHandler.MacHelpText": "Usa ⌘ + rotella per ingrandire la mappa",
          "CooperativeGesturesHandler.MobileHelpText": "Usa due dita per spostare la mappa",
        },
      });
    } catch {
      live.current.onUnavailable();
      return;
    }
    mapRef.current = map;
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();

    const onClick = (event: MapLayerMouseEvent) => {
      const key = event.features?.[0]?.properties?.key;
      live.current.onPick(typeof key === "string" ? key : null);
    };
    const onBackgroundClick = (event: MapLayerMouseEvent) => {
      const hit = map.queryRenderedFeatures(event.point, { layers: CLICKABLE_LAYERS.filter((id) => map.getLayer(id)) });
      if (hit.length === 0) live.current.onPick(null);
    };
    const pointer = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const plain = () => {
      map.getCanvas().style.cursor = "";
    };
    for (const id of CLICKABLE_LAYERS) {
      map.on("click", id, onClick);
      map.on("mouseenter", id, pointer);
      map.on("mouseleave", id, plain);
    }
    map.on("click", onBackgroundClick);
    map.on("error", (event) => {
      const failure = event as unknown as { sourceId?: string; tile?: unknown };
      // A tile that is missing is a hole in the basemap; the source itself failing is the base gone.
      if (failure.sourceId === "openmaptiles" && !failure.tile) live.current.onBaseFailed();
    });

    // A theme change (the toggle pins data-theme on <html>; the system can change too) rebuilds
    // the style from the new tokens. The lines and stations come from the same data.
    const restyle = () => {
      const next = readPalette(container);
      const { selectedDay: selected, pickedKey: picked } = live.current;
      map.setStyle(buildStyle(next, data, { selected, picked }));
    };
    let scheme = palette.scheme;
    const themeChanged = () => {
      const next = readPalette(container).scheme;
      if (next === scheme) return;
      scheme = next;
      restyle();
    };
    const observer = new MutationObserver(themeChanged);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const scheme$ = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    scheme$?.addEventListener("change", themeChanged);

    return () => {
      observer.disconnect();
      scheme$?.removeEventListener("change", themeChanged);
      mapRef.current = null;
      map.remove();
    };
  }, [model, data]);

  // Highlight a day: fade the others, widen the line, and bring the day into view.
  const shown = useRef<number | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const paint = selectionPaint(selectedDay, live.current.pickedKey);
    whenStyleReady(map, () => {
      for (const [layer, props] of Object.entries(paint)) {
        if (layer === LAYER_IDS.picked) continue;
        for (const [name, value] of Object.entries(props)) map.setPaintProperty(layer, name as "line-color", value as never);
      }
    });
    if (shown.current !== selectedDay) {
      const target = selectedDay === null ? modelBounds(model) : dayBounds(model, selectedDay);
      if (target) fit(map, target, true, cardRef.current?.offsetHeight ?? 0);
      shown.current = selectedDay;
    }
  }, [selectedDay, model]);

  // The picked station gets a ring.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    whenStyleReady(map, () => {
      map.setFilter(LAYER_IDS.picked, pickedFilter(pickedKey));
      map.setPaintProperty(LAYER_IDS.picked, "circle-stroke-opacity", pickedKey === null ? 0 : 1);
    });
  }, [pickedKey]);

  const picked = findStop(model, pickedKey);

  // A station that opens its card must not be under the card or the zoom buttons: if it is, the
  // map eases it into the free part of the frame (the card is part of what the person asked for,
  // and the station they tapped is what they are looking at).
  useEffect(() => {
    const map = mapRef.current;
    const found = findStop(model, pickedKey);
    const container = containerRef.current;
    const card = cardRef.current;
    if (!map || !found || !container || !card) return;
    const frame = container.getBoundingClientRect();
    const at = map.project([found.stop.lon, found.stop.lat]);
    const covered = [card, controlsRef.current].some((element) => {
      if (!element) return false;
      const box = element.getBoundingClientRect();
      return (
        at.x > box.left - frame.left - CLEAR &&
        at.x < box.right - frame.left + CLEAR &&
        at.y > box.top - frame.top - CLEAR &&
        at.y < box.bottom - frame.top + CLEAR
      );
    });
    if (!covered) return;
    map.easeTo({
      center: [found.stop.lon, found.stop.lat],
      offset: [-PADDING.right / 2 + PADDING.left / 2, -(card.offsetHeight + CLEAR) / 2],
      duration: reducedMotion() ? 0 : 300,
    });
  }, [model, pickedKey]);

  return (
    <div className="absolute inset-0">
      {/* maplibre sets position: relative on its container, so the box is sized, not placed. */}
      <div ref={containerRef} className="size-full" />
      <div ref={controlsRef} className="absolute right-2 bottom-2 flex flex-col gap-1.5">
        <span className="rounded-full bg-surface">
          <IconButton
            icon="plus"
            label="Ingrandisci la mappa"
            onClick={() => mapRef.current?.zoomIn({ duration: reducedMotion() ? 0 : 250 })}
          />
        </span>
        <span className="rounded-full bg-surface">
          <IconButton
            icon="minus"
            label="Riduci la mappa"
            onClick={() => mapRef.current?.zoomOut({ duration: reducedMotion() ? 0 : 250 })}
          />
        </span>
      </div>
      {picked ? (
        <div
          ref={cardRef}
          className="absolute bottom-2 left-2 flex max-w-[calc(100%-4.5rem)] items-start gap-1 rounded-sm border border-rule bg-surface py-2 pr-1 pl-3 shadow-pop sm:max-w-sm"
          data-testid="map-station"
        >
          <div className="min-w-0 pt-px">
            <p className="text-small leading-[1.3] font-semibold [overflow-wrap:anywhere]">{picked.stop.title}</p>
            <p className="text-meta text-ink-2">
              {stationCaption(picked.day, picked.stop)}
              {picked.stop.lodging ? ", alloggio" : ""}
            </p>
            {picked.stop.place ? <p className="text-meta text-ink-2 [overflow-wrap:anywhere]">{picked.stop.place}</p> : null}
            <Button
              variant="quiet"
              size="sm"
              icon="caret-down"
              className="-ml-3 min-h-7"
              onClick={() => onGoToStop(picked.stop.dayIndex, picked.stop.stopIndex)}
            >
              Vai alla tappa
            </Button>
          </div>
          <IconButton icon="x" label="Chiudi la scheda della tappa" size="sm" variant="bare" onClick={() => onPick(null)} />
        </div>
      ) : null}
    </div>
  );
}
