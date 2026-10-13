"""Send an eval run to the eval history (Atlas, "Valutazioni"): POST <url>/evals/runs.

    cd backend
    uv run python ../evals/upload.py ../evals/results/2026-10-13-1a2b3c4d5e6f.json \\
        --comparison comparison.json --workflow-run-url https://github.com/o/r/actions/runs/1

The URL and the token come from the environment, never from the command line (a command line
shows up in process lists and logs): EVALS_INGEST_URL (the backend's origin, for example
https://atlas.api.bellittim.com) and EVALS_INGEST_TOKEN (the bearer token the backend
checks against its own EVALS_INGEST_TOKEN setting). `--url` overrides the first, for local use.

The body is {"results": <evals/run.py JSON>, "comparison": <evals/compare.py --json or null>,
"workflow_run_url": <string or null>}. The backend is idempotent (run key = profile + git sha +
started_at): posting the same run again updates its comparison and workflow run URL, so a retry
is always safe.

CI must not fail because the history is down: any failure (no configuration, an unreadable
file, a refused or unreachable server) prints a GitHub `::warning::` and exits 0. `--strict`
turns those into a non-zero exit. Connection errors, timeouts, 429 and 5xx are retried (3
retries, growing pauses); any other 4xx is final. The token is never printed: not in a log
line, not in an error, not in the server's answer echoed back.

Exit codes: 0 sent, or skipped/failed without --strict; 1 failed with --strict; 2 usage error
(unreadable or invalid arguments are reported by argparse).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

URL_ENV = "EVALS_INGEST_URL"
TOKEN_ENV = "EVALS_INGEST_TOKEN"
ENDPOINT = "/evals/runs"
MAX_BODY_BYTES = 5 * 1024 * 1024
"""The backend rejects bigger bodies (413); fail here with a clear message instead."""
DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT = 30.0
BACKOFF_SECONDS = 2.0
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
RESULTS_KIND = "trip-planner-eval-results"

EXIT_OK = 0
EXIT_FAILED = 1


class UploadError(Exception):
    """The upload cannot be done or was refused: a warning in CI, exit 1 with --strict."""


class SkippedError(Exception):
    """Nothing to do (no URL or token configured): a notice, never an error."""


# --- building the request -----------------------------------------------------------------------


def read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UploadError(f"cannot read the {what} {path}: {error}") from error


def build_payload(
    results_path: Path, comparison_path: Path | None, workflow_run_url: str | None
) -> dict[str, Any]:
    results = read_json(results_path, "results file")
    if not isinstance(results, dict) or results.get("kind") != RESULTS_KIND:
        raise UploadError(f"{results_path} is not an eval results file")
    comparison: Any = None
    # A missing comparison file is not an error: compare.py writes it only when it ran.
    if comparison_path is not None and comparison_path.exists():
        comparison = read_json(comparison_path, "comparison file")
        if not isinstance(comparison, dict):
            raise UploadError(f"{comparison_path} is not a comparison JSON object")
    return {
        "results": results,
        "comparison": comparison,
        "workflow_run_url": workflow_run_url or None,
    }


def endpoint_url(base_url: str) -> str:
    """<base>/evals/runs; https only (a bearer token in clear text is refused), except for a
    local backend."""
    parts = urlsplit(base_url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise UploadError(f"{URL_ENV} is not an http(s) URL")
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise UploadError(f"{URL_ENV} must be https (the bearer token must not travel in clear)")
    if parts.username or parts.password:
        raise UploadError(f"{URL_ENV} must not carry credentials")
    return base_url.strip().rstrip("/") + ENDPOINT


def scrub(text: str, token: str) -> str:
    """`text` without the token, however it got into it."""
    return text.replace(token, "***") if token else text


# --- sending ------------------------------------------------------------------------------------


def post_with_retries(
    client: httpx.Client,
    url: str,
    body: bytes,
    token: str,
    *,
    retries: int,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> httpx.Response:
    """POST `body`; returns the final response (2xx or a non-retried error status). Raises
    UploadError once the retries are used up on connection errors or retryable statuses."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    last = "no attempt"
    for attempt in range(retries + 1):
        if attempt:
            pause = BACKOFF_SECONDS * 2 ** (attempt - 1)
            log(f"retry {attempt}/{retries} in {pause:g}s ({last})")
            sleep(pause)
        try:
            response = client.post(url, content=body, headers=headers)
        except httpx.HTTPError as error:
            # httpx messages never contain request headers, but scrub anyway.
            last = scrub(f"{type(error).__name__}: {error}", token)
            continue
        if response.status_code in RETRY_STATUSES:
            last = f"HTTP {response.status_code}"
            continue
        return response
    raise UploadError(f"the eval history did not answer after {retries + 1} attempts ({last})")


