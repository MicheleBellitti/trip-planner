import "server-only";

import { magicLinkEmail } from "@/lib/magic-link-email";

import type { AuthServerConfig } from "./auth-config";
import { sendEmail } from "./send-email";

export const MAGIC_LINK_MINUTES = 5;

/** Sends the sign-in link (lib/server/send-email.ts: Resend, or the console in development). */
export async function sendMagicLink(config: AuthServerConfig, { email, url }: { email: string; url: string }): Promise<void> {
  const message = magicLinkEmail({ url, expiresInMinutes: MAGIC_LINK_MINUTES });
  await sendEmail(config, { to: email, ...message }, { purpose: "sign-in" });
}
