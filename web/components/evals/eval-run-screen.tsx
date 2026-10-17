"use client";

/**
 * "/evals/[id]": one eval run (GET /evals/runs/{id}). The header with the run's facts and its
 * verdict, the comparison with the baseline, the requests as closed rows (the deep dive behind
 * each, the ones that stopped the gate first) and the agent versions closed at the end. A link to
 * `#richiesta-<id>` opens that request; "Più recente" and "Più vecchia" step to the neighbouring
 * runs. Fetched in the browser (the cookie), like the plans.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/nav/app-header";
import { Button, LinkButton } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { StateFact, StatePanel } from "@/components/states/state-panel";
import { api, API_ERROR_MESSAGES, ApiError, UnauthorizedError } from "@/lib/api";
import type { EvalRunDetail } from "@/lib/schemas/api";

import { AgentVersions } from "./agent-versions";
import { ComparisonSection } from "./comparison-section";
import { failingFirst, requestsLabel, runVerdict } from "./eval-model";
import { EvalRunSkeleton } from "./eval-run-skeleton";
import { RequestRow } from "./request-row";
import { RunHeader } from "./run-header";
import { StepLink } from "./run-pager";
import { evalRunPath, ROUTES } from "@/lib/routes";

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
        <AppHeader current="evals" />
        <main className="mx-auto max-w-page px-4 pt-2 lg:px-7">
          <StatePanel
            icon="warning"
            title="Questo collaudo non c'è"
            headingId="collaudo-mancante"
            actions={
              <LinkButton href={ROUTES.evals} variant="primary" icon="arrow-left">
                Torna ai collaudi
              </LinkButton>
            }
          >
            <StateFact label="Cosa è successo">{state.message}</StateFact>
            <StateFact label="Cosa puoi fare">
              Torna all&apos;elenco: i collaudi arrivano dalla CI dopo ogni run, e quello che cerchi potrebbe non
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
        <AppHeader current="evals" />
        <main className="mx-auto max-w-page px-4 pt-5 pb-16 lg:px-7 lg:pt-7">
          <BackLink />
          <Notice
            tone="error"
            title="Il collaudo non si è caricato"
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
      href={ROUTES.evals}
      className="-my-1.5 inline-flex min-h-11 items-center gap-1.5 rounded-xs text-meta text-ink-2 no-underline hover:text-ink hover:underline"
    >
      <Icon name="arrow-left" size={15} />
      Collaudi
    </Link>
  );
}

/** Opens the request row the address points to (`#richiesta-<id>`), on arrival and on every
 * later jump (a comparison finding's link), brings it into view and gives its summary the focus. */
function useOpenLinkedRequest() {
  useEffect(() => {
    const reveal = () => {
      const id = decodeURIComponent(window.location.hash.slice(1));
      const target = id ? document.getElementById(id) : null;
      if (!(target instanceof HTMLDetailsElement)) return;
      target.open = true;
      target.scrollIntoView?.({ block: "start" });
      // The keyboard and the screen reader land where the eye does.
      target.querySelector("summary")?.focus({ preventScroll: true });
    };
    reveal();
    window.addEventListener("hashchange", reveal);
    return () => window.removeEventListener("hashchange", reveal);
  }, []);
}

function RunPage({ run }: { run: EvalRunDetail }) {
  const verdict = runVerdict(run);
  const requests = failingFirst(run.results.requests);
  useOpenLinkedRequest();
  return (
    <>
      <AppHeader current="evals" />
      <main className="mx-auto max-w-page px-4 pt-5 pb-16 lg:px-7 lg:pt-7">
        <div className="flex max-w-[64rem] flex-wrap items-center justify-between gap-x-4">
          <BackLink />
          {/* The neighbours, in the list's direction: newer to the left, older to the right. */}
          <nav aria-label="Collaudi vicini" className="flex items-center gap-4">
            <StepLink href={run.next_run ? evalRunPath(run.next_run.id) : null} direction="newer">
              Più recente
            </StepLink>
            <StepLink href={run.previous_run ? evalRunPath(run.previous_run.id) : null} direction="older">
              Più vecchia
            </StepLink>
          </nav>
        </div>
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
              <div className="flex flex-wrap items-baseline gap-x-2">
                <h2 id="richieste" className="font-cond text-heading font-semibold">
                  Richieste
                </h2>
                <p className="text-meta text-ink-2">{requestsLabel(requests.length)}, apri una per i dettagli</p>
              </div>
              <div className="mt-2 divide-y divide-rule overflow-hidden rounded-md border border-rule bg-surface">
                {requests.map((request) => (
                  <RequestRow key={request.id} request={request} />
                ))}
              </div>
            </section>
          ) : null}

          <AgentVersions versions={run.results.agent_versions} className="mt-10" />
        </div>
      </main>
    </>
  );
}
