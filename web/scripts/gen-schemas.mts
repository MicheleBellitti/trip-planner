/**
 * Generates Zod schemas and TypeScript types from the backend's exported JSON Schemas.
 *
 *   npm run gen:schemas              # (re)write lib/schemas/generated/*.ts
 *   npm run gen:schemas -- --check   # exit 1 if a generated file is missing, stale or unexpected
 *
 * The sources are ../schema/*.json, written by `uv run python -m app.schemas` in backend/ from
 * the Pydantic models (the contract). The output is committed and deterministic: the same input
 * always gives the same bytes, so CI can run `--check` after the backend's own schema check.
 *
 * Only the JSON Schema subset the backend emits is supported. Any other keyword is an error, so
 * a contract change that this generator does not understand fails loudly instead of producing
 * a schema that silently accepts more than the backend does.
 *
 * Object strictness differs by direction:
 * - `request.json` is what the browser SENDS: objects are strict (`additionalProperties: false`
 *   becomes `z.strictObject`), like the backend's `extra="forbid"`.
 * - `ui_event.json` and `plan.json` are what the browser RECEIVES: objects strip unknown keys
 *   (`z.object`). The backend ships first when the contract changes (CLAUDE.md, contract rule
 *   7), so a new field must not make the deployed web app drop every event.
 *
 * The output uses `zod/mini` (functional API: `z.optional(x)`, `x.check(z.gte(0))`), which a
 * bundler can tree-shake: the classic `zod` entry costs about 35 KB gzip of first-load
 * JavaScript on /plans/[id], `zod/mini` a fraction (JS budget, README "Measure the JS"). The
 * schemas validate exactly the same; only the error *messages* differ (mini ships no locale,
 * and the web app shows its own Italian ones).
 *
 * Runs on Node's built-in type stripping (Node >= 22.18 / 23.6): erasable TypeScript only.
 */

import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export type ObjectMode = "strict" | "strip";

export interface SchemaTarget {
  /** File name in ../schema, e.g. "request.json". */
  source: string;
  /** File name in lib/schemas/generated, e.g. "request.ts". */
  output: string;
  /** How objects with `additionalProperties: false` treat unknown keys (see the module doc). */
  objects: ObjectMode;
  /** Export the source JSON Schema itself under this name (`as const`), e.g. for form metadata. */
  jsonSchemaExport?: string;
  /** Export the root's `x-error-codes` map under this name. */
  errorCodesExport?: string;
}

export const TARGETS: readonly SchemaTarget[] = [
  {
    source: "request.json",
    output: "request.ts",
    objects: "strict",
    jsonSchemaExport: "planRequestJsonSchema",
    errorCodesExport: "planRequestErrorCodes",
  },
  { source: "ui_event.json", output: "ui-event.ts", objects: "strip" },
  { source: "plan.json", output: "plan.ts", objects: "strip" },
];

const SUPPORTED_KEYWORDS = new Set([
  "$defs",
  "$ref",
  "additionalProperties",
  "anyOf",
  "default",
  "description",
  "enum",
  "exclusiveMaximum",
  "exclusiveMinimum",
  "format",
  "items",
  "maxItems",
  "maxLength",
  "maximum",
  "minItems",
  "minLength",
  "minimum",
  "pattern",
  "properties",
  "required",
  "title",
  "type",
  "x-error-codes",
]);

const LOCAL_REF_PREFIX = "#/$defs/";
const INDENT = "  ";
const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

export class SchemaGenerationError extends Error {
  constructor(where: string, message: string) {
    super(`${where}: ${message}`);
    this.name = "SchemaGenerationError";
  }
}

function isObject(value: Json | undefined): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asObject(value: Json | undefined, where: string): JsonObject {
  if (!isObject(value)) {
    throw new SchemaGenerationError(where, "expected a JSON object");
  }
  return value;
}

function asNumber(value: Json | undefined, where: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new SchemaGenerationError(where, "expected a number");
  }
  return value;
}

function asString(value: Json | undefined, where: string): string {
  if (typeof value !== "string") {
    throw new SchemaGenerationError(where, "expected a string");
  }
  return value;
}

