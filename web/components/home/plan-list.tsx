"use client";

/**
 * The home page's list (GET /plans), drawn as a line (DESIGN.md, "Plan rail"): a 3 px ink rail
 * down the left of the card and each plan a station on it, the plan's status glyph as its node
 * (the running plan's is the large "you are here" ring), then the destination's cover photo as a
 * 4:3 thumbnail (DESIGN.md, "Cover photos"; a tinted tile with the initial while it loads and when
 * the destination has none). The plans still running come first, under
 * "In corso", at heading size with only how long they have been going; then the latest eight under
 * "Recenti", quieter (status word, cost and creation time in ink-2), and the rest behind "Mostra
 * gli altri N". One plan, the one running or else the newest ready, is featured: a card with its
 * photo at the plan page's band shape (11 rem, 14 rem from 1080 px), above the list on the phone
 * and in the right-hand column from 1280 px; it is not repeated in the rows. Every row says when
 * the plan was created, so twins are told apart. Loading shows rows in their final shape; no plan
 * at all is an invitation with an example already written.
 *
 * The clock is read only in effects and callbacks, never in render: with Cache Components the
 * route is prerendered, and a Date.now() in render would be frozen into the static shell.
 */

import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { CoverCreditNote } from "@/components/plan/cover/cover-credit";
import { CoverFeature } from "@/components/plan/cover/cover-feature";
import { destinationFromTitle } from "@/components/plan/cover/cover-sources";
import { CoverThumb } from "@/components/plan/cover/cover-thumb";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Disclosure } from "@/components/ui/disclosure";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { PlanStatusGlyph } from "@/components/ui/status-badge";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { api, API_ERROR_MESSAGES, ApiError, UnauthorizedError } from "@/lib/api";
import { displayTitle, formatCreated, formatDateTime, formatRunningFor, formatUsd, splitDateRange } from "@/lib/format";
import { PLAN_STATUS_LABELS } from "@/lib/plan-events/labels";
import { todayInRome } from "@/lib/request-form";
import { useNow } from "@/lib/use-now";
import type { PlanStatus, PlanSummary } from "@/lib/schemas/api";

import { EmptyInvitation } from "./empty-invitation";
import { exampleRequest } from "./example";
import { planPath } from "@/lib/page-paths";

/** `openedAt` is the moment the list was last read: "Oggi" and "Ieri" are counted from it. It is
 * taken in the fetch callbacks, so the clock is never read while rendering. */
type ListState =
  | { kind: "loading" }
  | { kind: "ready"; plans: PlanSummary[]; openedAt: number }
  | { kind: "error"; message: string };

/** A plan running while the list is open is read again this often (quietly: no loading state, no
 * announcement). */
export const POLL_MS = 15_000;

/** How many finished plans show before "Mostra gli altri N". */
export const RECENT_ROWS = 8;

/** The rail's column: 36 px wide, so its centre (18 px) is where the rail and every node sit (the
 * node is 18 px: it just fits, and the title column keeps the width). */
const RAIL_COL = "2.25rem";
/** Narrow: rail, cover, title over meta, caret, 10 px apart. Wide: rail, cover, title, status,
 * cost, created, caret. "Wide" is the list's own width (a container query at 58 rem), not the
 * window's: beside the featured plan, from 1280 px, the list is narrower than at 1080 px, and the
 * columns would squeeze the title (the one thing that tells plans apart) to a few words. The cover
 * column is as wide as the thumbnail (4.5 rem narrow, 6 rem wide). */
const ROW_GRID =
  "grid-cols-[2.25rem_4.5rem_minmax(0,1fr)_1rem] @min-[58rem]:grid-cols-[2.25rem_6rem_minmax(0,1fr)_8rem_5.5rem_10.5rem_1rem]";

