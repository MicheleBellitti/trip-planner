import { describe, expect, it } from "vitest";

import { ApiError, MonthlyLimitError, QuotaReachedError, RateLimitedError } from "@/lib/api";

import { describeSubmitFailure, formatResetDay, waitWords } from "./failure";

describe("describeSubmitFailure", () => {
  it("says the monthly limit with the backend's figures and no 'send it again'", () => {
    const message = "Questo mese sono già stati spesi 98,40 $ su 100,00 $: il prossimo piano si potrà creare il mese prossimo.";
    const failure = describeSubmitFailure(
      new MonthlyLimitError({ status: 429, code: "monthly_limit_reached", message, data: { spent_cents: 9840, limit_cents: 10000 } }),
    );
    expect(failure).toEqual({ title: "Limite di spesa del mese raggiunto", body: message });
  });

  it("says the planner is not ready (503) and that the request is kept", () => {
    const message = "Il planner non è pronto in questo momento: nessun costo è stato addebitato. Riprova più tardi.";
    const failure = describeSubmitFailure(
      new ApiError({ kind: "planner_unavailable", status: 503, code: "planner_unavailable", message }),
    );
    expect(failure.title).toBe("Il planner non è pronto");
    expect(failure.body).toBe(`${message} La richiesta resta qui, pronta da inviare di nuovo.`);
  });

  it("tells a demo scenario sent to a backend without DEMO_MODE what to change", () => {
    const failure = describeSubmitFailure(
      new ApiError({
        kind: "not_found",
        status: 404,
        code: "demo_unavailable",
        message: "La modalità demo non è attiva su questo server.",
      }),
    );
    expect(failure.title).toBe("Modalità demo non attiva");
    expect(failure.body).toContain("Scegli «Nessuno» come scenario demo e riprova.");
  });

  it("covers the network, the auth check and anything unexpected, in Italian", () => {
    expect(describeSubmitFailure(new ApiError({ kind: "network", status: 0 })).title).toBe("Planner non raggiungibile");
    expect(describeSubmitFailure(new ApiError({ kind: "auth_unavailable", status: 503 })).title).toBe("Accesso non verificato");
    expect(describeSubmitFailure(new ApiError({ kind: "agents_unavailable", status: 502 })).title).toBe(
      "Il piano non è partito",
    );
    const unknown = describeSubmitFailure(new TypeError("boom"));
    expect(unknown.title).toBe("Il piano non è partito");
    expect(unknown.body).not.toContain("boom");
  });
});

describe("the economics' refusals", () => {
  const quota = { plans_used: 10, plans_limit: 10, cents_used: 1234, cents_limit: 1500, resets_at: "2026-11-01T00:00:00+01:00" };

  it("says which limit the quota hit, with the figures and the day the month turns", () => {
    const plans = describeSubmitFailure(new QuotaReachedError({ status: 429, code: "quota_plans_reached", message: "x", data: quota }));
    expect(plans).toEqual({
      title: "Hai usato i piani di questo mese",
      body: "Questo mese hai creato 10 piani su 10. Il prossimo si potrà creare dal 1° novembre.",
    });
    const cents = describeSubmitFailure(new QuotaReachedError({ status: 429, code: "quota_cents_reached", message: "x", data: quota }));
    expect(cents.title).toBe("Hai usato il budget di questo mese");
    expect(cents.body).toBe("Questo mese i tuoi piani hanno impegnato 12,34 $ su 15,00 $. Il prossimo si potrà creare dal 1° novembre.");
    // Without the figures (an older backend), the backend's own sentence.
    const bare = describeSubmitFailure(new QuotaReachedError({ status: 429, code: "quota_plans_reached", message: "Basta così.", data: null }));
    expect(bare.body).toBe("Basta così.");
  });

  it("says how long to wait after a burst, and keeps the request", () => {
    const failure = describeSubmitFailure(new RateLimitedError({ status: 429, code: "too_many_requests", message: "x", data: { retry_after_seconds: 90 } }, 90));
    expect(failure.title).toBe("Troppe richieste");
    expect(failure.body).toBe("Hai inviato molte richieste in poco tempo: aspetta 2 minuti e riprova. La richiesta resta qui, pronta da inviare di nuovo.");
    expect(waitWords(30)).toBe("30 secondi");
    expect(waitWords(60)).toBe("un minuto");
    expect(waitWords(600)).toBe("10 minuti");
  });

  it("says the planner is full (503) with the backend's sentence", () => {
    const message = "Il planner è al completo in questo momento: riprova tra qualche minuto. Nessun costo è stato addebitato.";
    const failure = describeSubmitFailure(new ApiError({ kind: "planner_busy", status: 503, code: "planner_busy", message }));
    expect(failure.title).toBe("Il planner è al completo");
    expect(failure.body).toContain(message);
  });

  it("writes the reset day in Italian, in Rome", () => {
    expect(formatResetDay("2026-11-01T00:00:00+01:00")).toBe("1° novembre");
    expect(formatResetDay("2026-12-01T00:00:00+01:00")).toBe("1° dicembre");
    expect(formatResetDay("2026-10-31T23:30:00Z")).toBe("1° novembre"); // 00:30 in Rome
  });
});
