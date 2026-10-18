"use client";

import { useEffect, useRef, useState, useTransition, type Ref } from "react";

import { inviteAction, removeRequestAction, resendInvitationAction } from "@/app/actions/waitlist";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { Icon, type IconName } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
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

/** Where a row action's answer is drawn: under the row it was acted on, in the list it was acted
 * in. When the row has left that list (invited, removed), its place keeps the address and the
 * answer until the next action, so the feedback stays where the click was. */
interface RowStatus {
  email: string;
  outcome: Outcome;
  list: "pending" | "invited";
  index: number;
}

/**
 * The invitations page's body: invite an address, the pending requests with "Invita" and "Togli",
 * the invitations with their state ("Invia l'email" when it never left, a quiet "Invia di nuovo"
 * when it is marked sent). Every action is a server action checked on the server
 * (app/actions/waitlist.ts); the page re-reads the rows after each one. A row action's answer is
 * one line under that row (RowStatus), the add form's a Notice under the form: each where the
 * action was, on the page's own surface. One visually hidden status region, there from the first
 * render, reads every answer aloud. After a row action focus moves to the next pending row's
 * button (the list shifts, the work goes on where the thumb is), and lands on the answer's line
 * only when no request is left or the action failed. Focus moves in effects, once the answer is
 * rendered: the fields and buttons are disabled while the action runs and cannot take focus
 * before the commit. "Togli" asks once, inline, before it removes. The view's one primary is the
 * add form's button: the rows' are secondary and quiet.
 */
