import { describe, expect, it } from "vitest";

import { planRequestErrorCodes, planRequestJsonSchema } from "./schemas/generated/request";
import {
  buildPlanRequest,
  childAgePath,
  emptyRequestForm,
  exampleRequestForm,
  fieldConstraints,
  fieldErrorsFromServer,
  MAX_NIGHTS,
  MAX_TRIP_DAYS,
  monthLabel,
  REQUEST_ERROR_MESSAGES,
  REQUEST_FIELD_COPY,
  REQUEST_FIELDS,
  requestErrorMessage,
  todayInRome,
  validatePlanRequest,
  validateRequestForm,
  type RequestFormValues,
} from "./request-form";

/** "Today" of the backend's tests: 2026-10-12 in Rome. */
const TODAY = "2026-10-12";

function request(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    origin: "Milano",
    destination: "Lisbona",
    dates: { exact_start: "2026-11-14", exact_end: "2026-11-17" },
    travelers: [{ kind: "adult" }, { kind: "adult" }, { kind: "child", age: 7 }],
    budget_eur: 1500,
    preferences: "Niente voli prima delle 8, cucina locale.",
    ...overrides,
  };
}

function codes(data: unknown): Set<string> {
  return new Set(validatePlanRequest(data, { today: TODAY }).map((issue) => `${issue.path}:${issue.code}`));
}

function form(overrides: Partial<RequestFormValues> = {}): RequestFormValues {
  return {
    ...emptyRequestForm(),
    origin: "Milano",
    destination: "Lisbona",
    exactStart: "2026-11-14",
    exactEnd: "2026-11-17",
    adults: 2,
    budgetEur: "1500",
    ...overrides,
  };
}

describe("metadata from schema/request.json", () => {
  it("has an Italian label for exactly the schema's fields", () => {
    expect(new Set(Object.keys(REQUEST_FIELD_COPY))).toEqual(new Set(REQUEST_FIELDS.keys()));
    for (const copy of Object.values(REQUEST_FIELD_COPY)) expect(copy.label.length).toBeGreaterThan(0);
  });

  it("reads the limits from the schema", () => {
    expect(fieldConstraints("origin")).toMatchObject({ required: true, minLength: 1, maxLength: 200 });
    expect(fieldConstraints("destination")).toMatchObject({ required: false, nullable: true, maxLength: 200 });
    expect(fieldConstraints("destination_idea").maxLength).toBe(500);
    expect(fieldConstraints("preferences").maxLength).toBe(2000);
    expect(fieldConstraints("travelers")).toMatchObject({ required: true, minItems: 1, maxItems: 9 });
    expect(fieldConstraints("travelers.kind").options).toEqual(["adult", "child"]);
    expect(fieldConstraints("travelers.age")).toMatchObject({ minimum: 0, maximum: 17, nullable: true });
    expect(fieldConstraints("dates.month").pattern).toBe("^\\d{4}-\\d{2}$");
    expect(fieldConstraints("dates.exact_start").format).toBe("date");
    expect(fieldConstraints("budget_eur")).toMatchObject({ type: "integer", exclusiveMinimum: 0 });
    expect(fieldConstraints("suggest_destination").default).toBe(false);
  });

  it("agrees with the backend on the longest trip", () => {
    expect(MAX_TRIP_DAYS).toBe(120);
    expect(planRequestJsonSchema.$defs.DateWindow.properties.nights.description).toContain(`1 to ${MAX_NIGHTS}`);
  });

  it("has an Italian message for every backend error code", () => {
    expect(new Set(Object.keys(REQUEST_ERROR_MESSAGES))).toEqual(new Set(Object.keys(planRequestErrorCodes)));
  });
});

