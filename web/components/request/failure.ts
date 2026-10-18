/**
 * What the request form says when POST /plans fails for a reason that is not a field: what
 * happened (the title), the backend's own Italian message, and what was kept.
 */

import { ApiError, MonthlyLimitError, QuotaReachedError, RateLimitedError } from "@/lib/api";
import { formatUsd } from "@/lib/format";

export interface SubmitFailure {
  title: string;
  body: string;
}

/** Nothing typed is lost when a plan does not start: the form keeps every value. */
const KEPT = "La richiesta resta qui, pronta da inviare di nuovo.";

const TITLES: Partial<Record<ApiError["kind"], string>> = {
  planner_busy: "Il planner è al completo",
  rate_limited: "Troppe richieste",
  planner_unavailable: "Il planner non è pronto",
  agents_unavailable: "Il piano non è partito",
  auth_unavailable: "Accesso non verificato",
  network: "Planner non raggiungibile",
  forbidden: "Account non abilitato",
  invalid_response: "Risposta inattesa dal planner",
  server: "Il piano non è partito",
};

const CODE_TITLES: Readonly<Record<string, string>> = {
  demo_unavailable: "Modalità demo non attiva",
  request_too_large: "Richiesta troppo lunga",
  bad_origin: "Richiesta rifiutata",
};

/** The quota's refusal in the form's own words: which limit, the figures, when it turns. */
export function describeQuotaRefusal(error: QuotaReachedError): SubmitFailure {
  const title = error.limit === "plans" ? "Hai usato i piani di questo mese" : "Hai usato il budget di questo mese";
  if (!error.quota) return { title, body: error.message };
  const { plans_used, plans_limit, cents_used, cents_limit, resets_at } = error.quota;
  const figures =
    error.limit === "plans"
      ? `Questo mese hai creato ${plans_used} piani su ${plans_limit}.`
      : `Questo mese i tuoi piani hanno impegnato ${formatUsd(cents_used)} su ${formatUsd(cents_limit)}.`;
  return { title, body: `${figures} Il prossimo si potrà creare dal ${formatResetDay(resets_at)}.` };
}

/** "1° novembre": the day the month turns, in Italian, from the backend's instant. */
export function formatResetDay(iso: string): string {
  const day = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "long", timeZone: "Europe/Rome" }).format(new Date(iso));
  return day.replace(/^1 /, "1° ");
}

export function describeSubmitFailure(error: unknown): SubmitFailure {
  if (error instanceof MonthlyLimitError) {
    // The message says when the next plan can start; "send it again" would be wrong today.
    return { title: "Limite di spesa del mese raggiunto", body: error.message };
  }
  if (error instanceof QuotaReachedError) {
    return describeQuotaRefusal(error);
  }
  if (error instanceof RateLimitedError) {
    const wait = error.retryAfterSeconds === null ? "un momento" : waitWords(error.retryAfterSeconds);
    return { title: TITLES.rate_limited ?? "Troppe richieste", body: `Hai inviato molte richieste in poco tempo: aspetta ${wait} e riprova. ${KEPT}` };
  }
  if (error instanceof ApiError) {
    const title = (error.code ? CODE_TITLES[error.code] : undefined) ?? TITLES[error.kind] ?? "Il piano non è partito";
    const hint = error.code === "demo_unavailable" ? " Scegli «Nessuno» come scenario demo e riprova." : "";
    return { title, body: `${error.message}${hint} ${KEPT}` };
  }
  return { title: "Il piano non è partito", body: `Qualcosa è andato storto. Riprova. ${KEPT}` };
}

/** "30 secondi", "un minuto", "10 minuti": a Retry-After in words. */
export function waitWords(seconds: number): string {
  if (seconds < 60) return `${seconds} secondi`;
  const minutes = Math.ceil(seconds / 60);
  return minutes === 1 ? "un minuto" : `${minutes} minuti`;
}
