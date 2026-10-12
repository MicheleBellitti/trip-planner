import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";
import * as z from "zod/mini";

import { PlanSchema } from "../lib/schemas/generated/plan";
import { PlanRequestSchema } from "../lib/schemas/generated/request";
import { UIEventSchema } from "../lib/schemas/generated/ui-event";
import happyPath from "../lib/plan-events/__fixtures__/happy-path.json";
import {
  expectedOutputs,
  generateModule,
  orderDefinitions,
  OUTPUT_DIR,
  SchemaGenerationError,
  TARGETS,
  type JsonObject,
  type SchemaTarget,
} from "./gen-schemas.mts";

const STRICT: SchemaTarget = { source: "test.json", output: "test.ts", objects: "strict" };
const STRIP: SchemaTarget = { source: "test.json", output: "test.ts", objects: "strip" };

/** Evaluate a generated module (TypeScript types erased by hand: the bodies are plain JS). */
function load(code: string): Record<string, z.ZodMiniType> {
  const js = code
    .replace(/^import \* as z from "zod\/mini";$/m, "")
    .replace(/^export type .*$/gm, "")
    .replace(/ as const;/g, ";")
    .replace(/^export const (\w+) = /gm, "const $1 = exports.$1 = ");
  const exports: Record<string, z.ZodMiniType> = {};
  new Function("z", "exports", js)(z, exports);
  return exports;
}

describe("committed output", () => {
  it("is up to date with ../schema (what `npm run gen:schemas -- --check` verifies)", () => {
    for (const [name, content] of expectedOutputs()) {
      expect(readFileSync(path.join(OUTPUT_DIR, name), "utf8"), name).toBe(content);
    }
  });

  it("is deterministic", () => {
    const first = expectedOutputs();
    const second = expectedOutputs();
    expect([...first.entries()]).toEqual([...second.entries()]);
    expect(TARGETS.map((target) => target.output)).toEqual(["request.ts", "ui-event.ts", "plan.ts"]);
  });
});

describe("generated contract schemas", () => {
  const event = happyPath.events[10];

  it("accept real UI events and reject what the backend rejects", () => {
    expect(UIEventSchema.safeParse(event).success).toBe(true);
    expect(UIEventSchema.safeParse({ ...event, ts: "2026-10-12T15:04:05" }).success).toBe(false); // naive
    expect(UIEventSchema.safeParse({ ...event, ts: "2026-10-12T13:04:05Z" }).success).toBe(true);
    expect(UIEventSchema.safeParse({ ...event, title: "prima riga\nseconda riga" }).success).toBe(false);
    expect(UIEventSchema.safeParse({ ...event, title: "x".repeat(201) }).success).toBe(false);
    expect(UIEventSchema.safeParse({ ...event, seq: -1 }).success).toBe(false);
    expect(UIEventSchema.safeParse({ ...event, agent: "planner" }).success).toBe(false);
    expect(UIEventSchema.safeParse({ ...event, detail: ["not", "an", "object"] }).success).toBe(false);
  });

  it("strip unknown keys from what the browser receives (the backend ships first)", () => {
    const parsed = UIEventSchema.parse({ ...event, added_by_a_newer_backend: true });
    expect(parsed).not.toHaveProperty("added_by_a_newer_backend");
  });

  it("are strict on what the browser sends", () => {
    const request = {
      origin: "Milano",
      destination: "Lisbona",
      dates: { exact_start: "2026-11-14", exact_end: "2026-11-17" },
      travelers: [{ kind: "adult" }],
      budget_eur: 1500,
    };
    expect(PlanRequestSchema.parse(request)).toMatchObject({ suggest_destination: false, preferences: null });
    expect(PlanRequestSchema.safeParse({ ...request, currency: "EUR" }).success).toBe(false);
    expect(PlanRequestSchema.safeParse({ ...request, dates: { month: "2026-1", nights: 3 } }).success).toBe(false);
    expect(PlanRequestSchema.safeParse({ ...request, travelers: [{ kind: "child", age: 18 }] }).success).toBe(false);
  });

  it("validate a plan's prices and dates", () => {
    const plan = {
      title: "Lisbona, weekend lungo di novembre",
      destination: "Lisbona, Portogallo",
      timezone: "Europe/Lisbon",
      start_date: "2026-11-14",
      end_date: "2026-11-17",
      travelers: 2,
      days: [{ date: "2026-11-14", stops: [{ ref: "d1-s1", title: "Arrivo", kind: "transfer", start_time: "09:30" }] }],
      bookings: [
        {
          title: "Volo Milano Malpensa → Lisbona",
          kind: "transport",
          book_by: "2026-11-07T18:00:00+01:00",
          scheduled_for: "2026-11-14T07:05:00+01:00",
          price: {
            amount_cents: 31200,
            currency: "EUR",
            status: "verified",
            source_url: "https://www.kiwi.com/it/",
            retrieved_at: "2026-10-12T15:04:00+02:00",
          },
        },
      ],
      summary: "Tre giorni a Lisbona.",
    };
    expect(PlanSchema.safeParse(plan).success).toBe(true);
    const badPrice = { ...plan, bookings: [{ ...plan.bookings[0], price: { ...plan.bookings[0]?.price, currency: "eur" } }] };
    expect(PlanSchema.safeParse(badPrice).success).toBe(false);
    const badTime = { ...plan, days: [{ date: "2026-11-14", stops: [{ ref: "a", title: "b", kind: "rest", start_time: "24:00" }] }] };
    expect(PlanSchema.safeParse(badTime).success).toBe(false);
  });
});

