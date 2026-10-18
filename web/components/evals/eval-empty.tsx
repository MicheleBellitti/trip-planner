import { cx } from "@/components/ui/cx";

/**
 * No eval run stored yet: not an empty page but an invitation that says how runs arrive (spec,
 * "Tutti gli stati sono disegnati"). The commands are code, so they stay as they are typed.
 */
export function EvalEmptyInvitation({ className }: { className?: string }) {
  return (
    <section
      aria-labelledby="collaudi-vuoti"
      className={cx("rounded-md border border-rule bg-surface px-4 py-5 sm:px-6 sm:py-6", className)}
    >
      <h2 id="collaudi-vuoti" className="font-cond text-heading font-semibold">
        Il primo collaudo arriva dalla CI
      </h2>
      <p className="mt-1.5 max-w-prose text-small text-ink-2">
        Dopo ogni run delle eval, la CI carica qui i risultati: li trovi in questa pagina con l&apos;esito del
        confronto, il costo e i voti del giudice. Una modifica agli agenti, ai prompt o alle skill ne avvia una nuova.
      </p>
      <div className="mt-5 border-t border-rule pt-4">
        <h3 className="text-meta font-semibold">Hai già un file dei risultati?</h3>
        <p className="mt-1 max-w-prose text-small text-ink-2">
          Dalla cartella <code className="whitespace-nowrap">backend/</code> importalo a mano. Con{" "}
          <code className="whitespace-nowrap">--comparison</code> porta anche il confronto con il riferimento.
        </p>
        <pre
          lang="en"
          tabIndex={0}
          className={cx(
            "mt-3 overflow-x-auto rounded-sm bg-notice-wash px-3 py-2.5 text-meta leading-[1.5] text-ink",
            "font-[ui-monospace,SFMono-Regular,Menlo,Consolas,monospace]",
          )}
        >
          <code>uv run python -m app.cli import-evals ../evals/results/&lt;data&gt;-&lt;sha&gt;.json</code>
        </pre>
      </div>
    </section>
  );
}
