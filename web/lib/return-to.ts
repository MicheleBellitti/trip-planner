import { ROUTES } from "./routes";

/**
 * Where to send the user after they sign in: the `returnTo` the API client put on the login URL
 * (lib/api.ts `loginUrl`, the full URL of the page a 401 interrupted), reduced to a same-origin
 * path. Anything else (another origin, a protocol-relative `//host`, a backslash trick, a
 * non-http scheme, garbage) becomes the plans list, so the login page can never be used to
 * bounce someone to a site of the attacker's choosing.
 *
 * The `//` check runs on the parsed path, not on the input: dot segments and their encoded forms
 * (`/.//evil.com`, `/a/..//evil.com`, `/%2e//evil.com`) and an empty first segment after this
 * origin (`https://<host>//evil.com`) all normalise to a path that starts with `//`, which a
 * redirect would read as another host.
 *
 * `origin` is this app's origin (`window.location.origin` in the browser, Better Auth's base URL
 * on the server). The result always starts with a single `/` and keeps the query and the hash.
 */
export function safeReturnTo(raw: string | null | undefined, origin: string): string {
  const fallback: string = ROUTES.plans;
  const value = raw?.trim();
  if (!value) return fallback;
  if (value.includes("\\")) return fallback;
  let url: URL;
  try {
    url = new URL(value, origin);
  } catch {
    return fallback;
  }
  if (url.origin !== new URL(origin).origin) return fallback;
  if (url.pathname.startsWith("//") || url.pathname.startsWith("/\\")) return fallback;
  if (url.pathname === ROUTES.login) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}
