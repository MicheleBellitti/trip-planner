import { BRAND_NAME } from "./brand";

/** The sign-in email, in Italian (the user reads it). Pure: lib/server/send-magic-link.ts sends it. */
export interface MagicLinkEmail {
  subject: string;
  text: string;
  html: string;
}

const MINUTE_WORDS: Record<number, string> = { 5: "cinque", 10: "dieci", 15: "quindici" };

function minutes(count: number): string {
  const word = MINUTE_WORDS[count] ?? String(count);
  return count === 1 ? "un minuto" : `${word} minuti`;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function magicLinkEmail({ url, expiresInMinutes }: { url: string; expiresInMinutes: number }): MagicLinkEmail {
  const validity = minutes(expiresInMinutes);
  const subject = `Il tuo link per entrare in ${BRAND_NAME}`;
  const text = [
    `Ecco il link per entrare in ${BRAND_NAME}:`,
    "",
    url,
    "",
    `Vale ${validity} e funziona una volta sola. Se non hai chiesto tu di entrare, ignora questo messaggio: nessuno può usare il link senza questa email.`,
  ].join("\n");
  const safeUrl = escapeHtml(url);
  const html = [
    `<p>Ecco il link per entrare in ${escapeHtml(BRAND_NAME)}:</p>`,
    `<p><a href="${safeUrl}">Entra in ${escapeHtml(BRAND_NAME)}</a></p>`,
    `<p>Vale ${validity} e funziona una volta sola. Se non hai chiesto tu di entrare, ignora questo messaggio: nessuno può usare il link senza questa email.</p>`,
    `<p style="color:#5b5e66;font-size:12px">Se il pulsante non funziona, copia questo indirizzo nel browser:<br>${safeUrl}</p>`,
  ].join("\n");
  return { subject, text, html };
}
