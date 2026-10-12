/**
 * The trip request form (/new): field metadata, client-side validation and the POST /plans body.
 *
 * - Field metadata (limits, required, enums, defaults) is DERIVED from schema/request.json (the
 *   generated `planRequestJsonSchema`), so the form and the backend never diverge (spec: "lo
 *   stesso modello genera il form del frontend tramite JSON Schema"). Only the Italian labels
 *   live here; a test fails when the schema gains a field that has no label.
 * - Validation mirrors backend/app/request.py: the field constraints plus the cross-field rules
 *   (destination or "Suggeriscimi tu"; fixed dates or month + nights; dates in the future in
 *   Europe/Rome; at most 120 days; children with an age, at least one adult), reported on the
 *   same paths the backend uses (`dates.exact_start`, `travelers.2.age`, ...), with the same
 *   error codes, as Italian messages. The backend stays the authority: its 422 issues map onto
 *   the same paths with `fieldErrorsFromServer`.
 */

import type { ValidationIssue } from "./schemas/api";
import {
  PlanRequestSchema,
  planRequestErrorCodes,
  planRequestJsonSchema,
  type PlanRequestErrorCode,
  type PlanRequestInput,
} from "./schemas/generated/request";

// --- schema metadata ------------------------------------------------------------------------

type SchemaNode = {
  readonly type?: string;
  readonly anyOf?: readonly SchemaNode[];
  readonly $ref?: string;
  readonly properties?: Readonly<Record<string, SchemaNode>>;
  readonly required?: readonly string[];
  readonly items?: SchemaNode;
  readonly enum?: readonly string[];
  readonly default?: unknown;
  readonly description?: string;
  readonly maxLength?: number;
  readonly minLength?: number;
  readonly pattern?: string;
  readonly format?: string;
  readonly minimum?: number;
  readonly maximum?: number;
  readonly exclusiveMinimum?: number;
  readonly minItems?: number;
  readonly maxItems?: number;
};

const ROOT = planRequestJsonSchema as unknown as SchemaNode & { readonly $defs: Record<string, SchemaNode> };

/** What the schema says about one field of the request. */
export interface FieldConstraints {
  /** Dotted path in PlanRequest: "origin", "dates.month", "travelers.age" (array items). */
  path: string;
  type: string;
  format: string | null;
  required: boolean;
  nullable: boolean;
  maxLength: number | null;
  minLength: number | null;
  pattern: string | null;
  minimum: number | null;
  maximum: number | null;
  exclusiveMinimum: number | null;
  minItems: number | null;
  maxItems: number | null;
  options: readonly string[] | null;
  default: unknown;
  /** The contract's English description (documentation, not UI copy). */
  description: string | null;
}

function resolveRef(node: SchemaNode): SchemaNode {
  if (!node.$ref) return node;
  const name = node.$ref.replace("#/$defs/", "");
  const target = ROOT.$defs[name];
  if (!target) throw new Error(`request schema: unknown $ref ${node.$ref}`);
  return target;
}

function unwrap(node: SchemaNode): { node: SchemaNode; nullable: boolean } {
  const resolved = resolveRef(node);
  if (!resolved.anyOf) return { node: resolved, nullable: false };
  const branches = resolved.anyOf.map(resolveRef);
  const nonNull = branches.filter((branch) => branch.type !== "null");
  if (nonNull.length !== 1 || !nonNull[0]) throw new Error("request schema: unsupported anyOf");
  return { node: nonNull[0], nullable: nonNull.length < branches.length };
}

function collectFields(node: SchemaNode, prefix: string, out: Map<string, FieldConstraints>): void {
  const properties = node.properties ?? {};
  const required = new Set(node.required ?? []);
  for (const [key, raw] of Object.entries(properties)) {
    const path = prefix ? `${prefix}.${key}` : key;
    const { node: field, nullable } = unwrap(raw);
    out.set(path, {
      path,
      type: field.type ?? "object",
      format: field.format ?? null,
      required: required.has(key),
      nullable,
      maxLength: field.maxLength ?? null,
      minLength: field.minLength ?? null,
      pattern: field.pattern ?? null,
      minimum: field.minimum ?? null,
      maximum: field.maximum ?? null,
      exclusiveMinimum: field.exclusiveMinimum ?? null,
      minItems: field.minItems ?? null,
      maxItems: field.maxItems ?? null,
      options: field.enum ?? null,
      default: raw.default ?? field.default,
      description: raw.description ?? field.description ?? null,
    });
    if (field.type === "object" && field.properties) collectFields(field, path, out);
    if (field.type === "array" && field.items) collectFields(resolveRef(field.items), path, out);
  }
}

