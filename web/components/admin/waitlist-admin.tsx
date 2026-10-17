"use client";

import { useActionState, useState } from "react";

import { inviteAction } from "@/app/actions/waitlist";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import type { WaitlistRow } from "@/lib/server/waitlist";
import { WAITLIST_NOTE_MAX, type WaitlistSource } from "@/lib/waitlist-policy";
import { INVITE_IDLE, type InviteError, type InviteState } from "@/lib/waitlist-state";

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

/** What an invitation did, in one sentence for the status line. */
export function inviteOutcome(state: InviteState): { tone: "info" | "warning" | "error"; text: string } | null {
  if (state.status === "idle") return null;
  if (state.status === "error") return { tone: "error", text: INVITE_ERRORS[state.error] };
  if (state.alreadyInvited) return { tone: "info", text: `${state.email} aveva già un invito: nessuna nuova email.` };
  if (state.emailSent) return { tone: "info", text: `Invito inviato a ${state.email}.` };
  return { tone: "warning", text: `${state.email} è stato invitato, ma l'email non è partita: riprova con «Invia l'email».` };
}

/**
 * The invitations page's body: add an address, the pending requests with "Invita", the
 * invitations with their state. Every action is a server action checked on the server
 * (app/actions/waitlist.ts); the page re-reads the rows after each one.
 */
export function WaitlistAdmin({ rows }: { rows: WaitlistRow[] }) {
  const pending = rows.filter((row) => row.invitedAt === null);
  const invited = rows.filter((row) => row.invitedAt !== null);
  return (
    <div className="grid max-w-[64rem] gap-9">
      <AddInvite />
      <section aria-labelledby="pending-title" className="grid gap-3">
        <h2 id="pending-title" className="font-cond text-heading font-semibold">
          In attesa <span className="font-normal text-ink-2">({pending.length})</span>
        </h2>
        {pending.length === 0 ? (
          <p className="text-small text-ink-2">Nessuna richiesta in attesa.</p>
        ) : (
          <ul className="divide-y divide-rule border-y border-rule">
            {pending.map((row) => (
              <Row key={row.email} row={row} />
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="invited-title" className="grid gap-3">
        <h2 id="invited-title" className="font-cond text-heading font-semibold">
          Invitati <span className="font-normal text-ink-2">({invited.length})</span>
        </h2>
        {invited.length === 0 ? (
          <p className="text-small text-ink-2">Nessun invito ancora: aggiungi un indirizzo qui sopra, o invita una richiesta.</p>
        ) : (
          <ul className="divide-y divide-rule border-y border-rule">
            {invited.map((row) => (
              <Row key={row.email} row={row} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function StatusLine({ state }: { state: InviteState }) {
  const outcome = inviteOutcome(state);
  if (!outcome) return null;
  return (
    <Notice tone={outcome.tone} role={outcome.tone === "error" ? "alert" : "status"} className="max-w-[34rem]">
      {outcome.text}
    </Notice>
  );
}

/** "Aggiungi un indirizzo": invites it at once and sends the email. */
function AddInvite() {
  const [state, formAction, pending] = useActionState<InviteState, FormData>(inviteAction, INVITE_IDLE);
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const emailError = state.status === "error" && state.error === "invalid_email" ? INVITE_ERRORS.invalid_email : null;
  const noteError = state.status === "error" && state.error === "note_too_long" ? INVITE_ERRORS.note_too_long : null;
  const general = state.status === "error" && !emailError && !noteError ? state : state.status === "invited" ? state : null;
  return (
    <section aria-labelledby="add-title" className="grid gap-4">
      <h2 id="add-title" className="font-cond text-heading font-semibold">
        Aggiungi un indirizzo
      </h2>
      {general ? <StatusLine state={general} /> : null}
      <form
        action={(data) => {
          formAction(data);
          setEmail("");
          setNote("");
        }}
        noValidate
        className="grid max-w-[26rem] gap-4"
      >
        <Field label="Indirizzo email" error={emailError}>
          {(control) => (
            <TextInput
              {...control}
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
              name="note"
              rows={2}
              maxLength={WAITLIST_NOTE_MAX}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              disabled={pending}
            />
          )}
        </Field>
        <Button type="submit" variant="primary" icon="plus" busy={pending} className="min-h-11 w-full sm:min-h-10 sm:w-auto sm:justify-self-start">
          {pending ? "Invio…" : "Invita"}
        </Button>
      </form>
    </section>
  );
}

/** One address: who, what they wrote, where from and when; the action on the right. */
function Row({ row }: { row: WaitlistRow }) {
  const [state, formAction, pending] = useActionState<InviteState, FormData>(inviteAction, INVITE_IDLE);
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
  return (
    <li className="grid gap-x-6 gap-y-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
      <div className="min-w-0">
        <p className="font-semibold text-ink [overflow-wrap:anywhere]">{row.email}</p>
        {row.note ? <p className="mt-0.5 max-w-prose text-small whitespace-pre-line text-ink-2">{row.note}</p> : null}
        <p className={cx("text-meta text-ink-2", row.note ? "mt-1" : "mt-0.5")}>{facts.join(" · ")}</p>
        {state.status !== "idle" ? (
          <div className="mt-2">
            <StatusLine state={state} />
          </div>
        ) : null}
      </div>
      {!invitedAt || needsEmail ? (
        <form action={formAction} className="sm:pt-0.5">
          <input type="hidden" name="email" value={row.email} />
          <Button type="submit" variant={invitedAt ? "secondary" : "primary"} size="sm" busy={pending} className="min-h-11 sm:min-h-8">
            {pending ? "Invio…" : invitedAt ? "Invia l'email" : "Invita"}
          </Button>
        </form>
      ) : null}
    </li>
  );
}
