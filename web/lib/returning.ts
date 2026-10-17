/**
 * Returning visitors skip the landing (brand spec, "Returning visitors skip the landing"). The API
 * client marks the browser after a successful authenticated call and clears the mark on a 401. An
 * inline script on "/" (components/landing/skip-landing-script.tsx) reads it before paint. The
 * mark holds no personal data, and every storage access fails safe to "show the landing".
 */
import { ROUTES } from "./routes";

export const SIGNED_IN_KEY = "atlas-signed-in";

export function markSignedIn(): void {
  try {
    localStorage.setItem(SIGNED_IN_KEY, "1");
  } catch {
    // Storage blocked: the landing simply shows next time.
  }
}

export function markSignedOut(): void {
  try {
    localStorage.removeItem(SIGNED_IN_KEY);
  } catch {
    // Storage blocked: nothing was stored either.
  }
}

/** The decision, as ES5 source so the inline script and the tests run the same code. It returns
 * the plans' path when the mark is set and the visitor did not come from a page of this site (a
 * bookmark, a typed URL, the login coming back), else null. */
export const SKIP_LANDING_DECISION = `function(storage,referrer,origin){try{if(storage.getItem(${JSON.stringify(
  SIGNED_IN_KEY,
)})!=="1")return null;var from="";try{from=referrer?new URL(referrer).origin:""}catch(e){}return from===origin?null:${JSON.stringify(
  ROUTES.plans,
)}}catch(e){return null}}`;

/** The inline script on "/": run the decision and leave before the landing paints. Silent when
 * storage cannot even be reached. */
export const SKIP_LANDING_BOOTSTRAP = `(function(){try{var to=(${SKIP_LANDING_DECISION})(window.localStorage,document.referrer,location.origin);if(to)location.replace(to)}catch(e){}})()`;