function checkKeywords(node: JsonObject, where: string): void {
  const unknown = Object.keys(node).filter((key) => !SUPPORTED_KEYWORDS.has(key));
  if (unknown.length > 0) {
    throw new SchemaGenerationError(where, `unsupported keyword(s): ${unknown.join(", ")}`);
  }
}

function refName(ref: string, defs: JsonObject, where: string): string {
  if (!ref.startsWith(LOCAL_REF_PREFIX)) {
    throw new SchemaGenerationError(where, `only local $refs are supported, got ${ref}`);
  }
  const name = ref.slice(LOCAL_REF_PREFIX.length);
  if (!(name in defs)) {
    throw new SchemaGenerationError(where, `$ref ${ref} has no matching $defs entry`);
  }
  if (!IDENTIFIER.test(name)) {
    throw new SchemaGenerationError(where, `$defs name ${JSON.stringify(name)} is not an identifier`);
  }
  return name;
}

function schemaConst(name: string): string {
  return `${name}Schema`;
}

function propertyKey(key: string): string {
  return IDENTIFIER.test(key) ? key : JSON.stringify(key);
}

function jsDoc(description: Json | undefined, indent: string): string[] {
  if (typeof description !== "string" || description.trim() === "") {
    return [];
  }
  const lines = description.replaceAll("*/", "*\\/").split("\n");
  if (lines.length === 1) {
    return [`${indent}/** ${lines[0]} */`];
  }
  return [`${indent}/**`, ...lines.map((line) => `${indent} *${line ? ` ${line}` : ""}`), `${indent} */`];
}

function literal(value: Json): string {
  return JSON.stringify(value);
}

interface Context {
  defs: JsonObject;
  objects: ObjectMode;
}

/** `base` with the checks of the `zod/mini` functional API: `z.int().check(z.gte(0))`. */
function withChecks(base: string, checks: string[]): string {
  return checks.length === 0 ? base : `${base}.check(${checks.join(", ")})`;
}

function numberChecks(node: JsonObject, where: string): string[] {
  const out: string[] = [];
  if ("minimum" in node) out.push(`z.gte(${asNumber(node.minimum, `${where}.minimum`)})`);
  if ("exclusiveMinimum" in node) out.push(`z.gt(${asNumber(node.exclusiveMinimum, `${where}.exclusiveMinimum`)})`);
  if ("maximum" in node) out.push(`z.lte(${asNumber(node.maximum, `${where}.maximum`)})`);
  if ("exclusiveMaximum" in node) out.push(`z.lt(${asNumber(node.exclusiveMaximum, `${where}.exclusiveMaximum`)})`);
  return out;
}

function stringBase(node: JsonObject, where: string): string {
  if (!("format" in node)) return "z.string()";
  const format = asString(node.format, `${where}.format`);
  switch (format) {
    case "date":
      return "z.iso.date()";
    case "date-time":
      // Instants always carry a UTC offset (contract rule 2): no naive datetimes.
      return "z.iso.datetime({ offset: true })";
    case "uri":
      return "z.url()";
    default:
      throw new SchemaGenerationError(where, `unsupported string format ${JSON.stringify(format)}`);
  }
}

function stringChecks(node: JsonObject, where: string): string[] {
  const out: string[] = [];
  if ("minLength" in node) out.push(`z.minLength(${asNumber(node.minLength, `${where}.minLength`)})`);
  if ("maxLength" in node) out.push(`z.maxLength(${asNumber(node.maxLength, `${where}.maxLength`)})`);
  if ("pattern" in node) {
    const pattern = asString(node.pattern, `${where}.pattern`);
    try {
      new RegExp(pattern, "u");
    } catch {
      throw new SchemaGenerationError(where, `pattern ${JSON.stringify(pattern)} is not a valid JS regex`);
    }
    out.push(`z.regex(new RegExp(${JSON.stringify(pattern)}, "u"))`);
  }
  return out;
}

