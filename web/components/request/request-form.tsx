"use client";

/**
 * The trip request form (/new, spec "Il form"): where from, where to or "Suggeriscimi tu" with
 * an idea, fixed dates or a month and nights, adults and children with their ages, the total
 * budget in euro, free preferences, then "Pianifica il viaggio" with the run's cost estimate.
 *
 * Field limits, validation and the POST /plans body come from lib/request-form.ts (derived from
 * the PlanRequest JSON Schema); the backend stays the authority and its 422 issues land on the
 * same fields. Errors are announced by moving focus to the first field that has one (its label,
 * error and hint are wired by Field); failures that are not a field's (429, 503, network) are
 * one alert above the button.
 */

import { useRouter } from "next/navigation";
import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { flushSync } from "react-dom";

import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Field, NumberStepper, SegmentedControl, Select, TextArea, TextInput } from "@/components/ui/field";
import { Icon } from "@/components/ui/icon";
import { useIsDesktop } from "@/components/live/hooks";
import { Notice } from "@/components/ui/notice";
import { api, RequestValidationError, UnauthorizedError } from "@/lib/api";
import {
  childAgePath,
  fieldConstraints,
  fieldErrorsFromServer,
  MAX_NIGHTS,
  validateRequestForm,
  type FieldErrors,
  type RequestFormValues,
} from "@/lib/request-form";
import { applyRemembered, readRemembered, rememberRequest } from "@/lib/remembered-request";

import { advanceOnEnter } from "./advance-on-enter";
import { describeSubmitFailure, type SubmitFailure } from "./failure";
import {
  ADULTS_ID,
  CHILDREN_ID,
  childAgeOptions,
  DEMO_SCENARIO_PATH,
  errorTargets,
  fieldId,
  groupErrorId,
  MAX_TRAVELERS,
  monthOptions,
  nextDay,
  placeErrors,
  withFieldWording,
} from "./form-model";
import { RequestSummary } from "./request-summary";
import { planPath } from "@/lib/page-paths";

/** The run's cost estimate under the button (spec: "circa 2–4 $"). */
export const COST_ESTIMATE = "Il planner costa circa 2–4 $ per piano";
/** Nights offered when the month mode is chosen and none were typed. */
const DEFAULT_NIGHTS = "7";

const SUBMIT_ID = "submit-plan";
const ESTIMATE_ID = "submit-plan-estimate";
const SUMMARY_ID = "request-errors";
const AGE_OPTIONS = childAgeOptions();

/** The error summary appears from three problems up, or when one has no field to sit by: with one
 * or two, the messages beside the fields are the whole story. */
export const SUMMARY_FROM = 3;
export function showsSummary(placed: number, unplaced: number): boolean {
  return placed + unplaced >= SUMMARY_FROM || unplaced > 0;
}

const maxLength = (path: string) => fieldConstraints(path).maxLength ?? undefined;

function joinIds(...ids: (string | false | null | undefined)[]): string | undefined {
  return ids.filter(Boolean).join(" ") || undefined;
}

/** Errors whose path matches `drop` removed; the same object when nothing changes. */
function withoutErrors(errors: FieldErrors, drop: (path: string) => boolean): FieldErrors {
  const keys = Object.keys(errors).filter(drop);
  if (keys.length === 0) return errors;
  const next = { ...errors };
  for (const key of keys) delete next[key];
  return next;
}

export interface RequestFormProps {
  /** Today in Europe/Rome (YYYY-MM-DD), from the server: the first departure is tomorrow. */
  today: string;
  /** Empty, or the home page's example (/new?esempio=1). */
  initialValues: RequestFormValues;
  /** Start from the last request's origin, adults and children's ages (kept in this browser).
   * Off for the home page's example, which is a request of its own. */
  restoreLast?: boolean;
  /** Development only (NEXT_PUBLIC_DEMO_SCENARIOS): the scenarios a DEMO_MODE backend replays. */
  demoScenarios?: readonly string[];
}

