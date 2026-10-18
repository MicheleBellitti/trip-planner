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

/** What the quota is asked for: a new plan (POST /plans) or a "Continua" (+2 $ on a paused plan). */
export type QuotaAction = "plan" | "continue";

/** The cents `action` needs under the quota (GET /me `next_plan_cents`, `continue_cents`); null
 * from a backend that predates them. */
function centsNeeded(quota: Quota, action: QuotaAction): number | null {
  const needed = action === "plan" ? quota.next_plan_cents : quota.continue_cents;
  return needed ?? null;
}

/**
 * Which limit would refuse `action` now, by the backend's own rule (app/quota.py): a new plan needs
 * a plan left (`plans_used < plans_limit`, checked first) and its budget to fit (`cents_used +
 * next_plan_cents <= cents_limit`); a "Continua" only needs its 2 $ to fit. Null when it would pass.
 * Without the needed cents (an older backend) only a month used up to the cent counts as reached.
 */
export function quotaBlocks(quota: Quota, action: QuotaAction = "plan"): "plans" | "cents" | null {
  if (action === "plan" && quota.plans_used >= quota.plans_limit) return "plans";
  const needed = centsNeeded(quota, action);
  const over = needed === null ? quota.cents_used >= quota.cents_limit : quota.cents_used + needed > quota.cents_limit;
  return over ? "cents" : null;
}

/** A limit of the month is reached: the next plan waits for the month to turn. */
export function quotaReached(quota: Quota): boolean {
  return quotaBlocks(quota, "plan") !== null;
}

/** "1 piano", "3 piani". */
export function plansWord(count: number): string {
  return `${count} ${count === 1 ? "piano" : "piani"}`;
}

/** A reached limit in the form's words (or the paused plan's, for a "Continua"): which one, the
 * figures, what the next step needs when the month is not used up to the cent, the day it turns. */
export function describeQuotaLimit(
  limit: "plans" | "cents",
  quota: Quota,
  action: QuotaAction = "plan",
): { title: string; body: string } {
  const reset = formatResetDay(quota.resets_at);
  const after = action === "plan" ? `Il prossimo si potrà creare dal ${reset}.` : `Si potrà continuare dal ${reset}.`;
  if (limit === "plans") {
    return {
      title: "Hai usato i piani di questo mese",
      body: `Questo mese hai creato ${plansWord(quota.plans_used)} su ${quota.plans_limit}. ${after}`,
    };
  }
  const committed = `Questo mese i tuoi piani hanno impegnato ${formatUsd(quota.cents_used)} su ${formatUsd(quota.cents_limit)}`;
  const needed = centsNeeded(quota, action);
  if (quota.cents_used >= quota.cents_limit || needed === null) {
    return { title: "Hai usato il budget di questo mese", body: `${committed}. ${after}` };
  }
  // Not used up to the cent: the next step's own budget is what does not fit.
  const left = formatUsd(Math.max(0, quota.cents_limit - quota.cents_used));
  const what = action === "plan" ? `un nuovo piano ne impegna ${formatUsd(needed)}` : `continuare ne impegna ${formatUsd(needed)}`;
  return {
    title: action === "plan" ? "Il budget del mese non basta per un altro piano" : "Il budget del mese non basta per continuare",
    body: `${committed}: ne restano ${left} e ${what}. ${after}`,
  };
}

/** Said before the user fills the form: GET /me's month would refuse a new plan (null while it
 * would not). The plans come first, like the backend's own check. */
export function describeQuotaStanding(quota: Quota, action: QuotaAction = "plan"): { title: string; body: string } | null {
  const limit = quotaBlocks(quota, action);
  return limit === null ? null : describeQuotaLimit(limit, quota, action);
}

/** The quota's refusal in the form's own words (or the paused plan's): which limit, the figures,
 * when it turns. */
export function describeQuotaRefusal(error: QuotaReachedError, action: QuotaAction = "plan"): SubmitFailure {
  const title = error.limit === "plans" ? "Hai usato i piani di questo mese" : "Hai usato il budget di questo mese";
  const described = error.quota ? describeQuotaLimit(error.limit, error.quota, action) : { title, body: error.message };
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

/** "1 secondo", "30 secondi", "un minuto", "10 minuti": a Retry-After in words. */
export function waitWords(seconds: number): string {
  if (seconds < 60) return seconds === 1 ? "1 secondo" : `${seconds} secondi`;
  const minutes = Math.ceil(seconds / 60);
  return minutes === 1 ? "un minuto" : `${minutes} minuti`;
}
