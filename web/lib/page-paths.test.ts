import { describe, expect, it } from "vitest";

import { evalRunPath, planPath } from "./page-paths";

describe("page paths", () => {
  it("builds a plan's and an eval run's path", () => {
    expect(planPath("p1")).toBe("/plans/p1");
    expect(evalRunPath("r1")).toBe("/evals/r1");
  });

  it("encodes the id, so it stays one path segment", () => {
    expect(planPath("a/b")).toBe("/plans/a%2Fb");
    expect(evalRunPath("a b")).toBe("/evals/a%20b");
  });
});
