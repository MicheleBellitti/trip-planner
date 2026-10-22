/**
 * The traveller's choices, as the web reads them: the `ask_traveller` pauses of the coordinator
 * (backend/app/choices.py, consumer.py `choice_asked_event` / `choice_answered_event`).
 *
 * A choice reaches the page in two shapes: the `choice` timeline event (`detail.phase` "asked"
 * carries the backend's `PendingChoice`, "answered" carries who answered and what) and
 * `GET /plans/{id}`'s `pending_choice`. Both are read here with the tolerant style of
 * plan-events/detail.ts: a missing or mistyped key gives `null`, a choice that cannot be shown
 * gives no choice at all, never an exception.
 *
 * This module is on the public demo's first load: it imports the schemas' types only (a test in
 * plan-events/detail-imports.test.ts keeps it so) and never zod.
 *
 * The timeline's titles are the backend's own (`event.title`). `askedTitle` and `answeredTitle`
 * spell them for the two places where no event exists yet (a plate drawn from a snapshot, the
 * demo's synthesized answer); tests pin both against the recorded fixture.
 */

import { BRAND_NAME } from "./brand";
import type { Cover } from "./schemas/api";
import type { UIEvent } from "./schemas/generated/ui-event";
import { AGENT_LABELS } from "./plan-events/labels";

export type ChoiceKind = "destination" | "journey" | "activities" | "food" | "other";
export type AnsweredBy = "traveller" | "skip" | "timeout" | "closed";

export interface ChoiceOptionView {
  id: string;
  title: string;
  /** Why it fits this traveller, Italian, one line. */
  reason: string;
  durationMin: number | null;
  /** For the whole party. */
  price: { amountCents: number; currency: string } | null;
  area: string | null;
  /** A free-licensed photo, host-pinned by `readPhoto`; null is "no photo". */
  photo: Cover | null;
}

export interface ChoiceView {
  id: string;
  kind: ChoiceKind;
  question: string;
  /** More than one option may be picked. */
  multiple: boolean;
  options: ChoiceOptionView[];
  /** ISO 8601 instants; the window is `deadlineAt - askedAt`. */
  askedAt: string;
  deadlineAt: string;
}

export interface ChoiceAnswerView {
  choiceId: string;
  kind: ChoiceKind | null;
  answeredBy: AnsweredBy;
  selected: string[];
  answeredAt: string | null;
}

/** What the page sends: the picks, or "Scegli tu". */
export type ChoiceAnswerInput = { selected: readonly string[] } | { skip: true };

/** `detail.tool` of the raw tool use that precedes a choice in the timeline. */
export const ASK_TRAVELLER_TOOL = "ask_traveller";

/** The panel's `id`, the plate's link target (`#scelta`); its heading is `${CHOICE_PANEL_ID}-domanda`. */
export const CHOICE_PANEL_ID = "scelta";

type Detail = UIEvent["detail"];
type Json = Record<string, unknown>;

const KINDS: readonly ChoiceKind[] = ["destination", "journey", "activities", "food", "other"];
const ANSWERED_BY: readonly AnsweredBy[] = ["traveller", "skip", "timeout", "closed"];

const isRecord = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isKind = (value: unknown): value is ChoiceKind => KINDS.includes(value as ChoiceKind);
const isAnsweredBy = (value: unknown): value is AnsweredBy => ANSWERED_BY.includes(value as AnsweredBy);

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function instant(value: unknown): string | null {
  const candidate = text(value);
  return candidate !== null && !Number.isNaN(Date.parse(candidate)) ? candidate : null;
}

