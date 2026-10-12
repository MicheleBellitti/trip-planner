/**
 * Virtualization of long timelines (spec: "timeline virtualizzata oltre 300 eventi"). Up to the
 * threshold every event is rendered; beyond it only the rows in view (plus some overscan).
 */

export const VIRTUALIZATION_THRESHOLD = 300;

/** True when a list of `count` events must be virtualized (strictly more than 300). */
export function shouldVirtualize(count: number, threshold = VIRTUALIZATION_THRESHOLD): boolean {
  return count > threshold;
}

export interface VirtualWindowInput {
  count: number;
  /** Fixed (or estimated) row height in px. */
  rowHeight: number;
  /** Scroll offset of the list's viewport, in px. */
  scrollTop: number;
  /** Height of the list's viewport, in px. */
  viewportHeight: number;
  /** Extra rows rendered above and below the viewport. */
  overscan?: number;
}

export interface VirtualWindow {
  /** First row to render (inclusive). */
  start: number;
  /** Row after the last one to render (exclusive). */
  end: number;
  /** Space above the first rendered row, in px. */
  offsetTop: number;
  /** Height of the whole list, in px. */
  totalHeight: number;
}

/** The rows to render for a fixed-height virtual list. Pure; clamps every input. */
export function virtualWindow({
  count,
  rowHeight,
  scrollTop,
  viewportHeight,
  overscan = 8,
}: VirtualWindowInput): VirtualWindow {
  const rows = Math.max(0, Math.floor(count));
  const height = Math.max(1, rowHeight);
  const totalHeight = rows * height;
  if (rows === 0) return { start: 0, end: 0, offsetTop: 0, totalHeight: 0 };
  const top = Math.min(Math.max(0, scrollTop), Math.max(0, totalHeight - 1));
  const first = Math.floor(top / height);
  const visible = Math.ceil(Math.max(0, viewportHeight) / height) + 1;
  const start = Math.max(0, first - overscan);
  const end = Math.min(rows, first + visible + overscan);
  return { start, end, offsetTop: start * height, totalHeight };
}
