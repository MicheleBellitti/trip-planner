import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/** The landing's footer: the lockup home and the one honest line about prices. */
export function LandingFooter() {
  return (
    <footer className="border-t border-rule">
      <div className="mx-auto flex max-w-landing flex-wrap items-center justify-between gap-x-6 gap-y-2.5 px-4 pt-5 pb-7 text-meta text-ink-2 lg:px-7">
        <Wordmark href={ROUTES.home} />
        <p>Prezzi e disponibilità si confermano sempre sul sito del fornitore.</p>
      </div>
    </footer>
  );
}
