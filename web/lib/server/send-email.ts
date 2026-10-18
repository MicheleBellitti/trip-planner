import "server-only";

import { Resend } from "resend";

import type { AuthServerConfig } from "./auth-config";

export interface OutgoingEmail {
  to: string;
  subject: string;
  text: string;
  html: string;
}

/**
 * Sends one transactional email through Resend, from AUTH_EMAIL_FROM. Without an email
 * configuration (development only: `readAuthConfig` refuses that in production) the message is
 * printed to the server console instead, so every flow runs locally with no account at Resend.
 * `purpose` names the message in that print and in errors; the address is never logged.
 */
export async function sendEmail(config: AuthServerConfig, email: OutgoingEmail, { purpose }: { purpose: string }): Promise<void> {
  if (config.email === null) {
    console.info(`[auth] ${purpose} email (development, no RESEND_API_KEY):\n${email.subject}\n\n${email.text}`);
    return;
  }
  const resend = new Resend(config.email.apiKey);
  const { error } = await resend.emails.send({
    from: config.email.from,
    to: email.to,
    subject: email.subject,
    text: email.text,
    html: email.html,
  });
  if (error) {
    // Resend's message names the problem (domain, key, quota), never the recipient.
    throw new Error(`Resend refused the ${purpose} email: ${error.name} ${error.message}`);
  }
}