export function PlanList({ className }: { className?: string }) {
  const [state, setState] = useState<ListState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .listPlans({ signal: controller.signal })
      .then((plans) => setState({ kind: "ready", plans, openedAt: Date.now() }))
      .catch((error: unknown) => {
        // 401: the browser is on its way to the login; keep the placeholder rows.
        if (controller.signal.aborted || error instanceof UnauthorizedError) return;
        setState({ kind: "error", message: error instanceof ApiError ? error.message : API_ERROR_MESSAGES.unknown });
      });
    return () => controller.abort();
  }, [attempt]);

  const anyRunning = state.kind === "ready" && state.plans.some((plan) => plan.status === "running");
  useEffect(() => {
    if (!anyRunning) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      api
        .listPlans({ signal: controller.signal })
        .then((plans) =>
          setState((current) => (current.kind === "ready" ? { kind: "ready", plans, openedAt: Date.now() } : current)),
        )
        .catch(() => {
          // Silent: the list keeps what it shows and tries again at the next beat.
        });
    }, POLL_MS);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [anyRunning]);

  if (state.kind === "loading") return <LoadingRows className={className} />;

  if (state.kind === "error") {
    return (
      <Notice
        tone="error"
        title="I piani non si sono caricati"
        className={cx(className, "max-w-[64rem]")}
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
    );
  }

  if (state.plans.length === 0) {
    return (
      <div className={cx(className, "max-w-[64rem]")}>
        <EmptyInvitation example={exampleRequest(todayInRome())} />
      </div>
    );
  }

  const { plans, openedAt } = state;
  // One plan gets the photo: the one running, else the newest that is ready. It leaves the rows.
  const featured = plans.find((plan) => plan.status === "running") ?? plans.find((plan) => plan.status === "ready") ?? null;
  const rows = featured ? plans.filter((plan) => plan !== featured) : plans;
  const running = rows.filter((plan) => plan.status === "running");
  const finished = rows.filter((plan) => plan.status !== "running");
  const recent = finished.slice(0, RECENT_ROWS);
  const older = finished.slice(RECENT_ROWS);

  return (
    <div className={cx(className, "xl:grid xl:grid-cols-[minmax(0,64rem)_22rem] xl:items-start xl:gap-x-8")}>
      {featured ? (
        <FeaturedPlan
          plan={featured}
          openedAt={openedAt}
          className="mb-5 max-w-[64rem] xl:sticky xl:top-6 xl:col-start-2 xl:row-start-1 xl:mb-0"
        />
      ) : null}
      <div className="max-w-[64rem] min-w-0 xl:col-start-1 xl:row-start-1">
        {rows.length > 0 ? (
          // overflow-hidden keeps the rows' hover wash and the rail inside the rounded corners;
          // the rows' focus ring is drawn inside for the same reason.
          <div className="@container relative overflow-hidden rounded-md border border-rule bg-surface">
            <Rail />
            <div
              aria-hidden="true"
              className={cx("hidden gap-x-4 border-b border-rule py-2 pr-4 text-micro text-ink-2 @min-[58rem]:grid", ROW_GRID)}
            >
              <span />
              <span />
              <span>Piano</span>
              <span>Stato</span>
              <span className="text-right">Costo</span>
              <span>Creato</span>
            </div>
            {running.length > 0 ? <PlanGroup title="In corso" plans={running} openedAt={openedAt} /> : null}
            {recent.length > 0 ? (
              <PlanGroup title="Recenti" plans={recent} divided={running.length > 0} openedAt={openedAt} />
            ) : null}
            {older.length > 0 ? (
              <Disclosure
                variant="section"
                summary={`Mostra gli altri ${older.length}`}
                className="[&>div]:pb-0 [&>summary]:pr-4 [&>summary]:pl-9"
              >
                <PlanRows plans={older} openedAt={openedAt} />
              </Disclosure>
            ) : null}
          </div>
        ) : null}
        <CoverCreditNote planIds={plans.map((plan) => plan.id)} className="mt-3" />
      </div>
    </div>
  );
}

