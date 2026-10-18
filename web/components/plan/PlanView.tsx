"use client";

/**
 * The finished plan (spec, "Il piano finito"; DESIGN.md, Layout): the three-line summary with
 * the estimated total and the warnings, the days as a vertical line of stops, the bookings as
 * rows with "Prenota entro" and "Quando" always separate and labelled, the discarded
 * alternatives in a closed section per kind, the timeline (the page's, through `timeline`), and
 * "Apri in TripTracker" right after the bookings, where the work of booking ends.
 *
 * What it reads:
 * - `detail.plan` (the accepted Plan), `detail.booking_links` and `detail.alternative_links`
 *   (the backend's allowlist verdict of each link, aligned with the lists: a link is a "Prenota
 *   su <sito>" button only when its verdict says `allowed`, otherwise it is plain text), and
 *   `detail.import_url` (TripTracker's /import?plan=<id>).
 * - From the Trip (GET /plans/{id}/trip) only `bookings[].title` and `bookings[].dueAt`,
 *   through lib/booking-dates `tripDueDates`: the "Prenota entro" the backend derived for a
 *   booking whose `book_by` is null (contract rule 1). PlanDetail does not carry it. The Trip
 *   is read only when some booking needs it (no `book_by`, a `scheduled_for`): from the `trip`
 *   prop when the page already has it, else PlanView reads it itself, once.
 */

import { useEffect, useId, useMemo, useState, type ReactNode } from "react";

import { useIsDesktop } from "@/components/live/hooks";
import { LinkButton } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Notice } from "@/components/ui/notice";
import { bookingDeadline, tripDueDates, type TripDueDates } from "@/lib/booking-dates";
import { displayTitle, HOME_TIMEZONE } from "@/lib/format";
import type { PlanDetail } from "@/lib/schemas/api";

import { BookingStrip } from "./booking-strip";
import { BookingRow } from "./bookings";
import { Itinerary } from "./itinerary";
import { CoverBand } from "./cover/cover-band";
import { PlanNowContext } from "./plan-now";
import type { CoverLoader } from "./cover/cover-store";
import { ItineraryDays, ItineraryMapPanel, ItineraryMapProvider } from "./map/itinerary-map";
import {
  alignedChecks,
  alternativeDeadline,
  alternativeGroups,
  alternativesCount,
  bookingStartsAtHome,
  planNeedsTrip,
  safeHttpUrl,
  sortByDeadline,
  tripPlaceLabel,
  tripZoneName,
} from "./plan-model";
import { PlanSummary } from "./plan-summary";

/** Reads GET /plans/{id}/trip; rejects when it cannot. */
export type TripLoader = (planId: string, signal: AbortSignal) => Promise<unknown>;

export interface PlanViewProps {
  /** GET /plans/{id} of a `ready` plan. */
  detail: PlanDetail;
  /** The Trip of GET /plans/{id}/trip if the page has already read it (TripTracker's JSON, read
   * through lib/booking-dates); null or absent: PlanView reads it itself, only when a booking
   * needs a derived "Prenota entro". */
  trip?: unknown;
  /** The run's timeline, closed (a Disclosure): shown last, under the alternatives, as DESIGN.md
   * lays the page out. */
  timeline?: ReactNode;
  /** The plan just appeared under a viewer who was watching it run: bring its top into view and
   * move the focus to its summary heading (a plan that is simply opened does neither). */
  arrival?: boolean;
  /** How to read the Trip when `trip` is not given (GET /plans/{id}/trip on the live page); none,
   * the derived "Prenota entro" dates stay unknown. Pass a stable function (a new one on every
   * render reads the Trip again). PlanView imports no API client: the page brings its loaders. */
  loadTrip?: TripLoader;
  /** How to read the destination's cover (GET /plans/{id}/cover live, the demo's own copy); none,
   * no photo. */
  loadCover?: CoverLoader;
  /** The plan's hand-off in place of "Apri in TripTracker" (the demo's "Pianifica il tuo
   * viaggio"): a heading for screen readers, a sentence and an in-app link. */
  handoff?: PlanHandoff;
  /** A notice above the plan (the demo's: the prices are an example). */
  notice?: ReactNode;
  /** A fixed "now" for the relative dates (the demo's recording date); none, the live clock. */
  now?: number;
}

