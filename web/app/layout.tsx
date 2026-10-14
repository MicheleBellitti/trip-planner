import type { Metadata, Viewport } from "next";
import { Barlow, Barlow_Semi_Condensed } from "next/font/google";
import type { ReactNode } from "react";

import { IconSprite } from "@/components/ui/icon-sprite";
import { DEFAULT_THEME, THEME_COLORS } from "@/components/ui/theme";
import { ThemeScript } from "@/components/ui/theme-script";
import { BRAND_DESCRIPTION, BRAND_NAME } from "@/lib/brand";

import "./globals.css";

/** Text face (DESIGN.md, Typography): Barlow 400/500/600, self-hosted by next/font. */
const barlow = Barlow({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--font-barlow",
});

/** Display face: Barlow Semi Condensed 600 for titles, lane names and the wordmark. */
const barlowSemiCondensed = Barlow_Semi_Condensed({
  subsets: ["latin"],
  weight: ["600"],
  display: "swap",
  variable: "--font-barlow-semi-condensed",
});

/** Hero face: Barlow Semi Condensed 700, for the landing and demo headings only (`font-hero`). Not
 * preloaded: the file loads only on the pages that use it, so the others pay nothing. */
const barlowSemiCondensedBold = Barlow_Semi_Condensed({
  subsets: ["latin"],
  weight: ["700"],
  display: "swap",
  preload: false,
  variable: "--font-barlow-semi-condensed-bold",
});

export const metadata: Metadata = {
  title: { default: BRAND_NAME, template: `%s · ${BRAND_NAME}` },
  description: BRAND_DESCRIPTION,
  applicationName: BRAND_NAME,
};

/** The browser chrome starts on the dark default's ground; ThemeToggle repaints it when light is
 * pinned (components/ui/theme-toggle.tsx). */
export const viewport: Viewport = {
  themeColor: THEME_COLORS[DEFAULT_THEME],
  colorScheme: "dark light",
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="it"
      className={`${barlow.variable} ${barlowSemiCondensed.variable} ${barlowSemiCondensedBold.variable}`}
      suppressHydrationWarning
    >
      <head>
        <ThemeScript />
      </head>
      <body>
        <IconSprite />
        {children}
      </body>
    </html>
  );
}
