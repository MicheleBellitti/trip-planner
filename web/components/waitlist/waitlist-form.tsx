"use client";

import { useActionState, useEffect, useRef, useState, type ReactNode } from "react";

import { joinWaitlistAction } from "@/app/actions/waitlist";
import { StatePanel } from "@/components/states/state-panel";
import { Button, LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { Turnstile, type TurnstileHandle } from "@/components/ui/turnstile";
import { ROUTES } from "@/lib/routes";
import { CHALLENGE_FAILED_MESSAGE, TURNSTILE_FIELD } from "@/lib/turnstile";
import { WAITLIST_NOTE_MAX, type WaitlistSource } from "@/lib/waitlist-policy";
import { JOIN_IDLE, type JoinState } from "@/lib/waitlist-state";

export const WAITLIST_EMAIL_LABEL = "Indirizzo email";
export const WAITLIST_NOTE_LABEL = "Il prossimo viaggio";
export const WAITLIST_SUBMIT = "Mettimi in lista";
export const WAITLIST_CHANGE_ADDRESS = "Cambia indirizzo";
export const WAITLIST_CONSENT = "Usiamo l'indirizzo solo per scriverti quando c'è posto.";
export const WAITLIST_INVALID_EMAIL = "Scrivi un indirizzo email completo.";
export const WAITLIST_NOTE_TOO_LONG = `Accorcia la nota: al massimo ${WAITLIST_NOTE_MAX} caratteri.`;
export const WAITLIST_FAILED = "Non è stato possibile metterti in lista. Riprova tra poco.";
export const WAITLIST_CHALLENGE_FAILED = CHALLENGE_FAILED_MESSAGE;
export const WAITLIST_TOO_MANY = "Troppe richieste da questa connessione in poco tempo: riprova tra qualche minuto.";

export const WAITLIST_RECEIVED_TITLE = "Ricevuto";

/** The one answer to a join, around the address, true for every address (lib/waitlist-state.ts
 * `JoinState`): it never says whether the address has an account or an invitation. */
export const WAITLIST_RECEIVED = {
  before: "Se ",
  after: " è già abilitato puoi accedere subito; altrimenti ti scriviamo lì quando c'è posto.",
} as const;

/** The answer to a join, as a panel: focused on arrival, so a keyboard or screen-reader user lands on
 * the news. `signIn` offers "Accedi" (not on the login page itself); `hint` is a second, quieter
 * sentence (what to do next); `actions` come after the sign-in link, when there is one. */
export function WaitlistOutcome({
  email,
  signIn = false,
  hint,
  actions,
  className,
}: {
  email: string;
  signIn?: boolean;
  hint?: string;
  actions?: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <div
      ref={ref}
      tabIndex={-1}
      className={cx("rounded-md outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus", className)}
    >
      <StatePanel
        icon="check-circle"
        title={WAITLIST_RECEIVED_TITLE}
        headingId="waitlist-received"
        actions={
          signIn || actions ? (
            <>
              {signIn ? (
                <LinkButton href={ROUTES.login} variant="secondary" icon="sign-in" className="pointer-coarse:min-h-11">
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
            {WAITLIST_RECEIVED.before}
            <strong className="font-semibold">{email}</strong>
            {WAITLIST_RECEIVED.after}
          </dd>
          {hint ? (
            <>
              <dt className="sr-only">Cosa puoi fare</dt>
              <dd className="m-0 mt-1.5 max-w-prose text-small text-ink-2">{hint}</dd>
            </>
          ) : null}
        </div>
      </StatePanel>
    </div>
  );
}

interface WaitlistFormProps {
  /** Where the request comes from (the row's `source`). */
  source: Extract<WaitlistSource, "landing" | "login">;
  /** After the button, "Hai già un invito? Accedi" (to the login, which forwards a live session to
   * the plans); the answer's panel then offers "Accedi" in its place. */
  signInHint?: boolean;
  className?: string;
}

/**
 * Join the waitlist: an address, two optional lines about the trip, one button. The server action
 * (app/actions/waitlist.ts) validates and answers; an address problem is a Field error on the field,
 * which takes focus and clears as soon as the field is edited; a failure is a Notice; the answer,
 * the same for every address, replaces the form with its panel, and "Cambia indirizzo" brings the form back with the
 * address kept and selected and the note as it was (a new key, since an action's state cannot be
 * reset in place). The fields are controlled, so a refused submit keeps what was typed.
 */
export function WaitlistForm({ source, signInHint = false, className }: WaitlistFormProps) {
  const [attempt, setAttempt] = useState(0);
  const [carried, setCarried] = useState({ email: "", note: "" });
  return (
    <JoinForm
      key={attempt}
      source={source}
      signInHint={signInHint}
      className={className}
      initialEmail={carried.email}
      initialNote={carried.note}
      selectEmail={attempt > 0}
      onChangeAddress={(email, note) => {
        setCarried({ email, note });
        setAttempt((count) => count + 1);
      }}
    />
  );
}

/** The join, with a rejected action (a dropped connection, a redeploy's "Failed to find Server
 * Action") answered as the failure it is instead of reaching the error page. */
async function joinOrFail(previous: JoinState, data: FormData): Promise<JoinState> {
  try {
    return await joinWaitlistAction(previous, data);
  } catch {
    return { status: "error", error: "failed" };
  }
}

function JoinForm({
  source,
  signInHint,
  className,
  initialEmail,
  initialNote,
  selectEmail,
  onChangeAddress,
}: WaitlistFormProps & {
  initialEmail: string;
  initialNote: string;
  selectEmail: boolean;
  onChangeAddress: (email: string, note: string) => void;
}) {
  const [state, formAction, pending] = useActionState<JoinState, FormData>(joinOrFail, JOIN_IDLE);
  const [email, setEmail] = useState(initialEmail);
  const [note, setNote] = useState(initialNote);
  // Which fields were edited since the last submit: a field's error shows only until then (the
  // action's state cannot be cleared in place, so the flags are reset when the form is sent).
  const [edited, setEdited] = useState({ email: false, note: false });
  const emailRef = useRef<HTMLInputElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  // The Turnstile token travels in a hidden field; a token is spent by one submit, so it leaves
  // the field as the form is sent (it is already in the FormData) and the widget is reset after
  // every answer: the next submit carries the fresh one, never the spent one.
  const [challenge, setChallenge] = useState<string | null>(null);
  const turnstile = useRef<TurnstileHandle>(null);

  function send(data: FormData) {
    setEdited({ email: false, note: false });
    setChallenge(null);
    formAction(data);
  }

  useEffect(() => {
    if (state.status !== "idle") turnstile.current?.reset();
  }, [state]);

  // The way back from an outcome: the field, with the kept address selected so typing replaces it.
  useEffect(() => {
    if (!selectEmail) return;
    emailRef.current?.focus();
    emailRef.current?.select();
  }, [selectEmail]);

  // A refused submit lands focus on the field that was refused: the error is read with it.
  useEffect(() => {
    if (state.status !== "error") return;
    if (state.error === "invalid_email") emailRef.current?.focus();
    else if (state.error === "note_too_long") noteRef.current?.focus();
  }, [state]);

  if (state.status === "received") {
    return (
      <WaitlistOutcome
        email={state.email}
        signIn={signInHint}
        className={className}
        actions={
          <Button
            variant="quiet"
            size="sm"
            icon="arrow-left"
            onClick={() => onChangeAddress(state.email, note)}
            className={cx("min-h-11 sm:min-h-8", !signInHint && "-ml-3")}
          >
            {WAITLIST_CHANGE_ADDRESS}
          </Button>
        }
      />
    );
  }

  const error = state.status === "error" ? state.error : null;
  const emailError = error === "invalid_email" && !edited.email ? WAITLIST_INVALID_EMAIL : null;
  const noteError = error === "note_too_long" && !edited.note ? WAITLIST_NOTE_TOO_LONG : null;
  const refusal =
    error === "failed" || error === "unavailable"
      ? WAITLIST_FAILED
      : error === "challenge_failed"
        ? WAITLIST_CHALLENGE_FAILED
        : error === "too_many_requests"
          ? WAITLIST_TOO_MANY
          : null;

  return (
    <form action={send} noValidate className={cx("grid gap-4", className)}>
      <input type="hidden" name="source" value={source} />
      <input type="hidden" name={TURNSTILE_FIELD} value={challenge ?? ""} />
      {refusal ? <Notice tone="error" role="alert" title={refusal} /> : null}
      <Field label={WAITLIST_EMAIL_LABEL} error={emailError}>
        {(control) => (
          <TextInput
            {...control}
            ref={emailRef}
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            spellCheck={false}
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
              setEdited((flags) => (flags.email ? flags : { ...flags, email: true }));
            }}
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
            ref={noteRef}
            name="note"
            rows={2}
            maxLength={WAITLIST_NOTE_MAX}
            value={note}
            onChange={(event) => {
              setNote(event.target.value);
              setEdited((flags) => (flags.note ? flags : { ...flags, note: true }));
            }}
            disabled={pending}
          />
        )}
      </Field>
      <p className="text-meta text-ink-2">{WAITLIST_CONSENT}</p>
      <Turnstile ref={turnstile} onToken={setChallenge} action="waitlist" />
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
          <LinkButton href={ROUTES.login} variant="secondary" icon="sign-in" className="pointer-coarse:min-h-11">
            Accedi
          </LinkButton>
        </p>
      ) : null}
    </form>
  );
}
