import type { ReactNode } from "react";

import { Chip } from "@/components/ui/chip";
import { cx } from "@/components/ui/cx";
import { Disclosure } from "@/components/ui/disclosure";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { PlanStatusGlyph } from "@/components/ui/status-badge";
import type { EvalCheck, EvalRequestResult, PlanStatus } from "@/lib/schemas/api";
import { PLAN_STATUS_LABELS } from "@/lib/plan-events/labels";

import {
  CHECK_STATUS_LABELS,
  checkBlocks,
  checkKind,
  checkLabel,
  checksSummary,
  formatJudgeMean,
  formatRunCost,
  formatSeconds,
  judgeOutcome,
  planDigest,
  requestAnchor,
  requestJudgeMean,
  requestStatusLabel,
  scoreWord,
  sortChecks,
} from "./eval-model";
import { CheckGlyph, checkTone, DashedRing, ScoreRoundel } from "./marks";

const KNOWN_STATUSES = new Set<string>(Object.keys(PLAN_STATUS_LABELS));

/**
 * One reference request of the run: who it is (title, tags), how its plan ended (status, cost,
 * searches, time), then what was found. Failures come first: a request that stopped the gate says
 * so in a notice, the checks are listed failures first, then the judge's scores with the judge's
 * reasons, then the accepted plan in one line and the request itself behind a disclosure.
 */
