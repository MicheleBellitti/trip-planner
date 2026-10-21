import { describe, expect, it } from "vitest";

import fixture from "./plan-events/__fixtures__/backend/choices.json";
import {
  answeredTitle,
  askedTitle,
  ASK_TRAVELLER_TOOL,
  choiceEyebrow,
  choiceIntro,
  choiceRule,
  choiceWindowMs,
  readAskedChoice,
  readChoice,
  readChoiceAnswer,
  readPhoto,
  type ChoiceKind,
  type ChoiceView,
} from "./choices";
import type { UIEvent } from "./schemas/generated/ui-event";

const events = fixture.events as unknown as UIEvent[];
const bySeq = (seq: number): UIEvent => events.find((event) => event.seq === seq)!;

const first = readAskedChoice(bySeq(53).detail)!;
const food = readAskedChoice(bySeq(77).detail)!;

const PHOTO = {
  url: "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0b/A.jpg/1920px-A.jpg",
  width: 1920,
  height: 1358,
  author: "Jose",
  license: "CC BY 2.5",
  license_url: "https://creativecommons.org/licenses/by/2.5",
  source_page: "https://commons.wikimedia.org/wiki/File:A.jpg",
  title: "A",
};

function raw(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    kind: "activities",
    question: "Cosa vuoi vedere?",
    multiple: true,
    options: [
      { id: "a", title: "Uno", reason: "Perché sì." },
      { id: "b", title: "Due", reason: "Perché no." },
    ],
    asked_at: "2026-10-12T10:00:00+00:00",
    deadline_at: "2026-10-12T10:04:00+00:00",
    ...overrides,
  };
}

describe("readChoice", () => {
  it("reads the fixture's first question: kind, question, three options, prices, durations, photos", () => {
    expect(ASK_TRAVELLER_TOOL).toBe("ask_traveller");
    expect(first).toMatchObject({ kind: "activities", question: "Cosa ti va di vedere?", multiple: true });
    expect(first.options.map((option) => option.id)).toEqual(["a1", "a2", "a3"]);
    expect(first.options[0]).toMatchObject({
      title: "Oceanário de Lisboa",
      durationMin: 150,
      price: { amountCents: 6000, currency: "EUR" },
      area: null,
    });
    expect(first.options[2]).toMatchObject({ durationMin: 210, price: null });
    expect(first.options.every((option) => option.photo?.url.startsWith("https://upload.wikimedia.org/"))).toBe(true);
    expect(choiceWindowMs(first)).toBe(240_000);
    expect(food.options.map((option) => option.photo)).toEqual([null, null, null]);
  });

  it("reads an answered event: choice id, who, picks", () => {
    expect(readChoiceAnswer(bySeq(56).detail)).toEqual({
      choiceId: first.id,
      kind: "activities",
      answeredBy: "traveller",
      selected: ["a1", "a2"],
      answeredAt: "2026-10-12T10:00:34.841000+00:00",
    });
    expect(readChoiceAnswer(bySeq(53).detail)).toBeNull();
    expect(readAskedChoice(bySeq(56).detail)).toBeNull();
    expect(readAskedChoice(null)).toBeNull();
  });

  it("gives no choice for a missing id, an unknown kind, one option or a bad deadline, and drops a bad option", () => {
    expect(readChoice(raw())).not.toBeNull();
    expect(readChoice(null)).toBeNull();
    expect(readChoice(raw({ id: "" }))).toBeNull();
    expect(readChoice(raw({ kind: "hotel" }))).toBeNull();
    expect(readChoice(raw({ question: " " }))).toBeNull();
    expect(readChoice(raw({ multiple: "yes" }))).toBeNull();
    expect(readChoice(raw({ deadline_at: "domani" }))).toBeNull();
    expect(readChoice(raw({ asked_at: undefined }))).toBeNull();
    expect(readChoice(raw({ options: [{ id: "a", title: "Uno", reason: "x" }] }))).toBeNull();

    const options = [
      { id: "a", title: "Uno", reason: "x", duration_min: "tanto", price: { amount_cents: "1" }, area: 5 },
      { id: "", title: "Senza id", reason: "x" },
      { id: "b", title: "", reason: "x" },
      { id: "c", title: "Senza motivo" },
      { id: "a", title: "Doppione", reason: "x" },
      { id: "d", title: "Quattro", reason: "x" },
    ];
    const choice = readChoice(raw({ options }))!;
    expect(choice.options.map((option) => option.id)).toEqual(["a", "d"]);
    expect(choice.options[0]).toMatchObject({ title: "Uno", durationMin: null, price: null, area: null, photo: null });
    expect(readChoice(raw({ options: options.slice(0, 2) }))).toBeNull();
  });

  it("keeps no photo off Wikimedia: an http image, another host, a file page elsewhere, a javascript: license", () => {
    expect(readPhoto(PHOTO)).toMatchObject({ url: PHOTO.url, license: "CC BY 2.5" });
    expect(readPhoto({ ...PHOTO, author: undefined, license_url: undefined })).toMatchObject({
      author: null,
      license_url: null,
    });
    expect(readPhoto({ ...PHOTO, url: PHOTO.url.replace("https", "http") })).toBeNull();
    expect(readPhoto({ ...PHOTO, url: "https://evil.example/upload.wikimedia.org/a.jpg" })).toBeNull();
    expect(readPhoto({ ...PHOTO, url: "https://upload.wikimedia.org.evil.example/a.jpg" })).toBeNull();
    expect(readPhoto({ ...PHOTO, source_page: "https://example.com/wiki/File:A.jpg" })).toBeNull();
    expect(readPhoto({ ...PHOTO, license_url: "javascript:alert(1)" })).toBeNull();
    expect(readPhoto({ ...PHOTO, width: 0 })).toBeNull();
    expect(readPhoto({ ...PHOTO, license: "" })).toBeNull();
    expect(readPhoto("https://upload.wikimedia.org/a.jpg")).toBeNull();
    expect(readPhoto(null)).toBeNull();
  });
});