/** Every field of PlanRequest, keyed by dotted path (array items without an index). */
export const REQUEST_FIELDS: ReadonlyMap<string, FieldConstraints> = (() => {
  const fields = new Map<string, FieldConstraints>();
  collectFields(ROOT, "", fields);
  return fields;
})();

export function fieldConstraints(path: string): FieldConstraints {
  const field = REQUEST_FIELDS.get(path);
  if (!field) throw new Error(`request schema has no field ${path}`);
  return field;
}

/** Italian copy of each request field. Keys must match REQUEST_FIELDS exactly (tested). */
export const REQUEST_FIELD_COPY: Readonly<Record<string, { label: string; placeholder?: string; hint?: string }>> = {
  origin: { label: "Da dove parti", placeholder: "Milano, oppure MXP" },
  destination: { label: "Dove vuoi andare", placeholder: "Lisbona" },
  suggest_destination: { label: "Suggeriscimi tu", hint: "Il planner propone fino a tre mete, con i motivi." },
  destination_idea: { label: "Che viaggio vorresti", placeholder: "mare a novembre, volo diretto" },
  dates: { label: "Quando" },
  "dates.exact_start": { label: "Partenza" },
  "dates.exact_end": { label: "Ritorno" },
  "dates.month": { label: "Mese di partenza" },
  "dates.nights": { label: "Notti" },
  travelers: { label: "Chi viaggia", hint: "Fino a 9 persone, almeno un adulto." },
  "travelers.kind": { label: "Adulto o bambino" },
  "travelers.age": { label: "Età" },
  budget_eur: { label: "Budget totale in euro", hint: "Per tutto il gruppo: viaggio, alloggio, attività." },
  preferences: { label: "Preferenze", placeholder: "niente voli prima delle 8, cucina locale" },
};

/** Italian labels of the traveler kinds (the schema's enum). */
export const TRAVELER_KIND_LABELS: Readonly<Record<string, string>> = { adult: "Adulto", child: "Bambino" };

/** The trip lasts at most 120 days, 119 nights (backend/app/plan.py MAX_TRIP_DAYS). */
export const MAX_TRIP_DAYS = 120;
export const MAX_NIGHTS = MAX_TRIP_DAYS - 1;

// --- error messages -------------------------------------------------------------------------

/** Italian messages of the request's own error codes (x-error-codes). Keys must match the
 * schema's codes exactly (tested). */
export const REQUEST_ERROR_MESSAGES: Readonly<Record<PlanRequestErrorCode, string>> = {
  adult_age_not_allowed: "L'età si indica solo per i bambini.",
  adult_required: "Serve almeno un adulto.",
  child_age_required: "Indica l'età del bambino (da 0 a 17 anni).",
  dates_conflict: "Scegli date fisse oppure mese e notti, non entrambi.",
  dates_required: "Scegli le date: fisse, oppure mese e numero di notti.",
  destination_conflict: "Indica una destinazione oppure chiedi un suggerimento, non entrambi.",
  destination_required: "Indica dove vuoi andare, oppure scegli «Suggeriscimi tu».",
  end_before_start: "Il ritorno non può essere prima della partenza.",
  exact_end_required: "Indica il giorno del ritorno.",
  exact_start_required: "Indica il giorno della partenza.",
  invalid_month: "Questo mese non esiste.",
  month_in_past: "Questo mese è già passato: scegli {current_month} o un mese successivo.",
  month_required: "Scegli il mese di partenza.",
  nights_required: "Indica quante notti.",
  start_not_in_future: "La partenza deve essere da domani in poi.",
  trip_too_long: "Il viaggio può durare al massimo {max_days} giorni ({max_nights} notti).",
};