def response_detail(response: httpx.Response, token: str) -> str:
    """The Italian message of the backend's error envelope, else a short slice of the body."""
    try:
        payload = response.json()
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            code, message = detail.get("code"), detail.get("message")
            return scrub(f"{code}: {message}" if message else str(code), token)[:300]
    except ValueError:
        pass
    return scrub(response.text.strip().replace("\n", " "), token)[:200]


def upload(
    results_path: Path,
    *,
    comparison_path: Path | None = None,
    workflow_run_url: str | None = None,
    url: str | None = None,
    token: str | None = None,
    retries: int = DEFAULT_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] | None = None,
) -> str | None:
    """Send the run. Returns the stored run's id (None when the server did not say). Raises
    SkippedError when URL or token are missing, UploadError on any failure. `transport` is for
    tests."""
    emit = log or (lambda message: print(message, flush=True))
    base_url = (url or "").strip()
    secret = (token or "").strip()
    if not base_url or not secret:
        missing = [name for name, value in ((URL_ENV, base_url), (TOKEN_ENV, secret)) if not value]
        raise SkippedError(f"{' and '.join(missing)} not set")
    target = endpoint_url(base_url)
    payload = build_payload(results_path, comparison_path, workflow_run_url)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_BODY_BYTES:
        raise UploadError(
            f"the payload is {len(body) / 1024 / 1024:.1f} MB, over the "
            f"{MAX_BODY_BYTES // 1024 // 1024} MB the eval history accepts"
        )
    with httpx.Client(timeout=timeout, transport=transport, follow_redirects=False) as client:
        response = post_with_retries(
            client, target, body, secret, retries=retries, sleep=sleep, log=emit
        )
    if response.status_code not in {200, 201}:
        hint = {
            401: " (wrong EVALS_INGEST_TOKEN)",
            404: " (ingest disabled on the backend, or a wrong EVALS_INGEST_URL)",
        }.get(response.status_code, "")
        raise UploadError(
            f"the eval history answered HTTP {response.status_code}{hint}: "
            f"{response_detail(response, secret)}"
        )
    try:
        data = response.json()
    except ValueError:
        data = None
    run_id = data.get("id") if isinstance(data, Mapping) else None
    verb = "created" if response.status_code == 201 else "updated (already known)"
    emit(f"Eval run {verb} in the history" + (f": {run_id}" if run_id else ""))
    return str(run_id) if run_id else None


# --- command line -------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evals/upload.py",
        description=f"POST an eval run to the eval history ({URL_ENV}, {TOKEN_ENV} in the "
        "environment).",
    )
    parser.add_argument("results", type=Path, help="evals/results/<date>-<sha>.json")
    parser.add_argument(
        "--comparison", type=Path, default=None, help="compare.py --json output (optional)"
    )
    parser.add_argument("--workflow-run-url", default=None, help="the CI run that produced it")
    parser.add_argument("--url", default=None, help=f"overrides {URL_ENV} (local use)")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 on any failure instead of a warning"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    token = env.get(TOKEN_ENV, "")
    try:
        upload(
            args.results,
            comparison_path=args.comparison,
            workflow_run_url=args.workflow_run_url,
            url=args.url or env.get(URL_ENV, ""),
            token=token,
            retries=max(0, args.retries),
            timeout=args.timeout,
            transport=transport,
            sleep=sleep,
        )
    except SkippedError as skipped:
        message = f"eval history upload skipped: {skipped}"
        if args.strict:
            print(f"::error::{message}", file=sys.stderr)
            return EXIT_FAILED
        print(f"::notice::{message}")
        return EXIT_OK
    except UploadError as error:
        message = scrub(str(error), token)
        if args.strict:
            print(f"::error::eval history upload failed: {message}", file=sys.stderr)
            return EXIT_FAILED
        print(f"::warning::eval history upload failed (the job goes on): {message}")
        return EXIT_OK
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