function objectExpression(node: JsonObject, where: string, ctx: Context, depth: number): string {
  const properties = "properties" in node ? asObject(node.properties, `${where}.properties`) : null;
  const additional = node.additionalProperties;
  if (additional !== undefined && typeof additional !== "boolean") {
    throw new SchemaGenerationError(where, "additionalProperties must be a boolean");
  }
  if (properties === null) {
    if (additional === false) return ctx.objects === "strict" ? "z.strictObject({})" : "z.object({})";
    return "z.record(z.string(), z.unknown())";
  }
  const requiredValue = node.required ?? [];
  if (!Array.isArray(requiredValue) || requiredValue.some((key) => typeof key !== "string")) {
    throw new SchemaGenerationError(`${where}.required`, "expected an array of strings");
  }
  const required = new Set(requiredValue as string[]);
  for (const key of required) {
    if (!(key in properties)) {
      throw new SchemaGenerationError(`${where}.required`, `${key} is not a property`);
    }
  }
  const factory =
    additional === true ? "z.looseObject" : ctx.objects === "strict" ? "z.strictObject" : "z.object";
  const inner = INDENT.repeat(depth + 1);
  const lines: string[] = [];
  for (const [key, value] of Object.entries(properties)) {
    const propWhere = `${where}.properties.${key}`;
    const prop = asObject(value, propWhere);
    let expression = schemaExpression(prop, propWhere, ctx, depth + 1);
    if (!required.has(key)) {
      if ("default" in prop) {
        const fallback = prop.default as Json;
        expression =
          typeof fallback === "object" && fallback !== null
            ? `z._default(${expression}, () => (${literal(fallback)}))`
            : `z._default(${expression}, ${literal(fallback)})`;
      } else {
        expression = `z.optional(${expression})`;
      }
    }
    lines.push(...jsDoc(prop.description, inner));
    lines.push(`${inner}${propertyKey(key)}: ${expression},`);
  }
  return `${factory}({\n${lines.join("\n")}\n${INDENT.repeat(depth)}})`;
}

/** The Zod expression for one schema node (without optional/default, which belong to the
 * property that holds it). `depth` is the indentation level of the line the expression starts
 * on. */
export function schemaExpression(node: JsonObject, where: string, ctx: Context, depth = 0): string {
  checkKeywords(node, where);

  if ("$ref" in node) {
    return schemaConst(refName(asString(node.$ref, `${where}.$ref`), ctx.defs, where));
  }

  if ("anyOf" in node) {
    const options = node.anyOf;
    if (!Array.isArray(options) || options.length === 0) {
      throw new SchemaGenerationError(where, "anyOf must be a non-empty array");
    }
    const branches = options.map((option, index) => asObject(option, `${where}.anyOf[${index}]`));
    const isNull = (branch: JsonObject) => branch.type === "null" && Object.keys(branch).length === 1;
    const nonNull = branches.filter((branch) => !isNull(branch));
    const nullable = nonNull.length < branches.length;
    if (nonNull.length === 0) return "z.null()";
    const expressions = nonNull.map((branch, index) =>
      schemaExpression(branch, `${where}.anyOf[${index}]`, ctx, depth),
    );
    const [only] = expressions;
    const base = expressions.length === 1 && only ? only : `z.union([${expressions.join(", ")}])`;
    return nullable ? `z.nullable(${base})` : base;
  }

  if ("enum" in node) {
    const values = node.enum;
    if (!Array.isArray(values) || values.length === 0 || values.some((v) => typeof v !== "string")) {
      throw new SchemaGenerationError(where, "only non-empty string enums are supported");
    }
    if (node.type !== undefined && node.type !== "string") {
      throw new SchemaGenerationError(where, "a string enum must have type string");
    }
    if (values.length === 1) return `z.literal(${literal(values[0] ?? null)})`;
    return `z.enum([${values.map((value) => literal(value)).join(", ")}])`;
  }

  switch (node.type) {
    case "string":
      return withChecks(stringBase(node, where), stringChecks(node, where));
    case "integer":
      return withChecks("z.int()", numberChecks(node, where));
    case "number":
      return withChecks("z.number()", numberChecks(node, where));
    case "boolean":
      return "z.boolean()";
    case "null":
      return "z.null()";
    case "array": {
      if (!("items" in node)) throw new SchemaGenerationError(where, "an array needs items");
      const items = schemaExpression(asObject(node.items, `${where}.items`), `${where}.items`, ctx, depth);
      const checks: string[] = [];
      if ("minItems" in node) checks.push(`z.minLength(${asNumber(node.minItems, `${where}.minItems`)})`);
      if ("maxItems" in node) checks.push(`z.maxLength(${asNumber(node.maxItems, `${where}.maxItems`)})`);
      return withChecks(`z.array(${items})`, checks);
    }
    case "object":
      return objectExpression(node, where, ctx, depth);
    default:
      throw new SchemaGenerationError(where, `unsupported or missing type ${JSON.stringify(node.type ?? null)}`);
  }
}