/**
 * The featured plan: its photo across the top of a card (the plan page's band shape), then the
 * title at heading size and the status line. The whole card is the link. The label above says why
 * this one: "In corso" while it runs, else "Ultimo piano pronto".
 */
function FeaturedPlan({ plan, openedAt, className }: { plan: PlanSummary; openedAt: number; className?: string }) {
  const headingId = useId();
  const live = plan.status === "running";
  return (
    <section aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="pb-1.5 text-micro font-semibold text-ink-2">
        {live ? "In corso" : "Ultimo piano pronto"}
      </h2>
      <Link
        href={planPath(plan.id)}
        data-featured=""
        className={cx(
          "group block overflow-hidden rounded-md border border-rule bg-surface no-underline",
          "transition-[background-color] duration-(--duration-hover) ease-out hover:bg-notice-wash",
          "focus-visible:-outline-offset-2",
        )}
      >
        <CoverFeature planId={plan.id} destination={destinationFromTitle(plan.title)} className="border-b border-rule" />
        <span className="flex items-start gap-3 px-4 py-3.5">
          <span aria-hidden="true" className={cx("mt-[3px] shrink-0", NODE_TONE[plan.status])}>
            <PlanStatusGlyph status={plan.status} size="node" />
          </span>
          <span className="min-w-0 flex-1">
            <span data-plan-title="" className="block font-cond text-heading font-semibold text-ink group-hover:underline">
              <PlanTitle title={plan.title} />
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <StatusMeta plan={plan} openedAt={openedAt} />
            </span>
          </span>
          <Icon name="caret-right" size={16} className="mt-1.5 shrink-0 text-ink-2" />
        </span>
      </Link>
    </section>
  );
}

/** A plan's title, with a date range ("14–18 aprile") that never breaks across lines. */
function PlanTitle({ title }: { title: string }) {
  return (
    <>
      {splitDateRange(displayTitle(title)).map((part, index) =>
        part.nowrap ? (
          <span key={index} className="whitespace-nowrap">
            {part.text}
          </span>
        ) : (
          part.text
        ),
      )}
    </>
  );
}

/** The line itself: 3 px of ink down the card, passing under the nodes and beside the headings,
 * clipped by the card's corners like a route that goes on past the edge of the map. */
function Rail() {
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute inset-y-0 z-[1] w-[3px] bg-ink"
      style={{ left: `calc(${RAIL_COL} / 2 - 1.5px)` }}
    />
  );
}

function PlanGroup({
  title,
  plans,
  divided = false,
  openedAt,
}: {
  title: string;
  plans: PlanSummary[];
  divided?: boolean;
  openedAt: number;
}) {
  return (
    <section className={divided ? "border-t border-rule" : undefined}>
      <h2 className="pt-3 pr-4 pb-1 pl-9 text-micro font-semibold text-ink-2">{title}</h2>
      <PlanRows plans={plans} openedAt={openedAt} />
    </section>
  );
}

function PlanRows({ plans, openedAt }: { plans: PlanSummary[]; openedAt: number }) {
  return (
    <ul className="divide-y divide-rule">
      {plans.map((plan) => (
        <li key={plan.id}>
          <PlanRow plan={plan} openedAt={openedAt} />
        </li>
      ))}
    </ul>
  );
}

/** A node's colour: ink for the live plan and the finished one, ink-2 for a plan that stopped
 * short, error red for the two failures. The word beside it says the same in letters. */
const NODE_TONE: Record<PlanStatus, string> = {
  running: "text-ink",
  ready: "text-ink",
  budget_paused: "text-ink-2",
  interrupted: "text-ink-2",
  failed: "text-error",
  blocked: "text-error",
};

