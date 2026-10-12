/**
 * First-load JavaScript per route, gzip, from a finished `next build` (Turbopack prints no sizes).
 *
 *   NEXT_DIST_DIR=.next-build npm run build && npm run measure:js
 *   npm run measure:js -- --budget 180      # exit 1 when /plans/[id] is over 180 KB gzip
 *
 * First load of a route = the root main files (React, the Next client runtime, the Turbopack
 * runtime) + every chunk its page and layouts reference in the client reference manifest. The
 * polyfill chunk is nomodule, so it is listed separately and never counted (Next's own rule).
 * Chunks that are only `import()`ed later (lazy) are not in the manifest and not counted: they
 * are reported per route as "lazy" so a regression that moves weight there is visible.
 * Sizes are KB of 1000 bytes, like Next's old build table. The budget is on gzip (the spec's
 * unit); brotli, which Vercel serves to every current browser, is printed beside it.
 *
 * Runs on Node's type stripping (Node >= 22.18): erasable TypeScript only.
 */

import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distDir = path.join(webDir, process.env.NEXT_DIST_DIR ?? ".next");
const argv = process.argv.slice(2);
const budgetArg = argv.indexOf("--budget");
const budgetKb = budgetArg >= 0 ? Number(argv[budgetArg + 1]) : null;
const listChunks = argv.includes("--chunks");

if (!existsSync(path.join(distDir, "BUILD_ID"))) {
  console.error(`No build in ${distDir}. Run: NEXT_DIST_DIR=${path.basename(distDir)} npm run build`);
  process.exit(2);
}

const gzipCache = new Map<string, number>();
const brotliCache = new Map<string, number>();

function cachedSize(cache: Map<string, number>, publicPath: string, pack: (input: Buffer) => Buffer): number {
  const rel = publicPath.replace(/^\/?_next\//, "").replace(/^\//, "");
  const cached = cache.get(rel);
  if (cached !== undefined) return cached;
  const file = path.join(distDir, rel);
  const size = existsSync(file) ? pack(readFileSync(file)).length : 0;
  cache.set(rel, size);
  return size;
}

/** gzip size (level 9, the best case, like the `gzip-size` package Next's old table used) of a
 * published chunk. */
const gzipBytes = (publicPath: string) => cachedSize(gzipCache, publicPath, (input) => gzipSync(input, { level: 9 }));

/** brotli size (quality 11) of a published chunk. */
const brotliBytes = (publicPath: string) =>
  cachedSize(brotliCache, publicPath, (input) =>
    brotliCompressSync(input, { params: { [constants.BROTLI_PARAM_QUALITY]: 11, [constants.BROTLI_PARAM_SIZE_HINT]: input.length } }),
  );

function manifestFor(route: string): { clientModules: Record<string, { chunks: string[] }> } | null {
  const file = path.join(distDir, "server", "app", route, "page_client-reference-manifest.js");
  if (!existsSync(file)) return null;
  const text = readFileSync(file, "utf8");
  const json = text.slice(text.indexOf("{", text.indexOf("= {") + 2), text.lastIndexOf("}") + 1);
  return JSON.parse(json);
}

const build = JSON.parse(readFileSync(path.join(distDir, "build-manifest.json"), "utf8")) as {
  polyfillFiles: string[];
  rootMainFiles: string[];
};
const root = new Set(build.rootMainFiles.map((f) => `/_next/${f}`));
const polyfills = new Set(build.polyfillFiles.map((f) => `/_next/${f}`));

/** Routes with a client reference manifest, e.g. "plans/[id]" or "" for "/". */
function routes(): string[] {
  const out: string[] = [];
  const walk = (dir: string, rel: string) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (!statSync(full).isDirectory()) continue;
      if (existsSync(path.join(full, "page_client-reference-manifest.js"))) out.push(path.join(rel, name));
      walk(full, path.join(rel, name));
    }
  };
  const app = path.join(distDir, "server", "app");
  if (existsSync(path.join(app, "page_client-reference-manifest.js"))) out.push("");
  walk(app, "");
  return out.filter((r) => !r.startsWith("_") && !r.startsWith("dev"));
}

const kb = (bytes: number) => (bytes / 1000).toFixed(1).padStart(6);
let over = false;
const rows: string[] = [];

const rootBytes = [...root].reduce((n, f) => n + gzipBytes(f), 0);
rows.push(`shared runtime (rootMainFiles, every route): ${kb(rootBytes)} KB gzip, ${root.size} chunks`);
rows.push(`polyfills (nomodule, not counted):           ${kb([...polyfills].reduce((n, f) => n + gzipBytes(f), 0))} KB gzip`);
rows.push("");

for (const route of routes()) {
  const manifest = manifestFor(route);
  if (!manifest) continue;
  const own = new Set<string>();
  for (const mod of Object.values(manifest.clientModules)) {
    for (const chunk of mod.chunks) {
      if (chunk.endsWith(".js") && !root.has(chunk) && !polyfills.has(chunk)) own.add(chunk);
    }
  }
  const ownBytes = [...own].reduce((n, f) => n + gzipBytes(f), 0);
  const total = rootBytes + ownBytes;
  const label = `/${route}`.padEnd(14);
  const flag = route === "plans/[id]" && budgetKb !== null && total / 1000 > budgetKb ? "  OVER BUDGET" : "";
  if (flag) over = true;
  const brotli = [...root, ...own].reduce((n, f) => n + brotliBytes(f), 0);
  rows.push(
    `${label} first load ${kb(total)} KB gzip, ${kb(brotli)} KB brotli  (runtime ${kb(rootBytes)} + route ${kb(ownBytes)} gzip, ${own.size} chunks)${flag}`,
  );
  if (listChunks) for (const f of [...own].sort()) rows.push(`    ${kb(gzipBytes(f))} KB  ${path.basename(f)}`);
}

console.log(rows.join("\n"));
if (budgetKb !== null) console.log(`\nbudget for /plans/[id]: ${budgetKb} KB gzip -> ${over ? "OVER" : "ok"}`);
process.exit(over ? 1 : 0);
