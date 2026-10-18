import { LinkButton } from "@/components/ui/button";
import { StateFact, StatePanel } from "@/components/states/state-panel";
import { BRAND_NAME } from "@/lib/brand";
import { ROUTES } from "@/lib/routes";

/**
 * The eval history answered 403 `admin_only`: the account is signed in but is not one of the
 * backend's ADMIN_EMAILS. The header hides the section from them (nav/section-stations.tsx); this is
 * the page reached by its address. The backend's own words, then the way back.
 */
export function AdminOnlyPanel({ message, className }: { message: string; className?: string }) {
  return (
    <StatePanel
      icon="warning"
      title={`Riservato a chi gestisce ${BRAND_NAME}`}
      headingId="state-admin-only"
      className={className}
      actions={
        <LinkButton href={ROUTES.plans} variant="primary" icon="arrow-left">
          Torna ai piani
        </LinkButton>
      }
    >
      <StateFact label="Cosa è successo">{message}</StateFact>
      <StateFact label="Cosa puoi fare">
        I collaudi misurano gli agenti dopo ogni modifica: servono a chi li mantiene. I tuoi piani sono nella
        lista.
      </StateFact>
    </StatePanel>
  );
}
