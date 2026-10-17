"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { authClient } from "@/lib/auth-client";
import { safeReturnTo } from "@/lib/return-to";
import { ROUTES } from "@/lib/routes";

export const GENERIC_SIGN_IN_ERROR = "Non è stato possibile accedere. Riprova.";
export const INVITE_ONLY_ERROR = "Questo indirizzo non è abilitato: l'accesso è su invito.";
export const TOO_MANY_REQUESTS_ERROR = "Troppi tentativi: aspetta un minuto e riprova.";
const LINK_SPENT_ERROR = "Il link non è più valido: ne vale uno solo, per cinque minuti. Chiedine un altro.";

/** What Better Auth puts in `?error=` when a magic link or a Google sign-in fails, in Italian. */
export const SIGN_IN_ERRORS: Record<string, string> = {
  INVALID_TOKEN: LINK_SPENT_ERROR,
  EXPIRED_TOKEN: LINK_SPENT_ERROR,
  new_user_signup_disabled: INVITE_ONLY_ERROR,
  signup_disabled: INVITE_ONLY_ERROR,
  SIGNUP_NOT_ALLOWED: INVITE_ONLY_ERROR,
  unable_to_create_user: INVITE_ONLY_ERROR,
  access_denied: "Accesso con Google annullato. Puoi riprovare quando vuoi.",
};
export const UNCONFIGURED_MESSAGE = "Gli account non sono configurati su questo server.";

export function signInErrorMessage(code: string | null | undefined): string | null {
  if (!code) return null;
  return SIGN_IN_ERRORS[code] ?? GENERIC_SIGN_IN_ERROR;
}

function messageForClientError(error: { status?: number; code?: string } | null | undefined): string {
  if (error?.code === "SIGNUP_NOT_ALLOWED" || error?.status === 403) return INVITE_ONLY_ERROR;
  if (error?.status === 429) return TOO_MANY_REQUESTS_ERROR;
  return GENERIC_SIGN_IN_ERROR;
}

type Phase = { kind: "form"; error: string | null } | { kind: "sent"; email: string };

interface LoginFormProps {
  /** The page to come back to after signing in (lib/api.ts `loginUrl`); reduced to a same-origin path. */
  returnTo: string | null;
  /** Better Auth's `?error=` after a failed link or Google callback. */
  errorCode: string | null;
  /** False when the server has no accounts database: the form is shown disabled, with the reason. */
  configured: boolean;
  googleEnabled: boolean;
}

/**
 * Sign in: an email for the magic link, or Google. No passwords (PRODUCT.md). The copy says what
 * happens next and how long the link lasts; the "sent" state keeps the address on screen so a typo
 * is caught, with a way back to the form. Errors answer the user's own action, so they are alerts.
 */
export function LoginForm({ returnTo, errorCode, configured, googleEnabled }: LoginFormProps) {
  const [phase, setPhase] = useState<Phase>({ kind: "form", error: signInErrorMessage(errorCode) });
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState<"link" | "google" | null>(null);

  const callbackURL = () => safeReturnTo(returnTo, window.location.origin);

  async function sendLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const address = email.trim();
    if (!address) return;
    setBusy("link");
    const { error } = await authClient.signIn.magicLink({
      email: address,
      callbackURL: callbackURL(),
      errorCallbackURL: ROUTES.login,
    });
    setBusy(null);
    if (error) {
      setPhase({ kind: "form", error: messageForClientError(error) });
      return;
    }
    setPhase({ kind: "sent", email: address });
  }

  async function withGoogle() {
    setBusy("google");
    const { error } = await authClient.signIn.social({
      provider: "google",
      callbackURL: callbackURL(),
      errorCallbackURL: ROUTES.login,
    });
    if (error) {
      setBusy(null);
      setPhase({ kind: "form", error: messageForClientError(error) });
    }
    // On success the browser is leaving for Google: the button stays busy until then.
  }

  if (phase.kind === "sent") {
    return (
      <section aria-labelledby="login-sent" className="rounded-md border border-rule bg-surface px-4 py-3.5 lg:px-5 lg:py-4">
        <h2 id="login-sent" className="flex items-center gap-2 font-cond text-heading font-semibold text-ink">
          <Icon name="check-circle" size={20} />
          Controlla la posta
        </h2>
        <p className="mt-2 max-w-prose text-small text-ink">
          Abbiamo mandato un link a <strong className="font-semibold">{phase.email}</strong>. Vale cinque minuti e
          funziona una volta sola: aprilo da questo dispositivo.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            variant="quiet"
            size="sm"
            icon="arrow-left"
            onClick={() => setPhase({ kind: "form", error: null })}
          >
            Usa un altro indirizzo
          </Button>
        </div>
      </section>
    );
  }

  return (
    <div className="grid gap-5">
      {!configured ? (
        <Notice tone="warning" title={UNCONFIGURED_MESSAGE}>
          Chi gestisce questo server deve impostare il database e la posta degli account (web/.env.example).
        </Notice>
      ) : null}
      {phase.error ? (
        <Notice tone="error" role="alert" title={phase.error} />
      ) : null}
      <form onSubmit={sendLink} noValidate={false} className="grid gap-4">
        <Field label="Email" hint="Ti mandiamo un link per entrare, senza password.">
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
              disabled={!configured || busy !== null}
            />
          )}
        </Field>
        <Button type="submit" variant="primary" icon="arrow-right" busy={busy === "link"} disabled={!configured || busy !== null}>
          {busy === "link" ? "Invio il link…" : "Inviami il link"}
        </Button>
      </form>
      {googleEnabled ? (
        <>
          <p className="flex items-center gap-3 text-meta text-ink-2" aria-hidden="true">
            <span className="h-px flex-1 bg-rule" />
            oppure
            <span className="h-px flex-1 bg-rule" />
          </p>
          <Button variant="secondary" onClick={withGoogle} busy={busy === "google"} disabled={!configured || busy !== null}>
            {busy === "google" ? "Vado su Google…" : "Continua con Google"}
          </Button>
        </>
      ) : null}
      <p className="text-meta text-ink-2">L&apos;accesso è su invito: entra solo chi è stato abilitato.</p>
    </div>
  );
}