export function RequestSection({ request, headingLevel = 2 }: { request: EvalRequestResult; headingLevel?: 2 | 3 }) {
  const anchor = requestAnchor(request.id);
  const headingId = `${anchor}-titolo`;
  const checks = sortChecks(request.checks);
  const shown = checks.filter((check) => checkKind(check.status) !== "skip");
  const skipped = checks.filter((check) => checkKind(check.status) === "skip");
  const outcome = judgeOutcome(request.judge);
  const digest = request.plan ? planDigest(request.plan) : null;
  const cost = formatRunCost(request.cost_cents);
  const took = formatSeconds(request.duration_seconds);
  const mean = formatJudgeMean(requestJudgeMean(request.judge));
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section
      id={anchor}
      aria-labelledby={headingId}
      className="scroll-mt-4 border-t border-rule pt-6 first:border-t-0 first:pt-0"
    >
      <Heading id={headingId} className="font-cond text-heading font-semibold">
        {request.title || request.id}
      </Heading>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <code className="text-micro text-ink-2 font-[ui-monospace,SFMono-Regular,Menlo,Consolas,monospace]">{request.id}</code>
        {request.tags.map((tag) => (
          <Chip key={tag} tone="quiet">
            {tag}
          </Chip>
        ))}
      </div>

      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-small">
        <Stat label="Piano">
          <span className="inline-flex items-center gap-1.5">
            {request.status && KNOWN_STATUSES.has(request.status) ? (
              <span className={request.status === "failed" || request.status === "blocked" ? "text-error" : "text-ink"}>
                <PlanStatusGlyph status={request.status as PlanStatus} />
              </span>
            ) : (
              <span className="text-ink-2">
                <DashedRing />
              </span>
            )}
            {requestStatusLabel(request.status)}
          </span>
        </Stat>
        <Stat label="Costo">{cost ?? <span className="text-ink-2">non registrato</span>}</Stat>
        <Stat label="Ricerche web">
          {request.web_search_requests === null ? <span className="text-ink-2">non registrate</span> : request.web_search_requests}
        </Stat>
        {took ? <Stat label="Durata">{took}</Stat> : null}
        {request.submit_attempts !== null ? <Stat label="Invii del piano">{request.submit_attempts}</Stat> : null}
        {mean ? <Stat label="Voto medio">{mean}</Stat> : null}
      </dl>

      {request.failure_reason || request.error || request.timed_out ? (
        <Notice tone="error" className="mt-4 max-w-[48rem]" title="Il piano non è arrivato in fondo">
          {request.failure_reason ? <p>{request.failure_reason}</p> : null}
          {request.timed_out ? <p>Il tempo massimo della valutazione è finito prima del piano.</p> : null}
          {request.error ? (
            <p lang="en" className="break-words">
              {request.error}
            </p>
          ) : null}
        </Notice>
      ) : null}

      <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:gap-x-10">
        <div className="min-w-0">
          <h3 className="flex items-baseline gap-2 font-cond text-title font-semibold">
            Controlli
            <span className="font-sans text-meta font-normal text-ink-2">{checksSummary(request.checks)}</span>
          </h3>
          {shown.length > 0 ? (
            <ul className="mt-1.5 divide-y divide-rule">
              {shown.map((check) => (
                <CheckRow key={check.name} check={check} />
              ))}
            </ul>
          ) : null}
          {skipped.length > 0 ? (
            // A skipped check says only why it did not run, usually the same sentence for all of
            // them: one closed row after the checks that did.
            <Disclosure
              summary={`${skipped.length === 1 ? "Un controllo saltato" : `${skipped.length} controlli saltati`}`}
              className={shown.length > 0 ? "mt-2.5" : "mt-1.5"}
            >
              <ul className="grid gap-2">
                {skipped.map((check) => (
                  <li key={check.name} className="flex items-start gap-2">
                    <span className="mt-[2px] text-ink-2">
                      <CheckGlyph status="skip" size={14} />
                    </span>
                    <span className="min-w-0">
                      <span className="text-ink">{checkLabel(check.name)}</span>
                      {check.message ? (
                        <span lang="en" className="block break-words">
                          {check.message}
                        </span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            </Disclosure>
          ) : null}
        </div>

        <div className="min-w-0">
          <h3 className="flex items-baseline gap-2 font-cond text-title font-semibold">
            Giudice
            {outcome.kind === "scores" ? (
              <span className="font-sans text-meta font-normal text-ink-2">media {mean} su 5</span>
            ) : null}
          </h3>
          {outcome.kind === "scores" ? (
            <ul className="mt-1.5 divide-y divide-rule">
              {outcome.rows.map((row) => (
                <li key={row.key} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2.5 py-2.5">
                  <ScoreRoundel score={row.score} />
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-baseline gap-x-2 text-small">
                      <span className="font-medium">{row.label}</span>
                      <span className={cx("text-meta", row.score <= 2 ? "text-error" : "text-ink-2")}>
                        {row.score <= 2 ? <Icon name="warning" size={13} className="mr-1 inline align-[-1px]" /> : null}
                        {scoreWord(row.score)}
                      </span>
                    </p>
                    {row.reason ? (
                      <p lang="en" className="mt-0.5 text-meta break-words text-ink-2">
                        {row.reason}
                      </p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-1.5 text-small text-ink-2">
              <p>{outcome.reason}</p>
              {outcome.detail ? (
                <p lang="en" className="mt-0.5 text-meta break-words">
                  {outcome.detail}
                </p>
              ) : null}
            </div>
          )}

          {digest ? (
            <div className="mt-6">
              <h3 className="font-cond text-title font-semibold">Piano accettato</h3>
              <p className="mt-1.5 text-small font-medium">{digest.title || "Senza titolo"}</p>
              <p className="mt-0.5 text-meta text-ink-2">
                {digest.days}, {digest.bookings}
                {request.warnings_count ? `, ${request.warnings_count} ${request.warnings_count === 1 ? "avviso" : "avvisi"}` : ""}
              </p>
            </div>
          ) : null}
        </div>
      </div>

      <Disclosure summary="Mostra la richiesta come JSON" className="mt-5">
        <pre
          lang="en"
          tabIndex={0}
          className="max-h-96 overflow-auto rounded-xs py-1 text-micro leading-[1.5] text-ink font-[ui-monospace,SFMono-Regular,Menlo,Consolas,monospace]"
        >
          {JSON.stringify(request.request, null, 2)}
        </pre>
      </Disclosure>
    </section>
  );
}

/** A caption over a figure, in a request's strip of facts. */
function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-micro text-ink-2">{label}</dt>
      <dd className="mt-0.5 text-small text-ink">{children}</dd>
    </div>
  );
}

/** One check: its glyph, its Italian name, its status in a word, then the file's own sentence
 * (English) and the lines behind it. */
function CheckRow({ check }: { check: EvalCheck }) {
  const kind = checkKind(check.status);
  const blocks = checkBlocks(check);
  return (
    <li className="grid grid-cols-[1rem_minmax(0,1fr)] gap-x-2.5 py-2.5">
      <span className={cx("mt-[3px]", checkTone(check.status))}>
        <CheckGlyph status={check.status} />
      </span>
      <div className="min-w-0">
        <p className="flex flex-wrap items-baseline gap-x-2 text-small">
          <span className="font-medium">{checkLabel(check.name)}</span>
          <span className={cx("text-meta", checkTone(check.status))}>{CHECK_STATUS_LABELS[kind]}</span>
          {blocks ? <span className="text-meta font-semibold text-error">bloccante</span> : null}
        </p>
        {check.message ? (
          <p lang="en" className="mt-0.5 text-meta break-words text-ink-2">
            {check.message}
          </p>
        ) : null}
        {check.details.length > 0 ? (
          <Disclosure summary={`Dettagli (${check.details.length})`} className="mt-1" contentLang="en">
            <ul className="grid gap-1 break-words">
              {check.details.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          </Disclosure>
        ) : null}
      </div>
    </li>
  );
}