/** Italian messages of pydantic's built-in error types and of the form's own parse errors. */
const GENERIC_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  missing: "Campo obbligatorio.",
  string_too_short: "Campo obbligatorio.",
  string_too_long: "Al massimo {max_length} caratteri.",
  string_type: "Scrivi un testo.",
  string_pattern_mismatch: "Formato non valido.",
  control_character: "Togli i caratteri speciali non stampabili.",
  greater_than: "Deve essere maggiore di {gt}.",
  greater_than_equal: "Deve essere almeno {ge}.",
  less_than_equal: "Deve essere al massimo {le}.",
  int_parsing: "Scrivi un numero intero.",
  int_type: "Scrivi un numero intero.",
  int_from_float: "Scrivi un numero intero.",
  // The only array of the request is `travelers`.
  too_short: "Indica almeno {min_length} persona.",
  too_long: "Al massimo {max_length} persone.",
  date_parsing: "Data non valida.",
  date_from_datetime_parsing: "Data non valida.",
  date_type: "Data non valida.",
  literal_error: "Scelta non valida.",
  enum: "Scelta non valida.",
  bool_type: "Scelta non valida.",
  bool_parsing: "Scelta non valida.",
  extra_forbidden: "Campo non previsto.",
  model_type: "Valore non valido.",
  list_type: "Valore non valido.",
};

const FALLBACK_MESSAGE = "Valore non valido.";

/** Used instead of a template whose figures are missing from the error's context. */
const PLAIN_MESSAGES: Readonly<Record<string, string>> = {
  string_too_long: "Testo troppo lungo.",
  greater_than: "Valore troppo basso.",
  greater_than_equal: "Valore troppo basso.",
  less_than_equal: "Valore troppo alto.",
  too_short: "Indica almeno una persona.",
  too_long: "Troppe persone.",
  month_in_past: "Questo mese è già passato.",
  trip_too_long: "Il viaggio è troppo lungo.",
};

const MONTH_NAMES = [
  "gennaio",
  "febbraio",
  "marzo",
  "aprile",
  "maggio",
  "giugno",
  "luglio",
  "agosto",
  "settembre",
  "ottobre",
  "novembre",
  "dicembre",
];

/** "2026-10" -> "ottobre 2026" (unchanged when it is not a YYYY-MM month). */
export function monthLabel(month: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  const name = match ? MONTH_NAMES[Number(match[2]) - 1] : undefined;
  return match && name ? `${name} ${match[1]}` : month;
}

function interpolate(template: string, ctx: Readonly<Record<string, unknown>>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => {
    const value = ctx[key];
    if (value === undefined || value === null) return whole;
    if (key === "current_month" || key === "month") return monthLabel(String(value));
    return String(value);
  });
}

/** The Italian message of an error code (request code or pydantic type), with `ctx` filled in. */
export function requestErrorMessage(code: string, ctx: Readonly<Record<string, unknown>> = {}): string {
  const template =
    (REQUEST_ERROR_MESSAGES as Readonly<Record<string, string>>)[code] ?? GENERIC_ERROR_MESSAGES[code];
  if (!template) return FALLBACK_MESSAGE;
  const filled = interpolate(template, ctx);
  // A template whose figures are missing from ctx would show "{gt}": say it without figures.
  return /\{\w+\}/.test(filled) ? (PLAIN_MESSAGES[code] ?? FALLBACK_MESSAGE) : filled;
}

// --- dates in Europe/Rome -------------------------------------------------------------------

const HOME_TIME_ZONE = "Europe/Rome";

