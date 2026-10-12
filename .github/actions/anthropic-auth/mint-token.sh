#!/usr/bin/env bash
# Mints a GitHub OIDC identity token for Anthropic Workload Identity Federation.
#
#   mint-token.sh once   mint one token, check it, write it atomically to the token file
#   mint-token.sh loop   rewrite the token file every INTERVAL seconds until the job ends
#
# Called by action.yml (docs/deploy.md, "Anthropic Workload Identity Federation"). The token is
# a bearer credential for a few minutes: it goes only into the 0600 file ANTHROPIC_OIDC_FILE,
# never to stdout, stderr, the job summary or $GITHUB_ENV. Only claims that identify the job
# (sub, aud, lifetime) are printed, to make a federation-rule mismatch easy to diagnose.
set -euo pipefail
umask 077

mode="${1:-once}"
: "${ANTHROPIC_OIDC_FILE:?ANTHROPIC_OIDC_FILE is not set}"
: "${ANTHROPIC_OIDC_AUDIENCE:?ANTHROPIC_OIDC_AUDIENCE is not set}"

if [ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ] || [ -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]; then
  echo "::error::GitHub did not offer an OIDC token to this job. Add 'permissions: id-token: write' to the job that uses this action (and to the calling job when it is a reusable workflow). Pull requests from forks never get one."
  exit 1
fi

# One request to GitHub's OIDC endpoint; prints the JWT on stdout.
fetch_token() {
  local audience url response
  audience="$(jq -rn --arg a "$ANTHROPIC_OIDC_AUDIENCE" '$a | @uri')"
  url="${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=${audience}"
  response="$(curl --fail --silent --show-error --location --retry 3 --retry-delay 2 \
    --max-time 20 --proto '=https' --tlsv1.2 \
    --header "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
    --header "Accept: application/json; api-version=2.0" \
    "$url")" || return 1
  printf '%s' "$response" | jq -er '.value'
}

# Writes the token with mode 0600 through a rename, so a reader (the SDK re-reads the file on
# every refresh) never sees a half-written file.
write_token() {
  local token="$1" dir tmp
  dir="$(dirname "$ANTHROPIC_OIDC_FILE")"
  tmp="$(mktemp "$dir/.token.XXXXXX")"
  chmod 0600 "$tmp"
  printf '%s' "$token" > "$tmp"
  mv -f "$tmp" "$ANTHROPIC_OIDC_FILE"
}

# The JWT payload (second segment), decoded; empty when it cannot be decoded.
payload_of() {
  local segment pad
  segment="$(printf '%s' "$1" | cut -d. -f2 | tr '_-' '/+')"
  pad=$(( ${#segment} % 4 ))
  case "$pad" in
    2) segment="${segment}==" ;;
    3) segment="${segment}=" ;;
  esac
  printf '%s' "$segment" | base64 -d 2>/dev/null || true
}

case "$mode" in
  once)
    token="$(fetch_token)" || {
      echo "::error::could not get an OIDC token from GitHub (ACTIONS_ID_TOKEN_REQUEST_URL answered with an error)"
      exit 1
    }
    if ! [[ "$token" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]]; then
      echo "::error::GitHub's answer is not a JWT"
      exit 1
    fi
    echo "::add-mask::${token}"
    write_token "$token"
    claims="$(payload_of "$token")"
    if [ -n "$claims" ]; then
      echo "OIDC token ready: $(printf '%s' "$claims" | jq -r '"sub=\(.sub) aud=\(.aud) valid_for=\((.exp - .iat))s"' 2>/dev/null || echo 'claims unreadable')"
    fi
    ;;
  loop)
    interval="${ANTHROPIC_OIDC_REFRESH_SECONDS:?ANTHROPIC_OIDC_REFRESH_SECONDS is not set}"
    # A GitHub job lasts 6 hours at most (35 days on self-hosted runners; the runner also kills
    # this process when the job ends), so stop on our own after 7 hours.
    deadline=$(( $(date +%s) + 7 * 3600 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
      sleep "$interval"
      if token="$(fetch_token)" && [[ "$token" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]]; then
        write_token "$token"
        echo "$(date -u +%FT%TZ) refreshed"
      else
        echo "$(date -u +%FT%TZ) refresh failed; the token file keeps the previous token"
      fi
    done
    ;;
  *)
    echo "usage: mint-token.sh once|loop" >&2
    exit 2
    ;;
esac
