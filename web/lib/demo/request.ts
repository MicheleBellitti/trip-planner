/**
 * The request the recorded demo run was given (its first user message, in
 * lib/plan-events/__fixtures__/backend/happy-path.json): the demo's header, the coordinator's
 * first message and the plan's "sotto il budget" must tell the same story. The fixture plan's own
 * request (8 and 11 years, 2.400 €) came from another run; components/demo/demo-plan-screen.test
 * keeps this one equal to the recording.
 */
import type { PlanRequest } from "@/lib/schemas/generated/request";

export const DEMO_REQUEST = {
  origin: "Milano",
  destination: "Lisbona",
  destination_idea: null,
  journey_mode: null,
  suggest_destination: false,
  dates: { exact_start: "2027-04-14", exact_end: "2027-04-18", month: null, nights: null },
  travelers: [
    { kind: "adult", age: null },
    { kind: "adult", age: null },
    { kind: "child", age: 9 },
    { kind: "child", age: 6 },
  ],
  budget_eur: 2800,
  preferences: "Niente voli prima delle 8, hotel centrale con camera familiare, ritmi tranquilli per i bambini.",
} satisfies PlanRequest;
