"""evals/upload.py: the POST to the eval history, retries, warnings instead of failures, and a
token that never reaches the output. Offline: httpx.MockTransport, plus one local socket server."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest

import upload

Json = dict[str, Any]

TOKEN = "s3cr3t-ingest-token-value"
URL = "https://pianifica.example.test"
RUN_URL = "https://github.com/o/r/actions/runs/42"

RESULTS: Json = {
    "kind": upload.RESULTS_KIND,
    "format": 1,
    "profile": "development",
    "git_sha": "1a2b3c4d5e6f7a8b",
    "started_at": "2026-10-13T08:00:00+02:00",
    "requests": [{"id": "a"}],
    "summary": {"plans": 1},
}
COMPARISON: Json = {"kind": "trip-planner-eval-comparison", "format": 1, "status": "passed"}


class Recorder:
    """A MockTransport handler that answers from a script and keeps the requests."""

    def __init__(self, *answers: httpx.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def write(path: Path, document: Any) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    return write(tmp_path / "results.json", RESULTS), write(
        tmp_path / "comparison.json", COMPARISON
    )


def run_main(
    args: list[str],
    recorder: Recorder,
    *,
    environ: dict[str, str] | None = None,
    sleeps: list[float] | None = None,
) -> int:
    env = {upload.URL_ENV: URL, upload.TOKEN_ENV: TOKEN} if environ is None else environ
    pauses = sleeps if sleeps is not None else []
    return upload.main(args, environ=env, transport=recorder.transport, sleep=pauses.append)


def test_posts_results_comparison_and_run_url_with_the_bearer_token(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    results, comparison = files
    recorder = Recorder(httpx.Response(201, json={"id": "0b1c"}))
    code = run_main(
        [str(results), "--comparison", str(comparison), "--workflow-run-url", RUN_URL], recorder
    )
    assert code == 0
    (request,) = recorder.requests
    assert request.method == "POST"
    assert str(request.url) == f"{URL}/evals/runs"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "results": RESULTS,
        "comparison": COMPARISON,
        "workflow_run_url": RUN_URL,
    }
    out = capsys.readouterr()
    assert "created" in out.out
    assert "0b1c" in out.out
    assert TOKEN not in out.out + out.err


def test_comparison_and_run_url_are_optional(files: tuple[Path, Path]) -> None:
    results, _ = files
    recorder = Recorder(httpx.Response(201, json={"id": "x"}))
    assert run_main([str(results)], recorder) == 0
    assert json.loads(recorder.requests[0].content) == {
        "results": RESULTS,
        "comparison": None,
        "workflow_run_url": None,
    }


def test_a_missing_comparison_file_is_sent_as_null(
    files: tuple[Path, Path], tmp_path: Path
) -> None:
    """compare.py writes its JSON only when it ran: its absence must not lose the run."""
    results, _ = files
    recorder = Recorder(httpx.Response(201, json={"id": "x"}))
    assert run_main([str(results), "--comparison", str(tmp_path / "none.json")], recorder) == 0
    assert json.loads(recorder.requests[0].content)["comparison"] is None


def test_an_existing_run_answers_200_and_is_reported_as_updated(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    results, _ = files
    assert run_main([str(results)], Recorder(httpx.Response(200, json={"id": "x"}))) == 0
    assert "updated" in capsys.readouterr().out


def test_trailing_slash_in_the_url_is_fine(files: tuple[Path, Path]) -> None:
    results, _ = files
    recorder = Recorder(httpx.Response(201, json={"id": "x"}))
    run_main([str(results)], recorder, environ={upload.URL_ENV: URL + "/", upload.TOKEN_ENV: TOKEN})
    assert str(recorder.requests[0].url) == f"{URL}/evals/runs"


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {upload.URL_ENV: URL},
        {upload.TOKEN_ENV: TOKEN},
        {upload.URL_ENV: " ", upload.TOKEN_ENV: " "},
    ],
)
def test_without_url_or_token_it_skips_with_a_notice(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str], environ: dict[str, str]
) -> None:
    recorder = Recorder(httpx.Response(201))
    assert run_main([str(files[0])], recorder, environ=environ) == 0
    assert recorder.requests == []
    out = capsys.readouterr().out
    assert out.startswith("::notice::eval history upload skipped")
    assert TOKEN not in out


def test_strict_makes_a_skip_an_error(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main([str(files[0]), "--strict"], Recorder(httpx.Response(201)), environ={}) == 1
    assert "::error::" in capsys.readouterr().err


def test_retries_connection_errors_and_5xx_with_growing_pauses(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder(
        httpx.ConnectError("refused"),
        httpx.Response(503),
        httpx.Response(502),
        httpx.Response(201, json={"id": "late"}),
    )
    sleeps: list[float] = []
    assert run_main([str(files[0])], recorder, sleeps=sleeps) == 0
    assert len(recorder.requests) == 4
    assert sleeps == [2.0, 4.0, 8.0]
    assert "late" in capsys.readouterr().out


def test_gives_up_after_three_retries_with_a_warning_and_exit_zero(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder(httpx.Response(500))
    sleeps: list[float] = []
    assert run_main([str(files[0])], recorder, sleeps=sleeps) == 0
    assert len(recorder.requests) == 4
    assert len(sleeps) == 3
    out = capsys.readouterr()
    assert out.out.count("::warning::eval history upload failed") == 1
    assert "4 attempts" in out.out
    assert TOKEN not in out.out + out.err


def test_strict_fails_after_the_retries(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder(httpx.ReadTimeout("slow"))
    assert run_main([str(files[0]), "--strict"], recorder) == 1
    assert len(recorder.requests) == 4
    assert "::error::eval history upload failed" in capsys.readouterr().err


def test_retries_option(files: tuple[Path, Path]) -> None:
    recorder = Recorder(httpx.Response(500))
    assert run_main([str(files[0]), "--retries", "1"], recorder) == 0
    assert len(recorder.requests) == 2
    recorder = Recorder(httpx.Response(500))
    assert run_main([str(files[0]), "--retries", "0"], recorder) == 0
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    ("status", "body", "hint"),
    [
        (401, {"detail": {"code": "invalid_ingest_token", "message": "Token non valido"}}, "wrong"),
        (404, {"detail": {"code": "evals_ingest_disabled", "message": "Disattivato"}}, "disabled"),
        (413, {"detail": {"code": "too_large", "message": "Troppo grande"}}, ""),
        (422, {"detail": {"code": "invalid_eval_results", "message": "Formato sconosciuto"}}, ""),
    ],
)
def test_client_errors_are_final_and_explained(
    files: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: Json,
    hint: str,
) -> None:
    recorder = Recorder(httpx.Response(status, json=body))
    sleeps: list[float] = []
    assert run_main([str(files[0])], recorder, sleeps=sleeps) == 0
    assert len(recorder.requests) == 1
    assert sleeps == []
    out = capsys.readouterr().out
    assert f"HTTP {status}" in out
    assert body["detail"]["code"] in out
    assert hint in out
    assert run_main([str(files[0]), "--strict"], Recorder(httpx.Response(status, json=body))) == 1


def test_the_token_is_scrubbed_from_what_the_server_echoes(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    echo = httpx.Response(400, text=f"bad header Authorization: Bearer {TOKEN}")
    assert run_main([str(files[0])], Recorder(echo)) == 0
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert "Bearer ***" in out.out
    envelope = httpx.Response(400, json={"detail": {"code": "x", "message": f"got {TOKEN}"}})
    assert run_main([str(files[0])], Recorder(envelope)) == 0
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_the_token_is_scrubbed_from_connection_errors(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder(httpx.ConnectError(f"cannot connect with {TOKEN}"))
    assert run_main([str(files[0])], recorder) == 0
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_a_plain_http_url_is_refused_except_for_localhost(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder(httpx.Response(201, json={"id": "x"}))
    http_env = {upload.URL_ENV: "http://example.test", upload.TOKEN_ENV: TOKEN}
    assert run_main([str(files[0]), "--strict"], recorder, environ=http_env) == 1
    assert recorder.requests == []
    assert "must be https" in capsys.readouterr().err
    local_env = {upload.URL_ENV: "http://localhost:8810", upload.TOKEN_ENV: TOKEN}
    assert run_main([str(files[0])], recorder, environ=local_env) == 0
    assert str(recorder.requests[0].url) == "http://localhost:8810/evals/runs"


@pytest.mark.parametrize("bad", ["ftp://x.test", "not a url", "https://user:pw@x.test"])
def test_invalid_urls_are_refused(files: tuple[Path, Path], bad: str) -> None:
    recorder = Recorder(httpx.Response(201))
    env = {upload.URL_ENV: bad, upload.TOKEN_ENV: TOKEN}
    assert run_main([str(files[0]), "--strict"], recorder, environ=env) == 1
    assert recorder.requests == []


def test_unreadable_or_foreign_results_are_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder(httpx.Response(201))
    assert run_main([str(tmp_path / "missing.json")], recorder) == 0
    assert "cannot read the results file" in capsys.readouterr().out
    foreign = write(tmp_path / "foreign.json", {"kind": "something-else"})
    assert run_main([str(foreign), "--strict"], recorder) == 1
    assert "not an eval results file" in capsys.readouterr().err
    assert recorder.requests == []


def test_a_broken_comparison_file_is_reported(files: tuple[Path, Path], tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    recorder = Recorder(httpx.Response(201))
    assert run_main([str(files[0]), "--comparison", str(bad), "--strict"], recorder) == 1
    assert recorder.requests == []


def test_a_payload_over_5_mb_is_not_sent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    big = write(tmp_path / "big.json", {**RESULTS, "blob": "x" * (upload.MAX_BODY_BYTES + 1)})
    recorder = Recorder(httpx.Response(201))
    assert run_main([str(big), "--strict"], recorder) == 1
    assert recorder.requests == []
    assert "5 MB" in capsys.readouterr().err


def test_redirects_are_not_followed_so_the_token_stays_on_the_configured_host(
    files: tuple[Path, Path],
) -> None:
    recorder = Recorder(httpx.Response(307, headers={"location": "https://evil.test/evals/runs"}))
    assert run_main([str(files[0]), "--strict"], recorder) == 1
    assert len(recorder.requests) == 1


def test_the_compare_json_feeds_the_upload(tmp_path: Path) -> None:
    """compare.py --json then upload.py: the two scripts agree on the document."""
    import compare

    run_file = write(tmp_path / "run.json", {**RESULTS, "requests": []})
    out = tmp_path / "comparison.json"
    compare.main([str(run_file), "--baseline", str(tmp_path / "none.json"), "--json", str(out)])
    recorder = Recorder(httpx.Response(201, json={"id": "x"}))
    assert run_main([str(run_file), "--comparison", str(out)], recorder) == 0
    sent = json.loads(recorder.requests[0].content)
    assert sent["comparison"]["kind"] == compare.COMPARISON_KIND
    assert sent["comparison"]["status"] == "blocked"  # no requests: the run blocks


# --- a real socket ------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list[tuple[str, str, bytes]]] = []
    statuses: ClassVar[list[int]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        type(self).seen.append((self.path, self.headers.get("authorization", ""), body))
        status = type(self).statuses.pop(0) if type(self).statuses else 201
        payload = json.dumps({"id": "from-server"}).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.seen = []
    _Handler.statuses = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_against_a_local_http_server_with_a_retry(
    files: tuple[Path, Path], server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _Handler.statuses = [503, 201]
    env = {upload.URL_ENV: server, upload.TOKEN_ENV: TOKEN}
    code = upload.main(
        [str(files[0]), "--comparison", str(files[1]), "--workflow-run-url", RUN_URL],
        environ=env,
        sleep=lambda _: None,
    )
    assert code == 0
    assert [(path, auth) for path, auth, _ in _Handler.seen] == [
        ("/evals/runs", f"Bearer {TOKEN}")
    ] * 2
    assert json.loads(_Handler.seen[-1][2])["workflow_run_url"] == RUN_URL
    out = capsys.readouterr()
    assert "from-server" in out.out
    assert TOKEN not in out.out + out.err