function collectRefs(node: Json, found: Set<string>): void {
  if (Array.isArray(node)) {
    for (const item of node) collectRefs(item, found);
  } else if (isObject(node)) {
    for (const [key, value] of Object.entries(node)) {
      if (key === "$ref" && typeof value === "string" && value.startsWith(LOCAL_REF_PREFIX)) {
        found.add(value.slice(LOCAL_REF_PREFIX.length));
      } else {
        collectRefs(value, found);
      }
    }
  }
}

/** $defs names in dependency order (a definition after everything it references), ties broken
 * alphabetically so the output is deterministic. Cycles are rejected (Zod would need lazy
 * getters, and the contract has none). */
export function orderDefinitions(defs: JsonObject): string[] {
  const names = Object.keys(defs).sort();
  const ordered: string[] = [];
  const state = new Map<string, "visiting" | "done">();
  const visit = (name: string, trail: string[]) => {
    const current = state.get(name);
    if (current === "done") return;
    if (current === "visiting") {
      throw new SchemaGenerationError("$defs", `reference cycle ${[...trail, name].join(" -> ")}`);
    }
    state.set(name, "visiting");
    const refs = new Set<string>();
    collectRefs(defs[name] ?? null, refs);
    for (const ref of [...refs].sort()) {
      if (!(ref in defs)) throw new SchemaGenerationError(`$defs.${name}`, `unknown $ref ${ref}`);
      visit(ref, [...trail, name]);
    }
    state.set(name, "done");
    ordered.push(name);
  };
  for (const name of names) visit(name, []);
  return ordered;
}

function typeExports(name: string, node: JsonObject): string[] {
  const lines = [`export type ${name} = z.output<typeof ${schemaConst(name)}>;`];
  if (node.type === "object" && "properties" in node) {
    lines.push(`export type ${name}Input = z.input<typeof ${schemaConst(name)}>;`);
  }
  return lines;
}

function definitionBlock(name: string, node: JsonObject, where: string, ctx: Context): string {
  const lines = [
    ...jsDoc(node.description, ""),
    `export const ${schemaConst(name)} = ${schemaExpression(node, where, ctx, 0)};`,
    ...typeExports(name, node),
  ];
  return lines.join("\n");
}

