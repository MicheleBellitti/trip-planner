/**
 * Where the app's pages live, so no link spells a path by hand (components/ui/invariants.test.ts).
 * The brand spec (docs/superpowers/specs/2026-10-14-atlas-brand-design.md) gives "/" to the public
 * landing and the plans list to "/plans" (step 2), and adds the public demo at "/demo" (step 3).
 */
export const ROUTES = {
  home: "/",
  plans: "/plans",
  newPlan: "/new",
  evals: "/evals",
  demo: "/demo",
} as const;

/** The public demo run (step 3) does not exist yet. Until it does, the landing offers "Scopri come
 * funziona" instead of "Guarda una corsa", so no button leads to a 404. Step 3 builds /demo and
 * flips this. */
export const DEMO_READY = false;
