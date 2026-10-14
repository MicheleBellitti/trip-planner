import { ImageResponse } from "next/og";

import { markDataUri, NIGHT } from "@/lib/brand-mark";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/** The home-screen icon (iOS): the mark on the night ground, rendered once at build time. iOS
 * rounds the corners itself. */
export default function AppleIcon() {
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
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- next/og draws a plain <img> */}
        <img src={markDataUri()} width={116} height={116} alt="" />
      </div>
    ),
    size,
  );
}