describe("validatePlanRequest mirrors backend/app/request.py", () => {
  it("accepts the backend tests' happy paths", () => {
    expect(codes(request())).toEqual(new Set());
    expect(codes(request({ dates: { month: "2027-01", nights: 7 } }))).toEqual(new Set());
    expect(
      codes(request({ destination: null, suggest_destination: true, destination_idea: "mare a novembre, volo diretto" })),
    ).toEqual(new Set());
    expect(codes(request({ dates: { exact_start: "2026-11-14", exact_end: "2026-11-14" } }))).toEqual(new Set());
    expect(codes(request({ travelers: Array.from({ length: 9 }, () => ({ kind: "adult" })) }))).toEqual(new Set());
    expect(codes(request({ dates: { month: "2026-10", nights: MAX_NIGHTS } }))).toEqual(new Set());
    expect(codes(request({ dates: { exact_start: "2026-10-13", exact_end: "2026-10-15" } }))).toEqual(new Set());
  });

  it.each([
    ["origin", 200],
    ["destination", 200],
    ["preferences", 2000],
  ])("caps %s at %i characters", (field, limit) => {
    expect(codes(request({ [field]: "x".repeat(limit) }))).toEqual(new Set());
    expect(codes(request({ [field]: "x".repeat(limit + 1) }))).toEqual(new Set([`${field}:string_too_long`]));
  });

  it("caps the destination idea at 500 characters", () => {
    const suggest = { destination: null, suggest_destination: true };
    expect(codes(request({ ...suggest, destination_idea: "x".repeat(501) }))).toEqual(
      new Set(["destination_idea:string_too_long"]),
    );
  });

  it("requires a non-blank origin", () => {
    const missing = request();
    delete missing.origin;
    expect(codes(missing)).toEqual(new Set(["origin:missing"]));
    expect(codes(request({ origin: "  " }))).toEqual(new Set(["origin:string_too_short"]));
  });

  it("wants a positive budget", () => {
    expect(codes(request({ budget_eur: 0 }))).toEqual(new Set(["budget_eur:greater_than"]));
    expect(codes(request({ budget_eur: -100 }))).toEqual(new Set(["budget_eur:greater_than"]));
  });

  it("wants between one and nine travelers", () => {
    expect(codes(request({ travelers: [] }))).toEqual(new Set(["travelers:too_short"]));
    expect(codes(request({ travelers: Array.from({ length: 10 }, () => ({ kind: "adult" })) }))).toEqual(
      new Set(["travelers:too_long"]),
    );
  });

  it("rejects unknown fields", () => {
    expect(codes(request({ currency: "EUR", dates: { exact_start: "2026-11-14", exact_end: "2026-11-17", flexible: true } }))).toEqual(
      new Set(["currency:extra_forbidden", "dates.flexible:extra_forbidden"]),
    );
  });

  it("wants a destination or a suggestion, not both", () => {
    expect(codes(request({ destination: null }))).toEqual(new Set(["destination:destination_required"]));
    expect(codes(request({ destination: "  " }))).toEqual(new Set(["destination:destination_required"]));
    expect(codes(request({ suggest_destination: true }))).toEqual(new Set(["destination:destination_conflict"]));
  });

  it("wants an age for every child and none for adults", () => {
    expect(codes(request({ travelers: [{ kind: "adult" }, { kind: "child" }] }))).toEqual(
      new Set(["travelers.1.age:child_age_required"]),
    );
    expect(codes(request({ travelers: [{ kind: "adult" }, { kind: "child", age: "" }] }))).toEqual(
      new Set(["travelers.1.age:child_age_required"]),
    );
    expect(codes(request({ travelers: [{ kind: "adult", age: 30 }] }))).toEqual(
      new Set(["travelers.0.age:adult_age_not_allowed"]),
    );
    expect(codes(request({ travelers: [{ kind: "adult" }, { kind: "child", age: 18 }] }))).toEqual(
      new Set(["travelers.1.age:less_than_equal"]),
    );
    expect(codes(request({ travelers: [{ kind: "infant", age: 1 }] }))).toEqual(new Set(["travelers.0.kind:literal_error"]));
  });

  it("wants at least one adult, reported with other independent problems", () => {
    expect(codes(request({ destination: null, travelers: [{ kind: "child", age: 9 }] }))).toEqual(
      new Set(["destination:destination_required", "travelers:adult_required"]),
    );
  });

  it("wants fixed dates or a month and nights", () => {
    expect(codes(request({ dates: {} }))).toEqual(new Set(["dates:dates_required"]));
    expect(codes(request({ dates: { exact_start: "2026-11-14", exact_end: "2026-11-17", month: "2026-11", nights: 3 } }))).toEqual(
      new Set(["dates:dates_conflict"]),
    );
    expect(codes(request({ dates: { exact_start: "2026-11-14", nights: 3 } }))).toEqual(new Set(["dates:dates_conflict"]));
    expect(codes(request({ dates: { exact_start: "2026-11-14" } }))).toEqual(new Set(["dates.exact_end:exact_end_required"]));
    expect(codes(request({ dates: { exact_end: "2026-11-14" } }))).toEqual(new Set(["dates.exact_start:exact_start_required"]));
  });

  it("checks fixed dates: order, length, in the future", () => {
    expect(codes(request({ dates: { exact_start: "2026-11-14", exact_end: "2026-11-13" } }))).toEqual(
      new Set(["dates.exact_end:end_before_start"]),
    );
    // 2026-11-01 -> 2027-02-28 is 119 nights (the most); one more is 120 days and a night too many.
    expect(codes(request({ dates: { exact_start: "2026-11-01", exact_end: "2027-03-01" } }))).toEqual(
      new Set(["dates.exact_end:trip_too_long"]),
    );
    expect(codes(request({ dates: { exact_start: "2026-11-01", exact_end: "2027-02-28" } }))).toEqual(new Set());
    for (const start of ["2026-10-12", "2026-10-11", "2026-08-30"]) {
      expect(codes(request({ dates: { exact_start: start, exact_end: "2026-11-20" } }))).toEqual(
        new Set(["dates.exact_start:start_not_in_future"]),
      );
    }
    expect(codes(request({ dates: { exact_start: "2026-10-01" } }))).toEqual(
      new Set(["dates.exact_start:start_not_in_future", "dates.exact_end:exact_end_required"]),
    );
    expect(codes(request({ dates: { exact_start: "2026-02-30", exact_end: "2026-03-02" } }))).toEqual(
      new Set(["dates.exact_start:date_parsing"]),
    );
  });

  it("checks flexible dates: month format, month exists, this month or later, nights", () => {
    expect(codes(request({ dates: { month: "2026-11" } }))).toEqual(new Set(["dates.nights:nights_required"]));
    expect(codes(request({ dates: { nights: 4 } }))).toEqual(new Set(["dates.month:month_required"]));
    expect(codes(request({ dates: { month: " ", nights: 4 } }))).toEqual(new Set(["dates.month:month_required"]));
    for (const month of ["2026-13", "2026-00"]) {
      expect(codes(request({ dates: { month, nights: 4 } }))).toEqual(new Set(["dates.month:invalid_month"]));
    }
    for (const month of ["2026-1", "11-2026", "2026/11", "novembre", "2026-١١"]) {
      expect(codes(request({ dates: { month, nights: 4 } }))).toEqual(new Set(["dates.month:string_pattern_mismatch"]));
    }
    for (const month of ["2026-09", "2025-12"]) {
      expect(codes(request({ dates: { month, nights: 4 } }))).toEqual(new Set(["dates.month:month_in_past"]));
    }
    expect(codes(request({ dates: { month: "2026-11", nights: 0 } }))).toEqual(new Set(["dates.nights:greater_than"]));
    expect(codes(request({ dates: { month: "2026-11", nights: MAX_NIGHTS + 1 } }))).toEqual(
      new Set(["dates.nights:trip_too_long"]),
    );
  });

  it("uses today's date in Rome", () => {
    // 23:30 UTC on Oct 12 is already Oct 13 in Rome.
    const lateEvening = new Date("2026-10-12T23:30:00Z");
    expect(todayInRome(lateEvening)).toBe("2026-10-13");
    expect(todayInRome(new Date("2026-10-12T10:00:00Z"))).toBe("2026-10-12");
    const today = todayInRome(lateEvening);
    expect(
      validatePlanRequest(request({ dates: { exact_start: "2026-10-13", exact_end: "2026-10-15" } }), { today }).map(
        (issue) => issue.code,
      ),
    ).toEqual(["start_not_in_future"]);
    expect(
      validatePlanRequest(request({ dates: { month: "2026-10", nights: 3 } }), { today: todayInRome(new Date("2026-10-31T23:30:00Z")) }).map(
        (issue) => issue.code,
      ),
    ).toEqual(["month_in_past"]);
  });

  it("rejects control characters but keeps tabs and new lines", () => {
    expect(codes(request({ origin: "Mila\u0000no" }))).toEqual(new Set(["origin:control_character"]));
    expect(codes(request({ destination: "\u0007Roma" }))).toEqual(new Set(["destination:control_character"]));
    expect(codes(request({ preferences: "Mare\r\nCucina locale\tok" }))).toEqual(new Set());
  });
});