/** The whole generated module for one JSON Schema. Pure and deterministic. */
export function generateModule(schema: JsonObject, target: SchemaTarget): string {
  const where = target.source;
  checkKeywords(schema, where);
  const rootName = asString(schema.title, `${where}.title`);
  if (!IDENTIFIER.test(rootName)) {
    throw new SchemaGenerationError(where, `title ${JSON.stringify(rootName)} is not an identifier`);
  }
  const defs = "$defs" in schema ? asObject(schema.$defs, `${where}.$defs`) : {};
  if (rootName in defs) {
    throw new SchemaGenerationError(where, `title ${rootName} collides with a $defs entry`);
  }
  const ctx: Context = { defs, objects: target.objects };

  const rootNode: JsonObject = { ...schema };
  delete rootNode.$defs;
  delete rootNode["x-error-codes"];

  const blocks: string[] = [
    [
      `// Generated by scripts/gen-schemas.mts from schema/${target.source}. Do not edit by hand:`,
      "// regenerate with `npm run gen:schemas` (CI runs `npm run gen:schemas -- --check`).",
      "",
      'import * as z from "zod/mini";',
    ].join("\n"),
  ];
  for (const name of orderDefinitions(defs)) {
    const node = asObject(defs[name], `${where}.$defs.${name}`);
    blocks.push(definitionBlock(name, node, `${where}.$defs.${name}`, ctx));
  }
  blocks.push(definitionBlock(rootName, rootNode, where, ctx));

  if (target.errorCodesExport) {
    const codes = asObject(schema["x-error-codes"], `${where}.x-error-codes`);
    const typeName = `${rootName}ErrorCode`;
    blocks.push(
      [
        `/** Stable error \`type\` codes of ${rootName}'s own rules, with the backend's English`,
        " * templates (the web app shows its own Italian messages). */",
        `export const ${target.errorCodesExport} = ${JSON.stringify(codes, null, 2)} as const;`,
        `export type ${typeName} = keyof typeof ${target.errorCodesExport};`,
      ].join("\n"),
    );
  }
  if (target.jsonSchemaExport) {
    blocks.push(
      [
        `/** schema/${target.source} itself, for metadata the Zod schema does not carry. */`,
        `export const ${target.jsonSchemaExport} = ${JSON.stringify(schema, null, 2)} as const;`,
      ].join("\n"),
    );
  }
  return `${blocks.join("\n\n")}\n`;
}

// --- CLI ------------------------------------------------------------------------------------

const WEB_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const SCHEMA_DIR = path.resolve(WEB_DIR, "..", "schema");
export const OUTPUT_DIR = path.join(WEB_DIR, "lib", "schemas", "generated");

export function expectedOutputs(schemaDir = SCHEMA_DIR): Map<string, string> {
  const outputs = new Map<string, string>();
  for (const target of TARGETS) {
    const source = path.join(schemaDir, target.source);
    const schema = asObject(JSON.parse(readFileSync(source, "utf8")) as Json, target.source);
    outputs.set(target.output, generateModule(schema, target));
  }
  return outputs;
}

function existingOutputs(outputDir: string): string[] {
  if (!existsSync(outputDir)) return [];
  return readdirSync(outputDir).filter((name) => name.endsWith(".ts")).sort();
}

export function main(argv: readonly string[]): number {
  const check = argv.includes("--check");
  const unknownArgs = argv.filter((arg) => arg !== "--check");
  if (unknownArgs.length > 0) {
    console.error(`gen-schemas: unknown argument(s) ${unknownArgs.join(" ")}`);
    return 2;
  }
  const expected = expectedOutputs();
  const present = existingOutputs(OUTPUT_DIR);

  if (check) {
    const problems: string[] = [];
    for (const [name, content] of expected) {
      const file = path.join(OUTPUT_DIR, name);
      if (!existsSync(file)) problems.push(`missing: ${name}`);
      else if (readFileSync(file, "utf8") !== content) problems.push(`stale: ${name}`);
    }
    for (const name of present) {
      if (!expected.has(name)) problems.push(`unexpected: ${name}`);
    }
    if (problems.length > 0) {
      console.error(
        `lib/schemas/generated is out of date with ../schema (run \`npm run gen:schemas\`):\n` +
          problems.map((line) => `  ${line}`).join("\n"),
      );
      return 1;
    }
    console.log(`lib/schemas/generated is up to date (${expected.size} files).`);
    return 0;
  }

  mkdirSync(OUTPUT_DIR, { recursive: true });
  for (const [name, content] of expected) {
    const file = path.join(OUTPUT_DIR, name);
    if (!existsSync(file) || readFileSync(file, "utf8") !== content) {
      writeFileSync(file, content, "utf8");
      console.log(`wrote lib/schemas/generated/${name}`);
    }
  }
  for (const name of present) {
    if (!expected.has(name)) {
      rmSync(path.join(OUTPUT_DIR, name));
      console.log(`removed lib/schemas/generated/${name}`);
    }
  }
  return 0;
}

const invokedPath = process.argv[1];
if (invokedPath && import.meta.url === pathToFileURL(path.resolve(invokedPath)).href) {
  process.exitCode = main(process.argv.slice(2));
}
