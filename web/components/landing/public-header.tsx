import { LinkButton } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/**
 * The landing's header (DESIGN.md, Landing): the lockup home, "Come funziona" (a jump down the
 * page, hidden below 480 px where the page is one short scroll), the bare theme toggle, and
 * "Accedi" to the plans. The plans page sends a signed-out visitor to TripTracker's login and back.
 */
export function PublicHeader() {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex min-h-16 max-w-landing items-center justify-between gap-2 px-4 lg:px-7">
        <Wordmark href={ROUTES.home} />
        <nav aria-label="Pagina" className="flex items-center gap-2">
          <a
            href="#come-funziona"
            className="inline-flex min-h-11 items-center rounded-full px-2.5 text-small text-ink-2 no-underline hover:text-ink max-[30rem]:hidden"
          >
            Come funziona
          </a>
          <ThemeToggle variant="bare" className="pointer-coarse:size-11" />
          <LinkButton href={ROUTES.plans} variant="secondary" className="pointer-coarse:min-h-11">
            Accedi
          </LinkButton>
        </nav>
      </div>
    </header>
  );
}