describe("Italian messages", () => {
  it("fills the context and formats months", () => {
    expect(requestErrorMessage("month_in_past", { month: "2026-09", current_month: "2026-10" })).toBe(
      "Questo mese è già passato: scegli ottobre 2026 o un mese successivo.",
    );
    expect(requestErrorMessage("trip_too_long", { max_days: 120, max_nights: 119, nights: 130 })).toBe(
      "Il viaggio può durare al massimo 120 giorni (119 notti).",
    );
    expect(requestErrorMessage("string_too_long", { max_length: 200 })).toBe("Al massimo 200 caratteri.");
  });

  it("never shows a placeholder or an English message", () => {
    expect(requestErrorMessage("string_too_long")).toBe("Testo troppo lungo.");
    expect(requestErrorMessage("trip_too_long")).toBe("Il viaggio è troppo lungo.");
    expect(requestErrorMessage("something_new")).toBe("Valore non valido.");
    for (const code of Object.keys(planRequestErrorCodes)) {
      expect(requestErrorMessage(code)).not.toMatch(/\{|\}/);
    }
  });

  it("formats months in Italian", () => {
    expect(monthLabel("2027-01")).toBe("gennaio 2027");
    expect(monthLabel("2026-12")).toBe("dicembre 2026");
    expect(monthLabel("non un mese")).toBe("non un mese");
  });
});

