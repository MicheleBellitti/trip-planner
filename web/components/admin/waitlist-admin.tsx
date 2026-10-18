"use client";

import { useEffect, useRef, useState, useTransition } from "react";

import { inviteAction, removeRequestAction, resendInvitationAction } from "@/app/actions/waitlist";
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

/** The removal's own wording where it differs; the rest is shared with the invitation. */
export const REMOVE_ERRORS: Record<InviteError, string> = {
  ...INVITE_ERRORS,
  failed: "Non è stato possibile togliere la richiesta. Riprova tra poco.",
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
  switch (state.delivery) {
    case "sent":
      return { tone: "info", text: `Invito inviato a ${state.email}.` };
    case "already_sent":
      return { tone: "info", text: `${state.email} aveva già un invito: nessuna nuova email.` };
    case "has_account":
      return { tone: "info", text: `${state.email} ha già un account: nessuna email.` };
    case "failed":
      return { tone: "warning", text: `${state.email} è stato invitato, ma l'email non è partita: riprova con «Invia l'email».` };
    case "resent":
      return { tone: "info", text: `Invito inviato di nuovo a ${state.email}.` };
    case "resend_skipped":
      return { tone: "info", text: `Nessuna nuova email a ${state.email}: l'invito era già stato rimandato, o l'indirizzo ha un account.` };
    case "resend_failed":
      return { tone: "warning", text: `L'email per ${state.email} non è partita di nuovo: riprova con «Invia di nuovo».` };
  }
}

/** What a row action says when the action itself never answered (a dropped connection, a
 * redeploy's "Failed to find Server Action"): the action's own failure, not the error page. */
export function unansweredOutcome(kind: RowAction): Outcome {
  return { tone: "error", text: kind === "remove" ? REMOVE_ERRORS.failed : INVITE_ERRORS.failed };
}

/** What removing a request did. */
export function removeOutcome(state: RemoveState): Outcome | null {
  if (state.status === "idle") return null;
  if (state.status === "error") return { tone: "error", text: REMOVE_ERRORS[state.error] };
  return { tone: "info", text: `${state.email} è stato tolto dalla lista.` };
}

type RowAction = "invite" | "remove" | "resend";

/**
 * The invitations page's body: invite an address, the pending requests with "Invita" and "Togli",
 * the invitations with their state ("Invia l'email" when it never left, a quiet "Invia di nuovo"
 * when it is marked sent). Every action is a server action checked on the server
 * (app/actions/waitlist.ts); the page re-reads the rows after each one. One status region for the
 * whole view, there from the first render, says what the last action did, the add form's included
 * (its field errors stay on the fields and clear it). It sticks to the top of the viewport, so the
 * sentence is in view wherever the action was, and `aria-live` reads it; after a row action focus
 * does not jump up to it but moves to the next pending row's button (the list shifts, the work goes
 * on where the thumb is), and lands on the region only when no request is left or the action
 * failed. Focus moves in effects, once the answer is rendered: the region is `display: none`
 * while empty and the fields are disabled while the action runs, and neither can take focus
 * before the commit. "Togli" asks once, inline, before it removes. The view's one primary is the
 * add form's button: the rows' are secondary and quiet.
 */
