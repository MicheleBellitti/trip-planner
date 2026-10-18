"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { joinWaitlistAction } from "@/app/actions/waitlist";
import { StatePanel } from "@/components/states/state-panel";
import { Button } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { Turnstile, type TurnstileHandle } from "@/components/ui/turnstile";
import { WAITLIST_FAILED, WAITLIST_SUBMIT, WAITLIST_TOO_MANY, WaitlistOutcome } from "@/components/waitlist/waitlist-form";
import { authClient } from "@/lib/auth-client";
import { CHALLENGE_FAILED_MESSAGE, TURNSTILE_FIELD, TURNSTILE_HEADER, turnstileSiteKey } from "@/lib/turnstile";
import { BRAND_NAME } from "@/lib/brand";
import { safeReturnTo } from "@/lib/return-to";
import { ROUTES } from "@/lib/routes";
import type { JoinOutcome } from "@/lib/waitlist-policy";
import { JOIN_IDLE } from "@/lib/waitlist-state";

/** The one sentence about the link, reused wherever it is described. */
export const LINK_VALIDITY = "Vale cinque minuti e funziona una volta sola.";
export const INVITE_ONLY_ERROR = "Questo indirizzo non ha ancora un invito.";
export const INVITE_ONLY_HELP = `${BRAND_NAME} è su invito: se ne hai uno, usa l'indirizzo a cui è arrivato; altrimenti mettiti in lista e ti scriviamo quando c'è posto.`;
/** After "Sei in lista" on this page: what the h1 "Accedi" still promises. */
export const LISTED_HINT = "Quando ti scriviamo, torna qui con lo stesso indirizzo.";

/** How long a send waits for a fresh Turnstile token after a reset before going without one. */
export const CHALLENGE_WAIT_MS = 6000;
/** Better Auth's `code` when the magic-link request did not pass the challenge (lib/auth.ts). */
const CHALLENGE_FAILED_CODE = "CHALLENGE_FAILED";
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
/** A refusal that came back from a callback (Google): the form below is the way to the list. */
const INVITE_ONLY: SignInNotice = {
  title: INVITE_ONLY_ERROR,
  body: "Scrivi qui sotto l'indirizzo con cui vuoi entrare: se non ha un invito, potrai metterti in lista.",
};

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

/** `sent` is a new object on every send, so the focus effect fires again on a resend; `listed` is
 * the waitlist's answer after a refused address asked to join. */
type Phase = { kind: "form" } | { kind: "sent"; email: string; again: boolean } | { kind: "listed"; email: string; outcome: JoinOutcome };

type Busy = "link" | "google" | "list" | null;

interface LoginFormProps {
  /** The page to come back to after signing in (lib/api.ts `loginUrl`); reduced to a same-origin path. */
  returnTo: string | null;
  /** Better Auth's `?error=` after a failed link or Google callback. */
  errorCode: string | null;
  /** False when the server has no accounts database: the lede and the reason, no form. */
  configured: boolean;
  googleEnabled: boolean;
  /** How the sent state leaves once the link was used elsewhere; the tests inject it. */
  navigate?: (url: string) => void;
}

/**
 * Sign in: an email for the link, or Google. No passwords (PRODUCT.md). One lede says why the user
 * is here when it knows (`returnTo`), what the link is and how long it lasts. An address problem
 * (shape, not invited) is a Field error on the input; a refused address also gets the way in,
 * "Mettimi in lista" (app/actions/waitlist.ts), whose answer replaces the form. Everything else (an
 * expired link, too many tries, a failure) is a Notice that answers the user's own action. The
 * "sent" state keeps the address on screen, says where to look, can send another link or change
 * the address, and heals itself: when the tab comes back into view it asks whether the link was
 * used elsewhere and, if so, goes where the user was headed. Focus follows every transition: the
 * input on an error and on the way back, the panel whenever a link leaves. The verb is always
 * "inviare".
 */
