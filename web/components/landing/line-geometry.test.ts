import { describe, expect, it } from "vitest";

import { CONVERGING_DESTINATION, CONVERGING_PATHS } from "@/lib/brand-mark";

import { LINE_MAP } from "./line-map";

type Point = readonly [number, number];
type Segment = readonly [Point, Point];

/** The vertices of a path made of absolute M, H, V and L commands (all the drawings use). */
function vertices(d: string): Point[] {
  const points: Point[] = [];
  let x = 0;
  let y = 0;
  for (const [, command, args] of d.matchAll(/([MHVL])\s*([^MHVL]*)/g)) {
    const values = args!.trim().split(/[\s,]+/).map(Number);
    if (command === "H") x = values[0]!;
    else if (command === "V") y = values[0]!;
    else [x, y] = [values[0]!, values[1]!];
    points.push([x, y]);
  }
  return points;
}

function segments(d: string): Segment[] {
  const points = vertices(d);
  return points.slice(1).map((point, index) => [points[index]!, point] as const);
}

/** Two segments lie on one track when they are collinear and overlap for a positive length. */
function shareTrack([a, b]: Segment, [c, d]: Segment): boolean {
  const cross = (o: Point, p: Point, q: Point) => (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0]);
  if (cross(a, b, c) !== 0 || cross(a, b, d) !== 0) return false;
  const axis = a[0] !== b[0] ? 0 : 1;
  const overlap =
    Math.min(Math.max(a[axis], b[axis]), Math.max(c[axis], d[axis])) -
    Math.max(Math.min(a[axis], b[axis]), Math.min(c[axis], d[axis]));
  return overlap > 0;
}

/** The direction a line enters the destination from, one step per axis. */
function arrival(d: string): string {
  const points = vertices(d);
  const [x0, y0] = points.at(-2)!;
  const [x1, y1] = points.at(-1)!;
  return `${Math.sign(x1 - x0)},${Math.sign(y1 - y0)}`;
}

const DRAWINGS = {
  "the landing map, wide": LINE_MAP.wide,
  "the landing map, tall": LINE_MAP.tall,
  "the closing and the link preview": { destination: CONVERGING_DESTINATION, paths: CONVERGING_PATHS },
};

describe.each(Object.entries(DRAWINGS))("%s", (_, { destination, paths }) => {
  const lines = Object.entries(paths);

  it("brings all five lines to the destination", () => {
    expect(lines).toHaveLength(5);
    for (const [, d] of lines) expect(vertices(d).at(-1)).toEqual([destination.cx, destination.cy]);
  });

  it("brings each line in from its own direction", () => {
    const directions = lines.map(([, d]) => arrival(d));
    expect(new Set(directions).size).toBe(lines.length);
  });

  it("never draws one line over another", () => {
    const shared: string[] = [];
    lines.forEach(([name, d], index) => {
      for (const [other, e] of lines.slice(index + 1)) {
        if (segments(d).some((s) => segments(e).some((t) => shareTrack(s, t)))) shared.push(`${name}/${other}`);
      }
    });
    expect(shared).toEqual([]);
  });
});
