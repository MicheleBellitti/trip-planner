import { magicLinkClient } from "better-auth/client/plugins";
import { createAuthClient } from "better-auth/react";

/** The browser side of the app's own accounts (lib/auth.ts): same origin, default base path. */
export const authClient = createAuthClient({ plugins: [magicLinkClient()] });