/** Today's date in Europe/Rome as YYYY-MM-DD (the backend's `clock.today()`). */
export function todayInRome(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: HOME_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function parseIsoDate(value: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const time = Date.UTC(year, month - 1, day);
  const date = new Date(time);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return time;
}

const DAY_MS = 86_400_000;

// --- validation (mirrors backend/app/request.py) ----------------------------------------------

export interface RequestIssue {
  /** Dotted PlanRequest path ("dates.exact_start", "travelers.2.age"); "" for the whole form. */
  path: string;
  /** A request error code (x-error-codes) or a pydantic type. */
  code: string;
  ctx?: Record<string, unknown>;
}

/** Field path -> Italian message (the first problem of each field). */
export type FieldErrors = Partial<Record<string, string>>;

const CONTROL_CHARACTER = /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/;

export interface ValidationOptions {
  /** Today in Europe/Rome, YYYY-MM-DD; defaults to `todayInRome()`. */
  today?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function checkText(
  issues: RequestIssue[],
  path: string,
  value: unknown,
  options: { required: boolean },
): string | null {
  const field = fieldConstraints(path);
  if (value === undefined || value === null) {
    if (options.required) issues.push({ path, code: "missing" });
    return null;
  }
  if (typeof value !== "string") {
    issues.push({ path, code: "string_type" });
    return null;
  }
  if (CONTROL_CHARACTER.test(value)) {
    issues.push({ path, code: "control_character" });
    return null;
  }
  const stripped = value.trim();
  if (!options.required && stripped === "") return null;
  if (field.minLength !== null && stripped.length < field.minLength) {
    issues.push({ path, code: "string_too_short", ctx: { min_length: field.minLength } });
    return null;
  }
  if (field.maxLength !== null && stripped.length > field.maxLength) {
    issues.push({ path, code: "string_too_long", ctx: { max_length: field.maxLength } });
    return null;
  }
  return stripped;
}

function checkPositiveInt(issues: RequestIssue[], path: string, value: unknown): number | null {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    issues.push({ path, code: "int_parsing" });
    return null;
  }
  const field = fieldConstraints(path);
  if (field.exclusiveMinimum !== null && value <= field.exclusiveMinimum) {
    issues.push({ path, code: "greater_than", ctx: { gt: field.exclusiveMinimum } });
    return null;
  }
  return value;
}

function checkDates(issues: RequestIssue[], value: unknown, today: string): void {
  if (!isRecord(value)) {
    issues.push({ path: "dates", code: value === undefined ? "missing" : "model_type" });
    return;
  }
  const fieldIssues: RequestIssue[] = [];
  const dateField = (key: "exact_start" | "exact_end"): string | null => {
    const raw = value[key];
    if (raw === undefined || raw === null) return null;
    if (typeof raw !== "string" || parseIsoDate(raw) === null) {
      fieldIssues.push({ path: `dates.${key}`, code: "date_parsing" });
      return null;
    }
    return raw;
  };
  const start = dateField("exact_start");
  const end = dateField("exact_end");
  let month: string | null = null;
  const rawMonth = value.month;
  if (rawMonth !== undefined && rawMonth !== null) {
    const pattern = new RegExp(fieldConstraints("dates.month").pattern ?? "", "u");
    if (typeof rawMonth !== "string") fieldIssues.push({ path: "dates.month", code: "string_type" });
    else if (rawMonth.trim() !== "" && !pattern.test(rawMonth.trim())) {
      fieldIssues.push({ path: "dates.month", code: "string_pattern_mismatch" });
    } else if (rawMonth.trim() !== "") month = rawMonth.trim();
  }
  let nights: number | null = null;
  if (value.nights !== undefined && value.nights !== null) nights = checkPositiveInt(fieldIssues, "dates.nights", value.nights);
  const unknown = Object.keys(value).filter((key) => !REQUEST_FIELDS.has(`dates.${key}`));
  for (const key of unknown) fieldIssues.push({ path: `dates.${key}`, code: "extra_forbidden" });
  if (fieldIssues.length > 0) {
    issues.push(...fieldIssues);
    return;
  }

  const exact = start !== null || end !== null;
  const flexible = month !== null || nights !== null;
  if (exact && flexible) {
    issues.push({ path: "dates", code: "dates_conflict" });
    return;
  }
  if (!exact && !flexible) {
    issues.push({ path: "dates", code: "dates_required" });
    return;
  }
  if (exact) {
    if (start === null) issues.push({ path: "dates.exact_start", code: "exact_start_required" });
    if (end === null) issues.push({ path: "dates.exact_end", code: "exact_end_required" });
    if (start !== null && start <= today) {
      issues.push({ path: "dates.exact_start", code: "start_not_in_future", ctx: { exact_start: start, today } });
    }
    if (start === null || end === null) return;
    const span = Math.round(((parseIsoDate(end) ?? 0) - (parseIsoDate(start) ?? 0)) / DAY_MS);
    if (span < 0) {
      issues.push({ path: "dates.exact_end", code: "end_before_start", ctx: { exact_start: start, exact_end: end } });
    } else if (span > MAX_NIGHTS) {
      issues.push({
        path: "dates.exact_end",
        code: "trip_too_long",
        ctx: { max_days: MAX_TRIP_DAYS, max_nights: MAX_NIGHTS, nights: span },
      });
    }
    return;
  }
  const currentMonth = today.slice(0, 7);
  if (month === null) {
    issues.push({ path: "dates.month", code: "month_required" });
  } else if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) {
    issues.push({ path: "dates.month", code: "invalid_month", ctx: { month } });
  } else if (month < currentMonth) {
    issues.push({ path: "dates.month", code: "month_in_past", ctx: { month, current_month: currentMonth } });
  }
  if (nights === null) {
    issues.push({ path: "dates.nights", code: "nights_required" });
  } else if (nights > MAX_NIGHTS) {
    issues.push({
      path: "dates.nights",
      code: "trip_too_long",
      ctx: { max_days: MAX_TRIP_DAYS, max_nights: MAX_NIGHTS, nights },
    });
  }
}

