/**
 * Where the app's pages live, so no link spells a path by hand (components/ui/invariants.test.ts).
 * Step 2 of the brand spec (docs/superpowers/specs/2026-10-14-atlas-brand-design.md) moves the
 * plans list from "/" to "/plans" and gives "/" to the public landing: that move is this file.
 */
export const ROUTES = {
  plans: "/",
  newPlan: "/new",
  evals: "/evals",
  /** The app's own sign-in (Better Auth, lib/auth.ts); takes `?returnTo=<same-origin page>`. */
  login: "/login",
} as const;
