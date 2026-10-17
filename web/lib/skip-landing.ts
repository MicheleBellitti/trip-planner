/**
 * The landing skip (brand spec, "Returning visitors skip the landing"): the decision and the inline
 * script that runs it on "/" before paint. Apart from lib/returning.ts so only the landing ships
 * these strings; the API client imports just the mark's two functions.
 */
import { SIGNED_IN_KEY } from "./returning";
import { ROUTES } from "./routes";

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
