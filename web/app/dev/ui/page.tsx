import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { AgentRoundel } from "@/components/ui/agent";
import { Button, LinkButton } from "@/components/ui/button";
import { Chip, ToolChip } from "@/components/ui/chip";
import { CostMeter } from "@/components/ui/cost-meter";
import { DatePair } from "@/components/ui/date-pair";
import { Disclosure } from "@/components/ui/disclosure";
import { Icon } from "@/components/ui/icon";
import { IconButton } from "@/components/ui/icon-button";
import { ICON_PATHS, type IconName } from "@/components/ui/icons";
import { Mark } from "@/components/ui/mark";
import { InlineStatus, Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { PlanStatusBadge, StatusBadge } from "@/components/ui/status-badge";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import {
  Timeline,
  TimelineItem,
  TimelineMeta,
  TimelineNext,
  TimelineTitle,
  TimelineWaiting,
} from "@/components/ui/timeline";
import { Toaster } from "@/components/ui/toast";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { Wordmark } from "@/components/ui/wordmark";
import { AGENTS, AGENT_LABELS } from "@/lib/plan-events/labels";
import type { LaneBadgeState } from "@/lib/plan-events/labels";
import type { PlanStatus } from "@/lib/schemas/api";

import { FoldedLineDemo, FormDemo, FreshStationDemo, MeterDemo, SheetDemo, ToastDemo } from "./demos";

export const metadata: Metadata = {
  title: "Componenti",
  robots: { index: false, follow: false },
};

/** The synthetic "now" of every example: 12 ott 2026, 10:36, as in the design study. */
const DEMO_NOW = Date.parse("2026-10-12T10:36:12+02:00");
const LISBON = "Europe/Lisbon";
const ROME = "Europe/Rome";

const COLOR_TOKENS = [
  ["ground", "Fondo della pagina"],
  ["surface", "Carte delle corsie, campi"],
  ["ink", "Testo, bottoni, anello di focus"],
  ["ink-2", "Testo secondario"],
  ["rule", "Filetti decorativi"],
  ["rule-strong", "Bordi dei controlli (3:1)"],
  ["line-coordinator", "Linea coordinatore"],
  ["line-flights", "Linea voli"],
  ["line-lodging", "Linea alloggio"],
  ["line-activities", "Linea attività"],
  ["line-transport", "Linea spostamenti"],
  ["error", "Errori"],
  ["error-wash", "Fondo degli errori"],
  ["notice-wash", "Fondo delle note, hover"],
  ["amber", "Solo scadenze vicine: filetto"],
  ["amber-ink", "Solo scadenze vicine: testo"],
  ["amber-wash", "Solo scadenze vicine: fondo"],
] as const;

const LANE_STATES: LaneBadgeState[] = ["waiting", "working", "done", "error", "stopped", "not_started"];
const PLAN_STATUSES: PlanStatus[] = ["running", "ready", "budget_paused", "interrupted", "failed", "blocked"];

/** Development only: a gallery of every component in every state, in both themes. */
export default function ComponentGalleryPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-rule bg-[color-mix(in_srgb,var(--ground)_92%,transparent)] backdrop-blur-[8px]">
        <div className="mx-auto flex max-w-page items-center justify-between gap-4 px-4 py-3 lg:px-7">
          <div className="flex items-baseline gap-3">
            <Wordmark href="/" />
            <span className="text-meta text-ink-2">Componenti</span>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-page px-4 pt-6 pb-16 lg:px-7">
        <h1 className="font-cond text-display font-semibold lg:text-display-lg">Componenti</h1>
        <p className="mt-1 max-w-prose text-small text-ink-2">
          Galleria di sviluppo per il controllo visivo: ogni componente in ogni stato, a sinistra nel tema
          chiaro e a destra nel tema scuro. Non esiste in produzione. I token sono in web/DESIGN.md.
        </p>

        <Section title="Colori">
          <ThemePair>
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {COLOR_TOKENS.map(([token, use]) => (
                <li key={token} className="flex items-center gap-3">
                  <span
                    className="size-9 shrink-0 rounded-sm inset-ring-1 inset-ring-rule"
                    style={{ backgroundColor: `var(--${token})` }}
                  />
                  <span className="min-w-0">
                    <span className="block text-small font-semibold">{token}</span>
                    <span className="block text-micro text-ink-2">{use}</span>
                  </span>
                </li>
              ))}
            </ul>
          </ThemePair>
        </Section>

        <Section title="Tipografia">
          <ThemePair>
            <div className="grid gap-3">
              <p className="font-cond text-display font-semibold">Lisbona, 14–18 nov</p>
              <p className="font-cond text-heading font-semibold">Anteprima delle prenotazioni</p>
              <p className="font-cond text-title font-semibold">Coordinatore</p>
              <p className="text-body">
                Da Milano, 2 adulti e 2 bambini (8 e 11 anni), budget 2.400 €. Cifre tabellari: 1,62 $ 4,00 $ 10:31.
              </p>
              <p className="text-small">Expedia · voli MXP→LIS · 14–18 nov</p>
              <p className="text-meta text-ink-2">Kiwi non risponde dopo 2 tentativi.</p>
              <p className="text-micro text-ink-2">7:12 · in corso da 0:14</p>
            </div>
          </ThemePair>
        </Section>

        <Section title="Icone (Phosphor 2.1.1, bold)">
          <ThemePair>
            <ul className="grid grid-cols-3 gap-x-2 gap-y-3 sm:grid-cols-5">
              {(Object.keys(ICON_PATHS) as IconName[]).map((name) => (
                <li key={name} className="flex flex-col items-center gap-1 text-center">
                  <Icon name={name} size={20} />
                  <span className="text-micro break-all text-ink-2">{name}</span>
                </li>
              ))}
            </ul>
          </ThemePair>
        </Section>

        <Section title="Bottoni">
          <ThemePair>
            <div className="grid gap-4">
              <Row label="Primario">
                <Button variant="primary">Pianifica il viaggio</Button>
                <Button variant="primary" icon="play">
                  Continua con 2 $ in più
                </Button>
                <Button variant="primary" disabled>
                  Disattivato
                </Button>
                <Button variant="primary" busy>
                  Avvio il piano…
                </Button>
              </Row>
              <Row label="Secondario">
                <Button icon="stop">Interrompi</Button>
                <Button>Continua il piano</Button>
                <Button disabled>Disattivato</Button>
                <Button busy>Interrompo…</Button>
              </Row>
              <Row label="Silenzioso">
                <Button variant="quiet" icon="arrows-clockwise">
                  Riprova
                </Button>
                <Button variant="quiet" disabled>
                  Disattivato
                </Button>
              </Row>
              <Row label="Piccolo">
                <Button size="sm" variant="primary">
                  Nuovo piano
                </Button>
                <Button size="sm" icon="plus">
                  Nuovo piano
                </Button>
                <Button size="sm" variant="quiet">
                  Annulla
                </Button>
              </Row>
              <Row label="Link">
                <LinkButton href="/new" icon="plus" variant="primary">
                  Nuovo piano
                </LinkButton>
                <LinkButton href="https://www.expedia.it" external variant="primary">
                  Prenota su Expedia
                </LinkButton>
                <LinkButton href="https://viaggi.bellittim.com/import" external>
                  Apri in TripTracker
                </LinkButton>
              </Row>
            </div>
          </ThemePair>
        </Section>

        <Section title="Bottoni a icona e tema">
          <ThemePair>
            <Row label="Stati">
              <IconButton icon="x" label="Chiudi" />
              <IconButton icon="arrow-left" label="Torna ai piani" />
              <IconButton icon="x" label="Chiudi" size="sm" />
              <IconButton icon="x" label="Chiudi il messaggio" size="sm" variant="bare" />
              <IconButton icon="x" label="Chiudi" disabled />
              <ThemeToggle />
            </Row>
          </ThemePair>
        </Section>

        <Section title="Agenti">
          <ThemePair>
            <div className="grid gap-3">
              {AGENTS.map((agent) => (
                <div key={agent} className="flex items-center gap-3">
                  <AgentRoundel agent={agent} size="sm" />
                  <AgentRoundel agent={agent} />
                  <AgentRoundel agent={agent} size="lg" />
                  <span className="font-cond text-title font-semibold">{AGENT_LABELS[agent]}</span>
                </div>
              ))}
            </div>
          </ThemePair>
        </Section>

        <Section title="Stato della corsia e del piano">
          <ThemePair>
            <div className="grid gap-4">
              <Row label="Corsia">
                {LANE_STATES.map((state) => (
                  <StatusBadge key={state} state={state} agent="flights" />
                ))}
              </Row>
              <Row label="Al lavoro, per agente">
                {AGENTS.map((agent) => (
                  <StatusBadge key={agent} state="working" agent={agent} />
                ))}
              </Row>
              <Row label="Piano">
                {PLAN_STATUSES.map((status) => (
                  <PlanStatusBadge key={status} status={status} />
                ))}
              </Row>
              <Row label="Piano, intestazione">
                {PLAN_STATUSES.map((status) => (
                  <PlanStatusBadge key={status} status={status} size="lg" />
                ))}
              </Row>
            </div>
          </ThemePair>
        </Section>

        <Section title="Chip e tool in corso">
          <ThemePair>
            <div className="grid gap-4">
              <Row label="Chip">
                <Chip>verificato</Chip>
                <Chip>stimato</Chip>
                <Chip tone="quiet">sviluppo</Chip>
                <Chip tone="quiet">3 alternative</Chip>
              </Row>
              <div className="grid gap-2 sm:grid-cols-2">
                {AGENTS.map((agent) => (
                  <ToolChip
                    key={agent}
                    agent={agent}
                    title={agent === "flights" ? "Expedia · voli MXP→LIS · 14–18 nov" : "Legge results/lodging.json · v2"}
                    elapsed="0:14"
                  />
                ))}
                <ToolChip
                  agent="activities"
                  title="Apre la pagina: Oceanário de Lisboa, orari e biglietti per famiglie con bambini"
                />
              </div>
              <div className="grid gap-2">
                {AGENTS.map((agent) => (
                  <ToolChip
                    key={agent}
                    agent={agent}
                    variant="inline"
                    title={agent === "transport" ? "Cerca sul web: Aeroporto di Lisbona → Alfama, metro e taxi" : "Expedia · voli MXP→LIS · 14–18 nov"}
                    elapsed={agent === "coordinator" ? null : "0:14"}
                  />
                ))}
              </div>
            </div>
          </ThemePair>
        </Section>

        <Section title="Costo della sessione">
          <ThemePair>
            <div className="grid gap-5">
              <CostMeter costCents={162} budgetCents={400} />
              <CostMeter costCents={45} budgetCents={60} />
              <CostMeter costCents={0} budgetCents={400} />
              <CostMeter costCents={400} budgetCents={400} />
              <CostMeter costCents={431} budgetCents={400} />
              <CostMeter costCents={null} budgetCents={400} />
              <CostMeter costCents={0} budgetCents={60} pending />
              <CostMeter costCents={38} budgetCents={60} hint="Aggiornato a fine turno" />
              <CostMeter costCents={120} budgetCents={null} />
              <MeterDemo />
            </div>
          </ThemePair>
        </Section>

        <Section title="Disclosure">
          <ThemePair>
            <div className="grid gap-3">
              <Disclosure summary="coordinatore → voli: incarico" contentLang="en">
                Find round-trip flights from Milan (MXP or LIN) to Lisbon for 2 adults and 2 children aged 8 and
                11, out Sat 14 Nov, back Wed 18 Nov 2026. Direct flights first.
              </Disclosure>
              <Disclosure summary="alloggio → coordinatore: esito" contentLang="en" defaultOpen>
                4 options in results/lodging.json v2. Best fit: 2-bedroom apartment in Alfama, 1,080 EUR for 4
                nights, free cancellation until 7 Nov.
              </Disclosure>
              <Disclosure variant="section" summary="Alternative scartate" meta="3">
                <p className="text-small text-ink-2">Hotel in Baixa, 1.240 € per 4 notti: oltre il budget.</p>
              </Disclosure>
              <Disclosure variant="section" summary="Timeline del giro" meta="42 eventi" defaultOpen>
                <p className="text-small text-ink-2">La timeline completa resta qui, richiusa sotto il piano.</p>
              </Disclosure>
            </div>
          </ThemePair>
        </Section>

        <Section title="Note e stato dello stream">
          <ThemePair>
            <div className="grid gap-3">
              <Notice tone="warning">Kiwi non risponde dopo 2 tentativi. Cerco su Expedia e lastminute.com.</Notice>
              <Notice tone="info">Prezzi stimati: 2 prenotazioni su 5 non hanno un prezzo verificato.</Notice>
              <Notice tone="error">La ricerca si è fermata. Esito parziale salvato; il coordinatore prosegue con gli altri.</Notice>
              <Notice
                tone="error"
                title="Interruzione non riuscita"
                action={
                  <Button size="sm" variant="quiet" icon="arrows-clockwise">
                    Riprova
                  </Button>
                }
              >
                Il backend non ha risposto. Il piano continua; riprova tra poco.
              </Notice>
              <InlineStatus turning>Stream in riconnessione. Gli eventi persi arrivano da soli.</InlineStatus>
              <InlineStatus icon="wifi-slash">Non aggiornato: sei offline, ultimo stato alle 10:41.</InlineStatus>
              <InlineStatus icon="sign-in">Sessione scaduta: accedi di nuovo per vedere il piano.</InlineStatus>
            </div>
          </ThemePair>
        </Section>

        <Section title="Date di una prenotazione">
          <ThemePair>
            <div className="grid gap-4">
              <Row label="In scadenza (entro 72 ore)">
                <DatePair
                  className="w-full"
                  deadline={{ kind: "date", at: "2026-10-14T23:59:00+02:00" }}
                  scheduledFor="2026-11-14T15:00:00+00:00"
                  scheduledHint="fino a mer 18 nov"
                  timeZone={LISBON}
                  now={DEMO_NOW}
                />
              </Row>
              <Row label="Il viaggio è in un altro fuso, il volo parte da casa: 'Quando' sull'ora di casa, quella di Lisbona sotto">
                <DatePair
                  className="w-full"
                  deadline={{ kind: "date", at: "2027-02-26T20:00:00Z" }}
                  scheduledFor="2027-04-14T08:40:00+01:00"
                  timeZone={LISBON}
                  deadlineTimeZone={ROME}
                  startsAtHome
                  tripLabel="a Lisbona"
                  now={DEMO_NOW}
                />
              </Row>
              <Row label="Prenotazione a destinazione: solo l'ora del viaggio, nessuna seconda ora">
                <DatePair
                  className="w-full"
                  deadline={{ kind: "date", at: "2027-03-14T20:00:00Z" }}
                  scheduledFor="2027-04-14T15:00:00+01:00"
                  timeZone={LISBON}
                  deadlineTimeZone={ROME}
                  tripLabel="a Lisbona"
                  now={DEMO_NOW}
                />
              </Row>
              <Row label="Non in scadenza">
                <DatePair
                  className="w-full"
                  deadline={{ kind: "date", at: "2026-10-30T23:59:00+01:00" }}
                  scheduledFor="2026-11-14T07:05:00+01:00"
                  scheduledHint="ritorno mer 18 nov"
                  timeZone={ROME}
                  now={DEMO_NOW}
                />
              </Row>
              <Row label="Tra poche ore, scaduta">
                <DatePair
                  className="w-full"
                  deadline={{ kind: "date", at: "2026-10-12T18:00:00+02:00" }}
                  scheduledFor="2026-11-15T10:00:00+00:00"
                  timeZone={LISBON}
                  now={DEMO_NOW}
                />
                <DatePair
                  className="w-full"
                  deadline={{ kind: "date", at: "2026-10-11T18:00:00+02:00" }}
                  scheduledFor="2026-11-15T10:00:00+00:00"
                  timeZone={LISBON}
                  now={DEMO_NOW}
                />
              </Row>
              <Row label="Senza dueAt">
                <DatePair
                  className="w-full"
                  deadline={{ kind: "book_now" }}
                  scheduledFor="2026-10-13T09:00:00+02:00"
                  timeZone={ROME}
                  now={DEMO_NOW}
                />
                <DatePair className="w-full" deadline={{ kind: "none" }} scheduledFor={null} timeZone={LISBON} now={DEMO_NOW} />
                <DatePair
                  className="w-full"
                  deadline={{ kind: "pending" }}
                  scheduledFor="2026-11-16T09:30:00+00:00"
                  timeZone={LISBON}
                  now={DEMO_NOW}
                />
                <DatePair
                  className="w-full"
                  deadline={{ kind: "unknown" }}
                  scheduledFor="2026-11-16T09:30:00+00:00"
                  timeZone={LISBON}
                  now={DEMO_NOW}
                />
              </Row>
              <Row label="Prima del primo secondo (now null)">
                <DatePair
                  className="w-full"
                  deadline={{ kind: "date", at: "2026-10-14T23:59:00+02:00" }}
                  scheduledFor="2026-11-14T15:00:00+00:00"
                  timeZone={LISBON}
                  now={null}
                />
              </Row>
              <Row label="Compatta" stack>
                <DatePair
                  variant="compact"
                  deadline={{ kind: "date", at: "2026-10-14T23:59:00+02:00" }}
                  scheduledFor="2026-11-14T15:00:00+00:00"
                  timeZone={LISBON}
                  now={DEMO_NOW}
                />
                <DatePair
                  variant="compact"
                  deadline={{ kind: "date", at: "2026-10-30T23:59:00+01:00" }}
                  scheduledFor="2026-11-14T07:05:00+01:00"
                  timeZone={ROME}
                  now={DEMO_NOW}
                />
                <DatePair
                  variant="compact"
                  deadline={{ kind: "book_now" }}
                  scheduledFor={null}
                  timeZone={ROME}
                  now={DEMO_NOW}
                />
              </Row>
            </div>
          </ThemePair>
        </Section>

        <Section title="Linea di una corsia">
          <ThemePair>
            <div className="grid gap-4">
              <LaneCard>
                <Timeline agent="coordinator" label="Eventi del coordinatore">
                  <TimelineItem kind="status" time="0:00">
                    <TimelineTitle>Sessione avviata</TimelineTitle>
                  </TimelineItem>
                  <TimelineItem kind="wave" time="0:26">
                    <TimelineTitle>Ondata 1</TimelineTitle>
                    <TimelineMeta>Voli, alloggio e attività in parallelo</TimelineMeta>
                  </TimelineItem>
                  <TimelineItem kind="message" time="0:26">
                    <Disclosure summary="coordinatore → voli: incarico" contentLang="en">
                      Find round-trip flights from Milan to Lisbon for 2 adults and 2 children.
                    </Disclosure>
                  </TimelineItem>
                  <TimelineItem kind="tool" time="7:38">
                    <TimelineTitle>Legge results/flights.json · v1</TimelineTitle>
                    <TimelineMeta>meno di 1 s</TimelineMeta>
                  </TimelineItem>
                  <TimelineItem kind="wave" time="7:40">
                    <TimelineTitle>Scelta</TimelineTitle>
                    <TimelineMeta>Volo diretto MXP→LIS e appartamento ad Alfama</TimelineMeta>
                  </TimelineItem>
                  <TimelineItem kind="wave" time="7:48">
                    <TimelineTitle>Ondata 2</TimelineTitle>
                    <TimelineMeta>Parte spostamenti</TimelineMeta>
                  </TimelineItem>
                  <TimelineItem kind="current" time="7:48">
                    <ToolChip agent="coordinator" title="Aspetta l'ondata 2" elapsed="0:20" />
                  </TimelineItem>
                  <TimelineNext />
                </Timeline>
              </LaneCard>
              <LaneCard>
                <Timeline agent="flights" label="Eventi di voli">
                  <TimelineItem kind="status" time="0:31">
                    <TimelineTitle>Al lavoro</TimelineTitle>
                  </TimelineItem>
                  <TimelineItem kind="failed" time="0:44">
                    <TimelineTitle>Kiwi · voli MXP→LIS · 14–18 nov</TimelineTitle>
                    <TimelineMeta tone="error">Nessuna risposta in 30 s</TimelineMeta>
                  </TimelineItem>
                  <TimelineItem kind="tool" time="1:52">
                    <TimelineTitle>lastminute.com · voli MXP→LIS · 14–18 nov</TimelineTitle>
                    <TimelineMeta>6,2 s</TimelineMeta>
                  </TimelineItem>
                  <TimelineItem kind="current" time="6:58">
                    <ToolChip agent="flights" title="Expedia · voli MXP→LIS · 14–18 nov" elapsed="0:14" />
                  </TimelineItem>
                  <TimelineNext />
                </Timeline>
              </LaneCard>
              <LaneCard>
                <Timeline agent="activities" label="Eventi di attività">
                  <TimelineItem kind="tool" time="4:58">
                    <TimelineTitle>Scrive results/activities.json · v1</TimelineTitle>
                    <TimelineMeta>meno di 1 s</TimelineMeta>
                  </TimelineItem>
                  <TimelineItem kind="error" time="5:04">
                    <TimelineTitle>Errore: ricerca interrotta</TimelineTitle>
                  </TimelineItem>
                </Timeline>
              </LaneCard>
              <LaneCard>
                <Timeline agent="lodging" label="Eventi di alloggio">
                  <TimelineItem kind="tool" time="4:52">
                    <TimelineTitle>Scrive results/lodging.json · v2</TimelineTitle>
                    <TimelineMeta>meno di 1 s</TimelineMeta>
                  </TimelineItem>
                  <TimelineItem kind="status" time="5:49">
                    <TimelineTitle>Finito</TimelineTitle>
                  </TimelineItem>
                </Timeline>
              </LaneCard>
              <LaneCard>
                <TimelineWaiting agent="transport">Parte dopo la scelta di volo e alloggio.</TimelineWaiting>
              </LaneCard>
              <LaneCard>
                <FreshStationDemo />
              </LaneCard>
              <LaneCard>
                <FoldedLineDemo />
              </LaneCard>
            </div>
          </ThemePair>
        </Section>

        <Section title="Sheet e messaggi">
          <ThemePair>
            <div className="grid gap-4">
              <Row label="Sheet (in basso sul telefono)">
                <SheetDemo />
              </Row>
              <Row label="Toast">
                <ToastDemo />
              </Row>
            </div>
          </ThemePair>
        </Section>

        <Section title="Caricamento">
          <ThemePair>
            <div aria-busy="true" className="grid gap-3">
              <VisuallyHidden>Caricamento delle corsie</VisuallyHidden>
              <LaneCard>
                <div className="flex items-center gap-2.5">
                  <Skeleton shape="round" className="size-[30px]" />
                  <Skeleton className="w-28 text-title" />
                  <Skeleton className="ml-auto w-16 text-meta" />
                </div>
                <div className="mt-3 grid gap-2 pl-[54px]">
                  <Skeleton className="w-4/5" />
                  <Skeleton className="w-3/5" />
                </div>
              </LaneCard>
              <div className="flex items-center gap-3 py-2">
                <Skeleton className="w-2/5 text-body" />
                <Skeleton className="ml-auto w-14 text-body" />
              </div>
            </div>
          </ThemePair>
        </Section>

        <Section title="Moduli">
          <ThemePair>
            <FormDemo />
          </ThemePair>
        </Section>

        <Section title="Testo per screen reader e marchio">
          <ThemePair>
            <div className="grid gap-3">
              <p className="text-small">
                Prenota su Expedia
                <VisuallyHidden> (si apre in una nuova scheda)</VisuallyHidden>
                <span className="text-ink-2"> (il resto della frase è letto solo dagli screen reader)</span>
              </p>
              <div className="flex flex-wrap items-end gap-4">
                <Mark className="size-16" />
                <Mark className="size-10" />
                <Mark className="size-7" />
                <Wordmark />
              </div>
              <p className="text-meta">
                Variante dark: <span className="dark:hidden">tema chiaro</span>
                <span className="hidden dark:inline">tema scuro</span>
              </p>
            </div>
          </ThemePair>
        </Section>
      </main>
      <Toaster />
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="mb-3 font-cond text-heading font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** The same content in a light and a dark panel: side by side from 1080 px, stacked below. */
function ThemePair({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {(["light", "dark"] as const).map((theme) => (
        <div key={theme} data-theme={theme} className="min-w-0 rounded-md border border-rule p-4">
          <p className="mb-3 text-micro text-ink-2">{theme === "light" ? "Chiaro" : "Scuro"}</p>
          {children}
        </div>
      ))}
    </div>
  );
}

function Row({ label, stack = false, children }: { label: string; stack?: boolean; children: ReactNode }) {
  return (
    <div className="grid gap-2">
      <p className="text-micro text-ink-2">{label}</p>
      <div className={stack ? "grid gap-2" : "flex flex-wrap items-center gap-2"}>{children}</div>
    </div>
  );
}

/** A lane-shaped frame for the examples: the phone's lane card (surface, rule edge, 16 px). */
function LaneCard({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-rule bg-surface px-3.5 py-3">{children}</div>;
}