function PlanRow({ plan, openedAt }: { plan: PlanSummary; openedAt: number }) {
  return (
    <Link
      href={planPath(plan.id)}
      className={cx(
        "group relative grid items-center gap-x-2.5 gap-y-1 py-3.5 pr-4 no-underline @min-[58rem]:gap-x-4",
        "transition-[background-color] duration-(--duration-hover) ease-out hover:bg-notice-wash",
        "focus-visible:-outline-offset-2",
        ROW_GRID,
      )}
    >
      {/* The station: the plan's status glyph on a disc that hides the rail behind it. */}
      <span
        aria-hidden="true"
        className={cx(
          "absolute z-[2] grid -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-surface",
          "top-1/2 transition-[background-color] duration-(--duration-hover) ease-out group-hover:bg-notice-wash",
          NODE_TONE[plan.status],
        )}
        style={{ left: `calc(${RAIL_COL} / 2)` }}
      >
        <PlanStatusGlyph status={plan.status} size="node" />
      </span>
      <CoverThumb
        planId={plan.id}
        destination={destinationFromTitle(plan.title)}
        className="col-start-2 row-span-2 row-start-1 w-full @min-[58rem]:row-span-1"
      />
      {/* Two lines at most, in either layout: the date range stays in one piece. */}
      <span
        data-plan-title=""
        className={cx(
          "col-start-3 row-start-1 line-clamp-2 min-w-0 font-cond font-semibold text-ink group-hover:underline",
          plan.status === "running" ? "text-heading" : "text-title",
        )}
      >
        <PlanTitle title={plan.title} />
      </span>
      <span className="col-start-3 row-start-2 flex flex-wrap items-center gap-x-3 gap-y-1 @min-[58rem]:contents">
        <StatusMeta plan={plan} openedAt={openedAt} columns />
      </span>
      <Icon
        name="caret-right"
        size={16}
        className="col-start-4 row-span-2 row-start-1 text-ink-2 @min-[58rem]:col-start-7 @min-[58rem]:row-span-1"
      />
    </Link>
  );
}

/**
 * The status word, the cost and when the plan was created (or how long it has run): the meta line
 * under a title. With `columns` (the rows) each part is placed in its desktop column; without
 * (the featured card) they just sit in a line. The created time is always there, so two plans
 * with one title are told apart. Under "In corso" the phone drops the word (the group says it).
 */
function StatusMeta({ plan, openedAt, columns = false }: { plan: PlanSummary; openedAt: number; columns?: boolean }) {
  const live = plan.status === "running";
  const failure = plan.status === "failed" || plan.status === "blocked";
  return (
    <>
      {/* The word of the status: the group heading says "In corso" for the live plans, so on the
          phone only the node and "da 14 min" speak; the desktop column and screen readers keep it. */}
      <span
        className={cx(
          "text-meta",
          columns && "@min-[58rem]:col-start-4 @min-[58rem]:row-start-1 @min-[58rem]:text-small",
          failure ? "text-error" : live ? "text-ink" : "text-ink-2",
          live && columns && "@max-[58rem]:sr-only",
        )}
      >
        {PLAN_STATUS_LABELS[plan.status]}
      </span>
      {live ? null : (
        <span className={cx("text-meta text-ink-2", columns && "@min-[58rem]:col-start-5 @min-[58rem]:row-start-1 @min-[58rem]:text-right @min-[58rem]:text-small")}>
          <VisuallyHidden>Costo </VisuallyHidden>
          {formatUsd(plan.cost_cents)}
        </span>
      )}
      <span className={cx("text-meta text-ink-2", columns && "@min-[58rem]:col-start-6 @min-[58rem]:row-start-1")}>
        {live ? (
          <RunningFor createdAt={plan.created_at} openedAt={openedAt} />
        ) : (
          <>
            <VisuallyHidden>Creato </VisuallyHidden>
            <Created iso={plan.created_at} openedAt={openedAt} />
          </>
        )}
      </span>
    </>
  );
}

/** "Oggi, 17:36", "Ieri, 21:40", "8 ott, 09:15": read in the browser, where the list is fetched. The full
 * date and time stay in the element for anyone who hovers or reads the markup. */
function Created({ iso, openedAt }: { iso: string; openedAt: number }) {
  return (
    <time dateTime={iso} title={formatDateTime(iso)}>
      {formatCreated(iso, openedAt)}
    </time>
  );
}

