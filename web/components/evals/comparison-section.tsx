import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import type { EvalComparison, EvalFinding, EvalRequestResult } from "@/lib/schemas/api";

import {
  costAgainstBaseline,
  criterionLabel,
  meanAgainstBaseline,
  orderedFindings,
  requestAnchor,
  ruleLabel,
  type RunVerdict,
} from "./eval-model";

/**
 * "Confronto con il riferimento": the gate's answer for this run. The blocking findings come
 * first, each in plain words (the rule, the request it is about, the sentence compare.py wrote);
 * then the figures against the baseline, and the notes. A run with no stored comparison says so.
 */
export function ComparisonSection({
  comparison,
  verdict,
  requests,
  className,
}: {
  comparison: EvalComparison | null;
  verdict: RunVerdict;
  requests: readonly Pick<EvalRequestResult, "id" | "title">[];
  className?: string;
}) {
  const titles = new Map(requests.map((request) => [request.id, request.title || request.id]));
  return (
    <section aria-labelledby="confronto" className={className}>
      <h2 id="confronto" className="font-cond text-heading font-semibold">
        Confronto con il riferimento
      </h2>
      {comparison === null ? (
        <Notice className="mt-3 max-w-prose">
          Nessun confronto salvato. La CI lo carica insieme ai risultati; a mano si aggiunge con{" "}
          <code className="whitespace-nowrap">--comparison</code>.
        </Notice>
      ) : (
        <ComparisonBody comparison={comparison} verdict={verdict} titles={titles} />
      )}
    </section>
  );
}

function ComparisonBody({
  comparison,
  verdict,
  titles,
}: {
  comparison: EvalComparison;
  verdict: RunVerdict;
  titles: Map<string, string>;
}) {
  const findings = orderedFindings(comparison);
  const blocking = findings.filter((finding) => finding.blocking);
  const criteria = comparison.criteria.filter((delta) => delta.current_mean !== null || delta.baseline_mean !== null);
  return (
    <div className="mt-3 grid gap-5">
      <p className="max-w-prose text-small text-ink-2">
        {comparison.report_only || !comparison.baseline_name ? (
          "Nessun riferimento: voti e costi non si confrontano."
        ) : (
          <>
            Riferimento: <code className="whitespace-nowrap">{comparison.baseline_name}</code>.
          </>
        )}{" "}
        {blocking.length > 0
          ? blocking.length === 1
            ? "Un problema blocca il confronto."
            : `${blocking.length} problemi bloccano il confronto.`
          : verdict === "aborted"
            ? ""
            : "Nessun problema blocca il confronto."}
      </p>

      {findings.length > 0 ? (
        <ul className="max-w-[48rem] divide-y divide-rule rounded-md border border-rule bg-surface">
          {findings.map((finding, index) => (
            <FindingRow key={index} finding={finding} requestTitle={finding.request_id ? titles.get(finding.request_id) : undefined} />
          ))}
        </ul>
      ) : null}

      {criteria.length > 0 || comparison.cost ? (
        <div>
          <h3 className="text-meta font-semibold">Rispetto al riferimento</h3>
          <dl className="mt-1.5 grid max-w-[34rem] grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-1.5 text-small">
            {criteria.map((delta) => (
              <div key={delta.criterion} className="col-span-2 grid grid-cols-subgrid">
                <dt className="text-ink-2">{criterionLabel(delta.criterion)}</dt>
                <dd className="text-right text-ink">{meanAgainstBaseline(delta.current_mean, delta.baseline_mean)}</dd>
              </div>
            ))}
            {comparison.cost ? (
              <div className="col-span-2 grid grid-cols-subgrid">
                <dt className="text-ink-2">Costo medio per piano</dt>
                <dd className="text-right text-ink">
                  {costAgainstBaseline(comparison.cost.current_mean_cents, comparison.cost.baseline_mean_cents)}
                </dd>
              </div>
            ) : null}
          </dl>
        </div>
      ) : null}

      {comparison.notes.length > 0 ? (
        <ul lang="en" className="grid max-w-prose gap-1 text-meta text-ink-2">
          {comparison.notes.map((note, index) => (
            <li key={index} className="flex items-start gap-2">
              <Icon name="info" size={15} className="mt-0.5" />
              <span>{note}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function FindingRow({ finding, requestTitle }: { finding: EvalFinding; requestTitle: string | undefined }) {
  return (
    <li className="grid grid-cols-[1.0625rem_minmax(0,1fr)] gap-x-2.5 px-3 py-2.5">
      <Icon name={finding.blocking ? "x-circle" : "info"} size={17} className={cx("mt-px", finding.blocking ? "text-error" : "text-ink-2")} />
      <div className="min-w-0">
        <p className="flex flex-wrap items-baseline gap-x-2 text-small">
          <span className={cx("font-semibold", finding.blocking ? "text-error" : "text-ink-2")}>
            {finding.blocking ? "Blocca" : "Segnala"}
          </span>
          <span className="font-medium">{ruleLabel(finding.rule)}</span>
          {finding.request_id ? (
            // Opens the request's row below (the run page opens the row a link points to).
            <a href={`#${requestAnchor(finding.request_id)}`} className="text-ink-2 underline-offset-[0.2em] hover:text-ink">
              {requestTitle ?? finding.request_id}
            </a>
          ) : null}
        </p>
        <p lang="en" className="mt-0.5 text-meta break-words text-ink-2">
          {finding.message}
        </p>
      </div>
    </li>
  );
}