describe("generator", () => {
  const schema: JsonObject = {
    title: "Thing",
    type: "object",
    additionalProperties: false,
    required: ["name", "when", "items"],
    properties: {
      name: { type: "string", minLength: 1, maxLength: 5, description: "A name." },
      when: { type: "string", format: "date-time" },
      items: { type: "array", items: { $ref: "#/$defs/Item" }, minItems: 1, maxItems: 2 },
      size: { anyOf: [{ type: "integer", minimum: 0, exclusiveMaximum: 10 }, { type: "null" }], default: null },
      flag: { type: "boolean", default: true },
      tags: { type: "array", items: { type: "string" }, default: [] },
      color: { enum: ["red", "green"], type: "string" },
      ratio: { type: "number", exclusiveMinimum: 0, maximum: 1 },
      meta: { type: "object", additionalProperties: true },
      "odd-key": { type: "string", pattern: "^a+$" },
      day: { type: "string", format: "date" },
      link: { type: "string", format: "uri" },
    },
    $defs: {
      Item: {
        type: "object",
        additionalProperties: false,
        required: ["kind"],
        properties: { kind: { $ref: "#/$defs/Kind" } },
        title: "Item",
      },
      Kind: { enum: ["a", "b"], type: "string", title: "Kind" },
    },
  };

  it("translates every supported keyword", () => {
    const code = generateModule(schema, STRICT);
    const { ThingSchema } = load(code) as { ThingSchema: z.ZodMiniType };
    const valid = { name: "abc", when: "2026-10-12T15:00:00+02:00", items: [{ kind: "a" }] };

    expect(ThingSchema.parse(valid)).toEqual({ ...valid, size: null, flag: true, tags: [] });
    const reject = (patch: Record<string, unknown>) => expect(ThingSchema.safeParse({ ...valid, ...patch }).success).toBe(false);
    reject({ name: "" });
    reject({ name: "toolong" });
    reject({ when: "2026-10-12T15:00:00" });
    reject({ items: [] });
    reject({ items: [{ kind: "a" }, { kind: "a" }, { kind: "b" }] });
    reject({ items: [{ kind: "c" }] });
    reject({ size: 10 });
    reject({ size: -1 });
    reject({ size: 1.5 });
    reject({ color: "blue" });
    reject({ ratio: 0 });
    reject({ ratio: 1.1 });
    reject({ "odd-key": "ab" });
    reject({ day: "2026-02-30" });
    reject({ link: "not a url" });
    reject({ extra: 1 });
    expect(ThingSchema.safeParse({ ...valid, meta: { anything: [1] }, size: 9, ratio: 1, day: "2026-11-14" }).success).toBe(true);
    expect(code).toContain("/** A name. */");
    expect(code).toContain('"odd-key": z.optional(z.string()');
    expect(code).toContain("export type ThingInput = z.input<typeof ThingSchema>;");
  });

  it("strips unknown keys in strip mode", () => {
    const { ThingSchema } = load(generateModule(schema, STRIP)) as { ThingSchema: z.ZodMiniType };
    const parsed = ThingSchema.parse({ name: "abc", when: "2026-10-12T13:00:00Z", items: [{ kind: "b", x: 1 }], extra: 1 });
    expect(parsed).not.toHaveProperty("extra");
  });

  it("orders definitions after their dependencies", () => {
    expect(orderDefinitions({ B: { $ref: "#/$defs/C" }, A: { $ref: "#/$defs/B" }, C: { type: "string" } })).toEqual(["C", "B", "A"]);
    expect(() => orderDefinitions({ A: { $ref: "#/$defs/B" }, B: { $ref: "#/$defs/A" } })).toThrow(/cycle/);
  });

  it("fails loudly on what it does not understand", () => {
    const withKeyword = (property: JsonObject) => ({ title: "T", type: "object", properties: { p: property } });
    expect(() => generateModule(withKeyword({ type: "string", contentEncoding: "base64" }), STRICT)).toThrow(SchemaGenerationError);
    expect(() => generateModule(withKeyword({ type: "string", format: "email" }), STRICT)).toThrow(/format/);
    expect(() => generateModule(withKeyword({ $ref: "#/$defs/Missing" }), STRICT)).toThrow(/no matching/);
    expect(() => generateModule(withKeyword({ $ref: "https://example.com/x.json" }), STRICT)).toThrow(/local/);
    expect(() => generateModule(withKeyword({ type: "string", pattern: "(?<" }), STRICT)).toThrow(/regex/);
    expect(() => generateModule({ type: "object" }, STRICT)).toThrow(/title/);
  });
});
