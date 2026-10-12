import { describe, expect, it } from "vitest";

import { ApiError, MonthlyLimitError } from "@/lib/api";

import { describeSubmitFailure } from "./failure";

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
