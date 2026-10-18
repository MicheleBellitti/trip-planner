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
  /** The app's own sign-in (Better Auth, lib/auth.ts); takes `?returnTo=<same-origin page>`. */
  login: "/login",
  /** The waitlist and the invitations, for the users who manage the planner (GET /me `is_admin`). */
  invites: "/admin/waitlist",
} as const;

/** The public demo run exists (step 3): the landing offers "Guarda una corsa" → /demo. Off, the
 * landing falls back to "Scopri come funziona", so no button can lead to a 404. */
export const DEMO_READY = true;
