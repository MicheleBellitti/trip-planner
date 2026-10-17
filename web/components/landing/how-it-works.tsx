import type { ReactNode } from "react";

import { RouteLine, TripFact } from "@/components/request/trip-outline";
import { AgentRoundel } from "@/components/ui/agent";
import { buttonClasses } from "@/components/ui/button";
import { Chip, ToolChip } from "@/components/ui/chip";
import { cx } from "@/components/ui/cx";
import { DatePair } from "@/components/ui/date-pair";
import { Icon } from "@/components/ui/icon";
import { StatusBadge } from "@/components/ui/status-badge";
import { Timeline, TimelineItem, TimelineMeta, TimelineNext, TimelineTitle } from "@/components/ui/timeline";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { AGENT_LABELS } from "@/lib/plan-events/labels";

/** The samples' fixed "now": the booking's deadline is two days away, so DatePair draws it due
 * soon (the amber's one job). The page is prerendered, so the sample never moves. */
const SAMPLE_NOW = Date.parse("2026-10-17T10:00:00+02:00");

/**
 * "Come funziona" (DESIGN.md, Landing): three stations on one ink line, vertical on the phone,
 * horizontal from 1080 px. Each one holds a real component with sample data. The samples are
 * illustrations: a screen reader hears one sentence (the figcaption), and the drawing is inert and
 * hidden from it, so nothing looks clickable that is not. The booking's "Prenota su Expedia" is
 * never a link (CLAUDE.md contract rule 4: booking URLs are never hand-written).
 */
export function HowItWorks() {
  return (
    <section
      id="come-funziona"
      aria-labelledby="come-funziona-titolo"
      className="mx-auto max-w-landing scroll-mt-4 px-4 pt-18 lg:px-7"
    >
      <h2 id="come-funziona-titolo" className="font-cond text-display font-semibold lg:text-display-lg">
        Come funziona
      </h2>
      <p className="mt-2 max-w-[36em] text-small text-ink-2">Tre fermate, dalla richiesta alla prenotazione.</p>
      <ol
        className={cx(
          "relative mt-9 grid gap-9 pl-9 lg:grid-cols-3 lg:gap-7 lg:pt-9 lg:pl-0",
          "before:absolute before:top-2.5 before:bottom-2.5 before:left-[11px] before:w-[3px] before:rounded-full before:bg-ink",
          "lg:before:inset-x-2 lg:before:top-1.5 lg:before:bottom-auto lg:before:h-[3px] lg:before:w-auto",
        )}
      >
        <Stop
          title="Descrivi il viaggio"
          text="Da dove parti e dove vuoi andare, oppure solo un'idea. Le date, chi viaggia, il budget. Bastano poche righe."
          caption="Esempio di richiesta: da Milano a Lisbona, dal 14 al 18 aprile 2027, 4 notti, 2 adulti e 2 bambini di 8 e 11 anni, 2.400 euro in tutto."
        >
          <RouteLine origin={{ text: "Milano" }} destination={{ text: "Lisbona" }} />
          <ul className="mt-3.5 grid gap-2 border-t border-rule pt-3 text-small">
            <TripFact icon="calendar-blank">14–18 aprile 2027, 4 notti</TripFact>
            <TripFact icon="users">2 adulti, 2 bambini di 8 e 11 anni</TripFact>
            <TripFact icon="wallet">2.400 € in tutto</TripFact>
          </ul>
        </Stop>
        <Stop
          title="Guarda gli agenti"
          text="Cinque agenti cercano in parallelo e vedi ogni passo mentre succede: chi lavora, su cosa, quanto costa."
          caption="Esempio di corsia: l'agente dei voli al lavoro. Ha ricevuto l'incarico, ha cercato su Expedia e ora sta cercando su Google Flights un volo diretto TAP, da 14 secondi."
        >
          <div className="flex items-center gap-2.5">
            <AgentRoundel agent="flights" size="md" />
            <span className="font-cond text-title font-semibold">{AGENT_LABELS.flights}</span>
            <StatusBadge state="working" agent="flights" className="ml-auto" />
          </div>
          <Timeline agent="flights" label="Esempio: la linea dei voli" className="mt-3">
            <TimelineItem kind="status" time="0:02">
              <TimelineTitle>Incarico ricevuto</TimelineTitle>
            </TimelineItem>
            <TimelineItem kind="tool" time="0:05">
              <TimelineTitle>Expedia · voli MXP→LIS</TimelineTitle>
              <TimelineMeta>1,3 s</TimelineMeta>
            </TimelineItem>
            <TimelineItem kind="current" time="0:06">
              <ToolChip agent="flights" title="Google Flights · TAP diretto" elapsed="0:14" />
            </TimelineItem>
            <TimelineNext />
          </Timeline>
        </Stop>
        <Stop
          title="Prenota entro la data"
          text="Ogni prenotazione ha due date: entro quando prenotarla e quando succede. Il prezzo ha la sua fonte, il link porta al sito giusto."
          caption="Esempio di prenotazione: il volo TAP tra Milano Malpensa e Lisbona, da prenotare entro lunedì 19 ottobre alle 23:59, in scadenza tra 2 giorni; il volo parte mercoledì 14 aprile alle 9:40. 472 euro, prezzo verificato su expedia.it."
        >
          <p className="text-body font-semibold">Volo TAP Milano Malpensa ⇄ Lisbona</p>
          <DatePair
            deadline={{ kind: "date", at: "2026-10-19T23:59:00+02:00" }}
            scheduledFor="2027-04-14T09:40:00+02:00"
            timeZone="Europe/Lisbon"
            deadlineTimeZone="Europe/Rome"
            startsAtHome
            tripLabel="a Lisbona"
            now={SAMPLE_NOW}
            className="mt-2.5"
          />
          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-small text-ink-2">
            <span className="font-semibold text-ink">472,00 €</span>
            <Chip>verificato</Chip>
            <span>Fonte expedia.it, letto il 17 ott 2026, 10:12</span>
          </p>
          <span className={cx(buttonClasses("primary"), "mt-3.5")}>
            Prenota su Expedia
            <Icon name="arrow-square-out" size={16} />
          </span>
        </Stop>
      </ol>
    </section>
  );
}

/** One station: its ring on the line, its title and sentence, and the sample as a figure. */
function Stop({ title, text, caption, children }: { title: string; text: string; caption: string; children: ReactNode }) {
  return (
    <li className="relative">
      <span
        aria-hidden="true"
        className="absolute top-[3px] -left-9 size-4 translate-x-1 rounded-full border-[3.5px] border-ink bg-ground lg:-top-9 lg:left-0 lg:translate-x-0"
      />
      <h3 className="font-cond text-heading font-semibold">{title}</h3>
      <p className="mt-1.5 max-w-[32em] text-small text-ink-2">{text}</p>
      <figure className="m-0 mt-4.5">
        <VisuallyHidden as="figcaption">{caption}</VisuallyHidden>
        <div aria-hidden="true" inert className="rounded-md border border-rule bg-surface px-4 py-3.5">
          {children}
        </div>
      </figure>
    </li>
  );
}