export function WaitlistAdmin({ rows, truncatedAt = null }: { rows: WaitlistRow[]; truncatedAt?: number | null }) {
  const pending = rows.filter((row) => row.invitedAt === null);
  const invited = rows.filter((row) => row.invitedAt !== null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState<{ email: string; kind: RowAction } | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [inFlight, startTransition] = useTransition();
  const statusRef = useRef<HTMLDivElement>(null);
  const items = useRef(new Map<string, HTMLLIElement>());
  const focusNext = useRef<string | null>(null);

  function register(email: string, element: HTMLLIElement | null) {
    if (element) items.current.set(email, element);
    else items.current.delete(email);
  }

  function run(kind: RowAction, email: string, sent?: string) {
    // The row leaves the list on success: focus will go to its neighbour, the one after it or else
    // the one before. An invited row's "Invia l'email" has no neighbour here: the region takes it.
    const index = pending.findIndex((row) => row.email === email);
    const next = index === -1 ? undefined : (pending[index + 1] ?? pending[index - 1]);
    focusNext.current = next?.email ?? null;
    setBusy({ email, kind });
    startTransition(async () => {
      const data = new FormData();
      data.set("email", email);
      if (sent) data.set("sent", sent);
      try {
        if (kind === "invite") setOutcome(inviteOutcome(await inviteAction(INVITE_IDLE, data)));
        else if (kind === "resend") setOutcome(inviteOutcome(await resendInvitationAction(INVITE_IDLE, data)));
        else setOutcome(removeOutcome(await removeRequestAction(REMOVE_IDLE, data)));
      } catch {
        // A rejection inside a transition would reach the error boundary: it is a failed action.
        setOutcome(unansweredOutcome(kind));
      }
    });
  }

  function announce(result: Outcome | null) {
    focusNext.current = null;
    setOutcome(result);
  }

  // Every answer is a new object, so a repeated outcome moves focus again. The answer can commit
  // a beat before the transition ends, while the rows' buttons are still disabled and cannot take
  // focus: the effect waits for `inFlight` to clear and remembers which answer it already placed.
  const placed = useRef<Outcome | null>(null);
  useEffect(() => {
    if (!outcome || inFlight || placed.current === outcome) return;
    placed.current = outcome;
    const next = outcome.tone === "error" || !focusNext.current ? null : items.current.get(focusNext.current)?.querySelector("button");
    (next ?? statusRef.current)?.focus();
  }, [outcome, inFlight]);

  return (
    <div className="grid max-w-[40rem] gap-9">
      <AddInvite onOutcome={announce} />
      {truncatedAt !== null ? (
        <p className="text-meta text-ink-2">
          Qui ci sono le prime {truncatedAt} voci, le richieste in attesa per prime: le altre restano salvate.
        </p>
      ) : null}
      <div
        ref={statusRef}
        tabIndex={-1}
        role="status"
        aria-live="polite"
        className={cx(
          "sticky top-0 z-10 -my-4 rounded-md bg-ground py-3 outline-none empty:hidden",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        )}
      >
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
              <Row
                key={row.email}
                row={row}
                busy={busy}
                inFlight={inFlight}
                confirming={confirming === row.email}
                onConfirm={(open) => setConfirming(open ? row.email : null)}
                onRun={run}
                itemRef={(element) => register(row.email, element)}
              />
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
 * controlled and cleared only once the server says the invitation went out; an address or note
 * problem is a Field error, which takes focus once the fields are enabled again; every other
 * answer goes to the page's status region through `onOutcome` (null clears it when a field error
 * takes over, so no stale sentence stays beside a fresh one). */
function AddInvite({ onOutcome }: { onOutcome: (outcome: Outcome | null) => void }) {
  const [state, setState] = useState<InviteState>(INVITE_IDLE);
  const [pending, startTransition] = useTransition();
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const emailRef = useRef<HTMLInputElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const emailError = state.status === "error" && state.error === "invalid_email" ? INVITE_ERRORS.invalid_email : null;
  const noteError = state.status === "error" && state.error === "note_too_long" ? INVITE_ERRORS.note_too_long : null;

  function submit(data: FormData) {
    startTransition(async () => {
      let result: InviteState;
      try {
        result = await inviteAction(INVITE_IDLE, data);
      } catch {
        result = { status: "error", error: "failed" }; // the action never answered: not the error page
      }
      setState(result);
      if (result.status === "invited") {
        setEmail("");
        setNote("");
      }
      const onField = result.status === "error" && (result.error === "invalid_email" || result.error === "note_too_long");
      onOutcome(onField ? null : inviteOutcome(result));
    });
  }

  useEffect(() => {
    if (pending || state.status !== "error") return;
    if (state.error === "invalid_email") emailRef.current?.focus();
    else if (state.error === "note_too_long") noteRef.current?.focus();
  }, [state, pending]);

  return (
    <section aria-labelledby="add-title" className="grid gap-4">
      <h2 id="add-title" className="font-cond text-heading font-semibold">
        Invita un indirizzo
      </h2>
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
 * with the address for a screen reader (fourteen buttons that all read "Invita" tell nothing).
 * "Togli" swaps itself for a one-line question with "Sì, togli" and "Annulla": the question takes
 * focus, and "Annulla" gives it back to "Togli". The question stays, busy, while the removal runs. */
function Row({
  row,
  busy,
  inFlight,
  confirming = false,
  onConfirm,
  onRun,
  itemRef,
}: {
  row: WaitlistRow;
  busy: { email: string; kind: RowAction } | null;
  inFlight: boolean;
  confirming?: boolean;
  onConfirm?: (open: boolean) => void;
  onRun: (kind: RowAction, email: string, sent?: string) => void;
  itemRef?: (element: HTMLLIElement | null) => void;
}) {
  const item = useRef<HTMLLIElement | null>(null);
  const wasConfirming = useRef(false);
  useEffect(() => {
    const buttons = item.current;
    if (confirming) buttons?.querySelector<HTMLButtonElement>('[data-action="confirm-remove"]')?.focus();
    else if (wasConfirming.current) buttons?.querySelector<HTMLButtonElement>('[data-action="remove"]')?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);

  const invitedAt = row.invitedAt;
  const facts: string[] = [];
  if (invitedAt) {
    facts.push(`invitato il ${formatDay(invitedAt)}${row.invitedBy ? ` da ${row.invitedBy}` : ""}`);
    facts.push(row.invitationSentAt ? "email inviata" : "email non inviata");
    if (row.registered) facts.push("ha un account");
  } else {
    facts.push(`${SOURCE_LABELS[row.source]}, ${formatDay(row.createdAt)}`);
    if (row.registered) facts.push("ha un account");
  }
  const needsEmail = invitedAt !== null && row.invitationSentAt === null && !row.registered;
  // Marked sent, but the email may never have left (the process died between the claim and the
  // send): the admin may send it once more, quietly, on the stamp this page shows.
  const mayResend = invitedAt !== null && row.invitationSentClaim !== null && !row.registered;
  const mine = (kind: RowAction) => inFlight && busy?.email === row.email && busy.kind === kind;
  const button = "min-h-11 sm:min-h-8";
  return (
    <li
      ref={(element) => {
        item.current = element;
        itemRef?.(element);
      }}
      className="grid gap-x-6 gap-y-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"
    >
      <div className="min-w-0">
        <p className="font-semibold text-ink [overflow-wrap:anywhere]">{row.email}</p>
        {row.note ? <p className="mt-0.5 max-w-prose text-small whitespace-pre-line text-ink-2">{row.note}</p> : null}
        <p className={cx("text-meta text-ink-2", row.note ? "mt-1" : "mt-0.5")}>{facts.join(" · ")}</p>
      </div>
      {!invitedAt ? (
        confirming ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 sm:pt-0.5">
            <span className="text-small text-ink-2">Togliere la richiesta?</span>
            <Button
              variant="secondary"
              size="sm"
              data-action="confirm-remove"
              busy={mine("remove")}
              disabled={inFlight}
              aria-label={`Sì, togli ${row.email}`}
              onClick={() => onRun("remove", row.email)}
              className={button}
            >
              {mine("remove") ? "Tolgo…" : "Sì, togli"}
            </Button>
            <Button variant="quiet" size="sm" disabled={inFlight} onClick={() => onConfirm?.(false)} className={button}>
              Annulla
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2 sm:pt-0.5">
            <Button
              variant="secondary"
              size="sm"
              busy={mine("invite")}
              disabled={inFlight}
              aria-label={`Invita ${row.email}`}
              onClick={() => onRun("invite", row.email)}
              className={button}
            >
              {mine("invite") ? "Invio…" : "Invita"}
            </Button>
            <Button
              variant="quiet"
              size="sm"
              data-action="remove"
              disabled={inFlight}
              aria-label={`Togli ${row.email}`}
              onClick={() => onConfirm?.(true)}
              className={button}
            >
              Togli
            </Button>
          </div>
        )
      ) : needsEmail ? (
        <div className="sm:pt-0.5">
          <Button
            variant="secondary"
            size="sm"
            busy={mine("invite")}
            disabled={inFlight}
            aria-label={`Invia l'email a ${row.email}`}
            onClick={() => onRun("invite", row.email)}
            className={button}
          >
            {mine("invite") ? "Invio…" : "Invia l'email"}
          </Button>
        </div>
      ) : mayResend ? (
        <div className="sm:pt-0.5">
          <Button
            variant="quiet"
            size="sm"
            busy={mine("resend")}
            disabled={inFlight}
            aria-label={`Invia di nuovo l'invito a ${row.email}`}
            onClick={() => onRun("resend", row.email, row.invitationSentClaim ?? undefined)}
            className={button}
          >
            {mine("resend") ? "Invio…" : "Invia di nuovo"}
          </Button>
        </div>
      ) : null}
    </li>
  );
}
