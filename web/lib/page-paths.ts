/**
 * The pages with an id in their path, built from ROUTES. Apart from lib/routes.ts so the pages that
 * only link to the sections do not ship them (the bundler keeps every export of a module it loads).
 */
import { ROUTES } from "./routes";

/** A plan's page. The id is one path segment, whatever it holds. */
export const planPath = (id: string): string => `${ROUTES.plans}/${encodeURIComponent(id)}`;

/** An eval run's page. */
export const evalRunPath = (id: string): string => `${ROUTES.evals}/${encodeURIComponent(id)}`;