/** A running plan's row says how long it has been going ("da 3 min", after the group's "In corso")
 * where the others say when they were created: the list reads as alive. Before the clock's first
 * tick it shows the creation time. */
function RunningFor({ createdAt, openedAt }: { createdAt: string; openedAt: number }) {
  const now = useNow();
  const since = Date.parse(createdAt);
  if (now === null || Number.isNaN(since)) {
    return (
      <>
        <VisuallyHidden>Creato </VisuallyHidden>
        <Created iso={createdAt} openedAt={openedAt} />
      </>
    );
  }
  const elapsed = now - since;
  return <>{elapsed < 60_000 ? "appena avviato" : `da ${formatRunningFor(elapsed)}`}</>;
}

function LoadingRows({ className }: { className?: string }) {
  // The loaded layout's shape: the featured card's place first (beside the list from 1280 px),
  // then the list card, so nothing moves when the plans arrive.
  return (
    <div aria-busy="true" className={cx(className, "xl:grid xl:grid-cols-[minmax(0,64rem)_22rem] xl:items-start xl:gap-x-8")}>
      <VisuallyHidden>Carico i piani…</VisuallyHidden>
      <div data-featured-placeholder="" className="mb-5 max-w-[64rem] xl:col-start-2 xl:row-start-1 xl:mb-0">
        {/* Each bar sits in its line's own box (0.8 em bar, the rest as padding), so the
            placeholder is as tall as the card: the label, a title on two lines (one where the
            card is wide, 1080 to 1279 px) and the status line. */}
        <div className="pb-1.5 text-micro">
          <div className="py-[0.275em]">
            <Skeleton className="w-32" />
          </div>
        </div>
        <div className="overflow-hidden rounded-md border border-rule bg-surface">
          <Skeleton shape="block" className="h-44 w-full rounded-none lg:h-56" />
          <div className="flex items-start gap-3 border-t border-rule px-4 py-3.5">
            <span aria-hidden="true" className="mt-[3px] size-[18px] shrink-0 rounded-full border-4 border-rule" />
            <div className="min-w-0 flex-1">
              <div className="grid gap-[0.4em] py-[0.2em] text-heading">
                <Skeleton className="w-full" />
                <Skeleton className="w-2/3 lg:max-xl:hidden" />
              </div>
              <div className="mt-1 py-[0.3em] text-meta">
                <Skeleton className="w-40" />
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="@container relative max-w-[64rem] min-w-0 overflow-hidden rounded-md border border-rule bg-surface xl:col-start-1 xl:row-start-1">
        <Rail />
        <ul className="divide-y divide-rule">
          {[0, 1, 2].map((row) => (
            <li key={row} className={cx("relative grid items-center gap-x-2.5 gap-y-2 py-3.5 pr-4 @min-[58rem]:gap-x-4", ROW_GRID)}>
              {/* A placeholder station on the rail, in the plan's final place. */}
              <span
                aria-hidden="true"
                className="absolute top-1/2 z-[2] size-[18px] -translate-x-1/2 -translate-y-1/2 rounded-full border-4 border-rule bg-surface"
                style={{ left: `calc(${RAIL_COL} / 2)` }}
              />
              <Skeleton shape="block" className="col-start-2 row-span-2 row-start-1 aspect-[4/3] w-full @min-[58rem]:row-span-1" />
              <Skeleton className={cx("col-start-3 text-title", row === 1 ? "w-3/5" : "w-4/5", "@min-[58rem]:w-3/4")} />
              <Skeleton className="col-start-3 row-start-2 w-40 @min-[58rem]:col-start-4 @min-[58rem]:row-start-1 @min-[58rem]:w-24" />
              <Skeleton className="hidden w-12 justify-self-end @min-[58rem]:col-start-5 @min-[58rem]:block" />
              <Skeleton className="hidden w-28 @min-[58rem]:col-start-6 @min-[58rem]:block" />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
