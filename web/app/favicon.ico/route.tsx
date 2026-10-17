import { readFile } from "node:fs/promises";
import path from "node:path";

import { ImageResponse } from "next/og";

/** The tab icon itself (app/icon.svg), read when the module loads, so the two never drift apart. */
const icon = await readFile(path.join(process.cwd(), "app/icon.svg"));
const iconUri = `data:image/svg+xml;base64,${icon.toString("base64")}`;

/**
 * "/favicon.ico", for the browsers, crawlers and bookmark tools that ask for it by name (pages
 * point at app/icon.svg): the same small mark on its night tile, 32 px, as a PNG, which every
 * browser reads at this path. Without it the request rendered the whole 404 page. It reads nothing
 * from the request, so Cache Components prerenders it at build time, like the link preview.
 */
export function GET() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex" }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- next/og rasterises <img>; next/image does not apply */}
        <img src={iconUri} width={32} height={32} alt="" />
      </div>
    ),
    { width: 32, height: 32 },
  );
}
