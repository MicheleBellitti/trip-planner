import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/**
 * The header of the signed-out pages (login): the lockup and the theme toggle, no sections (there
 * is nothing to navigate to before signing in). The lockup links to the public landing, never to
 * the plans: a signed-out visitor would only 401 there and bounce back here, losing `returnTo` on
 * the way. Same height and rule as AppHeaderBar.
 */
export function AuthHeader() {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex min-h-16 max-w-page items-center justify-between gap-2 px-4 lg:px-7">
        <Wordmark href={ROUTES.home} compact />
        <ThemeToggle variant="bare" className="pointer-coarse:size-11" />
      </div>
    </header>
  );
}
