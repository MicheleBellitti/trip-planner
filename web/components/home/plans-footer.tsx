import Link from "next/link";

import { Icon } from "@/components/ui/icon";
import { BRAND_NAME } from "@/lib/brand";
import { ROUTES } from "@/lib/routes";

/**
 * The plans page's last line (DESIGN.md, Navigation): the way to how Atlas works, the landing's
 * "Come funziona", so the page no longer ends on a photo credit and the app has its help. A link
 * with a fragment: the landing shows even for a signed-in browser (lib/skip-landing.ts).
 */
export function PlansFooter() {
  return (
    <footer className="mx-auto max-w-page px-4 pb-10 lg:px-7">
      <p className="border-t border-rule pt-4">
        <Link
          href={`${ROUTES.home}#come-funziona`}
          className="inline-flex min-h-11 items-center gap-2 text-small text-ink-2 no-underline hover:text-ink hover:underline"
        >
          <Icon name="info" size={16} />
          Come funziona {BRAND_NAME}
        </Link>
      </p>
    </footer>
  );
}
