import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/** The header of the signed-out pages (login): the lockup home and the theme toggle, no sections
 * (there is nothing to navigate to before signing in). Same height and rule as AppHeaderBar. */
export function AuthHeader() {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex min-h-16 max-w-page items-center justify-between gap-2 px-4 lg:px-7">
        <Wordmark href={ROUTES.plans} compact />
        <ThemeToggle variant="bare" className="pointer-coarse:size-11" />
      </div>
    </header>
  );
}
