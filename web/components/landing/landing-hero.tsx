import { LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { BRAND_DESCRIPTION, BRAND_TAGLINE } from "@/lib/brand";
import { AGENT_LABELS, AGENTS } from "@/lib/plan-events/labels";
import { DEMO_READY, ROUTES } from "@/lib/routes";
import type { AgentName } from "@/lib/schemas/generated/ui-event";

import { LineMap } from "./line-map";

/** What each agent does, in the legend (Italian, sentence case). */
const JOBS: Record<AgentName, string> = {
  coordinator: "decide e assembla il piano",
  flights: "cerca e confronta i voli",
  lodging: "trova dove dormire",
  activities: "sceglie cosa fare, con i biglietti",
  transport: "organizza come muoversi sul posto",
};

/**
 * The landing's first screen (DESIGN.md, Landing): the tagline, the lede, one call to action (the
 * demo once it exists, else a jump to "Come funziona"; "Accedi" lives in the header and the
 * closing), the legend of the five lines, and the line map converging on the sample destination.
 * On the phone the map comes before the legend; from 1080 px the legend sits under the copy.
 */
export function LandingHero({ demoReady = DEMO_READY }: { demoReady?: boolean }) {
  return (
    <section aria-labelledby="landing-title" className="mx-auto max-w-landing px-4 pt-8 lg:px-7 lg:pt-12">
      <div className="grid gap-7 lg:grid-cols-[0.95fr_1.15fr] lg:gap-x-8 lg:gap-y-8">
        <div className="lg:col-start-1 lg:row-start-1">
          <h1 id="landing-title" className="font-hero text-hero font-bold tracking-[-0.01em] lg:text-hero-lg">
            {BRAND_TAGLINE}
          </h1>
          <p className="mt-4 max-w-[30em] text-lede text-ink-2">{BRAND_DESCRIPTION}</p>
          <div className="mt-6 flex flex-wrap gap-2.5">
            {demoReady ? (
              <LinkButton href={ROUTES.demo} variant="primary" icon="play" className="pointer-coarse:min-h-11">
                Guarda una corsa
              </LinkButton>
            ) : (
              <LinkButton href="#come-funziona" variant="primary" className="pointer-coarse:min-h-11">
                Scopri come funziona
              </LinkButton>
            )}
          </div>
        </div>
        <div className="lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:self-start">
          <LineMap />
        </div>
        <div className="lg:col-start-1 lg:row-start-2">
          <p id="legenda" className="border-t border-rule pt-3 text-micro text-ink-2">
            Legenda
          </p>
          <ul aria-labelledby="legenda" className="mt-2 grid max-w-[30em] gap-y-2 text-meta">
            {AGENTS.map((agent) => (
              <li
                key={agent}
                data-agent={agent}
                className="grid grid-cols-[30px_7rem_minmax(0,1fr)] items-start gap-x-3.5"
              >
                <span
                  aria-hidden="true"
                  className={cx("mt-[7px] block rounded-[3px] bg-line", agent === "coordinator" ? "h-2" : "h-1.5")}
                />
                <span className="font-semibold text-ink">{AGENT_LABELS[agent]}</span>
                <span className="text-ink-2">{JOBS[agent]}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="mt-5 flex flex-wrap justify-between gap-x-4 gap-y-1 border-t border-rule pt-3 pb-4 text-micro text-ink-2">
        <span>Corsa di prova: Milano → Lisbona, 2 adulti e 2 bambini</span>
        <span>38°43′ N, 9°08′ O</span>
      </p>
    </section>
  );
}
