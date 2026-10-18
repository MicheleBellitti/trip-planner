/**
 * What the request form says when POST /plans fails for a reason that is not a field: what
 * happened (the title), the backend's own Italian message, and what was kept. Also the words of
 * the month's quota before the press, when GET /me already says it is used up.
 */

import type { NoticeTone } from "@/components/ui/notice";
import { ApiError, MonthlyLimitError, QuotaReachedError, RateLimitedError } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import type { Quota } from "@/lib/schemas/api";

export interface SubmitFailure {
  title: string;
  body: string;
  /** `warning` for a refusal by rule (the quota, the ceiling, the planner full, a burst): nothing
   * failed, so it is not red (DESIGN.md, Notice). `error` for everything that did. */
  tone: NoticeTone;
  /** The user's own month is used up: the standing notice would say the same, so one is enough. */
  quota: boolean;
}

/** Nothing typed is lost when a plan does not start: the form keeps every value. */
const KEPT = "La richiesta resta qui, pronta da inviare di nuovo.";

const TITLES: Partial<Record<ApiError["kind"], string>> = {
  planner_busy: "Il planner è al completo",
  rate_limited: "Un momento",
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

/** A limit of the month is reached: the next plan waits for the month to turn. */
export function quotaReached(quota: Quota): boolean {
  return quota.plans_used >= quota.plans_limit || quota.cents_used >= quota.cents_limit;
}

/** A reached limit in the form's words: which one, the figures, the day the month turns. */
export function describeQuotaLimit(limit: "plans" | "cents", quota: Quota): { title: string; body: string } {
  const title = limit === "plans" ? "Hai usato i piani di questo mese" : "Hai usato il budget di questo mese";
  const figures =
    limit === "plans"
      ? `Questo mese hai creato ${quota.plans_used} piani su ${quota.plans_limit}.`
      : `Questo mese i tuoi piani hanno impegnato ${formatUsd(quota.cents_used)} su ${formatUsd(quota.cents_limit)}.`;
  return { title, body: `${figures} Il prossimo si potrà creare dal ${formatResetDay(quota.resets_at)}.` };
}

/** Said before the user fills the form: the month GET /me reported is used up (null while it is
 * not). The plans come first, like the backend's own check. */
export function describeQuotaStanding(quota: Quota): { title: string; body: string } | null {
  if (quota.plans_used >= quota.plans_limit) return describeQuotaLimit("plans", quota);
  if (quota.cents_used >= quota.cents_limit) return describeQuotaLimit("cents", quota);
  return null;
}

/** The quota's refusal in the form's own words: which limit, the figures, when it turns. */
export function describeQuotaRefusal(error: QuotaReachedError): SubmitFailure {
  const title = error.limit === "plans" ? "Hai usato i piani di questo mese" : "Hai usato il budget di questo mese";
  const described = error.quota ? describeQuotaLimit(error.limit, error.quota) : { title, body: error.message };
  return { ...described, tone: "warning", quota: true };
}

/** "1° novembre": the day the month turns, in Italian, from the backend's instant. */
export function formatResetDay(iso: string): string {
  const day = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "long", timeZone: "Europe/Rome" }).format(new Date(iso));
  return day.replace(/^1 /, "1° ");
}

export function describeSubmitFailure(error: unknown): SubmitFailure {
  if (error instanceof MonthlyLimitError) {
    // The message says when the next plan can start; "send it again" would be wrong today.
    return { title: "Limite di spesa del mese raggiunto", body: error.message, tone: "warning", quota: false };
  }
  if (error instanceof QuotaReachedError) {
    return describeQuotaRefusal(error);
  }
  if (error instanceof RateLimitedError) {
    const wait = error.retryAfterSeconds === null ? "un momento" : waitWords(error.retryAfterSeconds);
    return {
      title: TITLES.rate_limited ?? "Un momento",
      body: `Hai inviato molte richieste in poco tempo: aspetta ${wait} e riprova. ${KEPT}`,
      tone: "warning",
      quota: false,
    };
  }
  if (error instanceof ApiError && error.kind === "planner_busy") {
    // The backend's sentence would repeat the title: the form's own words, same facts.
    return {
      title: TITLES.planner_busy ?? "Il planner è al completo",
      body: `Tutti i posti sono occupati in questo momento: riprova tra qualche minuto. Nessun costo è stato addebitato. ${KEPT}`,
      tone: "warning",
      quota: false,
    };
  }
  if (error instanceof ApiError) {
    const title = (error.code ? CODE_TITLES[error.code] : undefined) ?? TITLES[error.kind] ?? "Il piano non è partito";
    const hint = error.code === "demo_unavailable" ? " Scegli «Nessuno» come scenario demo e riprova." : "";
    return { title, body: `${error.message}${hint} ${KEPT}`, tone: "error", quota: false };
  }
  return { title: "Il piano non è partito", body: `Qualcosa è andato storto. Riprova. ${KEPT}`, tone: "error", quota: false };
}

/** "30 secondi", "un minuto", "10 minuti": a Retry-After in words. */
export function waitWords(seconds: number): string {
  if (seconds < 60) return `${seconds} secondi`;
  const minutes = Math.ceil(seconds / 60);
  return minutes === 1 ? "un minuto" : `${minutes} minuti`;
}
