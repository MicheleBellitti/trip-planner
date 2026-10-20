"use client";

/** Interactive pieces of the /dev/ui gallery (development only). */

import { useId, useState, type ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import { ToolChip } from "@/components/ui/chip";
import { ChoiceCard, type ChoiceCardMedia } from "@/components/ui/choice-card";
import { CostMeter } from "@/components/ui/cost-meter";
import { Field, NumberStepper, SegmentedControl, Select, TextArea, TextInput } from "@/components/ui/field";
import { Sheet } from "@/components/ui/sheet";
import {
  Timeline,
  TimelineEarlier,
  TimelineItem,
  TimelineMeta,
  TimelineNext,
  TimelineTitle,
} from "@/components/ui/timeline";
import { toast } from "@/components/ui/toast";
import type { ChoiceOptionView } from "@/lib/choices";

export function SheetDemo() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button icon="stop" onClick={() => setOpen(true)}>
        Interrompi
      </Button>
      <Sheet
        open={open}
        onOpenChange={setOpen}
        title="Interrompere il piano?"
        description="Gli agenti chiudono il passo in corso e quello che hanno trovato resta salvato."
        footer={
          <>
            <Button onClick={() => setOpen(false)}>Continua il piano</Button>
            <Button
              variant="primary"
              onClick={() => {
                setOpen(false);
                toast("Interruzione richiesta. Gli agenti chiudono il passo in corso.");
              }}
            >
              Interrompi il piano
            </Button>
          </>
        }
      />
    </>
  );
}

export function ToastDemo() {
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" onClick={() => toast("Link copiato.")}>
        Mostra un messaggio
      </Button>
      <Button
        size="sm"
        onClick={() =>
          toast("Interruzione non riuscita: il piano è già finito. Ricarica la pagina per vederlo.", { tone: "error" })
        }
      >
        Mostra un errore
      </Button>
    </div>
  );
}

const COST_STEPS = [0, 48, 162, 233, 371, 400];

export function MeterDemo() {
  const [step, setStep] = useState(2);
  return (
    <div className="grid gap-3">
      <CostMeter costCents={COST_STEPS[step] ?? 0} budgetCents={400} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={step === 0} onClick={() => setStep((value) => Math.max(0, value - 1))}>
          Togli costo
        </Button>
        <Button
          size="sm"
          disabled={step === COST_STEPS.length - 1}
          onClick={() => setStep((value) => Math.min(COST_STEPS.length - 1, value + 1))}
        >
          Aggiungi costo
        </Button>
      </div>
    </div>
  );
}

interface DemoStation {
  id: number;
  time: string;
  title: string;
  meta: string;
}

const NEXT_STATIONS: DemoStation[] = [
  { id: 1, time: "7:31", title: "Expedia · voli MXP→LIS · 14–18 nov", meta: "18,4 s" },
  { id: 2, time: "7:34", title: "Scrive results/flights.json · v1", meta: "meno di 1 s" },
];

/** Plays the arrival of new stations, to see the line draw (or fade, with reduced motion). */
export function FreshStationDemo() {
  const [arrived, setArrived] = useState(0);
  const stations = NEXT_STATIONS.slice(0, arrived);
  return (
    <div className="grid gap-3">
      <Timeline agent="flights" label="Eventi di voli (prova)">
        <TimelineItem kind="tool" time="4:35">
          <TimelineTitle>Expedia · voli LIN→LIS · 14–18 nov</TimelineTitle>
          <TimelineMeta>5,8 s</TimelineMeta>
        </TimelineItem>
        {stations.map((station, index) => (
          <TimelineItem key={station.id} kind="tool" time={station.time} fresh={index === arrived - 1}>
            <TimelineTitle>{station.title}</TimelineTitle>
            <TimelineMeta>{station.meta}</TimelineMeta>
          </TimelineItem>
        ))}
        <TimelineItem kind="current" time="7:36">
          <ToolChip agent="flights" title="Scrive results/flights.json · v1" elapsed="0:02" />
        </TimelineItem>
        <TimelineNext />
      </Timeline>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={arrived >= NEXT_STATIONS.length} onClick={() => setArrived((value) => value + 1)}>
          Aggiungi una fermata
        </Button>
        <Button size="sm" variant="quiet" disabled={arrived === 0} onClick={() => setArrived(0)}>
          Ricomincia
        </Button>
      </div>
    </div>
  );
}