describe("the form", () => {
  it("builds the POST /plans body: trimmed, only the chosen modes, adults then children", () => {
    const values = form({
      origin: "  Milano ",
      destination: " Lisbona ",
      destinationIdea: "leftover from 'Suggeriscimi tu'",
      month: "2026-11",
      nights: "4",
      adults: 2,
      childAges: ["7", ""],
      budgetEur: "1.500",
      preferences: "   ",
    });

    expect(buildPlanRequest(values)).toEqual({
      origin: "Milano",
      destination: "Lisbona",
      suggest_destination: false,
      dates: { exact_start: "2026-11-14", exact_end: "2026-11-17" },
      travelers: [{ kind: "adult" }, { kind: "adult" }, { kind: "child", age: 7 }, { kind: "child" }],
      budget_eur: 1500,
    });
    expect(buildPlanRequest({ ...values, dateMode: "flexible", suggestDestination: true }).dates).toEqual({
      month: "2026-11",
      nights: 4,
    });
    expect(buildPlanRequest({ ...values, suggestDestination: true })).toMatchObject({
      suggest_destination: true,
      destination_idea: "leftover from 'Suggeriscimi tu'",
    });
    expect(buildPlanRequest({ ...values, suggestDestination: true })).not.toHaveProperty("destination");
  });

  it("reads the budget in whole euros and never multiplies a decimal", () => {
    const budget = (budgetEur: string) => buildPlanRequest(form({ budgetEur })).budget_eur;

    expect(budget("1500")).toBe(1500);
    expect(budget(" 1.500 € ")).toBe(1500);
    expect(budget("12.000")).toBe(12000);
    expect(budget("1 500")).toBe(1500);
    // A decimal reaches validation as text: "Scrivi un numero intero.", not 150050 or 24005.
    expect(budget("1500.50")).toBe("1500.50");
    expect(budget("1500,50")).toBe("1500,50");
    expect(budget("2400.5")).toBe("2400.5");
    expect(budget("1.50")).toBe("1.50");
    expect(budget("1.500,00")).toBe("1.500,00");

    const result = validateRequestForm(form({ budgetEur: "1500.5" }), { today: TODAY });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.budget_eur).toBe("Scrivi un numero intero.");
  });

  it("returns a valid request when the form passes", () => {
    const result = validateRequestForm(form({ childAges: ["7"] }), { today: TODAY });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.request.travelers).toEqual([
        { kind: "adult", age: null },
        { kind: "adult", age: null },
        { kind: "child", age: 7 },
      ]);
      expect(result.request.dates).toMatchObject({ exact_start: "2026-11-14", exact_end: "2026-11-17" });
    }
  });

  it("reports Italian errors on the request's paths", () => {
    const result = validateRequestForm(
      form({ origin: "", destination: "", exactStart: "2026-10-01", exactEnd: "", adults: 1, childAges: [""], budgetEur: "mille" }),
      { today: TODAY },
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors).toEqual({
        origin: "Campo obbligatorio.",
        destination: "Indica dove vuoi andare, oppure scegli «Suggeriscimi tu».",
        "dates.exact_start": "La partenza deve essere da domani in poi.",
        "dates.exact_end": "Indica il giorno del ritorno.",
        [childAgePath(0, 1)]: "Indica l'età del bambino (da 0 a 17 anni).",
        budget_eur: "Scrivi un numero intero.",
      });
    }
  });

  it("asks for a whole number of nights", () => {
    const result = validateRequestForm(form({ dateMode: "flexible", month: "2026-11", nights: "3,5" }), { today: TODAY });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors["dates.nights"]).toBe("Scrivi un numero intero.");
  });

  it("maps the backend's 422 issues onto the same fields", () => {
    expect(
      fieldErrorsFromServer([
        { type: "destination_required", loc: ["body", "destination"], msg: "give a destination" },
        { type: "child_age_required", loc: ["body", "travelers", 2, "age"], msg: "a child needs an age" },
        {
          type: "month_in_past",
          loc: ["body", "dates", "month"],
          msg: "month 2026-09 is in the past",
          ctx: { month: "2026-09", current_month: "2026-10" },
        },
        { type: "string_too_long", loc: ["body", "origin"], msg: "too long", ctx: { max_length: 200 } },
        { type: "a_new_backend_code", loc: ["body", "preferences"], msg: "something" },
      ]),
    ).toEqual({
      destination: "Indica dove vuoi andare, oppure scegli «Suggeriscimi tu».",
      "travelers.2.age": "Indica l'età del bambino (da 0 a 17 anni).",
      "dates.month": "Questo mese è già passato: scegli ottobre 2026 o un mese successivo.",
      origin: "Al massimo 200 caratteri.",
      preferences: "Valore non valido.",
    });
  });

  it("offers the spec's example, Lisbona in mid-April with two children, always in the future", () => {
    const example = exampleRequestForm(TODAY);
    expect(example).toMatchObject({
      origin: "Milano",
      destination: "Lisbona",
      dateMode: "exact",
      exactStart: "2027-04-14",
      exactEnd: "2027-04-18",
      adults: 2,
      childAges: ["8", "11"],
      budgetEur: "2.400",
    });
    const result = validateRequestForm(example, { today: TODAY });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.request.budget_eur).toBe(2400);
    expect(exampleRequestForm("2027-04-13").exactStart).toBe("2027-04-14");
    expect(validateRequestForm(exampleRequestForm("2027-04-13"), { today: "2027-04-13" }).ok).toBe(true);
    expect(exampleRequestForm("2027-04-14").exactStart).toBe("2028-04-14");
    expect(exampleRequestForm("2026-01-01").exactEnd).toBe("2026-04-18");
  });

  it("says which fields of the chosen date mode are empty instead of 'no dates'", () => {
    const exact = validateRequestForm(form({ exactStart: "", exactEnd: "" }), { today: TODAY });
    expect(exact.ok).toBe(false);
    if (!exact.ok) {
      expect(exact.errors.dates).toBeUndefined();
      expect(exact.errors["dates.exact_start"]).toBe("Indica il giorno della partenza.");
      expect(exact.errors["dates.exact_end"]).toBe("Indica il giorno del ritorno.");
    }
    const flexible = validateRequestForm(form({ dateMode: "flexible", month: "", nights: "" }), { today: TODAY });
    expect(flexible.ok).toBe(false);
    if (!flexible.ok) {
      expect(flexible.errors.dates).toBeUndefined();
      expect(flexible.errors["dates.month"]).toBe("Scegli il mese di partenza.");
      expect(flexible.errors["dates.nights"]).toBe("Indica quante notti.");
    }
  });

  it("starts empty, one adult, destination mode, fixed dates", () => {
    expect(emptyRequestForm()).toMatchObject({ adults: 1, childAges: [], suggestDestination: false, dateMode: "exact" });
  });
});