export interface PlanHandoff {
  title: string;
  text: string;
  label: string;
  href: string;
}

type Fetched = { planId: string; ok: true; trip: unknown } | { planId: string; ok: false };

/** The Trip's due dates, for `bookingDeadline`: from the `trip` prop, or read once. */
function useTripDueDates(detail: PlanDetail, provided: unknown, loadTrip: TripLoader | undefined): TripDueDates {
  const plan = detail.plan;
  const hasProvided = provided !== null && provided !== undefined;
  const needed = plan !== null && planNeedsTrip(plan);
  // GET /trip answers 409 before `ready`, so a plan in another state is never asked.
  const shouldFetch = needed && !hasProvided && detail.status === "ready" && loadTrip !== undefined;
  const [fetched, setFetched] = useState<Fetched | null>(null);

  useEffect(() => {
    if (!shouldFetch) return;
    const planId = detail.id;
    const controller = new AbortController();
    loadTrip?.(planId, controller.signal).then(
      (trip) => {
        if (!controller.signal.aborted) setFetched({ planId, ok: true, trip });
      },
      () => {
        if (!controller.signal.aborted) setFetched({ planId, ok: false });
      },
    );
    return () => controller.abort();
  }, [detail.id, shouldFetch, loadTrip]);

  return useMemo((): TripDueDates => {
    if (!plan || !needed) return { state: "loaded", dueAt: null };
    if (hasProvided) return { state: "loaded", dueAt: tripDueDates(provided, plan) };
    if (detail.status !== "ready") return { state: "failed" };
    if (fetched?.planId !== detail.id) return { state: "loading" };
    return fetched.ok ? { state: "loaded", dueAt: tripDueDates(fetched.trip, plan) } : { state: "failed" };
  }, [plan, needed, hasProvided, provided, detail.status, detail.id, fetched]);
}

