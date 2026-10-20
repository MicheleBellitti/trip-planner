"use client";

/**
 * /demo (spec, "Demo"): the recorded `choices` run replayed through the live screen's own view,
 * then the real finished plan. Everything it shows is in the bundle: the events, the plan, the
 * Trip and the cover. It never constructs or calls an API client and opens no stream; the
 * booking links stay the real, allowlisted ones.
 *
 * The run asks the traveller twice (what to see, what to eat): the replay holds on each question
 * (lib/demo/use-replay-events) and the panel shows the cards with the demo's own countdown and
 * rule. Untouched, the recording's picks show and its answer lands; a visitor who picks takes
 * over, and their answer becomes the coordinator's station. The finished plan is the recording's
 * whatever they pick, and the notice says so. While a question waits, the tab title starts with
 * "Tocca a te ·".
 */

import { useEffect, useMemo, useState } from "react";

import type { ChoiceControls } from "@/components/choice/choice-panel";
import { PublicHeader } from "@/components/landing/public-header";
import { PLAN_STATE_ID } from "@/components/live/live-header";
import { loadChoicePanel, loadPlanView, PlanScreenView } from "@/components/live/plan-screen-view";
import detailJson from "@/components/plan/__fixtures__/happy-path.detail.json";
import tripJson from "@/components/plan/__fixtures__/happy-path.trip.json";
import type { CoverLoader } from "@/components/plan/cover/cover-store";
import { Notice } from "@/components/ui/notice";
import { BRAND_NAME } from "@/lib/brand";
import coverJson from "@/lib/demo/cover.json";
import { DEMO_REQUEST } from "@/lib/demo/request";
import { formatElapsed } from "@/lib/format";
import { DEMO_CHOICE_WINDOW_MS, useReplayEvents } from "@/lib/demo/use-replay-events";
import backend from "@/lib/plan-events/__fixtures__/backend/choices.json";
import { ROUTES, WAITLIST_HREF } from "@/lib/routes";
import type { Cover, PlanDetail } from "@/lib/schemas/api";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { DemoBar } from "./demo-bar";
import { useSignedIn } from "./use-signed-in";

const EVENTS = backend.events as unknown as UIEvent[];
const EPOCH = EVENTS[0]!.ts;
/** The recorded run's own length (the replay compresses it to 45 s, plus the questions' waits):
 * what the finished plan says. The plan and the Trip are the happy path's: this run submits it. */
const RECORDED_DURATION = formatElapsed(Date.parse(EVENTS.at(-1)!.ts) - Date.parse(EPOCH));
/** The plan's relative dates read on the recording's day, so the showcase never goes stale. */
const RECORDED_NOW = Date.parse(EPOCH);

/** The recorded plan, told with the request its run was given and no TripTracker link. */
const DETAIL = { ...detailJson, request: DEMO_REQUEST, import_url: null } as unknown as PlanDetail;
const COVER = coverJson as Cover;
const loadCover: CoverLoader = async () => COVER;

/** The finished plan's hand-off, in TripTracker's place: plan a trip, or, for a visitor, the
 * waitlist first and "Accedi" for the invited. */
const PLAN_HANDOFF = {
  title: "Il tuo viaggio",
  text: "Descrivi il tuo viaggio: cinque agenti lo pianificano così, con le date entro cui prenotare.",
  label: "Pianifica il tuo viaggio",
  href: ROUTES.newPlan,
};
const SIGN_IN_HANDOFF = {
  title: "Il tuo viaggio",
  text: `${BRAND_NAME} è su invito. Mettiti in lista e ti scriviamo quando c'è posto; se hai già un invito, accedi.`,
  label: "Mettiti in lista",
  href: WAITLIST_HREF,
  secondary: { label: "Accedi", href: ROUTES.login },
};

const NOTICE = (
  <Notice tone="info">
    Una corsa registrata: prezzi e disponibilità sono un esempio, e le scelte non cambiano il piano. I link portano ai
    siti veri.
  </Notice>
);

/** The intro's second sentence while a question's window runs, in place of the live "scelgo io". */
const DEMO_RULE = `Se non scegli entro ${DEMO_CHOICE_WINDOW_MS / 1000} secondi, la corsa prosegue con le scelte registrate.`;

export function DemoPlanScreen() {
  const [run, setRun] = useState(0);
  const [speed, setSpeed] = useState(1);
  // "Ricomincia" remounts the run: the reducer, the lanes and the live baseline start over. The
  // focus, which sat on the button that just went away, moves to the plan's state.
  const restart = () => {
    setRun((count) => count + 1);
    requestAnimationFrame(() => document.getElementById(PLAN_STATE_ID)?.focus());
  };
  return <DemoRun key={run} speed={speed} onSpeed={setSpeed} onRestart={restart} />;
}

function DemoRun({
  speed,
  onSpeed,
  onRestart,
}: {
  speed: number;
  onSpeed: (speed: number) => void;
  onRestart: () => void;
}) {
  const { state, now, done, skip, hold, answer, touch } = useReplayEvents(EVENTS, { speed, epoch: EPOCH });
  const signedIn = useSignedIn();

  // The choice's and the finished plan's chunks, warmed while the run plays so the questions and
  // the arrival are instant.
  useEffect(() => {
    const id = window.setTimeout(() => {
      void loadChoicePanel();
      void loadPlanView();
    }, 1500);
    return () => window.clearTimeout(id);
  }, []);

  // The panel's controls on the replay: its countdown and rule while the window runs, the
  // recording's picks when it answers, and the visitor's answer in place of the recording's (the
  // focus moves to the plan's state, as live). The state sits in the sticky header, always on
  // screen while the run plays, and a plain focus() would throw the page to its top (Chrome
  // scrolls to a sticky element's place in the flow), away from the camera's work.
  const choice = useMemo<ChoiceControls>(
    () => ({
      answer: (_choiceId, input) => {
        answer(input);
        requestAnimationFrame(() => document.getElementById(PLAN_STATE_ID)?.focus({ preventScroll: true }));
        return Promise.resolve(null);
      },
      deadlineAt: hold?.resumeAt ?? null,
      windowMs: DEMO_CHOICE_WINDOW_MS,
      rule: hold !== null && hold.resumeAt !== null ? DEMO_RULE : null,
      autoPick: hold?.autoPick ?? null,
      onTouch: touch,
    }),
    [hold, answer, touch],
  );

  // While a question waits, the tab says whose turn it is; its own title comes back after.
  const holding = hold !== null;
  useEffect(() => {
    if (!holding) return;
    const previous = document.title;
    document.title = `Tocca a te · ${previous}`;
    return () => {
      document.title = previous;
    };
  }, [holding]);

  return (
    <PlanScreenView
      state={state}
      detail={DETAIL}
      clock={now}
      stale={false}
      connection="open"
      header={<PublicHeader themeToggle={false} />}
      bar={<DemoBar speed={speed} onSpeed={onSpeed} onRestart={onRestart} onSkip={skip} done={done} signedIn={signedIn} />}
      followLanes="show"
      choice={choice}
      durationLabel="Corsa registrata: durata"
      finishedElapsed={RECORDED_DURATION}
      costLabel="costo"
      trip={tripJson}
      planView={{ loadCover, handoff: signedIn ? PLAN_HANDOFF : SIGN_IN_HANDOFF, notice: NOTICE, now: RECORDED_NOW }}
    />
  );
}