export function LoginForm({ returnTo, errorCode, configured, googleEnabled, navigate }: LoginFormProps) {
  const [phase, setPhase] = useState<Phase>({ kind: "form" });
  const [email, setEmail] = useState("");
  const [fieldError, setFieldError] = useState<ReactNode>(null);
  const [notice, setNotice] = useState<SignInNotice | null>(() => signInError(errorCode));
  const [busy, setBusy] = useState<Busy>(null);
  /** The address the server refused: the way in is the waitlist, offered beside the field. */
  const [refusedAddress, setRefusedAddress] = useState<string | null>(null);
  // Bumped whenever focus should land on the input after the next render (an error, the way back
  // from the sent state): an effect does it once the field is mounted and enabled again.
  const [focusInput, setFocusInput] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const sentRef = useRef<HTMLDivElement>(null);
  // Turnstile: the latest token, and who is waiting for the next one (a send right after a reset,
  // before the fresh token arrived). A token is spent by one request, so every request resets the
  // widget afterwards.
  const challengeToken = useRef<string | null>(null);
  const challengeWaiters = useRef<Array<(token: string | null) => void>>([]);
  const turnstile = useRef<TurnstileHandle>(null);
  const onChallenge = useCallback((token: string | null) => {
    challengeToken.current = token;
    if (token) for (const waiter of challengeWaiters.current.splice(0)) waiter(token);
  }, []);

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

  // The link usually opens in another tab, or in the mail app's own browser, and this tab would
  // say "Controlla la posta" forever. Each time it comes back into view it asks whether a session
  // now exists and, if so, goes where the user was headed, so the 401 heals where it happened.
  useEffect(() => {
    if (phase.kind !== "sent") return;
    let checking = false;
    const check = async () => {
      if (checking || document.visibilityState !== "visible") return;
      checking = true;
      try {
        const { data } = await authClient.getSession();
        if (data?.session) (navigate ?? ((url: string) => window.location.assign(url)))(safeReturnTo(returnTo, window.location.origin));
      } catch {
        // The next return to the tab asks again.
      } finally {
        checking = false;
      }
    };
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, [phase.kind, returnTo, navigate]);

  /** Sends the link to `address`; `again` marks a resend from the sent state. */
  /** The challenge's token for the next request: null when the challenge is off; otherwise the
   * one at hand, or the next one within `CHALLENGE_WAIT_MS` (after a reset it takes a moment). */
  function challenge(): Promise<string | null> {
    if (!turnstileSiteKey()) return Promise.resolve(null);
    if (challengeToken.current) return Promise.resolve(challengeToken.current);
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        challengeWaiters.current = challengeWaiters.current.filter((waiter) => waiter !== settle);
        resolve(null);
      }, CHALLENGE_WAIT_MS);
      const settle = (token: string | null) => {
        clearTimeout(timer);
        resolve(token);
      };
      challengeWaiters.current.push(settle);
    });
  }

  /** The token was spent: forget it and ask the widget for the next one. */
  function spendChallenge() {
    if (!turnstileSiteKey()) return;
    challengeToken.current = null;
    turnstile.current?.reset();
  }

  async function send(address: string, again: boolean) {
    setBusy("link");
    setNotice(null);
    setFieldError(null);
    const token = await challenge();
    const { error } = await authClient.signIn.magicLink({
      email: address,
      callbackURL: callbackURL(),
      errorCallbackURL: errorCallbackURL(),
      fetchOptions: token ? { headers: { [TURNSTILE_HEADER]: token } } : undefined,
    });
    spendChallenge();
    setBusy(null);
    if (error) {
      failed(error, { inSentState: again, action: "link", address });
      return;
    }
    setPhase({ kind: "sent", email: address, again });
  }

  /** The refused address asks to join the waitlist (source "login"); the answer replaces the form. */
  async function joinList(address: string) {
    setBusy("list");
    setNotice(null);
    const data = new FormData();
    data.set("email", address);
    data.set("source", "login");
    const token = await challenge();
    if (token) data.set(TURNSTILE_FIELD, token);
    const state = await joinWaitlistAction(JOIN_IDLE, data);
    spendChallenge();
    setBusy(null);
    if (state.status === "idle" || state.status === "error") {
      const error = state.status === "error" ? state.error : null;
      setNotice({
        title:
          error === "challenge_failed" ? CHALLENGE_FAILED_MESSAGE : error === "too_many_requests" ? WAITLIST_TOO_MANY : WAITLIST_FAILED,
      });
      return;
    }
    if (state.status === "already_invited" || state.status === "already_registered") {
      // The door is open after all: the link goes out as if the first try had worked.
      setRefusedAddress(null);
      setFieldError(null);
      void send(address, false);
      return;
    }
    setPhase({ kind: "listed", email: state.email, outcome: state.status });
  }

  function failed(
    error: ClientError,
    { inSentState, action, address }: { inSentState: boolean; action: "link" | "google"; address: string | null },
  ) {
    if (error.code === CHALLENGE_FAILED_CODE) {
      setNotice({ title: CHALLENGE_FAILED_MESSAGE });
      if (!inSentState) setFocusInput((tick) => tick + 1);
      return;
    }
    if (error.code === "SIGNUP_NOT_ALLOWED" || error.status === 403) {
      if (inSentState) setPhase({ kind: "form" });
      setRefusedAddress(address);
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
    // Enter on an address that stands refused does what the primary says, not another refusal.
    if (refusedAddress && address.toLowerCase() === refusedAddress.toLowerCase()) {
      void joinList(refusedAddress);
      return;
    }
    void send(address, false);
  }

  async function withGoogle() {
    setBusy("google");
    setNotice(null);
    setFieldError(null);
    const { error } = await authClient.signIn.social({
      provider: "google",
      callbackURL: callbackURL(),
      errorCallbackURL: errorCallbackURL(),
    });
    if (error) {
      setBusy(null);
      failed(error, { inSentState: false, action: "google", address: null });
    }
    // On success the browser is leaving for Google: the button stays busy until then.
  }

  if (phase.kind === "listed") {
    return (
      <WaitlistOutcome
        outcome={phase.outcome}
        email={phase.email}
        hint={LISTED_HINT}
        actions={
          <Button
            variant="quiet"
            size="sm"
            icon="arrow-left"
            onClick={() => {
              setRefusedAddress(null);
              setFieldError(null);
              setPhase({ kind: "form" });
              selectOnFocus.current = true;
              setFocusInput((tick) => tick + 1);
            }}
            className="-ml-3 min-h-11 sm:min-h-8"
          >
            Cambia indirizzo
          </Button>
        }
      />
    );
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
              Non lo vedi? Guarda nella posta indesiderata, o chiedine un altro. Se lo apri da un altro posto,
              questa pagina ti porta avanti da sola.
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
                  if (refusedAddress) setRefusedAddress(null);
                }}
                disabled={busy !== null}
              />
            )}
          </Field>
          <Turnstile ref={turnstile} onToken={onChallenge} action="login" />
          {/* While an address stands refused, the way in is the primary and comes first, and the failed
              action steps back without its arrow; typing another address clears `refusedAddress` and
              undoes the swap. The submit button keeps Enter: `submit` turns it into the join then. */}
          <div className="grid gap-2.5 sm:flex sm:flex-wrap sm:items-center">
            {refusedAddress ? (
              <Button
                type="button"
                variant="primary"
                icon="arrow-right"
                busy={busy === "list"}
                disabled={busy !== null}
                onClick={() => void joinList(refusedAddress)}
                className="min-h-11 w-full sm:min-h-10 sm:w-auto"
              >
                {busy === "list" ? "Invio…" : WAITLIST_SUBMIT}
              </Button>
            ) : null}
            <Button
              type="submit"
              variant={refusedAddress ? "secondary" : "primary"}
              icon={refusedAddress ? undefined : "arrow-right"}
              busy={busy === "link"}
              disabled={busy !== null}
              // 44 px on the phone, like the field above it; 40 px and its own width from 640 px (DESIGN.md,
              // Buttons; the grid would otherwise stretch it).
              className="min-h-11 w-full sm:min-h-10 sm:w-auto"
            >
              {busy === "link" ? "Invio il link…" : "Inviami il link"}
            </Button>
          </div>
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
