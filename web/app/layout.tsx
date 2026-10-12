import type { Metadata, Viewport } from "next";
import { Barlow, Barlow_Semi_Condensed } from "next/font/google";
import type { ReactNode } from "react";

import { IconSprite } from "@/components/ui/icon-sprite";
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

export const metadata: Metadata = {
  title: { default: BRAND_NAME, template: `%s · ${BRAND_NAME}` },
  description: BRAND_DESCRIPTION,
  applicationName: BRAND_NAME,
};

/** The browser chrome matches the ground token of each system theme. */
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f2f4f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0c121b" },
  ],
  colorScheme: "light dark",
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="it" className={`${barlow.variable} ${barlowSemiCondensed.variable}`} suppressHydrationWarning>
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