function checkTravelers(issues: RequestIssue[], value: unknown): void {
  if (!Array.isArray(value)) {
    issues.push({ path: "travelers", code: value === undefined ? "missing" : "list_type" });
    return;
  }
  const list = fieldConstraints("travelers");
  if (list.minItems !== null && value.length < list.minItems) {
    issues.push({ path: "travelers", code: "too_short", ctx: { min_length: list.minItems } });
    return;
  }
  if (list.maxItems !== null && value.length > list.maxItems) {
    issues.push({ path: "travelers", code: "too_long", ctx: { max_length: list.maxItems } });
    return;
  }
  const kinds = fieldConstraints("travelers.kind").options ?? [];
  const age = fieldConstraints("travelers.age");
  let adults = 0;
  let valid = true;
  value.forEach((traveler: unknown, index) => {
    const path = `travelers.${index}`;
    if (!isRecord(traveler)) {
      issues.push({ path, code: "model_type" });
      valid = false;
      return;
    }
    const kind = traveler.kind;
    if (typeof kind !== "string" || !kinds.includes(kind)) {
      issues.push({ path: `${path}.kind`, code: kind === undefined ? "missing" : "literal_error" });
      valid = false;
      return;
    }
    const years = traveler.age === "" ? null : (traveler.age ?? null);
    if (kind === "adult") {
      adults += 1;
      if (years !== null) issues.push({ path: `${path}.age`, code: "adult_age_not_allowed" });
      return;
    }
    if (years === null) {
      issues.push({ path: `${path}.age`, code: "child_age_required" });
    } else if (typeof years !== "number" || !Number.isInteger(years)) {
      issues.push({ path: `${path}.age`, code: "int_parsing" });
    } else if (age.minimum !== null && years < age.minimum) {
      issues.push({ path: `${path}.age`, code: "greater_than_equal", ctx: { ge: age.minimum } });
    } else if (age.maximum !== null && years > age.maximum) {
      issues.push({ path: `${path}.age`, code: "less_than_equal", ctx: { le: age.maximum } });
    }
  });
  if (valid && adults === 0) issues.push({ path: "travelers", code: "adult_required" });
}

/** Validate a POST /plans body the way backend/app/request.py does, reporting every problem
 * at once (the backend reports its cross-field rules only once the fields are valid). */
