import { LinkButton } from "@/components/ui/button";
import { WaitlistForm } from "@/components/waitlist/waitlist-form";
import { BRAND_NAME } from "@/lib/brand";
import { DEMO_READY, ROUTES, WAITLIST_ANCHOR } from "@/lib/routes";

import { ConvergingLines } from "./converging-lines";

/**
 * The landing's closing (DESIGN.md, Landing): the five lines entering the destination, then the
 * invitation. Atlas is by invitation: the waitlist form is the way in for a stranger, "Accedi" for
 * the invited (here and in the header, never in the hero). With the demo, "Guarda una corsa" comes
 * first and the list follows under "Accesso su invito."; until it exists, the list is the closing.
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
            Una corsa registrata, riprodotta con i veri componenti di {BRAND_NAME}: gli agenti al lavoro, il costo
            della corsa, il piano finito con le sue prenotazioni. Dura meno di un minuto e non costa nulla.
          </p>
          <div className="mt-5.5 flex flex-wrap gap-2.5">
            <LinkButton href={ROUTES.demo} variant="primary" icon="play" className="pointer-coarse:min-h-11">
              Guarda una corsa
            </LinkButton>
            <LinkButton href={ROUTES.plans} variant="secondary" className="pointer-coarse:min-h-11">
              Accedi
            </LinkButton>
          </div>
          <h3 id={WAITLIST_ANCHOR} className="mt-10 scroll-mt-6 font-cond text-heading font-semibold">
            Accesso su invito.
          </h3>
          <p className="mt-1.5 max-w-[34em] text-small text-ink-2">
            Lascia il tuo indirizzo: ti scriviamo quando c&apos;è posto.
          </p>
          <WaitlistForm source="landing" className="mt-4 max-w-[26rem]" />
        </>
      ) : (
        <>
          <h2 id="landing-close-title" className="font-cond text-display font-semibold lg:text-display-lg">
            {BRAND_NAME} è su invito.
          </h2>
          <p className="mt-2.5 max-w-[34em] text-lede text-ink-2">
            Lascia il tuo indirizzo: ti scriviamo quando c&apos;è posto. Se hai già un invito, accedi e pianifica il
            prossimo viaggio.
          </p>
          <WaitlistForm source="landing" signInHint className="mt-6 max-w-[26rem]" />
        </>
      )}
    </section>
  );
}
