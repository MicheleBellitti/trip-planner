/**
 * What the request form says when POST /plans fails for a reason that is not a field: what
 * happened (the title), the backend's own Italian message, and what was kept.
 */

import { ApiError, MonthlyLimitError } from "@/lib/api";

export interface SubmitFailure {
  title: string;
  body: string;
}

/** Nothing typed is lost when a plan does not start: the form keeps every value. */
const KEPT = "La richiesta resta qui, pronta da inviare di nuovo.";

const TITLES: Partial<Record<ApiError["kind"], string>> = {
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

export function describeSubmitFailure(error: unknown): SubmitFailure {
  if (error instanceof MonthlyLimitError) {
    // The message says when the next plan can start; "send it again" would be wrong today.
    return { title: "Limite di spesa del mese raggiunto", body: error.message };
  }
  if (error instanceof ApiError) {
    const title = (error.code ? CODE_TITLES[error.code] : undefined) ?? TITLES[error.kind] ?? "Il piano non è partito";
    const hint = error.code === "demo_unavailable" ? " Scegli «Nessuno» come scenario demo e riprova." : "";
    return { title, body: `${error.message}${hint} ${KEPT}` };
  }
  return { title: "Il piano non è partito", body: `Qualcosa è andato storto. Riprova. ${KEPT}` };
}