export function validatePlanRequest(request: unknown, options: ValidationOptions = {}): RequestIssue[] {
  const today = options.today ?? todayInRome();
  const issues: RequestIssue[] = [];
  if (!isRecord(request)) return [{ path: "", code: "model_type" }];

  for (const key of Object.keys(request)) {
    if (!REQUEST_FIELDS.has(key)) issues.push({ path: key, code: "extra_forbidden" });
  }
  checkText(issues, "origin", request.origin, { required: true });
  const destination = checkText(issues, "destination", request.destination, { required: false });
  const suggest = request.suggest_destination ?? false;
  if (typeof suggest !== "boolean") issues.push({ path: "suggest_destination", code: "bool_type" });
  // Validated even when dropped (suggest_destination false), like the backend's field checks.
  checkText(issues, "destination_idea", request.destination_idea, { required: false });
  checkText(issues, "preferences", request.preferences, { required: false });
  checkDates(issues, request.dates, today);
  checkTravelers(issues, request.travelers);
  if (request.budget_eur === undefined) issues.push({ path: "budget_eur", code: "missing" });
  else checkPositiveInt(issues, "budget_eur", request.budget_eur);

  const destinationOk = !issues.some((issue) => issue.path === "destination");
  if (destinationOk && typeof suggest === "boolean") {
    if (destination !== null && suggest) issues.push({ path: "destination", code: "destination_conflict" });
    else if (destination === null && !suggest) issues.push({ path: "destination", code: "destination_required" });
  }
  return issues;
}

/** First message per path, in Italian. */
export function issuesToFieldErrors(issues: readonly RequestIssue[]): FieldErrors {
  const errors: FieldErrors = {};
  for (const issue of issues) {
    errors[issue.path] ??= requestErrorMessage(issue.code, issue.ctx);
  }
  return errors;
}

/** FastAPI's 422 issues (`loc` = ["body", ...path]) as Italian field errors on the same paths. */
export function fieldErrorsFromServer(issues: readonly ValidationIssue[]): FieldErrors {
  return issuesToFieldErrors(
    issues.map((issue) => {
      const loc = issue.loc[0] === "body" ? issue.loc.slice(1) : issue.loc;
      return { path: loc.join("."), code: issue.type, ctx: issue.ctx ?? undefined };
    }),
  );
}

// --- the form ---------------------------------------------------------------------------------

/** What the form holds: strings as typed, modes as chosen. */
export interface RequestFormValues {
  origin: string;
  /** "Suggeriscimi tu": the planner chooses the destination. */
  suggestDestination: boolean;
  destination: string;
  destinationIdea: string;
  dateMode: "exact" | "flexible";
  /** YYYY-MM-DD (input type=date), "" when empty. */
  exactStart: string;
  exactEnd: string;
  /** YYYY-MM (input type=month), "" when empty. */
  month: string;
  nights: string;
  adults: number;
  /** One entry per child, "" until an age is chosen. */
  childAges: string[];
  budgetEur: string;
  preferences: string;
}

export function emptyRequestForm(): RequestFormValues {
  return {
    origin: "",
    suggestDestination: Boolean(fieldConstraints("suggest_destination").default),
    destination: "",
    destinationIdea: "",
    dateMode: "exact",
    exactStart: "",
    exactEnd: "",
    month: "",
    nights: "",
    adults: 1,
    childAges: [],
    budgetEur: "",
    preferences: "",
  };
}

/** The home page's invitation: "un esempio di richiesta già scritto", the spec's own trip
 * ("Lisbona a metà aprile, 2 adulti e 2 bambini, 2.400 €"): Milano to Lisbona from 14 to 18
 * April, two adults and two children aged 8 and 11. The next 14 April after `today`
 * (YYYY-MM-DD, Europe/Rome), so the example is valid whatever the date. */
export function exampleRequestForm(today: string): RequestFormValues {
  const year = Number(today.slice(0, 4));
  const startYear = today < `${year}-04-14` ? year : year + 1;
  return {
    ...emptyRequestForm(),
    origin: "Milano",
    destination: "Lisbona",
    dateMode: "exact",
    exactStart: `${startYear}-04-14`,
    exactEnd: `${startYear}-04-18`,
    adults: 2,
    childAges: ["8", "11"],
    budgetEur: "2.400",
    preferences: "Quartieri tranquilli, cucina locale.",
  };
}

/** The form's travelers are adults first, then children: child `i` is `travelers.<adults+i>`. */
export function childAgePath(childIndex: number, adults: number): string {
  return `travelers.${adults + childIndex}.age`;
}

