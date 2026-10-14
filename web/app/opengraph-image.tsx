import { readFile } from "node:fs/promises";
import path from "node:path";

import { ImageResponse } from "next/og";

import { BRAND_NAME, BRAND_TAGLINE } from "@/lib/brand";
import { markDataUri, NIGHT } from "@/lib/brand-mark";

export const alt = `${BRAND_NAME}: ${BRAND_TAGLINE}`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** The five agent lines converging on a destination, as at the end of the landing hero. No text:
 * the inner SVG is rasterised without fonts. 1056 × 150 units. */
const CONVERGING_LINES = [
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1056 150">`,
  `<g fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="7">`,
  `<path d="M0 75 H990" stroke="${NIGHT.coordinator}" stroke-width="9"/>`,
  `<path d="M0 15 H930 L990 75" stroke="${NIGHT.flights}"/>`,
  `<path d="M0 45 H960 L990 75" stroke="${NIGHT.lodging}"/>`,
  `<path d="M0 105 H960 L990 75" stroke="${NIGHT.activities}"/>`,
  `<path d="M120 135 H930 L990 75" stroke="${NIGHT.transport}"/>`,
  `</g>`,
  `<circle cx="990" cy="75" r="26" fill="${NIGHT.ground}" stroke="${NIGHT.ink}" stroke-width="7"/>`,
  `<circle cx="990" cy="75" r="9" fill="${NIGHT.ink}"/>`,
  `</svg>`,
].join("");

/** The link preview of every page (WhatsApp, Slack, iMessage): mark and name, the tagline, the
 * lines converging. Static: rendered once at build time from the vendored hero face. */
export default async function OpengraphImage() {
  const bold = await readFile(path.join(process.cwd(), "assets/fonts/BarlowSemiCondensed-Bold.ttf"));
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "60px 72px 56px",
          background: NIGHT.ground,
          color: NIGHT.ink,
          fontFamily: "Barlow Semi Condensed",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 44 }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- next/og draws a plain <img> */}
          <img src={markDataUri()} width={56} height={56} alt="" />
          {BRAND_NAME}
        </div>
        <div style={{ display: "flex", fontSize: 96, lineHeight: 0.98, maxWidth: 780 }}>{BRAND_TAGLINE}</div>
        {/* eslint-disable-next-line @next/next/no-img-element -- next/og draws a plain <img> */}
        <img src={`data:image/svg+xml;base64,${btoa(CONVERGING_LINES)}`} width={1056} height={150} alt="" />
      </div>
    ),
    { ...size, fonts: [{ name: "Barlow Semi Condensed", data: bold, weight: 700, style: "normal" }] },
  );
}
