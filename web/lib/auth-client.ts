import { magicLinkClient } from "better-auth/client/plugins";
import { createAuthClient } from "better-auth/react";

import { markSignedOut } from "./returning";

/** A successful sign-out, whoever asked for it, forgets what this browser remembers about the
 * account: the returning-visitor mark and the tab's admin flag (lib/returning.ts). */
export function forgetOnSignOut({ request }: { request: { url: URL | string } }): void {
  if (/\/sign-out(?:[?#]|$)/.test(String(request.url))) markSignedOut();
}

/** The browser side of the app's own accounts (lib/auth.ts): same origin, default base path. */
export const authClient = createAuthClient({
  plugins: [magicLinkClient()],
  fetchOptions: { onSuccess: forgetOnSignOut },
});