describe("the choice copy", () => {
  it("spells the five asked titles as the backend does", () => {
    expect(askedTitle("activities")).toBe(bySeq(53).title);
    expect(askedTitle("food")).toBe(bySeq(77).title);
    expect(askedTitle("destination")).toBe("Tocca a te: scegli la destinazione");
    expect(askedTitle("journey")).toBe("Tocca a te: scegli come viaggiare");
    expect(askedTitle("other")).toBe("Tocca a te: scegli tra le opzioni");
  });

  it("answeredTitle matches the recorded 'Hai scelto: …' and the three other answers", () => {
    expect(answeredTitle(first, "traveller", ["a2", "a1"])).toBe(bySeq(56).title);
    expect(answeredTitle(food, "traveller", ["c1", "c2"])).toBe(bySeq(80).title);
    expect(answeredTitle(first, "skip", [])).toBe("Hai lasciato scegliere ad Atlas");
    expect(answeredTitle(first, "timeout", [])).toBe("Tempo scaduto: sceglie Atlas");
    expect(answeredTitle(first, "closed", [])).toBe("Domanda chiusa: piano interrotto");
  });

  it("writes the eyebrow per kind, with and without a destination", () => {
    const of = (kind: ChoiceKind): ChoiceView => ({ ...first, kind });
    expect(choiceEyebrow(of("activities"), "Lisbona")).toBe("Attività ha trovato 3 idee per Lisbona");
    expect(choiceEyebrow(of("activities"), null)).toBe("Attività ha trovato 3 idee");
    expect(choiceEyebrow(of("food"), "Lisbona")).toBe("Il coordinatore propone 3 modi di mangiare a Lisbona");
    expect(choiceEyebrow(of("food"), null)).toBe("Il coordinatore propone 3 modi di mangiare");
    expect(choiceEyebrow(of("destination"), "Lisbona")).toBe("Il coordinatore propone 3 mete");
    expect(choiceEyebrow(of("journey"), null)).toBe("Il coordinatore propone 3 modi di viaggiare");
    expect(choiceEyebrow(of("other"), "Lisbona")).toBe("Il coordinatore propone 3 opzioni");
  });

  it("writes the intro and the rule: 'Scegline una.', '… anche più di una.', 4 minuti, 90 secondi, 15 secondi", () => {
    expect(choiceIntro(first)).toBe("Scegli quelle che ti piacciono, anche più di una.");
    expect(choiceIntro({ ...first, multiple: false })).toBe("Scegline una.");
    expect(choiceRule(240_000)).toBe("Se non scegli entro 4 minuti, scelgo io.");
    // Whole minutes from 120 s, rounded down: the rule never promises more time than there is.
    expect(choiceRule(120_000)).toBe("Se non scegli entro 2 minuti, scelgo io.");
    expect(choiceRule(150_000)).toBe("Se non scegli entro 2 minuti, scelgo io.");
    expect(choiceRule(239_000)).toBe("Se non scegli entro 3 minuti, scelgo io.");
    // Seconds under 120 s.
    expect(choiceRule(119_000)).toBe("Se non scegli entro 119 secondi, scelgo io.");
    expect(choiceRule(90_000)).toBe("Se non scegli entro 90 secondi, scelgo io.");
    expect(choiceRule(60_000)).toBe("Se non scegli entro 60 secondi, scelgo io.");
    expect(choiceRule(15_000)).toBe("Se non scegli entro 15 secondi, scelgo io.");
    expect(choiceRule(1_000)).toBe("Se non scegli entro 1 secondo, scelgo io.");
    expect(choiceWindowMs({ ...first, deadlineAt: "2020-01-01T00:00:00Z" })).toBe(0);
  });
});
