import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { readMessage, readPlanStatus } from "./detail";

const here = path.dirname(fileURLToPath(import.meta.url));

describe("lib/plan-events/detail.ts", () => {
  it("reads the schemas' types only: two enum checks must not pull zod and every schema into the demo", () => {
    const source = readFileSync(path.join(here, "detail.ts"), "utf8");
    const valueImports = [...source.matchAll(/^import \{([^}]*)\} from "\.\.\/schemas\/[^"]+";$/gm)]
      .map((match) => match[1]!)
      .filter((names) => names.split(",").some((name) => name.trim() !== "" && !name.trim().startsWith("type ")));
    expect(valueImports).toEqual([]);
  });

  it("still tells a plan status and an agent from anything else", () => {
    expect(readPlanStatus({ plan_status: "ready" })).toBe("ready");
    expect(readPlanStatus({ plan_status: "pronto" })).toBeNull();
    expect(readMessage({ sender: "flights", recipient: "Coordinatore", text: "fatto" })).toMatchObject({
      from: "flights",
      to: "coordinator",
    });
    expect(readMessage({ sender: "utente", recipient: "coordinatore", text: "ciao" })?.from ?? null).toBeNull();
  });
});
