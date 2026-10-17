import { LinkButton } from "@/components/ui/button";
import { DEMO_READY, ROUTES } from "@/lib/routes";

import { ConvergingLines } from "./converging-lines";

/**
 * The landing's closing (DESIGN.md, Landing): the five lines entering the destination, then the
 * invitation. With the demo: watch a whole run, then sign in, "Accesso su invito.". Until it
 * exists: Atlas is by invitation, sign in. "Accedi" lives here and in the header, never in the hero.
 */
export function LandingClose({ demoReady = DEMO_READY }: { demoReady?: boolean }) {
  return (
    <section aria-labelledby="landing-close-title" className="mx-auto max-w-landing px-4 pt-20 pb-14 lg:px-7">
      <ConvergingLines className="mb-7" />
      {demoReady ? (
        <>
          <h2 id="landing-close-title" className="font-cond text-display font-semibold lg:text-display-lg">
            Guarda una corsa intera, senza account.
          </h2>
          <p className="mt-2.5 max-w-[34em] text-lede text-ink-2">
            Una corsa registrata, riprodotta con i veri componenti di Atlas: gli agenti al lavoro, il costo che
            sale, il piano finito con le sue prenotazioni. Dura meno di un minuto e non costa nulla.
          </p>
          <div className="mt-5.5 flex flex-wrap gap-2.5">
            <LinkButton href={ROUTES.demo} variant="primary" icon="play" className="pointer-coarse:min-h-11">
              Guarda una corsa
            </LinkButton>
            <LinkButton href={ROUTES.plans} variant="secondary" className="pointer-coarse:min-h-11">
              Accedi
            </LinkButton>
          </div>
          <p className="mt-3.5 text-meta text-ink-2">Accesso su invito.</p>
        </>
      ) : (
        <>
          <h2 id="landing-close-title" className="font-cond text-display font-semibold lg:text-display-lg">
            Atlas è su invito.
          </h2>
          <p className="mt-2.5 max-w-[34em] text-lede text-ink-2">
            Se hai un invito, accedi con il tuo account TripTracker e pianifica il prossimo viaggio. Presto qui
            potrai guardare una corsa intera, senza account.
          </p>
          <div className="mt-5.5">
            <LinkButton href={ROUTES.plans} variant="primary" icon="sign-in" className="pointer-coarse:min-h-11">
              Accedi
            </LinkButton>
          </div>
        </>
      )}
    </section>
  );
}
