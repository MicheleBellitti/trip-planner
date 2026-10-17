"use client";

import { useActionState, useEffect, useRef, useState, type ReactNode } from "react";

import { joinWaitlistAction } from "@/app/actions/waitlist";
import { StatePanel } from "@/components/states/state-panel";
import { Button, LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { ROUTES } from "@/lib/routes";
import { WAITLIST_NOTE_MAX, type JoinOutcome, type WaitlistSource } from "@/lib/waitlist-policy";
import { JOIN_IDLE, type JoinState } from "@/lib/waitlist-state";

export const WAITLIST_EMAIL_LABEL = "Indirizzo email";
export const WAITLIST_NOTE_LABEL = "Il prossimo viaggio";
export const WAITLIST_SUBMIT = "Mettimi in lista";
export const WAITLIST_CONSENT = "Usiamo l'indirizzo solo per scriverti quando c'è posto.";
export const WAITLIST_INVALID_EMAIL = "Scrivi un indirizzo email completo.";
export const WAITLIST_NOTE_TOO_LONG = `Accorcia la nota: al massimo ${WAITLIST_NOTE_MAX} caratteri.`;
export const WAITLIST_FAILED = "Non è stato possibile metterti in lista. Riprova tra poco.";

/** What each outcome says: the title, the sentence (with the address), and whether to offer sign-in. */
export const WAITLIST_OUTCOMES: Record<JoinOutcome, { title: string; before: string; after: string; signIn: boolean }> = {
  joined: { title: "Sei in lista", before: "Ti scriviamo a ", after: " quando c'è posto. Nessun altro messaggio da noi.", signIn: false },
  already_listed: { title: "Sei già in lista", before: "Abbiamo già ", after: ": ti scriviamo lì quando c'è posto.", signIn: false },
  already_invited: { title: "Hai già un invito", before: "", after: " può già entrare: accedi e ti inviamo il link.", signIn: true },
  already_registered: { title: "Hai già un account", before: "Con ", after: " sei già entrato: accedi e ti inviamo il link.", signIn: true },
};

/** The answer to a join, as a panel: focused on arrival, so a keyboard or screen-reader user lands on
 * the news. `actions` come after the sign-in link, when there is one. */
export function WaitlistOutcome({
  outcome,
  email,
  actions,
  className,
}: {
  outcome: JoinOutcome;
  email: string;
  actions?: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  const words = WAITLIST_OUTCOMES[outcome];
  return (
    <div ref={ref} tabIndex={-1} className={cx("rounded-md outline-none", className)}>
      <StatePanel
        icon={words.signIn ? "sign-in" : "check-circle"}
        title={words.title}
        headingId={`waitlist-${outcome}`}
        actions={
          words.signIn || actions ? (
            <>
              {words.signIn ? (
                <LinkButton href={ROUTES.login} variant="primary" icon="sign-in" className="pointer-coarse:min-h-11">
                  Accedi
                </LinkButton>
              ) : null}
              {actions}
            </>
          ) : null
        }
      >
        <div className="min-w-0 lg:col-span-3">
          <dt className="sr-only">Cosa succede ora</dt>
          <dd role="status" className="m-0 max-w-prose text-small text-ink [overflow-wrap:anywhere]">
            {words.before}
            <strong className="font-semibold">{email}</strong>
            {words.after}
          </dd>
        </div>
      </StatePanel>
    </div>
  );
}

interface WaitlistFormProps {
  /** Where the request comes from (the row's `source`). */
  source: Extract<WaitlistSource, "landing" | "login">;
  /** After the button, "Hai già un invito? Accedi" (to the plans, which ask to sign in): it goes
   * with the form, so the outcome panel's own "Accedi" is never doubled. */
  signInHint?: boolean;
  className?: string;
}

/**
 * Join the waitlist: an address, two optional lines about the trip, one button. The server action
 * (app/actions/waitlist.ts) validates and answers; an address problem is a Field error, a failure
 * a Notice, and the four outcomes replace the form with their panel. The fields are controlled,
 * so a refused submit keeps what was typed.
 */
export function WaitlistForm({ source, signInHint = false, className }: WaitlistFormProps) {
  const [state, formAction, pending] = useActionState<JoinState, FormData>(joinWaitlistAction, JOIN_IDLE);
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");

  if (state.status !== "idle" && state.status !== "error") {
    return <WaitlistOutcome outcome={state.status} email={state.email} className={className} />;
  }

  const error = state.status === "error" ? state.error : null;
  const emailError = error === "invalid_email" ? WAITLIST_INVALID_EMAIL : null;
  const noteError = error === "note_too_long" ? WAITLIST_NOTE_TOO_LONG : null;
  const failed = error === "failed" || error === "unavailable";

  return (
    <form action={formAction} noValidate className={cx("grid gap-4", className)}>
      <input type="hidden" name="source" value={source} />
      {failed ? <Notice tone="error" role="alert" title={WAITLIST_FAILED} /> : null}
      <Field label={WAITLIST_EMAIL_LABEL} error={emailError}>
        {(control) => (
          <TextInput
            {...control}
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            spellCheck={false}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={pending}
          />
        )}
      </Field>
      <Field
        label={WAITLIST_NOTE_LABEL}
        optional
        hint="Due righe su dove e quando: invitiamo prima chi ha un viaggio in vista."
        error={noteError}
      >
        {(control) => (
          <TextArea
            {...control}
            name="note"
            rows={2}
            maxLength={WAITLIST_NOTE_MAX}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            disabled={pending}
          />
        )}
      </Field>
      <p className="text-meta text-ink-2">{WAITLIST_CONSENT}</p>
      <Button
        type="submit"
        variant="primary"
        icon="arrow-right"
        busy={pending}
        className="min-h-11 w-full sm:min-h-10 sm:w-auto sm:justify-self-start"
      >
        {pending ? "Invio…" : WAITLIST_SUBMIT}
      </Button>
      {signInHint ? (
        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-small text-ink-2">
          Hai già un invito?
          <LinkButton href={ROUTES.plans} variant="secondary" icon="sign-in" className="pointer-coarse:min-h-11">
            Accedi
          </LinkButton>
        </p>
      ) : null}
    </form>
  );
}
