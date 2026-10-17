/**
 * Who may create an account (lib/auth.ts, the `user.create.before` hook and the magic-link
 * request hook). Pure, so it is tested without a database.
 *
 * `AUTH_ALLOWED_EMAILS` is a comma list of addresses, compared trimmed and lower-cased. Empty
 * means nobody can sign up (existing accounts keep signing in: the list gates creation only);
 * `*` means everybody (the public launch). Phase 1's later PR replaces the variable with an
 * allowlist table and a waitlist, behind the same `isSignupAllowed`.
 */

export type AllowList = { readonly everyone: true } | { readonly everyone: false; readonly emails: ReadonlySet<string> };

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function parseAllowedEmails(raw: string | undefined): AllowList {
  const entries = (raw ?? "")
    .split(",")
    .map((entry) => normalizeEmail(entry))
    .filter((entry) => entry.length > 0);
  if (entries.includes("*")) return { everyone: true };
  return { everyone: false, emails: new Set(entries) };
}

export function isSignupAllowed(email: string | null | undefined, list: AllowList): boolean {
  if (!email) return false;
  const normalized = normalizeEmail(email);
  if (!normalized.includes("@")) return false;
  return list.everyone || list.emails.has(normalized);
}
