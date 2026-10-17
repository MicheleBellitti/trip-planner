"use client";

import { useEffect, useRef, useState, useTransition } from "react";

import { inviteAction, removeRequestAction } from "@/app/actions/waitlist";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import type { WaitlistRow } from "@/lib/server/waitlist";
import { WAITLIST_NOTE_MAX, type WaitlistSource } from "@/lib/waitlist-policy";
import { INVITE_IDLE, REMOVE_IDLE, type InviteError, type InviteState, type RemoveState } from "@/lib/waitlist-state";

export const SOURCE_LABELS: Record<WaitlistSource, string> = {
  landing: "dal sito",
  login: "dalla pagina di accesso",
  admin: "aggiunto a mano",
};

export const INVITE_ERRORS: Record<InviteError, string> = {
  invalid_email: "Scrivi un indirizzo email completo.",
  note_too_long: `Accorcia la nota: al massimo ${WAITLIST_NOTE_MAX} caratteri.`,
  signed_out: "La sessione è scaduta: accedi di nuovo e riprova.",
  forbidden: "Questa sezione è riservata a chi gestisce il planner.",
  unavailable: "Gli account non sono configurati su questo server.",
  failed: "Non è stato possibile invitare. Riprova tra poco.",
};

/** Dates are shown in the planner's home time zone, the same on the server and in the browser. */
const DATE = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "short", year: "numeric", timeZone: "Europe/Rome" });

export function formatDay(iso: string): string {
  return DATE.format(new Date(iso));
}

export interface Outcome {
  tone: "info" | "warning" | "error";
  text: string;
}

/** What an invitation did, in one sentence for the status line. */
export function inviteOutcome(state: InviteState): Outcome | null {
  if (state.status === "idle") return null;
  if (state.status === "error") return { tone: "error", text: INVITE_ERRORS[state.error] };
  if (state.alreadyInvited) return { tone: "info", text: `${state.email} aveva già un invito: nessuna nuova email.` };
  if (state.emailSent) return { tone: "info", text: `Invito inviato a ${state.email}.` };
  return { tone: "warning", text: `${state.email} è stato invitato, ma l'email non è partita: riprova con «Invia l'email».` };
}

/** What removing a request did. */
export function removeOutcome(state: RemoveState): Outcome | null {
  if (state.status === "idle") return null;
  if (state.status === "error") return { tone: "error", text: INVITE_ERRORS[state.error] };
  return { tone: "info", text: `${state.email} è stato tolto dalla lista.` };
}

/**
 * The invitations page's body: invite an address, the pending requests with "Invita" and "Togli",
 * the invitations with their state. Every action is a server action checked on the server
 * (app/actions/waitlist.ts); the page re-reads the rows after each one. One status region, there
 * from the first render, says what the last row action did and takes focus after it, so the
 * answer survives the row's move between the lists and reaches a screen reader; the add form has
 * its own line. Focus moves in effects, once the answer is rendered: the status region is
 * `display: none` while empty and the fields are disabled while the action runs, and neither can
 * take focus before the commit. The view's one primary is the add form's button: the rows' are
 * secondary.
 */
