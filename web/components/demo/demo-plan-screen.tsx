"use client";

/**
 * /demo (spec, "Demo"): the recorded happy-path run replayed through the live screen's own view,
 * then the real finished plan. Everything it shows is in the bundle: the events, the plan, the
 * Trip and the cover. It never constructs or calls an API client and opens no stream; the
 * booking links stay the real, allowlisted ones.
 */

import { useEffect, useState } from "react";

import { PublicHeader } from "@/components/landing/public-header";
import { PLAN_STATE_ID } from "@/components/live/live-header";
import { loadPlanView, PlanScreenView } from "@/components/live/plan-screen-view";
import detailJson from "@/components/plan/__fixtures__/happy-path.detail.json";
import tripJson from "@/components/plan/__fixtures__/happy-path.trip.json";
import type { CoverLoader } from "@/components/plan/cover/cover-store";
import { Notice } from "@/components/ui/notice";
import { BRAND_NAME } from "@/lib/brand";
import coverJson from "@/lib/demo/cover.json";
import { DEMO_REQUEST } from "@/lib/demo/request";
import { formatElapsed } from "@/lib/format";
import { useReplayEvents } from "@/lib/demo/use-replay-events";
import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import { ROUTES, WAITLIST_HREF } from "@/lib/routes";
import type { Cover, PlanDetail } from "@/lib/schemas/api";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { DemoBar } from "./demo-bar";
import { useSignedIn } from "./use-signed-in";

const EVENTS = backend.events as unknown as UIEvent[];
const EPOCH = EVENTS[0]!.ts;
/** The recorded run's own length (the replay compresses it to 45 s): what the finished plan says. */
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
  <Notice tone="info">Una corsa registrata: prezzi e disponibilità sono un esempio. I link portano ai siti veri.</Notice>
);

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
  const { state, now, done, skip } = useReplayEvents(EVENTS, { speed, epoch: EPOCH });
  const signedIn = useSignedIn();

  // The finished plan's chunk, warmed while the run plays so the arrival is instant.
  useEffect(() => {
    const id = window.setTimeout(() => void loadPlanView(), 1500);
    return () => window.clearTimeout(id);
  }, []);

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
      durationLabel="Corsa registrata: durata"
      finishedElapsed={RECORDED_DURATION}
      costLabel="costo"
      trip={tripJson}
      planView={{ loadCover, handoff: signedIn ? PLAN_HANDOFF : SIGN_IN_HANDOFF, notice: NOTICE, now: RECORDED_NOW }}
    />
  );
}

