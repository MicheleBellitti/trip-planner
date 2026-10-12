"use client";

/**
 * "/evals/[id]": one eval run (GET /evals/runs/{id}). The header with the run's facts and its
 * verdict, the comparison with the baseline, an index of the requests, one section per request
 * and the agent versions closed at the end. Fetched in the browser (the cookie), like the plans.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { SiteHeader } from "@/components/home/site-header";
import { Button, LinkButton } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { StateFact, StatePanel } from "@/components/states/state-panel";
import { api, API_ERROR_MESSAGES, ApiError, UnauthorizedError } from "@/lib/api";
import type { EvalRunDetail } from "@/lib/schemas/api";

import { AgentVersions } from "./agent-versions";
import { ComparisonSection } from "./comparison-section";
import { checksSummary, failingFirst, formatJudgeMean, requestAnchor, requestJudgeMean, requestStatusLabel, requestsLabel, runVerdict } from "./eval-model";
import { EvalRunSkeleton } from "./eval-run-skeleton";
import { CheckGlyph } from "./marks";
import { RequestSection } from "./request-section";
import { RunHeader } from "./run-header";

type ScreenState =
  | { kind: "loading" }
  | { kind: "ready"; run: EvalRunDetail }
  | { kind: "missing"; message: string }
  | { kind: "error"; message: string };

export function EvalRunScreen({ runId }: { runId: string }) {
  const [state, setState] = useState<ScreenState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getEvalRun(runId, { signal: controller.signal })
      .then((run) => setState({ kind: "ready", run }))
      .catch((error: unknown) => {
        // 401: the browser is on its way to TripTracker's login; keep the skeleton.
        if (controller.signal.aborted || error instanceof UnauthorizedError) return;
        const message = error instanceof ApiError ? error.message : API_ERROR_MESSAGES.unknown;
        setState(error instanceof ApiError && error.kind === "not_found" ? { kind: "missing", message } : { kind: "error", message });
      });
    return () => controller.abort();
  }, [runId, attempt]);

  if (state.kind === "loading") return <EvalRunSkeleton />;

  if (state.kind === "missing") {
    return (
      <>
        <SiteHeader current="evals" />
        <main className="mx-auto max-w-page px-4 pt-2 lg:px-7">
          <StatePanel
            icon="warning"
            title="Questa valutazione non c'è"
            headingId="valutazione-mancante"
            actions={
              <LinkButton href="/evals" variant="primary" icon="arrow-left">
                Torna alle valutazioni
              </LinkButton>
            }
          >
            <StateFact label="Cosa è successo">{state.message}</StateFact>
            <StateFact label="Cosa puoi fare">
              Torna all&apos;elenco: le valutazioni arrivano dalla CI dopo ogni run, e quella che cerchi potrebbe non
              essere ancora stata caricata.
            </StateFact>
          </StatePanel>
        </main>
      </>
    );
  }

  if (state.kind === "error") {
    return (
      <>
        <SiteHeader current="evals" />
        <main className="mx-auto max-w-page px-4 pt-5 pb-16 lg:px-7 lg:pt-7">
          <BackLink />
          <Notice
            tone="error"
            title="La valutazione non si è caricata"
            className="mt-4 max-w-[48rem]"
            action={
              <Button
                size="sm"
                variant="quiet"
                icon="arrows-clockwise"
                onClick={() => {
                  setState({ kind: "loading" });
                  setAttempt((value) => value + 1);
                }}
              >
                Riprova
              </Button>
            }
          >
            {state.message}
          </Notice>
        </main>
      </>
    );
  }

  return <RunPage run={state.run} />;
}

function BackLink() {
  return (
    <Link
      href="/evals"
      className="-my-1.5 inline-flex min-h-11 items-center gap-1.5 rounded-xs text-meta text-ink-2 no-underline hover:text-ink hover:underline"
    >
      <Icon name="arrow-left" size={15} />
      Valutazioni
    </Link>
  );
}

function RunPage({ run }: { run: EvalRunDetail }) {
  const verdict = runVerdict(run);
  const requests = failingFirst(run.results.requests);
  return (
    <>
      <SiteHeader current="evals" />
      <main className="mx-auto max-w-page px-4 pt-5 pb-16 lg:px-7 lg:pt-7">
        <BackLink />
        <div className="mt-2 max-w-[64rem]">
          <RunHeader run={run} />
          <ComparisonSection
            comparison={run.comparison}
            verdict={verdict}
            requests={run.results.requests}
            className="mt-9"
          />

          {requests.length > 0 ? (
            <section aria-labelledby="richieste" className="mt-9">
              <h2 id="richieste" className="font-cond text-heading font-semibold">
                Richieste
                <span className="ml-2 font-sans text-meta font-normal text-ink-2">{requestsLabel(requests.length)}</span>
              </h2>
              <ul className="mt-2 divide-y divide-rule rounded-md border border-rule bg-surface">
                {requests.map((request) => {
                  const mean = formatJudgeMean(requestJudgeMean(request.judge));
                  return (
                    <li key={request.id}>
                      <a
                        href={`#${requestAnchor(request.id)}`}
                        className="grid grid-cols-[1.0625rem_minmax(0,1fr)] gap-x-2.5 px-3 py-2.5 no-underline transition-[background-color] duration-(--duration-hover) ease-out first:rounded-t-md last:rounded-b-md hover:bg-notice-wash focus-visible:-outline-offset-2"
                      >
                        <span className={request.checks_passed ? "mt-px text-ink-2" : "mt-px text-error"}>
                          <CheckGlyph status={request.checks_passed ? "pass" : "fail"} size={17} />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-small font-medium text-ink">{request.title || request.id}</span>
                          <span className="mt-0.5 block text-meta text-ink-2">
                            {requestStatusLabel(request.status)}, {checksSummary(request.checks).toLocaleLowerCase("it")}
                            {mean ? `, voto ${mean}` : ""}
                          </span>
                        </span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}

          <div className="mt-9 grid gap-8">
            {requests.map((request) => (
              <RequestSection key={request.id} request={request} />
            ))}
          </div>

          <AgentVersions versions={run.results.agent_versions} className="mt-10" />
        </div>
      </main>
    </>
  );
}
