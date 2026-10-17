import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";

/**
 * The header of the signed-out pages (login): the lockup and the theme toggle, no sections (there
 * is nothing to navigate to before signing in). The lockup is not a link here: DESIGN.md's "the
 * lockup links to the plans" is a rule for signed-in pages, and until the public landing ships the
 * plans list would only 401 and bounce back to this page, losing `returnTo` on the way. Same
 * height and rule as AppHeaderBar.
 */
export function AuthHeader() {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex min-h-16 max-w-page items-center justify-between gap-2 px-4 lg:px-7">
        <Wordmark compact />
        <ThemeToggle variant="bare" className="pointer-coarse:size-11" />
      </div>
    </header>
  );
}
