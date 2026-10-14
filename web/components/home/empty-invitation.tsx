import { RouteLine, TripFact } from "@/components/request/trip-outline";
import { LinkButton } from "@/components/ui/button";
import { BRAND_TAGLINE } from "@/lib/brand";

import { EXAMPLE_HREF, type ExampleRequest } from "./example";

/**
 * No plan yet: not an empty page but an invitation, with a request already written (spec,
 * "Tutti gli stati sono disegnati"). "Parti da questo esempio" opens the form filled in with it.
 */
export function EmptyInvitation({ example }: { example: ExampleRequest }) {
  return (
    <section aria-labelledby="invito-titolo" className="rounded-md border border-rule bg-surface px-4 py-5 sm:px-6 sm:py-6">
      <h2 id="invito-titolo" className="font-cond text-heading font-semibold">
        {BRAND_TAGLINE}
      </h2>
      <p className="mt-1.5 max-w-prose text-small text-ink-2">
        Descrivi un viaggio e cinque agenti lo preparano mentre li guardi lavorare: voli, alloggio, attività e
        spostamenti, ognuno con la data entro cui prenotarlo. Puoi partire da questa richiesta, già scritta.
      </p>

      <figure className="mt-5 grid gap-4 border-t border-rule pt-4">
        <blockquote className="font-cond text-title font-semibold">«{example.sentence}»</blockquote>
        <figcaption className="grid gap-4 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] sm:gap-x-8">
          <RouteLine origin={{ text: example.origin }} destination={{ text: example.destination }} />
          <ul className="grid content-start gap-2 text-small">
            <TripFact icon="calendar-blank">{example.dates}</TripFact>
            <TripFact icon="users">{example.travelers}</TripFact>
            <TripFact icon="wallet">{example.budget} in tutto</TripFact>
            {example.preferences ? <TripFact icon="compass">{example.preferences}</TripFact> : null}
          </ul>
        </figcaption>
      </figure>

      <LinkButton href={EXAMPLE_HREF} variant="secondary" className="mt-5">
        Parti da questo esempio
      </LinkButton>
    </section>
  );
}