export function WaitlistAdmin({ rows }: { rows: WaitlistRow[] }) {
  const pending = rows.filter((row) => row.invitedAt === null);
  const invited = rows.filter((row) => row.invitedAt !== null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState<{ email: string; kind: "invite" | "remove" } | null>(null);
  const [inFlight, startTransition] = useTransition();
  const statusRef = useRef<HTMLDivElement>(null);

  function run(kind: "invite" | "remove", email: string) {
    setBusy({ email, kind });
    startTransition(async () => {
      const data = new FormData();
      data.set("email", email);
      setOutcome(kind === "invite" ? inviteOutcome(await inviteAction(INVITE_IDLE, data)) : removeOutcome(await removeRequestAction(REMOVE_IDLE, data)));
    });
  }

  // Every answer is a new object, so a repeated outcome moves focus again.
  useEffect(() => {
    if (outcome) statusRef.current?.focus();
  }, [outcome]);

  return (
    <div className="grid max-w-[40rem] gap-9">
      <AddInvite />
      <div ref={statusRef} tabIndex={-1} role="status" aria-live="polite" className="-my-4 rounded-md outline-none empty:hidden">
        {outcome ? <Notice tone={outcome.tone}>{outcome.text}</Notice> : null}
      </div>
      <section aria-labelledby="pending-title" className="grid gap-3">
        <h2 id="pending-title" className="font-cond text-heading font-semibold">
          In attesa <span className="font-normal text-ink-2">({pending.length})</span>
        </h2>
        {pending.length === 0 ? (
          <p className="text-small text-ink-2">Nessuna richiesta in attesa.</p>
        ) : (
          <ul className="divide-y divide-rule border-y border-rule">
            {pending.map((row) => (
              <Row key={row.email} row={row} busy={busy} inFlight={inFlight} onRun={run} />
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="invited-title" className="grid gap-3">
        <h2 id="invited-title" className="font-cond text-heading font-semibold">
          Invitati <span className="font-normal text-ink-2">({invited.length})</span>
        </h2>
        {invited.length === 0 ? (
          <p className="text-small text-ink-2">Nessun invito ancora: invita un indirizzo qui sopra, o una richiesta.</p>
        ) : (
          <ul className="divide-y divide-rule border-y border-rule">
            {invited.map((row) => (
              <Row key={row.email} row={row} busy={busy} inFlight={inFlight} onRun={run} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** "Invita un indirizzo": a row with source "admin", invited at once, the email sent. The fields are
 * cleared only once the invitation went through; a refused address stays in its field, focused. */
function AddInvite() {
  const [state, setState] = useState<InviteState>(INVITE_IDLE);
  const [pending, startTransition] = useTransition();
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const emailRef = useRef<HTMLInputElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const statusRef = useRef<HTMLDivElement>(null);
  const emailError = state.status === "error" && state.error === "invalid_email" ? INVITE_ERRORS.invalid_email : null;
  const noteError = state.status === "error" && state.error === "note_too_long" ? INVITE_ERRORS.note_too_long : null;
  const line = emailError || noteError ? null : inviteOutcome(state);

  function submit(data: FormData) {
    startTransition(async () => {
      const result = await inviteAction(INVITE_IDLE, data);
      setState(result);
      if (result.status === "invited") {
        setEmail("");
        setNote("");
      }
    });
  }

  // The answer lands focus where it belongs once the fields are enabled again: a refused field, or
  // the status line (the success, or a failure that is not about one field).
  useEffect(() => {
    if (pending || state.status === "idle") return;
    if (state.status === "error" && state.error === "invalid_email") emailRef.current?.focus();
    else if (state.status === "error" && state.error === "note_too_long") noteRef.current?.focus();
    else statusRef.current?.focus();
  }, [state, pending]);

  return (
    <section aria-labelledby="add-title" className="grid gap-4">
      <h2 id="add-title" className="font-cond text-heading font-semibold">
        Invita un indirizzo
      </h2>
      <div ref={statusRef} tabIndex={-1} role="status" aria-live="polite" className="rounded-md outline-none empty:hidden">
        {line ? <Notice tone={line.tone}>{line.text}</Notice> : null}
      </div>
      <form action={submit} noValidate className="grid max-w-[26rem] gap-4">
        <Field label="Indirizzo email" error={emailError}>
          {(control) => (
            <TextInput
              {...control}
              ref={emailRef}
              type="email"
              name="email"
              autoComplete="off"
              inputMode="email"
              spellCheck={false}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={pending}
            />
          )}
        </Field>
        <Field label="Nota" optional hint="Chi è, o perché: la vedi solo tu." error={noteError}>
          {(control) => (
            <TextArea
              {...control}
              ref={noteRef}
              name="note"
              rows={2}
              maxLength={WAITLIST_NOTE_MAX}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              disabled={pending}
            />
          )}
        </Field>
        <Button type="submit" variant="primary" busy={pending} className="min-h-11 w-full sm:min-h-10 sm:w-auto sm:justify-self-start">
          {pending ? "Invio…" : "Invita"}
        </Button>
      </form>
    </section>
  );
}

/** One address: who, what they wrote, where from and when; the actions on the right, each named
 * with the address for a screen reader (fourteen buttons that all read "Invita" tell nothing). */
function Row({
  row,
  busy,
  inFlight,
  onRun,
}: {
  row: WaitlistRow;
  busy: { email: string; kind: "invite" | "remove" } | null;
  inFlight: boolean;
  onRun: (kind: "invite" | "remove", email: string) => void;
}) {
  const invitedAt = row.invitedAt;
  const facts: string[] = [];
  if (invitedAt) {
    facts.push(`invitato il ${formatDay(invitedAt)}${row.invitedBy ? ` da ${row.invitedBy}` : ""}`);
    facts.push(row.invitationSentAt ? "email inviata" : "email non inviata");
    if (row.registered) facts.push("ha un account");
  } else {
    facts.push(`${SOURCE_LABELS[row.source]}, ${formatDay(row.createdAt)}`);
  }
  const needsEmail = invitedAt !== null && row.invitationSentAt === null && !row.registered;
  const mine = (kind: "invite" | "remove") => inFlight && busy?.email === row.email && busy.kind === kind;
  return (
    <li className="grid gap-x-6 gap-y-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
      <div className="min-w-0">
        <p className="font-semibold text-ink [overflow-wrap:anywhere]">{row.email}</p>
        {row.note ? <p className="mt-0.5 max-w-prose text-small whitespace-pre-line text-ink-2">{row.note}</p> : null}
        <p className={cx("text-meta text-ink-2", row.note ? "mt-1" : "mt-0.5")}>{facts.join(" · ")}</p>
      </div>
      {!invitedAt ? (
        <div className="flex flex-wrap items-center gap-2 sm:pt-0.5">
          <Button
            variant="secondary"
            size="sm"
            busy={mine("invite")}
            disabled={inFlight}
            aria-label={`Invita ${row.email}`}
            onClick={() => onRun("invite", row.email)}
            className="min-h-11 sm:min-h-8"
          >
            {mine("invite") ? "Invio…" : "Invita"}
          </Button>
          <Button
            variant="quiet"
            size="sm"
            busy={mine("remove")}
            disabled={inFlight}
            aria-label={`Togli ${row.email}`}
            onClick={() => onRun("remove", row.email)}
            className="min-h-11 sm:min-h-8"
          >
            {mine("remove") ? "Tolgo…" : "Togli"}
          </Button>
        </div>
      ) : needsEmail ? (
        <div className="sm:pt-0.5">
          <Button
            variant="secondary"
            size="sm"
            busy={mine("invite")}
            disabled={inFlight}
            aria-label={`Invia l'email a ${row.email}`}
            onClick={() => onRun("invite", row.email)}
            className="min-h-11 sm:min-h-8"
          >
            {mine("invite") ? "Invio…" : "Invia l'email"}
          </Button>
        </div>
      ) : null}
    </li>
  );
}
