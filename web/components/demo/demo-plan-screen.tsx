"use client";

/**
 * /demo (spec, "Demo"): the recorded happy-path run replayed through the live screen's own view,
 * then the real finished plan. Everything it shows is in the bundle: the events, the plan, the
 * Trip and the cover. It never constructs or calls an API client and opens no stream; the
 * booking links stay the real, allowlisted ones.
 */

import { useEffect, useState } from "react";

import { PublicHeader } from "@/components/landing/public-header";
import { loadPlanView, PlanScreenView } from "@/components/live/plan-screen-view";
import detailJson from "@/components/plan/__fixtures__/happy-path.detail.json";
import tripJson from "@/components/plan/__fixtures__/happy-path.trip.json";
import type { CoverLoader } from "@/components/plan/cover/cover-store";
import { Notice } from "@/components/ui/notice";
import coverJson from "@/lib/demo/cover.json";
import { DEMO_REQUEST } from "@/lib/demo/request";
import { useReplayEvents } from "@/lib/demo/use-replay-events";
import backend from "@/lib/plan-events/__fixtures__/backend/happy-path.json";
import { ROUTES } from "@/lib/routes";
import type { Cover, PlanDetail } from "@/lib/schemas/api";
import type { UIEvent } from "@/lib/schemas/generated/ui-event";

import { DemoBar } from "./demo-bar";

const EVENTS = backend.events as unknown as UIEvent[];
const EPOCH = EVENTS[0]!.ts;

/** The recorded plan, told with the request its run was given and no TripTracker link. */
const DETAIL = { ...detailJson, request: DEMO_REQUEST, import_url: null } as unknown as PlanDetail;
const COVER = coverJson as Cover;
const loadCover: CoverLoader = async () => COVER;

const HANDOFF = {
  title: "Il tuo viaggio",
  text: "Descrivi il tuo viaggio: cinque agenti lo pianificano così, con le date entro cui prenotare.",
  label: "Pianifica il tuo viaggio",
  href: ROUTES.newPlan,
};

const NOTICE = (
  <Notice tone="info">Una corsa registrata: prezzi e disponibilità sono un esempio. I link portano ai siti veri.</Notice>
);

export function DemoPlanScreen() {
  const [run, setRun] = useState(0);
  const [speed, setSpeed] = useState(1);
  // "Ricomincia" remounts the run: the reducer, the lanes and the live baseline start over.
  return <DemoRun key={run} speed={speed} onSpeed={setSpeed} onRestart={() => setRun((count) => count + 1)} />;
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
      bar={<DemoBar speed={speed} onSpeed={onSpeed} onRestart={onRestart} onSkip={skip} done={done} />}
      costLabel="Costo della corsa registrata"
      trip={tripJson}
      planView={{ loadCover, handoff: HANDOFF, notice: NOTICE }}
    />
  );
}