function positiveInt(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

/** An `http(s)` URL (or, with `host`, an `https` URL on exactly that host); anything else null. */
function url(value: unknown, host?: string): string | null {
  const candidate = text(value);
  if (candidate === null) return null;
  try {
    const parsed = new URL(candidate);
    if (host !== undefined) return parsed.protocol === "https:" && parsed.hostname === host ? candidate : null;
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? candidate : null;
  } catch {
    return null;
  }
}

/**
 * A photo as `CoverSchema` accepts it, without zod: the image is `https` on upload.wikimedia.org,
 * the file page `https` on commons.wikimedia.org, the license link `http(s)` or null. Anything
 * else is no photo (agents never write image URLs; the backend only looks them up).
 */
export function readPhoto(value: unknown): Cover | null {
  if (!isRecord(value)) return null;
  const photoUrl = url(value.url, "upload.wikimedia.org");
  const sourcePage = url(value.source_page, "commons.wikimedia.org");
  const width = positiveInt(value.width);
  const height = positiveInt(value.height);
  const license = text(value.license);
  if (!photoUrl || !sourcePage || !width || !height || !license || typeof value.title !== "string") return null;
  const licenseUrl = value.license_url ?? null;
  if (licenseUrl !== null && url(licenseUrl) === null) return null;
  return {
    url: photoUrl,
    width,
    height,
    author: typeof value.author === "string" ? value.author : null,
    license,
    license_url: licenseUrl as string | null,
    source_page: sourcePage,
    title: value.title,
  };
}

function readOption(value: unknown): ChoiceOptionView | null {
  if (!isRecord(value)) return null;
  const id = text(value.id);
  const title = text(value.title);
  const reason = text(value.reason);
  if (!id || !title || !reason) return null;
  const price = isRecord(value.price) ? value.price : null;
  const amount = price?.amount_cents;
  const currency = text(price?.currency);
  return {
    id,
    title,
    reason,
    durationMin: positiveInt(value.duration_min),
    price:
      typeof amount === "number" && Number.isInteger(amount) && amount >= 0 && currency
        ? { amountCents: amount, currency }
        : null,
    area: text(value.area),
    photo: readPhoto(value.photo),
  };
}

/** A `PendingChoice` object (the asked event's `detail.choice`, or `pending_choice`), or null
 * when it cannot be shown: no id, unknown kind, no question, `multiple` not a boolean, fewer
 * than two usable options, or an unreadable `asked_at` / `deadline_at`. An option without an id,
 * a title or a reason, or whose id repeats, is dropped. */
export function readChoice(value: unknown): ChoiceView | null {
  if (!isRecord(value)) return null;
  const id = text(value.id);
  const question = text(value.question);
  const askedAt = instant(value.asked_at);
  const deadlineAt = instant(value.deadline_at);
  if (!id || !isKind(value.kind) || !question || typeof value.multiple !== "boolean") return null;
  if (!askedAt || !deadlineAt || !Array.isArray(value.options)) return null;
  const seen = new Set<string>();
  const options: ChoiceOptionView[] = [];
  for (const raw of value.options as unknown[]) {
    const option = readOption(raw);
    if (!option || seen.has(option.id)) continue;
    seen.add(option.id);
    options.push(option);
  }
  if (options.length < 2) return null;
  return { id, kind: value.kind, question, multiple: value.multiple, options, askedAt, deadlineAt };
}

function phase(detail: Detail, wanted: "asked" | "answered"): Json | null {
  if (!detail || detail.event_type !== "backend.choice" || detail.phase !== wanted) return null;
  return detail;
}

/** The question of a `choice` event in its "asked" phase. */
export function readAskedChoice(detail: Detail): ChoiceView | null {
  const asked = phase(detail, "asked");
  return asked ? readChoice(asked.choice) : null;
}

/** Who answered a question and with what, from a `choice` event in its "answered" phase. */
export function readChoiceAnswer(detail: Detail): ChoiceAnswerView | null {
  const answered = phase(detail, "answered");
  if (!answered) return null;
  const choiceId = text(answered.choice_id);
  if (!choiceId || !isAnsweredBy(answered.answered_by)) return null;
  const selected = Array.isArray(answered.selected)
    ? (answered.selected as unknown[]).filter((id): id is string => typeof id === "string")
    : [];
  return {
    choiceId,
    kind: isKind(answered.kind) ? answered.kind : null,
    answeredBy: answered.answered_by,
    selected,
    answeredAt: instant(answered.answered_at),
  };
}

const ASKED_TITLES: Record<ChoiceKind, string> = {
  destination: "Tocca a te: scegli la destinazione",
  journey: "Tocca a te: scegli come viaggiare",
  activities: "Tocca a te: scegli cosa vedere",
  food: "Tocca a te: scegli cosa mangiare",
  other: "Tocca a te: scegli tra le opzioni",
};

/** The timeline title of a question, as the backend writes it (choices.asked_title). */
export function askedTitle(kind: ChoiceKind): string {
  return ASKED_TITLES[kind];
}

/** The timeline title of an answer, as the backend writes it (choices.answered_title): the picks
 * in the order offered, not the order given. */
export function answeredTitle(choice: ChoiceView, by: AnsweredBy, selected: readonly string[]): string {
  if (by === "traveller") {
    const titles = choice.options
      .filter((option) => selected.includes(option.id))
      .map((option) => option.title)
      .join(", ");
    return `Hai scelto: ${titles}`.replace(/\s+/g, " ").trim();
  }
  if (by === "skip") return `Hai lasciato scegliere ad ${BRAND_NAME}`;
  if (by === "timeout") return `Tempo scaduto: sceglie ${BRAND_NAME}`;
  return "Domanda chiusa: piano interrotto";
}

/** The line above the question: who found the options and how many. `destination` is the
 * request's, or null; without it the sentence drops its place. */
export function choiceEyebrow(choice: ChoiceView, destination: string | null): string {
  const n = choice.options.length;
  const place = destination?.trim() || null;
  switch (choice.kind) {
    case "activities":
      return `${AGENT_LABELS.activities} ha trovato ${n} idee${place ? ` per ${place}` : ""}`;
    case "food":
      return `Il coordinatore propone ${n} modi di mangiare${place ? ` a ${place}` : ""}`;
    case "destination":
      return `Il coordinatore propone ${n} mete`;
    case "journey":
      return `Il coordinatore propone ${n} modi di viaggiare`;
    case "other":
      return `Il coordinatore propone ${n} opzioni`;
  }
}

/** The first sentence under the question. */
export function choiceIntro(choice: ChoiceView): string {
  return choice.multiple ? "Scegli quelle che ti piacciono, anche più di una." : "Scegline una.";
}

/** The second sentence, while the window runs: seconds under 120 s ("90 secondi"), else whole
 * minutes rounded down, so the rule never promises more time than there is ("4 minuti"). */
export function choiceRule(windowMs: number): string {
  const seconds = Math.max(0, Math.round(windowMs / 1000));
  if (seconds < 120) return `Se non scegli entro ${seconds} ${seconds === 1 ? "secondo" : "secondi"}, scelgo io.`;
  return `Se non scegli entro ${Math.floor(seconds / 60)} minuti, scelgo io.`;
}

/** How long the traveller has: `deadlineAt - askedAt`, never negative. */
export function choiceWindowMs(choice: ChoiceView): number {
  return Math.max(0, Date.parse(choice.deadlineAt) - Date.parse(choice.askedAt));
}