export function WaitlistAdmin({ rows, truncatedAt = null }: { rows: WaitlistRow[]; truncatedAt?: number | null }) {
  const pending = rows.filter((row) => row.invitedAt === null);
  const invited = rows.filter((row) => row.invitedAt !== null);
  const [status, setStatus] = useState<RowStatus | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [busy, setBusy] = useState<{ email: string; kind: RowAction } | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [inFlight, startTransition] = useTransition();
  const statusLine = useRef<HTMLParagraphElement>(null);
  const items = useRef(new Map<string, HTMLLIElement>());
  const focusNext = useRef<string | null>(null);

  function register(email: string, element: HTMLLIElement | null) {
    if (element) items.current.set(email, element);
    else items.current.delete(email);
  }

  function run(kind: RowAction, email: string, sent?: string) {
    // The row leaves the list on success: focus will go to its neighbour, the one after it or else
    // the one before. An invited row's actions have no neighbour here: its answer's line takes it.
    const inPending = pending.findIndex((row) => row.email === email);
    const list = inPending === -1 ? "invited" : "pending";
    const index = inPending === -1 ? invited.findIndex((row) => row.email === email) : inPending;
    const next = inPending === -1 ? undefined : (pending[inPending + 1] ?? pending[inPending - 1]);
    focusNext.current = next?.email ?? null;
    setBusy({ email, kind });
    startTransition(async () => {
      const data = new FormData();
      data.set("email", email);
      if (sent) data.set("sent", sent);
      let outcome: Outcome | null;
      try {
        if (kind === "invite") outcome = inviteOutcome(await inviteAction(INVITE_IDLE, data));
        else if (kind === "resend") outcome = inviteOutcome(await resendInvitationAction(INVITE_IDLE, data));
        else outcome = removeOutcome(await removeRequestAction(REMOVE_IDLE, data));
      } catch {
        // A rejection inside a transition would reach the error boundary: it is a failed action.
        outcome = unansweredOutcome(kind);
      }
      if (!outcome) return;
      setStatus({ email, outcome, list, index });
      setAnnouncement(outcome.text);
    });
  }

  function announceForm(outcome: Outcome | null) {
    setStatus(null);
    setAnnouncement(outcome?.text ?? "");
  }

  // Every answer is a new object, so a repeated outcome moves focus again. The answer can commit
  // a beat before the transition ends, while the rows' buttons are still disabled and cannot take
  // focus: the effect waits for `inFlight` to clear and remembers which answer it already placed.
  const placed = useRef<RowStatus | null>(null);
  useEffect(() => {
    if (!status || inFlight || placed.current === status) return;
    placed.current = status;
    const next = status.outcome.tone === "error" || !focusNext.current ? null : items.current.get(focusNext.current)?.querySelector("button");
    (next ?? statusLine.current)?.focus();
  }, [status, inFlight]);

  const pendingStatus = status?.list === "pending" ? status : null;
  const invitedStatus = status?.list === "invited" ? status : null;
  // The acted-on request left the list: its answer keeps the row's place.
  const ghost = pendingStatus && !pending.some((row) => row.email === pendingStatus.email) ? pendingStatus : null;
  const ghostAt = ghost ? Math.min(ghost.index, pending.length) : -1;

  return (
    <div className="grid max-w-[40rem] gap-9">
      <AddInvite onOutcome={announceForm} />
      {truncatedAt !== null ? (
        <p className="text-meta text-ink-2">
          Qui ci sono le prime {truncatedAt} voci, le richieste in attesa per prime: le altre restano salvate.
        </p>
      ) : null}
      <VisuallyHidden as="div" role="status" aria-live="polite">
        {announcement}
      </VisuallyHidden>
      <section aria-labelledby="pending-title" className="grid gap-3">
        <h2 id="pending-title" className="font-cond text-heading font-semibold">
          In attesa <span className="font-normal text-ink-2">({pending.length})</span>
        </h2>
        {pending.length === 0 && !ghost ? (
          <p className="text-small text-ink-2">Nessuna richiesta in attesa.</p>
        ) : (
          <ul className="divide-y divide-rule border-y border-rule">
            {pending.flatMap((row, index) => {
              const item = (
                <Row
                  key={row.email}
                  row={row}
                  busy={busy}
                  inFlight={inFlight}
                  confirming={confirming === row.email}
                  onConfirm={(open) => setConfirming(open ? row.email : null)}
                  onRun={run}
                  itemRef={(element) => register(row.email, element)}
                  status={pendingStatus?.email === row.email ? pendingStatus.outcome : null}
                  statusRef={statusLine}
                />
              );
              return index === ghostAt && ghost ? [<Ghost key={`ghost-${ghost.email}`} status={ghost} statusRef={statusLine} />, item] : [item];
            })}
            {ghost && ghostAt === pending.length ? <Ghost key={`ghost-${ghost.email}`} status={ghost} statusRef={statusLine} /> : null}
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
              <Row
                key={row.email}
                row={row}
                busy={busy}
                inFlight={inFlight}
                onRun={run}
                status={invitedStatus?.email === row.email ? invitedStatus.outcome : null}
                statusRef={statusLine}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

const STATUS_ICONS: Record<Outcome["tone"], IconName> = { info: "check-circle", warning: "warning", error: "x-circle" };

/** A row action's answer: one line on the page's surface, no frame of its own, the glyph carrying
 * the tone (never colour alone; error red only for an error). Focusable, so focus can land on it. */
function StatusLine({ outcome, statusRef }: { outcome: Outcome; statusRef?: Ref<HTMLParagraphElement> }) {
  return (
    <p
      ref={statusRef}
      tabIndex={-1}
      data-row-status=""
      className={cx(
        "flex items-start gap-2 rounded-xs text-meta outline-none sm:col-span-2 [overflow-wrap:anywhere]",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        outcome.tone === "error" ? "text-error" : "text-ink",
      )}
    >
      <Icon name={STATUS_ICONS[outcome.tone]} size={15} className="mt-px shrink-0" />
      <span>{outcome.text}</span>
    </p>
  );
}

/** The place of a request that has just left the list: its address and the answer, until the next action. */
function Ghost({ status, statusRef }: { status: RowStatus; statusRef: Ref<HTMLParagraphElement> }) {
  return (
    <li className="grid gap-y-1.5 py-3">
      <p className="font-semibold text-ink-2 [overflow-wrap:anywhere]">{status.email}</p>
      <StatusLine outcome={status.outcome} statusRef={statusRef} />
    </li>
  );
}

/** "Invita un indirizzo": a row with source "admin", invited at once, the email sent. The fields are
 * controlled and cleared only once the server says the invitation went out; an address or note
 * problem is a Field error, which takes focus once the fields are enabled again; every other
 * answer is a Notice under the form, which takes focus, and is read aloud by the page's region
 * through `onOutcome` (null clears both when a field error takes over, so no stale sentence stays
 * beside a fresh one). */
function AddInvite({ onOutcome }: { onOutcome: (outcome: Outcome | null) => void }) {
  const [state, setState] = useState<InviteState>(INVITE_IDLE);
  const [pending, startTransition] = useTransition();
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const emailRef = useRef<HTMLInputElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const [answer, setAnswer] = useState<Outcome | null>(null);
  const answerRef = useRef<HTMLDivElement>(null);
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
      const outcome = onField ? null : inviteOutcome(result);
      setAnswer(outcome);
      onOutcome(outcome);
    });
  }

  useEffect(() => {
    if (!pending && answer) answerRef.current?.focus();
  }, [answer, pending]);

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
      {answer ? (
        // No surface of its own: the Notice is the one frame; this only takes focus.
        <div
          ref={answerRef}
          tabIndex={-1}
          className="max-w-[26rem] rounded-sm outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          <Notice tone={answer.tone}>{answer.text}</Notice>
        </div>
      ) : null}
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
  status = null,
  statusRef,
}: {
  row: WaitlistRow;
  busy: { email: string; kind: RowAction } | null;
  inFlight: boolean;
  confirming?: boolean;
  onConfirm?: (open: boolean) => void;
  onRun: (kind: RowAction, email: string, sent?: string) => void;
  itemRef?: (element: HTMLLIElement | null) => void;
  /** The answer to the last action on this row, drawn under it. */
  status?: Outcome | null;
  statusRef?: Ref<HTMLParagraphElement>;
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
  // A quiet button has no edge: its text is what lines up. Leading on the phone, it gives its
  // padding back on the left (the text column); trailing in the right-hand column from 640 px, on
  // the right (the bordered buttons' edge).
  const quietLead = "-ml-3 sm:ml-0 sm:-mr-3";
  const quietTrail = "sm:-mr-3";
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
            <Button variant="quiet" size="sm" disabled={inFlight} onClick={() => onConfirm?.(false)} className={cx(button, quietTrail)}>
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
              className={cx(button, quietTrail)}
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
            className={cx(button, quietLead)}
          >
            {mine("resend") ? "Invio…" : "Invia di nuovo"}
          </Button>
        </div>
      ) : null}
      {status ? <StatusLine outcome={status} statusRef={statusRef} /> : null}
    </li>
  );
}
