import { BRAND_NAME } from "./brand";
import { escapeHtml } from "./magic-link-email";

/**
 * The invitation, in Italian (the person reads it). Pure: lib/server/send-invitation.ts sends it.
 * The link is the plain login page: the address is named in the body, never put in a URL (URLs
 * end up in browser histories and server logs; an email address should not).
 */
export interface InvitationEmail {
  subject: string;
  text: string;
  html: string;
}

export function invitationEmail({ loginUrl, email }: { loginUrl: string; email: string }): InvitationEmail {
  const subject = `Hai un invito per ${BRAND_NAME}`;
  const text = [
    `Hai un invito per ${BRAND_NAME}: descrivi un viaggio e cinque agenti lo preparano mentre li guardi lavorare, con le date entro cui prenotare.`,
    "",
    `Per entrare apri la pagina di accesso e usa questo indirizzo: ${email}`,
    "",
    loginUrl,
    "",
    `Ti arriverà un link per entrare, senza password. Se non sai di cosa si tratta, ignora questo messaggio: senza questo indirizzo email nessuno può usare l'invito.`,
  ].join("\n");
  const safeUrl = escapeHtml(loginUrl);
  const html = [
    `<p>Hai un invito per ${escapeHtml(BRAND_NAME)}: descrivi un viaggio e cinque agenti lo preparano mentre li guardi lavorare, con le date entro cui prenotare.</p>`,
    `<p>Per entrare apri la pagina di accesso e usa questo indirizzo: <strong>${escapeHtml(email)}</strong>.</p>`,
    `<p><a href="${safeUrl}">Entra in ${escapeHtml(BRAND_NAME)}</a></p>`,
    `<p>Ti arriverà un link per entrare, senza password. Se non sai di cosa si tratta, ignora questo messaggio: senza questo indirizzo email nessuno può usare l'invito.</p>`,
    `<p style="color:#5b5e66;font-size:12px">Se il pulsante non funziona, copia questo indirizzo nel browser:<br>${safeUrl}</p>`,
  ].join("\n");
  return { subject, text, html };
}
