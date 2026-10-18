import "server-only";

import { Resend } from "resend";

import { magicLinkEmail } from "@/lib/magic-link-email";

import type { AuthServerConfig } from "./auth-config";

export const MAGIC_LINK_MINUTES = 5;

/**
 * Sends the sign-in link through Resend. Without an email configuration (development only:
 * `readAuthConfig` refuses that in production) the link is printed to the server console, so
 * the whole flow runs locally with no account at Resend. The address is never logged.
 */
export async function sendMagicLink(config: AuthServerConfig, { email, url }: { email: string; url: string }): Promise<void> {
  const message = magicLinkEmail({ url, expiresInMinutes: MAGIC_LINK_MINUTES });
  if (config.email === null) {
    console.info(`[auth] magic link (development, no RESEND_API_KEY):\n${url}`);
    return;
  }
  const resend = new Resend(config.email.apiKey);
  const { error } = await resend.emails.send({
    from: config.email.from,
    to: email,
    subject: message.subject,
    text: message.text,
    html: message.html,
  });
  if (error) {
    // Resend's message names the problem (domain, key, quota), never the recipient.
    throw new Error(`Resend refused the sign-in email: ${error.name} ${error.message}`);
  }
}
