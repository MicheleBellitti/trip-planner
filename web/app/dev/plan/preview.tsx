"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import type { CoverLoader } from "@/components/plan/cover/cover-store";
import { PlanView, type TripLoader } from "@/components/plan/PlanView";
import happyDetail from "@/components/plan/__fixtures__/happy-path.detail.json";
import happyTrip from "@/components/plan/__fixtures__/happy-path.trip.json";
import kiwiDetail from "@/components/plan/__fixtures__/mcp-failure.detail.json";
import kiwiTrip from "@/components/plan/__fixtures__/mcp-failure.trip.json";
import { cx } from "@/components/ui/cx";
import { Disclosure } from "@/components/ui/disclosure";
import { PlanStatusBadge } from "@/components/ui/status-badge";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";
import { api } from "@/lib/api";
import { PlanDetailSchema, type PlanDetail } from "@/lib/schemas/api";

type PreviewScenario = "happy" | "kiwi" | "edge" | "fetch" | "failed";

const SCENARIOS: readonly PreviewScenario[] = ["happy", "kiwi", "edge", "fetch", "failed"];

const LABELS: Record<PreviewScenario, string> = {
  happy: "Pronto",
  kiwi: "Fonte caduta",
  edge: "Casi limite",
  fetch: "Trip in arrivo",
  failed: "Trip non letto",
};

const HOUR = 3_600_000;
/** The edge case's clock: when this module loaded in the browser (never read on the server). */
const LOADED_AT = typeof window === "undefined" ? 0 : Date.now();

/** The page's query, read in the browser only (null on the server): the plan formats dates
 * with Intl and the edge case is built around the browser's clock, so nothing of it is
 * rendered on the server. */
function useQuery(): URLSearchParams | null {
  const search = useSyncExternalStore(
    () => () => {},
    () => window.location.search,
    () => null,
  );
  return useMemo(() => (search === null ? null : new URLSearchParams(search)), [search]);
}

/** The running backend's Trip and cover, as the plan page reads them (PlanView imports no client). */
const liveLoadTrip: TripLoader = (planId, signal) => api.getTrip(planId, { signal });
const liveLoadCover: CoverLoader = (planId) => api.getCover(planId);

/** `?plan=<id>`: a plan of the running backend, read with lib/api like the plan page does;
 * PlanView reads its Trip and cover through the loaders above. */
function useLivePlan(planId: string | null): { planId: string; detail: PlanDetail | null; error: string | null } | null {
  const [live, setLive] = useState<{ planId: string; detail: PlanDetail | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!planId) return;
    let active = true;
    api.getPlan(planId).then(
      (detail) => {
        if (active) setLive({ planId, detail, error: null });
      },
      (error: unknown) => {
        if (active) setLive({ planId, detail: null, error: error instanceof Error ? error.message : String(error) });
      },
    );
    return () => {
      active = false;
    };
  }, [planId]);
  return planId && live?.planId === planId ? live : null;
}

/** The happy plan, bent around `now`: one deadline within 72 hours, one already past, one "Da
 * prenotare subito" (the Trip has no dueAt), a link outside the allowlist, a booking with no
 * dates, an unsafe stop URL, a long title and a long warning. */
function edgeCase(now: number): { detail: PlanDetail; trip: unknown } {
  const detail = PlanDetailSchema.parse(structuredClone(happyDetail));
  const trip = structuredClone(happyTrip) as { bookings: Record<string, unknown>[] };
  const plan = detail.plan;
  if (!plan) throw new Error("fixture without a plan");
  const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "+00:00");
  const [flight, hotel, oceanario, pena, aerobus] = plan.bookings;
  if (!flight || !hotel || !oceanario || !pena || !aerobus) throw new Error("fixture changed");

  flight.book_by = iso(now + 30 * HOUR);
  hotel.book_by = iso(now - 3 * HOUR);
  hotel.title = "Hotel Lisboa Plaza, camera familiare con due letti matrimoniali e colazione inclusa (4 notti)";
  if (trip.bookings[1]) trip.bookings[1].title = hotel.title; // the Trip copies each title
  delete trip.bookings[2]?.dueAt; // the backend left it out: "Da prenotare subito"
  pena.book_by = iso(now + 20 * 24 * HOUR);
  pena.link = "https://www.parquesdesintra.pt/en/tickets/?park=pena&date=2027-04-16&time=10:30&adults=2&children=2";
  aerobus.scheduled_for = null;
  aerobus.book_by = null;
  aerobus.phone = "+351 21 358 2334";
  if (trip.bookings[4]) delete trip.bookings[4].scheduledFor;
  detail.booking_links = [
    detail.booking_links[0] ?? null,
    detail.booking_links[1] ?? null,
    null,
    { allowed: false, provider: null, label: null, host: "www.parquesdesintra.pt" },
    null,
  ];
  const firstStop = plan.days[0]?.stops[0];
  if (firstStop) firstStop.url = "javascript:alert(1)";
  // The link check's three dead cases (PlanDetail.link_health): a stop page with a homepage
  // fallback ("Sito di ..."), a price source without one ("pagina non trovata") and a Google
  // Flights booking link, which never falls back to a button ("Pagina non trovata").
  const stopPage = plan.days.flatMap((day) => day.stops).find((stop) => stop.url);
  const flightsLink = "https://www.google.com/travel/flights?q=Flights%20from%20MXP%20to%20LIS";
  flight.link = flightsLink;
  detail.link_health = {
    ...(stopPage?.url ? { [stopPage.url]: { status: "dead", fallback: new URL(stopPage.url).origin + "/", fallback_allowed: false } } : {}),
    ...(oceanario.price ? { [oceanario.price.source_url]: { status: "dead", fallback: null, fallback_allowed: false } } : {}),
    [flightsLink]: { status: "dead", fallback: "https://www.google.com/", fallback_allowed: false },
  };
  plan.alternatives = [
    ...(plan.alternatives ?? []),
    {
      title: "Ingressi Quinta da Regaleira",
      kind: "ticket",
      vendor: "Fundação Cultursintra",
      book_by: iso(now + 50 * HOUR),
      book_by_reason: null,
      scheduled_for: "2027-04-16T14:00:00+01:00",
      link: null,
      notes: null,
      phone: null,
      price: null,
      stop_ref: null,
    },
  ];
  detail.alternative_links = [
    detail.alternative_links[0] ?? null,
    { allowed: false, provider: null, label: null, host: "www.martinhal.com" },
    null,
  ];
  plan.warnings = [
    ...(plan.warnings ?? []),
    "Il prezzo dell'Aerobus è letto sul sito ufficiale e può cambiare in alta stagione; nessuna data di partenza è ancora fissata, quindi non c'è una scadenza da rispettare.",
  ];
  return { detail, trip };
}