function parseInteger(raw: string): number | string {
  const trimmed = raw.trim();
  return /^\d+$/.test(trimmed) ? Number(trimmed) : trimmed;
}

/** The budget as typed in its text field: whole euros, with spaces and "€" ignored and the
 * Italian thousands dot accepted only in its exact form ("1.500", "12.000"). Anything else,
 * a decimal above all ("1500,50", "2400.5"), is passed through as text so validation answers
 * "Scrivi un numero intero." instead of reading the separator away and multiplying the amount. */
export function parseBudget(raw: string): number | string {
  const compact = raw.replace(/[\s€]/g, "");
  if (/^\d{1,3}(\.\d{3})+$/.test(compact)) return Number(compact.replace(/\./g, ""));
  return parseInteger(compact);
}

/** The POST /plans body for the form's values: trimmed text, blank optional text left out,
 * only the chosen date mode, adults then children. Unparseable numbers are passed through as
 * text so validation reports them (`int_parsing`). */
export function buildPlanRequest(values: RequestFormValues): Record<string, unknown> {
  const optional = (value: string) => (value.trim() === "" ? undefined : value.trim());
  const request: Record<string, unknown> = {
    origin: values.origin.trim(),
    suggest_destination: values.suggestDestination,
    dates:
      values.dateMode === "exact"
        ? { exact_start: optional(values.exactStart) ?? null, exact_end: optional(values.exactEnd) ?? null }
        : { month: optional(values.month) ?? null, nights: values.nights.trim() === "" ? null : parseInteger(values.nights) },
    travelers: [
      ...Array.from({ length: Math.max(0, values.adults) }, () => ({ kind: "adult" })),
      ...values.childAges.map((age) => (age.trim() === "" ? { kind: "child" } : { kind: "child", age: parseInteger(age) })),
    ],
    budget_eur: values.budgetEur.trim() === "" ? undefined : parseBudget(values.budgetEur),
  };
  if (values.suggestDestination) {
    request.destination_idea = optional(values.destinationIdea);
  } else {
    request.destination = optional(values.destination);
  }
  request.preferences = optional(values.preferences);
  for (const key of Object.keys(request)) if (request[key] === undefined) delete request[key];
  return request;
}

export type RequestFormResult =
  | { ok: true; request: PlanRequestInput }
  | { ok: false; errors: FieldErrors; issues: RequestIssue[] };

/** The form always sends the chosen date mode, so "no dates at all" (`dates_required`, the
 * request's rule) means that mode's fields are empty: say so on those fields. */
function datesRequiredOnFields(values: RequestFormValues, issues: RequestIssue[]): RequestIssue[] {
  return issues.flatMap((issue): RequestIssue[] => {
    if (issue.path !== "dates" || issue.code !== "dates_required") return [issue];
    return values.dateMode === "exact"
      ? [
          { path: "dates.exact_start", code: "exact_start_required" },
          { path: "dates.exact_end", code: "exact_end_required" },
        ]
      : [
          { path: "dates.month", code: "month_required" },
          { path: "dates.nights", code: "nights_required" },
        ];
  });
}

/** Validate the form and, when it passes, return the POST /plans body. */
export function validateRequestForm(values: RequestFormValues, options: ValidationOptions = {}): RequestFormResult {
  const request = buildPlanRequest(values);
  const issues = datesRequiredOnFields(values, validatePlanRequest(request, options));
  if (issues.length > 0) return { ok: false, errors: issuesToFieldErrors(issues), issues };
  // The generated schema is the last word on shape (types, limits, unknown keys).
  const parsed = PlanRequestSchema.safeParse(request);
  if (!parsed.success) {
    const schemaIssues: RequestIssue[] = parsed.error.issues.map((issue) => ({
      path: issue.path.map(String).join("."),
      code: "model_type",
    }));
    return { ok: false, errors: issuesToFieldErrors(schemaIssues), issues: schemaIssues };
  }
  return { ok: true, request: parsed.data };
}

/** Every request error code the backend can return, with its English template (re-exported for
 * tests and tooling). */
export { planRequestErrorCodes };