/** The request's total budget in euro (stored as an open object: read it defensively). */
function requestBudget(request: PlanDetail["request"]): number | null {
  const value = request?.budget_eur;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function SectionHeading({ id, children, lead }: { id: string; children: ReactNode; lead?: ReactNode }) {
  return (
    <div className="max-w-prose">
      <h2 id={id} className="font-cond text-heading font-semibold">
        {children}
      </h2>
      {lead ? <p className="mt-0.5 text-small text-ink-2">{lead}</p> : null}
    </div>
  );
}

/** The finished plan of a `ready` plan. */
export function PlanView({
  detail,
  trip = null,
  timeline,
  arrival = false,
  loadTrip,
  loadCover,
  handoff: ownHandoff,
  notice,
  now,
}: PlanViewProps) {
  const baseId = useId().replace(/[^\w-]/g, "");
  const tripDates = useTripDueDates(detail, trip, loadTrip);
  const plan = detail.plan;
  // From 1080 px the TripTracker hand-off joins "Da prenotare" in the right column of the top;
  // below it comes after the bookings, where the work of booking ends.
  const desktop = useIsDesktop();
  const summaryId = `${baseId}-sintesi`;

  // The lanes give way to the plan under the same scroll offset: bring the plan's top into view
  // (never scrolling down) and start a screen reader at the summary.
  useEffect(() => {
    if (!arrival || !plan) return;
    const heading = document.getElementById(summaryId);
    if (!heading) return;
    heading.focus({ preventScroll: true });
    const top = heading.getBoundingClientRect().top;
    if (top < 0) window.scrollTo({ top: Math.max(0, window.scrollY + top - 24), behavior: "auto" });
    // Once, when the plan appears.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!plan) {
    return <Notice tone="info">Il piano non è ancora disponibile: arriva quando gli agenti hanno finito.</Notice>;
  }

  const ids = {
    summary: summaryId,
    toBook: `${baseId}-da-prenotare`,
    days: `${baseId}-giorni`,
    bookings: `${baseId}-prenotazioni`,
    bookingsHeading: `${baseId}-prenotazioni-titolo`,
    alternatives: `${baseId}-alternative`,
    triptracker: `${baseId}-triptracker`,
  };
  const bookingAnchor = (index: number) => `${baseId}-prenotazione-${index + 1}`;
  const checks = alignedChecks(detail.booking_links, plan.bookings.length);
  const groups = alternativeGroups(plan.alternatives ?? [], detail.alternative_links);
  const deadlines = plan.bookings.map((booking, index) => bookingDeadline(booking, index, tripDates));
  // "Da prenotare" and "Prenotazioni" list the bookings in the same order (most urgent first), so
  // a tap in the strip lands on the next row, not further down and up again. The itinerary keeps
  // the agent's order.
  const items = plan.bookings.map((booking, index) => ({
    index,
    booking,
    deadline: deadlines[index] ?? ({ kind: "unknown" } as const),
    check: checks[index] ?? null,
  }));
  const byUrgency = sortByDeadline(items);
  const zoneName = tripZoneName(plan, HOME_TIMEZONE);
  // A booking that starts from home (the flight) reads on the clock at home, with the trip's as the
  // second line; the others read on the trip's clock alone.
  const tripLabel = zoneName ? tripPlaceLabel(plan) : null;
  const importUrl = detail.import_url && safeHttpUrl(detail.import_url) ? detail.import_url : null;

  const handoff = ownHandoff ? (
    <section
      aria-labelledby={ids.triptracker}
      className={desktop ? "mt-6 min-w-0 border-t border-rule pt-4" : "min-w-0"}
    >
      <h2 id={ids.triptracker} className="sr-only">
        {ownHandoff.title}
      </h2>
      <p className="max-w-prose text-small text-ink-2">{ownHandoff.text}</p>
      <LinkButton href={ownHandoff.href} variant="secondary" className="mt-3 w-full sm:w-auto lg:w-full">
        {ownHandoff.label}
      </LinkButton>
    </section>
  ) : importUrl ? (
    <section
      aria-labelledby={ids.triptracker}
      className={desktop ? "mt-6 min-w-0 border-t border-rule pt-4" : "min-w-0"}
    >
      <h2 id={ids.triptracker} className="sr-only">
        TripTracker
      </h2>
      <p className="max-w-prose text-small text-ink-2">
        Porta giorni, tappe e prenotazioni in TripTracker, con le loro scadenze: lì ti ricorda cosa prenotare.
      </p>
      <LinkButton href={importUrl} external variant="secondary" className="mt-3 w-full sm:w-auto lg:w-full">
        Apri in TripTracker
      </LinkButton>
    </section>
  ) : null;

  // From 1080 px the itinerary map joins them in the sticky right cell (in view while the days are
  // read); on the phone it opens "Giorno per giorno", above the list.
  const aside = desktop ? (
    <>
      {handoff}
      <ItineraryMapPanel className="mt-5 border-t border-rule pt-3" />
    </>
  ) : null;

  return (
    <PlanNowContext.Provider value={now ?? null}>
    <div className="flex min-w-0 flex-col gap-10 lg:gap-12">
      {notice ? <div>{notice}</div> : null}
      {/* The destination's photo, with its credit: nothing when the destination has none. */}
      <CoverBand planId={detail.id} destination={plan.destination} loadCover={loadCover} />

      {/* From 1080 px the summary and "Giorno per giorno" share one two-column grid: the text on
          the left, "Da prenotare", the hand-off and the map in one sticky cell on the right
          (PlanSummary), which stays beside the stops until "Prenotazioni" begins. */}
      <ItineraryMapProvider plan={plan}>
        <div className="flex min-w-0 flex-col gap-10 lg:grid lg:grid-cols-[minmax(0,1fr)_28rem] lg:items-start lg:gap-x-12 lg:gap-y-0">
          <PlanSummary
            plan={plan}
            title={displayTitle(detail.title)}
            budgetEur={requestBudget(detail.request)}
            headingId={ids.summary}
            aside={aside}
          >
            {plan.bookings.length > 0 ? (
              <BookingStrip
                headingId={ids.toBook}
                anchor={bookingAnchor}
                items={items}
              />
            ) : null}
          </PlanSummary>

          <section aria-labelledby={ids.days} className="min-w-0 lg:col-start-1 lg:mt-12">
            <SectionHeading id={ids.days} lead={zoneName ? `Gli orari sono quelli di ${zoneName.replace(/^ora di /, "")}.` : undefined}>
              Giorno per giorno
            </SectionHeading>
            <div className="mt-4">
              {plan.days.length > 0 ? (
                <>
                  {desktop ? null : <ItineraryMapPanel className="mb-8" />}
                  <ItineraryDays>
                    <Itinerary
                      days={plan.days}
                      startDate={plan.start_date}
                      timeZone={plan.timezone}
                      bookings={plan.bookings}
                      bookingAnchor={bookingAnchor}
                    />
                  </ItineraryDays>
                </>
              ) : (
                <p className="text-small text-ink-2">Il piano non ha ancora tappe per giorno.</p>
              )}
            </div>
          </section>
        </div>
      </ItineraryMapProvider>

      <section id={ids.bookings} aria-labelledby={ids.bookingsHeading} className="min-w-0 scroll-mt-24">
        <SectionHeading
          id={ids.bookingsHeading}
          lead="Ognuna si prenota e si paga sul sito del fornitore, entro la sua data."
        >
          Prenotazioni
        </SectionHeading>
        {plan.bookings.length > 0 ? (
          <ol className="m-0 mt-2 list-none p-0">
            {byUrgency.map(({ booking, index, check, deadline }) => (
              <BookingRow
                key={`${booking.title}-${index}`}
                id={bookingAnchor(index)}
                booking={booking}
                check={check ?? null}
                deadline={deadline}
                timeZone={plan.timezone}
                startsAtHome={bookingStartsAtHome(plan, booking)}
                tripLabel={tripLabel}
              />
            ))}
          </ol>
        ) : (
          <p className="mt-3 text-small text-ink-2">Questo piano non ha niente da prenotare.</p>
        )}
      </section>

      {desktop ? null : handoff}

      {groups.length > 0 ? (
        <section aria-labelledby={ids.alternatives} className="min-w-0">
          <SectionHeading
            id={ids.alternatives}
            lead="Opzioni valide che il coordinatore non ha scelto. Restano qui e non vanno in TripTracker."
          >
            Alternative scartate
          </SectionHeading>
          <div className="mt-3 border-b border-rule">
            {groups.map((group) => (
              <Disclosure
                key={group.category}
                variant="section"
                summary={group.label}
                meta={alternativesCount(group.items.length)}
              >
                <ul className="m-0 list-none p-0">
                  {group.items.map((item) => (
                    <BookingRow
                      key={`${item.booking.title}-${item.index}`}
                      alternative
                      booking={item.booking}
                      check={item.check}
                      deadline={alternativeDeadline(item.booking)}
                      timeZone={plan.timezone}
                      startsAtHome={bookingStartsAtHome(plan, item.booking)}
                      tripLabel={tripLabel}
                    />
                  ))}
                </ul>
              </Disclosure>
            ))}
          </div>
        </section>
      ) : null}

      {timeline}

    </div>
    </PlanNowContext.Provider>
  );
}
