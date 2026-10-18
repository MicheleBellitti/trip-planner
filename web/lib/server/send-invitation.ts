import "server-only";

import { invitationEmail } from "@/lib/invitation-email";
import { ROUTES } from "@/lib/routes";

import type { AuthServerConfig } from "./auth-config";
import { sendEmail } from "./send-email";

/** Sends the invitation to `email`: the login page's address, and the invited address named in
 * the body (lib/invitation-email.ts). */
export async function sendInvitation(config: AuthServerConfig, { email }: { email: string }): Promise<void> {
  const message = invitationEmail({ loginUrl: `${config.baseUrl}${ROUTES.login}`, email });
  await sendEmail(config, { to: email, ...message }, { purpose: "invitation" });
}
