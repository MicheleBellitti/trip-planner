"use client";

import { Button, LinkButton } from "@/components/ui/button";
import { BRAND_NAME } from "@/lib/brand";
import { ROUTES } from "@/lib/routes";

/**
 * The demo's bar (spec, "Demo"), in place of "Interrompi": what this run is, then "Ricomincia",
 * "2×" and "Salta al piano" while it plays; once it ends, "Ricomincia" and the demo's own ask
 * where the arrival lands: "Pianifica il tuo viaggio" for a browser that has signed in before,
 * "Accedi" for anyone else, honest that access is by invitation. Its
 * own row in the live header's state group, so it fits a phone beside nothing else.
 */
export function DemoBar({
  speed,
  onSpeed,
  onRestart,
  onSkip,
  done,
  signedIn,
}: {
  signedIn: boolean;
  speed: number;
  onSpeed: (speed: number) => void;
  onRestart: () => void;
  onSkip: () => void;
  done: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-rule pt-2.5 lg:border-0 lg:pt-0">
      <p className="text-meta text-ink-2">
        {done ? `Fine della corsa dimostrativa. ${BRAND_NAME} è su invito.` : "Corsa dimostrativa: dati di esempio, gratis per te"}
      </p>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="quiet" icon="arrows-clockwise" onClick={onRestart} className="pointer-coarse:min-h-11">
          Ricomincia
        </Button>
        {done ? (
          // A browser that has signed in before plans a trip; anyone else signs in (by invitation):
          // the form would only send them to the login after they filled it in.
          signedIn ? (
            <LinkButton href={ROUTES.newPlan} variant="primary" size="sm" className="pointer-coarse:min-h-11">
              Pianifica il tuo viaggio
            </LinkButton>
          ) : (
            <LinkButton href={ROUTES.plans} variant="primary" size="sm" icon="sign-in" className="pointer-coarse:min-h-11">
              Accedi
            </LinkButton>
          )
        ) : (
          <>
            <Button
              size="sm"
              variant="secondary"
              aria-pressed={speed === 2}
              // The visible "2×" leads the name, so a voice user can say what they see (WCAG 2.5.3).
              aria-label="2×, velocità doppia"
              onClick={() => onSpeed(speed === 2 ? 1 : 2)}
              className="pointer-coarse:min-h-11 pointer-coarse:min-w-11 aria-pressed:bg-notice-wash aria-pressed:inset-ring-[1.5px] aria-pressed:inset-ring-ink"
            >
              2×
            </Button>
            <Button size="sm" variant="secondary" onClick={onSkip} className="pointer-coarse:min-h-11">
              Salta al piano
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