export function RequestForm({ today, initialValues, restoreLast = false, demoScenarios = [] }: RequestFormProps) {
  const router = useRouter();
  const [values, setValues] = useState<RequestFormValues>(initialValues);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [failure, setFailure] = useState<SubmitFailure | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [demoScenario, setDemoScenario] = useState("");
  const desktop = useIsDesktop();
  const destinationMode = useId();
  const dateMode = useId();

  // After hydration (the server cannot know): the form is still untouched on the first effect.
  useEffect(() => {
    if (restoreLast) setValues((current) => applyRemembered(current, readRemembered()));
  }, [restoreLast]);

  const demo = demoScenarios.length > 0;
  const targets = errorTargets(values, { demo });
  const { placed, unplaced } = placeErrors(errors, targets);
  const tomorrow = nextDay(today);
  const children = values.childAges.length;

  function change(patch: Partial<RequestFormValues>, clears: (path: string) => boolean) {
    setValues((current) => ({ ...current, ...patch }));
    setErrors((current) => withoutErrors(current, clears));
  }

  const is = (path: string) => (candidate: string) => candidate === path;
  const startsWith = (prefix: string) => (candidate: string) =>
    candidate === prefix || candidate.startsWith(`${prefix}.`);

  /** Shows `next` and moves focus to the first field that has an error, after it rendered (so
   * the field's description already carries its message). */
  function showErrors(found: FieldErrors) {
    const next = withFieldWording(found);
    flushSync(() => setErrors(next));
    const { placed: shown, unplaced: loose } = placeErrors(next, errorTargets(values, { demo }));
    // With a summary on screen (three or more problems) it takes the focus: its count and links
    // are what to read first. Fewer: the first field with a problem.
    const target = showsSummary(shown.length, loose.length)
      ? document.getElementById(SUMMARY_ID)
      : shown[0]
        ? document.getElementById(shown[0].controlId)
        : document.getElementById(SUMMARY_ID);
    target?.focus();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setFailure(null);
    const result = validateRequestForm(values, { today });
    if (!result.ok) {
      showErrors(result.errors);
      return;
    }
    setErrors({});
    setSubmitting(true);
    try {
      const { id } = await api.createPlan(result.request, {
        demoScenario: demo ? demoScenario : null,
      });
      rememberRequest(values);
      router.push(planPath(id));
    } catch (error) {
      // 401: the browser is on its way to the login; stay busy until it leaves.
      if (error instanceof UnauthorizedError) return;
      if (error instanceof RequestValidationError) {
        const fromServer = fieldErrorsFromServer(error.issues);
        if (Object.keys(fromServer).length > 0) {
          flushSync(() => setSubmitting(false));
          showErrors(fromServer);
          return;
        }
      }
      flushSync(() => {
        setSubmitting(false);
        setFailure(describeSubmitFailure(error));
      });
      document.getElementById(SUBMIT_ID)?.focus();
    }
  }

  const errorCount = placed.length + unplaced.length;
  // Three or more problems: a count and a link to each field. On the phone it sits at the top,
  // where the focus goes (the button is a screen below the first field); from 1080 px, beside
  // the button.
  const summary = showsSummary(placed.length, unplaced.length) ? (
    <Notice
      id={SUMMARY_ID}
      tabIndex={-1}
      tone="error"
      title={errorCount === 1 ? "Un campo da sistemare" : `${errorCount} campi da sistemare`}
    >
      <ul className="grid">
        {placed.map((error) => (
          <li key={error.path}>
            <a
              href={`#${error.controlId}`}
              className="inline-block py-1.5 font-semibold underline"
              onClick={(event) => {
                event.preventDefault();
                document.getElementById(error.controlId)?.focus();
              }}
            >
              {error.label}
            </a>
          </li>
        ))}
        {unplaced.map((error) => (
          <li key={error.path}>{error.message}</li>
        ))}
      </ul>
    </Notice>
  ) : null;

  const tripSection = (
    <Section title="Il viaggio" className={desktop || !summary ? "max-lg:border-t-0 max-lg:pt-0" : undefined}>
      <Field id={fieldId("origin")} label="Da dove parti" hint="Una città o un aeroporto" error={errors.origin}>
        {(control) => (
          <TextInput
            {...control}
            value={values.origin}
            maxLength={maxLength("origin")}
            placeholder="Milano, oppure MXP"
            autoComplete="off"
            enterKeyHint="next"
            onChange={(event) => change({ origin: event.target.value }, is("origin"))}
          />
        )}
      </Field>
      <SegmentedControl
        legend="Destinazione"
        name={destinationMode}
        options={[
          { value: "pick", label: "La scelgo io" },
          { value: "suggest", label: "Suggeriscimi tu" },
        ]}
        value={values.suggestDestination ? "suggest" : "pick"}
        onValueChange={(mode) =>
          change(
            { suggestDestination: mode === "suggest" },
            (path) => path === "destination" || path === "destination_idea" || path === "suggest_destination",
          )
        }
      />
      {values.suggestDestination ? (
        <Field
          id={fieldId("destination_idea")}
          label="Che viaggio vorresti"
          hint="Il planner propone fino a tre mete, con i motivi."
          optional
          error={errors.destination_idea}
        >
          {(control) => (
            <TextArea
              {...control}
              rows={2}
              value={values.destinationIdea}
              maxLength={maxLength("destination_idea")}
              placeholder="Mare a novembre, volo diretto"
              onChange={(event) => change({ destinationIdea: event.target.value }, is("destination_idea"))}
            />
          )}
        </Field>
      ) : (
        <Field
          id={fieldId("destination")}
          label="Dove vuoi andare"
          hint="Una città, una regione o un paese"
          error={errors.destination}
        >
          {(control) => (
            <TextInput
              {...control}
              value={values.destination}
              maxLength={maxLength("destination")}
              placeholder="Per esempio Lisbona"
              autoComplete="off"
              enterKeyHint="next"
              onChange={(event) => change({ destination: event.target.value }, is("destination"))}
            />
          )}
        </Field>
      )}
    </Section>
  );

  const whenSection = (
    <Section title="Quando">
      <SegmentedControl
        legend="Date"
        name={dateMode}
        options={[
          { value: "exact", label: "Date fisse" },
          { value: "flexible", label: "Mese e notti" },
        ]}
        value={values.dateMode}
        onValueChange={(mode) =>
          change(
            mode === "flexible" && values.nights.trim() === ""
              ? { dateMode: mode, nights: DEFAULT_NIGHTS }
              : { dateMode: mode },
            startsWith("dates"),
          )
        }
      />
      {values.dateMode === "exact" ? (
        <div className="grid grid-cols-2 items-start gap-3">
          <Field id={fieldId("dates.exact_start")} label="Partenza" error={errors["dates.exact_start"]}>
            {(control) => (
              <TextInput
                {...control}
                type="date"
                aria-describedby={joinIds(control["aria-describedby"], errors.dates && groupErrorId("dates"))}
                value={values.exactStart}
                min={tomorrow}
                onChange={(event) => change({ exactStart: event.target.value }, startsWith("dates"))}
              />
            )}
          </Field>
          <Field id={fieldId("dates.exact_end")} label="Ritorno" error={errors["dates.exact_end"]}>
            {(control) => (
              <TextInput
                {...control}
                type="date"
                value={values.exactEnd}
                min={values.exactStart || tomorrow}
                onChange={(event) => change({ exactEnd: event.target.value }, startsWith("dates"))}
              />
            )}
          </Field>
        </div>
      ) : (
        <div className="grid gap-2">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
            <Field id={fieldId("dates.month")} label="Mese di partenza" error={errors["dates.month"]}>
              {(control) => (
                <Select
                  {...control}
                  aria-describedby={joinIds(control["aria-describedby"], errors.dates && groupErrorId("dates"))}
                  value={values.month}
                  onChange={(event) => change({ month: event.target.value }, startsWith("dates"))}
                >
                  <option value="">Scegli il mese</option>
                  {monthOptions(today, 18, values.month).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field id={fieldId("dates.nights")} label="Notti" error={errors["dates.nights"]}>
              {(control) => (
                <NumberStepper
                  {...control}
                  value={Number(values.nights) || 1}
                  min={1}
                  max={MAX_NIGHTS}
                  decrementLabel="Una notte in meno"
                  incrementLabel="Una notte in più"
                  onValueChange={(nights) => change({ nights: String(nights) }, startsWith("dates"))}
                />
              )}
            </Field>
          </div>
          <p className="text-meta text-ink-2">Il planner sceglie i giorni migliori del mese.</p>
        </div>
      )}
      {errors.dates ? <GroupError id={groupErrorId("dates")}>{errors.dates}</GroupError> : null}
    </Section>
  );

  const travelersSection = (
    <Section title="Chi viaggia" titleId="travelers-title" description="Fino a 9 persone, almeno un adulto.">
      <div
        role="group"
        aria-labelledby="travelers-title"
        aria-describedby={errors.travelers ? groupErrorId("travelers") : undefined}
        className="grid gap-4"
      >
        <div className="flex flex-wrap gap-x-8 gap-y-4">
          <Field id={ADULTS_ID} label="Adulti" hint="Da 18 anni">
            {(control) => (
              <NumberStepper
                {...control}
                aria-describedby={joinIds(control["aria-describedby"], errors.travelers && groupErrorId("travelers"))}
                aria-invalid={errors.travelers ? true : undefined}
                value={values.adults}
                min={1}
                max={MAX_TRAVELERS - children}
                decrementLabel="Togli un adulto"
                incrementLabel="Aggiungi un adulto"
                onValueChange={(adults) => change({ adults }, startsWith("travelers"))}
              />
            )}
          </Field>
          <Field id={CHILDREN_ID} label="Bambini" hint="Sotto i 18 anni">
            {(control) => (
              <NumberStepper
                {...control}
                value={children}
                min={0}
                max={MAX_TRAVELERS - values.adults}
                decrementLabel="Togli un bambino"
                incrementLabel="Aggiungi un bambino"
                onValueChange={(count) =>
                  change(
                    {
                      childAges: Array.from({ length: count }, (_, index) => values.childAges[index] ?? ""),
                    },
                    startsWith("travelers"),
                  )
                }
              />
            )}
          </Field>
        </div>
        {children > 0 ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {values.childAges.map((age, index) => {
              const path = childAgePath(index, values.adults);
              return (
                <Field key={index} id={fieldId(path)} label={`Età del bambino ${index + 1}`} error={errors[path]}>
                  {(control) => (
                    <Select
                      {...control}
                      value={age}
                      onChange={(event) =>
                        change(
                          {
                            childAges: values.childAges.map((current, position) =>
                              position === index ? event.target.value : current,
                            ),
                          },
                          (candidate) => candidate === path || candidate === "travelers",
                        )
                      }
                    >
                      <option value="">Scegli</option>
                      {AGE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              );
            })}
          </div>
        ) : null}
        {errors.travelers ? <GroupError id={groupErrorId("travelers")}>{errors.travelers}</GroupError> : null}
      </div>
    </Section>
  );

  const budgetSection = (
    <Section title="Budget e preferenze">
      <Field
        id={fieldId("budget_eur")}
        label="Budget totale"
        hint="Per tutto il gruppo: voli, alloggio, attività e spostamenti."
        error={errors.budget_eur}
      >
        {(control) => (
          <span className="relative block max-w-[15rem]">
            {/* Text, not number: parseBudget reads "2.400" and whole euros, and validation
                names anything else ("2400,50") instead of the browser dropping it. */}
            <TextInput
              {...control}
              inputMode="numeric"
              autoComplete="off"
              placeholder="Per esempio 2.400"
              enterKeyHint="go"
              className="pr-9"
              value={values.budgetEur}
              onChange={(event) => change({ budgetEur: event.target.value }, is("budget_eur"))}
            />
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-input text-ink-2"
            >
              €
            </span>
          </span>
        )}
      </Field>
      <Field
        id={fieldId("preferences")}
        label="Preferenze"
        hint="Quello che conta per te, in poche parole."
        optional
        error={errors.preferences}
      >
        {(control) => (
          <TextArea
            {...control}
            value={values.preferences}
            maxLength={maxLength("preferences")}
            placeholder="Niente voli prima delle 8, quartiere tranquillo, cucina locale"
            className="lg:min-h-20"
            onChange={(event) => change({ preferences: event.target.value }, is("preferences"))}
          />
        )}
      </Field>
    </Section>
  );

  const demoBlock = demo ? (
    <div className="rounded-sm border border-dashed border-rule-strong px-3 py-3 lg:col-span-2">
      <Field
        id={fieldId(DEMO_SCENARIO_PATH)}
        label="Scenario demo"
        hint="Solo in sviluppo: il backend in modalità demo riproduce questa sessione registrata, qualunque sia la richiesta."
        optional
        error={errors[DEMO_SCENARIO_PATH]}
      >
        {(control) => (
          <Select
            {...control}
            value={demoScenario}
            onChange={(event) => {
              setDemoScenario(event.target.value);
              setErrors((current) => withoutErrors(current, is(DEMO_SCENARIO_PATH)));
            }}
          >
            <option value="">Nessuno</option>
            {demoScenarios.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </Select>
        )}
      </Field>
    </div>
  ) : null;

  return (
    <form
      onSubmit={submit}
      onKeyDown={advanceOnEnter}
      noValidate
      aria-label="Richiesta di viaggio"
      className="grid max-w-[40rem] gap-8 lg:max-w-none lg:grid-cols-[minmax(0,50rem)_minmax(0,20rem)] lg:items-start lg:gap-x-14"
    >
      {/* One markup for every width, so the server's HTML is already the right layout: the four
          sections in the phone's order, stacked. From 1080 px the two wrappers stop being
          transparent (display: contents below) and become two columns that each read top to
          bottom: the trip and its dates on the left, the party and the money on the right. They
          balance (about 600 px each, with children too), so the whole request fits a 900 px
          screen. */}
      <div className="grid gap-8 lg:grid-cols-2 lg:gap-x-12 lg:gap-y-6">
        {desktop ? null : summary}
        <div className="contents lg:grid lg:content-start lg:gap-6">
          {tripSection}
          {whenSection}
        </div>
        <div className="contents lg:grid lg:content-start lg:gap-6">
          {travelersSection}
          {budgetSection}
        </div>
        {demoBlock}
      </div>

      <div className="grid gap-4 border-t border-rule pt-6 lg:sticky lg:top-6 lg:rounded-md lg:border lg:bg-surface lg:p-5">
        <RequestSummary values={values} className="hidden lg:grid" />

        {desktop ? summary : null}

        {failure ? (
          <Notice tone="error" role="alert" title={failure.title}>
            {failure.body}
          </Notice>
        ) : null}

        <div className="grid justify-items-stretch gap-2 sm:justify-items-start lg:justify-items-stretch">
          <Button
            id={SUBMIT_ID}
            type="submit"
            variant="primary"
            busy={submitting}
            aria-describedby={ESTIMATE_ID}
            // 44 px on the phone, like the fields above it; 40 px from 640 px (DESIGN.md, Buttons).
            className="min-h-11 w-full sm:min-h-10 sm:w-auto lg:w-full"
          >
            {submitting ? "Avvio il piano…" : "Pianifica il viaggio"}
          </Button>
          <p
            id={ESTIMATE_ID}
            className="flex items-center gap-1.5 text-meta text-ink-2 sm:justify-self-start lg:justify-self-center"
          >
            <Icon name="wallet" size={15} />
            {COST_ESTIMATE}
          </p>
        </div>
      </div>
    </form>
  );
}

function Section({
  title,
  titleId,
  description,
  className,
  children,
}: {
  title: string;
  titleId?: string;
  description?: string;
  /** Placement from 1080 px (the form's sections share two columns). */
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={cx(
        "grid content-start gap-5 border-t border-rule pt-6 lg:pt-5",
        className,
      )}
    >
      <div className="lg:col-span-full">
        <h2 id={titleId} className="font-cond text-heading font-semibold">
          {title}
        </h2>
        {description ? <p className="mt-1 text-meta text-ink-2">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** A group's error (the dates, the travellers), drawn like Field's own error line. */
function GroupError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="flex items-start gap-1.5 text-meta text-error">
      <Icon name="x-circle" size={15} className="mt-0.5" />
      <span>{children}</span>
    </p>
  );
}
