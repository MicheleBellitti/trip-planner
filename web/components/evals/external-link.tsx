import { safeHttpUrl } from "@/components/plan/plan-model";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { VisuallyHidden } from "@/components/ui/visually-hidden";

/** "Esecuzione su GitHub" for a github.com address, else the host: a reader knows where it goes. */
export function workflowLabel(url: URL): string {
  const host = url.hostname.replace(/^www\./, "");
  return host === "github.com" ? "Esecuzione su GitHub" : `Esecuzione su ${host}`;
}

/**
 * The link to the CI run that produced an eval, in a new tab. The address comes from the backend
 * (it was uploaded by CI), so it is a link only when it is an absolute http(s) URL with no user
 * info; anything else is not drawn at all.
 */
export function WorkflowLink({
  href,
  short = false,
  className,
}: {
  href: string | null | undefined;
  /** "GitHub" alone, for a table cell. */
  short?: boolean;
  className?: string;
}) {
  const url = safeHttpUrl(href);
  if (!url) return null;
  const label = workflowLabel(url);
  return (
    <a
      href={url.href}
      target="_blank"
      rel="noopener noreferrer"
      className={cx(
        "inline-flex items-center gap-1.5 text-meta text-ink underline decoration-rule-strong underline-offset-[0.2em]",
        "hover:decoration-ink",
        // A target of 24 px with a mouse and 44 px under a finger (DESIGN.md, Layout).
        "-my-1 py-1 pointer-coarse:-my-3 pointer-coarse:py-3",
        className,
      )}
    >
      {short ? "GitHub" : label}
      <Icon name="arrow-square-out" size={14} />
      <VisuallyHidden>{short ? ` (${label}, si apre in una nuova scheda)` : " (si apre in una nuova scheda)"}</VisuallyHidden>
    </a>
  );
}

/** A commit's first seven characters in a monospace face, tabular, with the full sha on hover
 * and for screen readers' copy. Null when the run did not know its commit. */
export function Sha({ sha, short, className }: { sha: string | null; short: string | null; className?: string }) {
  if (!short) {
    return (
      <span className={cx("text-ink-2", className)}>
        <span className="lg:hidden">commit non indicato</span>
        <span className="hidden lg:inline">ignoto</span>
      </span>
    );
  }
  return (
    <code
      title={sha ?? undefined}
      className={cx("font-[ui-monospace,SFMono-Regular,Menlo,Consolas,monospace] tracking-tight tabular-nums", className)}
    >
      {short}
    </code>
  );
}
