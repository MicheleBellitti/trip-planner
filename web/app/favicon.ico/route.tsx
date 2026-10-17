import { ImageResponse } from "next/og";

import { MARK_GEOMETRY_SMALL, markDataUri, NIGHT } from "@/lib/brand-mark";

/**
 * "/favicon.ico", for the browsers, crawlers and bookmark tools that ask for it by name (pages
 * point at app/icon.svg): the small mark on the night tile, 32 px, as a PNG, which every browser
 * reads at this path. Without it the request rendered the whole 404 page. It reads nothing from the
 * request, so Cache Components prerenders it at build time, like the link preview.
 */
export function GET() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: NIGHT.ground,
          borderRadius: 7,
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- next/og rasterises <img>; next/image does not apply */}
        <img src={markDataUri(NIGHT, MARK_GEOMETRY_SMALL)} width={28} height={28} alt="" />
      </div>
    ),
    { width: 32, height: 32 },
  );
}