const never: TripLoader = () => new Promise(() => {});
const slow: TripLoader = (_planId, signal) =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(structuredClone(happyTrip)), 2500);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("aborted", "AbortError"));
    });
  });
const failing: TripLoader = () => Promise.reject(new Error("409 plan_not_ready"));

export function PlanPreview() {
  const query = useQuery();
  const livePlanId = query?.get("plan") ?? null;
  const live = useLivePlan(livePlanId);
  const scenario = query === null || livePlanId ? null : (SCENARIOS.find((name) => name === query.get("scenario")) ?? "happy");
  const data = useMemo(() => {
    if (scenario === null) return null;
    switch (scenario) {
      case "kiwi":
        return { detail: PlanDetailSchema.parse(kiwiDetail), trip: kiwiTrip as unknown, loadTrip: never };
      case "edge":
        return { ...edgeCase(LOADED_AT), loadTrip: never };
      case "fetch":
        return { detail: PlanDetailSchema.parse(happyDetail), trip: null, loadTrip: slow };
      case "failed":
        return { detail: PlanDetailSchema.parse(happyDetail), trip: null, loadTrip: failing };
      default:
        return { detail: PlanDetailSchema.parse(happyDetail), trip: happyTrip as unknown, loadTrip: never };
    }
  }, [scenario]);
  const loadTrip = useCallback<TripLoader>((planId, signal) => (data ? data.loadTrip(planId, signal) : never(planId, signal)), [data]);

  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex max-w-page items-center justify-between gap-3 px-4 py-3 lg:px-7">
        <Wordmark />
        <ThemeToggle />
      </header>
      <main className="mx-auto max-w-page px-4 pb-16 lg:px-7">
        <nav aria-label="Scenari di anteprima" className="mb-6 flex flex-wrap gap-2 text-meta">
          {SCENARIOS.map((name) => (
            <a
              key={name}
              href={`/dev/plan?scenario=${name}`}
              aria-current={name === scenario ? "page" : undefined}
              className={cx(
                "rounded-full border border-rule-strong px-2.5 py-0.5",
                name === scenario ? "bg-notice-wash font-semibold" : "text-ink-2",
              )}
            >
              {LABELS[name]}
            </a>
          ))}
        </nav>
        {livePlanId ? (
          live?.detail ? (
            <>
              <div className="mb-6 flex flex-col gap-2">
                <PlanStatusBadge status={live.detail.status} />
                <h1 className="font-cond text-display font-semibold lg:text-display-lg xl:text-display-xl">
                  {live.detail.title}
                </h1>
              </div>
              <PlanView detail={live.detail} loadTrip={liveLoadTrip} loadCover={liveLoadCover} />
            </>
          ) : (
            <p className="text-small text-ink-2">{live?.error ?? "Carico il piano…"}</p>
          )
        ) : null}
        {data ? (
          <>
            <div className="mb-6 flex flex-col gap-2">
              <PlanStatusBadge status={data.detail.status} />
              <h1 className="font-cond text-display font-semibold lg:text-display-lg xl:text-display-xl">
                {data.detail.title}
              </h1>
            </div>
            <PlanView
              detail={data.detail}
              trip={data.trip}
              loadTrip={loadTrip}
              loadCover={liveLoadCover}
              timeline={
                <Disclosure variant="section" summary="Il lavoro degli agenti" meta="32 eventi">
                  <p className="text-small text-ink-2">Qui la pagina mette la timeline del giro, chiusa.</p>
                </Disclosure>
              }
            />
          </>
        ) : null}
      </main>
    </div>
  );
}
