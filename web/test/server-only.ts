/**
 * Stands in for the `server-only` package under vitest (vitest.config.mts aliases it here): the
 * real package throws when imported outside React Server Components, which is right in the app
 * and wrong in a unit test of a server module.
 */
export {};
