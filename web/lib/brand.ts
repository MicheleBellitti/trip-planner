/**
 * The brand's words, decided by Michele (web/PRODUCT.md, "Decisions"): the name on 2026-10-12, the
 * tagline on 2026-10-14. Each is spelled here and nowhere else (components/ui/invariants.test.ts):
 * page metadata, the header lockup, the link preview and the landing read them. The repo and the
 * spec keep their own names.
 */
export const BRAND_NAME = "Atlas";

/** The line of the brand: the landing hero, the metadata, the link preview, the empty plans list. */
export const BRAND_TAGLINE = "Ogni viaggio ha il suo atlante.";

/** The page description and the landing's lede (Italian, sentence case). */
export const BRAND_DESCRIPTION =
  "Da Milano a Lisbona in un pomeriggio di lavoro, fatto da altri. Cinque agenti AI tracciano voli, alloggio, attività e spostamenti, e ti lasciano un piano con le date entro cui prenotare.";

/** The production origin: absolute URLs in metadata (the link preview image) start here. */
export const BRAND_URL = "https://atlas.bellittim.com";
