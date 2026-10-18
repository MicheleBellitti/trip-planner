"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { StatePanel } from "@/components/states/state-panel";
import { Button } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { authClient } from "@/lib/auth-client";
import { safeReturnTo } from "@/lib/return-to";
import { ROUTES } from "@/lib/routes";

/** The one sentence about the link, reused wherever it is described. */
export const LINK_VALIDITY = "Vale cinque minuti e funziona una volta sola.";
export const INVITE_ONLY_ERROR = "Questo indirizzo non è abilitato.";
export const INVITE_ONLY_HELP =
  "L'accesso è su invito: usa l'indirizzo a cui è arrivato, o chiedi a chi ti ha invitato di abilitarlo.";
export const INVALID_EMAIL_ERROR = "Scrivi un indirizzo email completo.";
export const TOO_MANY_REQUESTS_ERROR = "Troppi tentativi: aspetta un minuto e riprova.";
export const SEND_FAILED_ERROR = "Non è stato possibile inviare il link. Riprova.";
export const GENERIC_SIGN_IN_ERROR = "Non è stato possibile accedere. Riprova.";
export const UNCONFIGURED_MESSAGE = "Gli account non sono configurati su questo server.";

export interface SignInNotice {
  title: string;
  body?: string;
}

/** The lede already says how long a link lasts: the notice only says what to do. */
const LINK_SPENT: SignInNotice = { title: "Il link non è più valido.", body: "Chiedine un altro qui sotto." };
const INVITE_ONLY: SignInNotice = { title: INVITE_ONLY_ERROR, body: INVITE_ONLY_HELP };

/** What Better Auth puts in `?error=` when a magic link or a Google sign-in fails, in Italian. */
export const SIGN_IN_ERRORS: Record<string, SignInNotice> = {
  INVALID_TOKEN: LINK_SPENT,
  EXPIRED_TOKEN: LINK_SPENT,
  new_user_signup_disabled: INVITE_ONLY,
  signup_disabled: INVITE_ONLY,
  SIGNUP_NOT_ALLOWED: INVITE_ONLY,
  unable_to_create_user: INVITE_ONLY,
  access_denied: { title: "Accesso con Google annullato.", body: "Puoi riprovare quando vuoi, o entrare con il link via email." },
};

export function signInError(code: string | null | undefined): SignInNotice | null {
  if (!code) return null;
  return SIGN_IN_ERRORS[code] ?? { title: GENERIC_SIGN_IN_ERROR };
}

/** Where the field may take focus on arrival: a wide screen driven by a mouse or trackpad. */
const DESKTOP_POINTER = "(min-width: 640px) and (pointer: fine)";

/** A shape check, not a validator: the server decides. It keeps the browser's own English bubble away. */
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface ClientError {
  status?: number;
  code?: string;
}

/** `sent` is a new object on every send, so the focus effect fires again on a resend. */
type Phase = { kind: "form" } | { kind: "sent"; email: string; again: boolean };

interface LoginFormProps {
  /** The page to come back to after signing in (lib/api.ts `loginUrl`); reduced to a same-origin path. */
  returnTo: string | null;
  /** Better Auth's `?error=` after a failed link or Google callback. */
  errorCode: string | null;
  /** False when the server has no accounts database: the lede and the reason, no form. */
  configured: boolean;
  googleEnabled: boolean;
}

/**
 * Sign in: an email for the link, or Google. No passwords (PRODUCT.md). One lede says why the user
 * is here when it knows (`returnTo`), what the link is and how long it lasts. An address problem
 * (shape, not invited) is a Field error on the input; everything else (an expired link, too many
 * tries, a failure) is a Notice that answers the user's own action. The "sent" state keeps the
 * address on screen, says where to look, and can send another link or change the address. Focus
 * follows every transition: the input on an error and on the way back, the panel whenever a link
 * leaves. The verb is always "inviare".
 */