/** The phone's open lane: older stations folded into one row, unfolded on request. */
export function FoldedLineDemo() {
  const [expanded, setExpanded] = useState(false);
  const older = ["Expedia · voli MXP→LIS · 14–18 nov", "Ricerca web: TAP TP827 orario", "Consegna l'esito"];
  return (
    <Timeline agent="flights" label="Eventi di voli (riga ripiegata)">
      <TimelineEarlier count={older.length} expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
      {expanded
        ? older.map((title, index) => (
            <TimelineItem key={title} kind="tool" time={`0:0${index + 2}`}>
              <TimelineTitle>{title}</TimelineTitle>
            </TimelineItem>
          ))
        : null}
      <TimelineItem kind="tool" time="0:12">
        <TimelineTitle>Legge la pagina www.martinhal.com</TimelineTitle>
        <TimelineMeta>1,3 s</TimelineMeta>
      </TimelineItem>
      <TimelineItem kind="current" time="0:14">
        <ToolChip agent="flights" title="Link di prenotazione · Google Flights · MXP→LIS" elapsed="0:02" />
      </TimelineItem>
      <TimelineNext />
    </Timeline>
  );
}

const MONTHS = ["novembre 2026", "dicembre 2026", "gennaio 2027"] as const;

export function FormDemo() {
  const [where, setWhere] = useState<"destination" | "suggest">("destination");
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(2);
  const groupName = useId();
  return (
    <div className="grid gap-5">
      <SegmentedControl
        legend="Dove vai"
        name={groupName}
        options={[
          { value: "destination", label: "Destinazione" },
          { value: "suggest", label: "Suggeriscimi tu" },
        ]}
        value={where}
        onValueChange={setWhere}
      />
      <Field label="Da dove parti" hint="Una città o un aeroporto">
        {(control) => <TextInput {...control} defaultValue="Milano" autoComplete="off" />}
      </Field>
      <Field label="Destinazione" error="Scrivi una città o scegli “Suggeriscimi tu”.">
        {(control) => <TextInput {...control} placeholder="Per esempio Lisbona" />}
      </Field>
      <Field label="Mese">
        {(control) => (
          <Select {...control} defaultValue={MONTHS[0]}>
            {MONTHS.map((month) => (
              <option key={month}>{month}</option>
            ))}
          </Select>
        )}
      </Field>
      <div className="flex flex-wrap gap-6">
        <Field label="Adulti">
          {(control) => (
            <NumberStepper
              {...control}
              value={adults}
              onValueChange={setAdults}
              min={1}
              max={9}
              decrementLabel="Togli un adulto"
              incrementLabel="Aggiungi un adulto"
            />
          )}
        </Field>
        <Field label="Bambini">
          {(control) => (
            <NumberStepper
              {...control}
              value={children}
              onValueChange={setChildren}
              min={0}
              max={9}
              decrementLabel="Togli un bambino"
              incrementLabel="Aggiungi un bambino"
            />
          )}
        </Field>
      </div>
      <Field label="Preferenze" optional hint="Quello che conta per te, in poche parole">
        {(control) => <TextArea {...control} placeholder="Volo diretto, quartiere tranquillo, niente auto" />}
      </Field>
      <Field label="Budget totale in euro">
        {(control) => <TextInput {...control} inputMode="numeric" defaultValue="2400" disabled />}
      </Field>
    </div>
  );
}

/** A choice card held in one state, for the gallery's still rows (the page is a Server Component
 * and cannot hand it a handler). Each has its own name, so the light and dark copies of a radio
 * never share a group. */
export function ChoiceCardStill(props: Omit<ComponentProps<typeof ChoiceCard>, "name" | "onChange">) {
  const name = useId();
  return <ChoiceCard {...props} name={name} onChange={() => undefined} />;
}

/** A question's cards to try: several picks (checkboxes) or one (radios). */
export function ChoiceGroupDemo({
  label,
  options,
  multiple,
  media,
}: {
  label: string;
  options: readonly ChoiceOptionView[];
  multiple: boolean;
  media: ChoiceCardMedia;
}) {
  const name = useId();
  const [picked, setPicked] = useState<readonly string[]>([]);
  const toggle = (id: string, checked: boolean) =>
    setPicked((current) => {
      if (!multiple) return [id];
      return checked ? [...current, id] : current.filter((value) => value !== id);
    });
  return (
    <div role={multiple ? "group" : "radiogroup"} aria-label={label} className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
      {options.map((option) => (
        <ChoiceCard
          key={option.id}
          option={option}
          control={multiple ? "checkbox" : "radio"}
          name={name}
          checked={picked.includes(option.id)}
          onChange={(checked) => toggle(option.id, checked)}
          media={media}
        />
      ))}
    </div>
  );
}
