import type { Metadata } from "next";

import { LandingHero } from "@/components/landing/landing-hero";
import { PublicHeader } from "@/components/landing/public-header";
import { SkipLandingScript } from "@/components/landing/skip-landing-script";
import { BRAND_NAME, BRAND_TAGLINE } from "@/lib/brand";

/** Absolute: the root layout's "%s · Atlas" template would put the name last. */
export const metadata: Metadata = { title: { absolute: `${BRAND_NAME} · ${BRAND_TAGLINE}` } };

/**
 * "/": the public landing (brand spec, section 2), prerendered with no client fetch. A returning,
 * signed-in visitor is sent to /plans before it paints (SkipLandingScript, first in the markup).
 */
export default function LandingPage() {
  return (
    <>
      <SkipLandingScript />
      <PublicHeader />
      <main>
        <LandingHero />
      </main>
    </>
  );
}