export function LoginForm({ returnTo, errorCode, configured, googleEnabled }: LoginFormProps) {
  const [phase, setPhase] = useState<Phase>({ kind: "form" });
  const [email, setEmail] = useState("");
  const [fieldError, setFieldError] = useState<ReactNode>(null);
  const [notice, setNotice] = useState<SignInNotice | null>(() => signInError(errorCode));
  const [busy, setBusy] = useState<"link" | "google" | null>(null);
  // Bumped whenever focus should land on the input after the next render (an error, the way back
  // from the sent state): an effect does it once the field is mounted and enabled again.
  const [focusInput, setFocusInput] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const sentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (phase.kind === "sent") sentRef.current?.focus();
  }, [phase]);

  // Selecting the kept address on the way back from the sent state lets typing replace it.
  const selectOnFocus = useRef(false);
  useEffect(() => {
    if (focusInput === 0) return;
    inputRef.current?.focus();
    if (selectOnFocus.current) {
      inputRef.current?.select();
      selectOnFocus.current = false;
    }
  }, [focusInput]);

  // A failed resend (too many tries, a failure) leaves the busy button disabled: focus would fall
  // to the document, so it goes back to the panel, where the alert is.
  useEffect(() => {
    if (phase.kind === "sent" && notice) sentRef.current?.focus();
  }, [notice, phase.kind]);

  // A one-field page: on a desktop the field is ready to type into. Never on a phone, where the
  // keyboard would cover the words, and never over a notice the user should read first.
  useEffect(() => {
    if (!configured || errorCode) return;
    const desktop = typeof window.matchMedia === "function" && window.matchMedia(DESKTOP_POINTER).matches;
    if (desktop) inputRef.current?.focus();
  }, [configured, errorCode]);

  // The callback's `?error=` has been shown: drop it, so a reload or "Cambia indirizzo" does not
  // bring a spent link's notice back. `returnTo` stays.
  useEffect(() => {
    if (!errorCode) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("error");
    window.history.replaceState(window.history.state, "", url);
  }, [errorCode]);

  const callbackURL = () => safeReturnTo(returnTo, window.location.origin);
  /** Where a spent link or a cancelled Google sign-in lands: this page, still knowing the way back. */
  const errorCallbackURL = () =>
    returnTo ? `${ROUTES.login}?returnTo=${encodeURIComponent(callbackURL())}` : ROUTES.login;

  /** Sends the link to `address`; `again` marks a resend from the sent state. */
  async function send(address: string, again: boolean) {
    setBusy("link");
    setNotice(null);
    setFieldError(null);
    let error: ClientError | null;
    try {
      ({ error } = await authClient.signIn.magicLink({
        email: address,
        callbackURL: callbackURL(),
        errorCallbackURL: errorCallbackURL(),
      }));
    } catch {
      // A network failure rejects instead of answering with an error: it is a failed send too.
      error = {};
    } finally {
      setBusy(null);
    }
    if (error) {
      failed(error, { inSentState: again, action: "link" });
      return;
    }
    setPhase({ kind: "sent", email: address, again });
  }

  /** Only the invite rule (lib/auth.ts `SIGNUP_NOT_ALLOWED`) is about the address: Better Auth
   * answers 403 for other refusals too (an origin or callback it does not trust), and those are
   * the generic failure. */
  function failed(error: ClientError, { inSentState, action }: { inSentState: boolean; action: "link" | "google" }) {
    if (error.code === "SIGNUP_NOT_ALLOWED") {
      if (inSentState) setPhase({ kind: "form" });
      setFieldError(
        <>
          <strong className="font-semibold">{INVITE_ONLY_ERROR}</strong> {INVITE_ONLY_HELP}
        </>,
      );
      setFocusInput((tick) => tick + 1);
      return;
    }
    const failure = action === "link" ? SEND_FAILED_ERROR : GENERIC_SIGN_IN_ERROR;
    setNotice({ title: error.status === 429 ? TOO_MANY_REQUESTS_ERROR : failure });
    if (!inSentState) setFocusInput((tick) => tick + 1);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const address = email.trim();
    if (!EMAIL_SHAPE.test(address)) {
      setNotice(null);
      setFieldError(INVALID_EMAIL_ERROR);
      setFocusInput((tick) => tick + 1);
      return;
    }
    void send(address, false);
  }

  async function withGoogle() {
    setBusy("google");
    setNotice(null);
    setFieldError(null);
    let error: ClientError | null;
    try {
      ({ error } = await authClient.signIn.social({
        provider: "google",
        callbackURL: callbackURL(),
        errorCallbackURL: errorCallbackURL(),
      }));
    } catch {
      error = {}; // a network failure rejects instead of answering with an error
    }
    if (error) {
      setBusy(null);
      failed(error, { inSentState: false, action: "google" });
    }
    // On success the browser is leaving for Google: the button stays busy until then.
  }

  if (phase.kind === "sent") {
    return (
      // Focusable, so the swap from the form (and every resend) lands a keyboard or screen-reader
      // user on the news.
      <div ref={sentRef} tabIndex={-1} className="rounded-md outline-none">
        <StatePanel
          icon="sign-in"
          title="Controlla la posta"
          headingId="login-sent"
          footer={notice ? <Notice tone="error" role="alert" title={notice.title}>{notice.body}</Notice> : null}
          actions={
            <>
              <Button
                variant="quiet"
                size="sm"
                icon="arrows-clockwise"
                busy={busy === "link"}
                onClick={() => void send(phase.email, true)}
                // The quiet button's padding would indent its icon past the text column.
                className="-ml-3 min-h-11 sm:min-h-8"
              >
                {busy === "link" ? "Invio il link…" : "Inviane un altro"}
              </Button>
              <Button
                variant="quiet"
                size="sm"
                icon="arrow-left"
                disabled={busy !== null}
                onClick={() => {
                  setNotice(null);
                  setPhase({ kind: "form" });
                  selectOnFocus.current = true;
                  setFocusInput((tick) => tick + 1);
                }}
                className="min-h-11 sm:min-h-8"
              >
                Cambia indirizzo
              </Button>
            </>
          }
        >
          <div className="min-w-0 lg:col-span-3">
            <dt className="sr-only">Cosa è successo</dt>
            <dd aria-live="polite" className="m-0 max-w-prose text-small text-ink [overflow-wrap:anywhere]">
              {phase.again ? "Abbiamo inviato un altro link a " : "Abbiamo inviato un link a "}
              <strong className="font-semibold">{phase.email}</strong>. {LINK_VALIDITY}
            </dd>
            <dt className="sr-only">Cosa puoi fare</dt>
            <dd className="m-0 mt-1.5 max-w-prose text-small text-ink-2">
              Non lo vedi? Guarda nella posta indesiderata, o chiedine un altro.
            </dd>
          </div>
        </StatePanel>
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <p className="max-w-prose text-pretty text-small text-ink-2">
        {returnTo ? "Accedi per tornare dove eri: ti inviamo un link. " : "Ti inviamo un link per entrare, senza password. "}
        {LINK_VALIDITY}
      </p>
      {!configured ? (
        <Notice tone="warning" title={UNCONFIGURED_MESSAGE}>
          Chi gestisce questo server deve ancora configurare gli account.
        </Notice>
      ) : null}
      {notice ? (
        <Notice tone="error" role="alert" title={notice.title}>
          {notice.body}
        </Notice>
      ) : null}
      {configured ? (
        <form onSubmit={submit} noValidate className="grid gap-4">
          <Field label="Indirizzo email" hint="Quello invitato, o con cui sei già entrato." error={fieldError}>
            {(control) => (
              <TextInput
                {...control}
                ref={inputRef}
                type="email"
                name="email"
                autoComplete="email"
                inputMode="email"
                spellCheck={false}
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  if (fieldError) setFieldError(null);
                }}
                disabled={busy !== null}
              />
            )}
          </Field>
          <Button
            type="submit"
            variant="primary"
            icon="arrow-right"
            busy={busy === "link"}
            disabled={busy !== null}
            // 44 px on the phone, like the field above it; 40 px and its own width from 640 px (DESIGN.md,
            // Buttons; the grid would otherwise stretch it).
            className="min-h-11 w-full sm:min-h-10 sm:w-auto sm:justify-self-start"
          >
            {busy === "link" ? "Invio il link…" : "Inviami il link"}
          </Button>
        </form>
      ) : null}
      {configured && googleEnabled ? (
        <>
          <p className="flex items-center gap-3 text-meta text-ink-2" aria-hidden="true">
            <span className="h-px flex-1 bg-rule" />
            oppure
            <span className="h-px flex-1 bg-rule" />
          </p>
          <Button
            variant="secondary"
            onClick={withGoogle}
            busy={busy === "google"}
            disabled={busy !== null}
            className="min-h-11 w-full sm:min-h-10 sm:w-auto sm:justify-self-start"
          >
            {busy === "google" ? "Apro Google…" : "Continua con Google"}
          </Button>
        </>
      ) : null}
    </div>
  );
}
