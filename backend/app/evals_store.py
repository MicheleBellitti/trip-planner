"""Eval history: store the results of `evals/run.py` and read them back for the web app.

The CI eval job (`.github/workflows/evals.yml`) uploads each run with `POST /evals/runs`, and
`python -m app.cli import-evals` loads a results file by hand; both call `store_eval_run`. The
web app lists the runs (`GET /evals/runs`) and opens one (`GET /evals/runs/{id}`). Routes:
app/routes.py; the table: `db.EvalRunRecord`; the decision: docs/backend-interfaces.md.

Input contract (shared with the CI and web sides):

- `results`: the JSON `evals/run.py` writes (`kind` "trip-planner-eval-results", `format` 1,
  `started_at`, `profile`, `git_sha`, `aborted`, `requests[]`, `summary`, ...). Validated loosely:
  an unknown kind or format, a missing or naive `started_at`, an empty profile or `requests`
  that is not a list of objects are refused; every other key is stored untouched.
- `comparison`: optional, what `evals/compare.py --json` writes (`kind`
  "trip-planner-eval-comparison", `format` 1, `status` passed | blocked | report_only).
- `workflow_run_url`: optional http(s) link to the CI run.

A run is identified by `run_key` = profile, git sha and start time (`run_key`): uploading it
again (a CI retry) stores nothing new and only fills in the comparison and the workflow link
that were missing or changed. The list fields are computed once at ingest (`summarize_run`) and
kept in `eval_runs.summary`, so listing never reads the stored documents.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, cast

import structlog
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    ValidationError,
    field_validator,
)
from sqlalchemy import func, literal, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import EvalRunRecord, JsonObject

RESULTS_KIND = "trip-planner-eval-results"
RESULTS_FORMAT = 1
COMPARISON_KIND = "trip-planner-eval-comparison"
COMPARISON_FORMAT = 1

MAX_INGEST_BYTES = 5 * 1024 * 1024
"""Largest `POST /evals/runs` body (and `import-evals` file): the six reference requests with
their plans and Trips are about 40 KB today, so this is generous."""
MAX_URL_LENGTH = 2000
"""TripTracker's URL cap (LIMITE), reused for the workflow run link."""
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
MAX_LIST_OFFSET = 1_000_000
MAX_BLOCKING_FINDINGS = 3
"""How many of a comparison's blocking findings the list keeps: enough to say why a run stopped."""
MAX_FINDING_MESSAGE = 500
"""Far beyond any history, and well inside Postgres's bigint."""

CompareStatus = Literal["passed", "blocked", "report_only"]
COMPARE_STATUSES: tuple[CompareStatus, ...] = ("passed", "blocked", "report_only")

log = structlog.get_logger(__name__)


class InvalidEvalResultsError(ValueError):
    """The uploaded document is not an eval run `store_eval_run` can keep. `errors` are
    `{"field", "reason"}` objects (reasons are English and never echo the input)."""

    def __init__(self, errors: Sequence[Mapping[str, str]]) -> None:
        self.errors: list[dict[str, str]] = [dict(error) for error in errors]
        super().__init__("; ".join(f"{e['field']}: {e['reason']}" for e in self.errors))


def _invalid(field: str, reason: str) -> InvalidEvalResultsError:
    return InvalidEvalResultsError([{"field": field, "reason": reason}])


# --- models -------------------------------------------------------------------------------------


class BlockingFinding(BaseModel):
    """A reason the gate stopped a run, kept in the summary so the list can say it."""

    rule: str = Field(description="compare.py's rule: deterministic checks, judge criteria, ...")
    message: str = Field(description="compare.py's own sentence (English).")
    request_id: str | None = Field(default=None, description="The request it is about, if any.")
    request_title: str | None = Field(
        default=None, description="That request's title in the results, when it has one."
    )


class RunMetrics(BaseModel):
    """The list fields computed from the documents (`eval_runs.summary`). The last three were
    added later: a summary stored before them reads as no baseline and no findings."""

    requests_total: int = Field(description="Requests of the run.")
    requests_accepted: int = Field(description="Requests whose plan ended `ready`.")
    checks_passed: int = Field(description="Requests with `checks_passed` true.")
    blocking_failures_count: int = Field(description="Blocking check failures, all requests.")
    total_cost_cents: int = Field(description="Managed Agents list cost of the run, US cents.")
    web_search_requests: int = Field(description="Web searches of the run.")
    judge_mean: float | None = Field(
        default=None, description="Mean of every criterion score of every request; None if none."
    )
    compare_status: CompareStatus | None = Field(
        default=None, description="The comparison's verdict; None when the run was not compared."
    )
    reference_judge_mean: float | None = Field(
        default=None,
        description="The baseline's judge mean (the mean of its criteria means); None without one.",
    )
    reference_cost_per_plan_cents: float | None = Field(
        default=None, description="The baseline's mean cost per plan, US cents; None without one."
    )
    blocking_findings: list[BlockingFinding] = Field(
        default_factory=list[BlockingFinding],
        description=f"The comparison's first {MAX_BLOCKING_FINDINGS} findings that block it.",
    )


class EvalRunSummary(RunMetrics):
    """One row of the history list."""

    id: uuid.UUID
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    git_sha: str | None = None
    profile: str
    aborted: bool
    workflow_run_url: str | None = Field(
        default=None, description="The CI run that produced it, when uploaded by CI."
    )


class EvalRunDetail(EvalRunSummary):
    """A run with its stored documents, and its neighbours in the list's order."""

    results: dict[str, Any] = Field(description="The JSON written by evals/run.py, as uploaded.")
    comparison: dict[str, Any] | None = Field(
        default=None, description="evals/compare.py --json, when the run was compared."
    )
    previous_run: EvalRunSummary | None = Field(
        default=None, description="The run just before it (older), as a list row; None if first."
    )
    next_run: EvalRunSummary | None = Field(
        default=None, description="The run just after it (newer), as a list row; None if newest."
    )


class EvalRunListResponse(BaseModel):
    runs: list[EvalRunSummary] = Field(description="Newest first.")
    total: int = Field(description="Runs in the history, for the pages of the list.")


class EvalRunCreated(BaseModel):
    """Answer of POST /evals/runs: 201 for a new run, 200 when it already existed."""

    id: uuid.UUID


class IngestBody(BaseModel):
    """Body of POST /evals/runs."""

    model_config = ConfigDict(extra="ignore")

    results: dict[str, Any] = Field(description="The JSON written by evals/run.py.")
    comparison: dict[str, Any] | None = Field(
        default=None, description="evals/compare.py --json, or null."
    )
    workflow_run_url: str | None = Field(default=None, description="CI run link, or null.")


class ResultsHead(BaseModel):
    """The few keys of a results document the store depends on."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["trip-planner-eval-results"]
    format: Literal[1]
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    git_sha: Annotated[str, StringConstraints(max_length=64)] | None = None
    profile: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    aborted: StrictBool = False
    requests: list[dict[str, Any]]

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def _timestamps_are_text(cls, value: object) -> object:
        # Pydantic would also take a unix timestamp; the file always has ISO 8601 text.
        if value is not None and not isinstance(value, str):
            msg = "must be an ISO 8601 string with a UTC offset"
            raise ValueError(msg)
        return value

    @field_validator("git_sha", mode="before")
    @classmethod
    def _blank_sha_is_missing(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value


class _ComparisonHead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["trip-planner-eval-comparison"] = COMPARISON_KIND
    format: Literal[1] = COMPARISON_FORMAT


@dataclass(frozen=True, slots=True)
class StoredEvalRun:
    id: uuid.UUID
    created: bool
    """False when the run was already stored (an idempotent repeat)."""


# --- validation ---------------------------------------------------------------------------------


def parse_json(raw: bytes | str) -> Any:
    """`json.loads` that refuses NaN and Infinity (Postgres `jsonb` cannot hold them) and
    reports any failure as `InvalidEvalResultsError`."""

    def refuse_constant(name: str) -> Any:
        msg = f"{name} is not valid JSON"
        raise ValueError(msg)

    try:
        return json.loads(raw, parse_constant=refuse_constant)
    except RecursionError:
        raise _invalid("(body)", "nested too deeply") from None
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        raise _invalid("(body)", f"not valid JSON ({type(exc).__name__})") from None


def clean_json(value: Any) -> Any:
    """A copy of a parsed JSON value with U+0000 removed from every string and key (Postgres
    `jsonb` rejects it, CLAUDE.md "Database and migrations"); a non-finite float is refused."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid("(body)", "contains a number that is not finite")
        return value
    if isinstance(value, list):
        return [clean_json(item) for item in cast(list[Any], value)]
    if isinstance(value, dict):
        return {
            clean_json(key): clean_json(item) for key, item in cast(dict[Any, Any], value).items()
        }
    return value


def _validation_errors(prefix: str, exc: ValidationError) -> InvalidEvalResultsError:
    errors: list[dict[str, str]] = []
    for error in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in (prefix, *error["loc"]) if part != "")
        errors.append({"field": location or "(body)", "reason": error["msg"]})
    return InvalidEvalResultsError(errors)


def validate_results(results: Mapping[str, Any]) -> ResultsHead:
    """The results document's head, or `InvalidEvalResultsError`."""
    try:
        return ResultsHead.model_validate(results)
    except ValidationError as exc:
        raise _validation_errors("results", exc) from None


def validate_comparison(comparison: Mapping[str, Any] | None) -> None:
    """A comparison, when given, must not claim another kind or format."""
    if comparison is None:
        return
    try:
        _ComparisonHead.model_validate(comparison)
    except ValidationError as exc:
        raise _validation_errors("comparison", exc) from None


def validate_workflow_run_url(url: str | None) -> str | None:
    """The link normalized (trimmed, blank means none); only http(s) URLs of at most 2000
    characters are accepted."""
    if url is None:
        return None
    value = url.strip()
    if not value:
        return None
    if len(value) > MAX_URL_LENGTH or not value.startswith(("https://", "http://")):
        raise _invalid("workflow_run_url", "must be an http(s) URL of at most 2000 characters")
    if any(char.isspace() or ord(char) < 0x20 for char in value):
        raise _invalid("workflow_run_url", "must not contain spaces or control characters")
    return value


# --- derived fields -----------------------------------------------------------------------------


def run_key(profile: str, git_sha: str | None, started_at: dt.datetime) -> str:
    """The identity of a run: profile, git sha and start instant (in UTC, so the same instant
    written with another offset is the same run)."""
    instant = started_at.astimezone(dt.UTC).isoformat(timespec="microseconds")
    return f"{profile}|{git_sha or ''}|{instant}"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}


def comparison_status(comparison: Mapping[str, Any] | None) -> CompareStatus | None:
    """The verdict of an `evals/compare.py --json` document: its `status` when it is one of
    passed | blocked | report_only, else derived from `blocked` and `report_only`; None for no
    comparison or one this code cannot read."""
    if comparison is None:
        return None
    status = comparison.get("status")
    for known in COMPARE_STATUSES:
        if status == known:
            return known
    if comparison.get("blocked") is True:
        return "blocked"
    if comparison.get("report_only") is True:
        return "report_only"
    if comparison.get("blocked") is False:
        return "passed"
    return None


def _sequence(value: object) -> Sequence[Any]:
    return cast(Sequence[Any], value) if isinstance(value, list) else []


def comparison_reference(comparison: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    """The baseline a comparison measured against: its judge mean (the mean of the criteria's
    baseline means) and its mean cost per plan in cents; (None, None) without a baseline."""
    if comparison is None:
        return None, None
    means = [
        mean
        for criterion in _sequence(comparison.get("criteria"))
        if (mean := _number(_mapping(criterion).get("baseline_mean"))) is not None
    ]
    judge = round(sum(means) / len(means), 3) if means else None
    cost = _number(_mapping(comparison.get("cost")).get("baseline_mean_cents"))
    return judge, cost


def blocking_findings(
    requests: Sequence[Mapping[str, Any]], comparison: Mapping[str, Any] | None
) -> list[BlockingFinding]:
    """The comparison's first findings that block it, each with its request's title. A finding
    blocks when its `blocks` says so; older documents have only `blocking`."""
    if comparison is None:
        return []
    titles = {
        str(entry.get("id")): title
        for entry in requests
        if isinstance(title := entry.get("title"), str) and title.strip()
    }
    found: list[BlockingFinding] = []
    for item in _sequence(comparison.get("findings")):
        finding = _mapping(item)
        blocks = finding.get("blocks")
        if not (blocks is True or (blocks is None and finding.get("blocking") is True)):
            continue
        request_id = finding.get("request_id")
        request_id = request_id if isinstance(request_id, str) and request_id else None
        found.append(
            BlockingFinding(
                rule=str(finding.get("rule") or ""),
                message=str(finding.get("message") or "")[:MAX_FINDING_MESSAGE],
                request_id=request_id,
                request_title=titles.get(request_id) if request_id else None,
            )
        )
        if len(found) == MAX_BLOCKING_FINDINGS:
            break
    return found


def summarize_run(
    requests: Sequence[Mapping[str, Any]], comparison: Mapping[str, Any] | None
) -> RunMetrics:
    """The list fields of a run, computed as `evals/run.py`'s `summarize` does, plus what the
    comparison measured against and why it blocked."""
    costs = 0.0
    searches = 0.0
    scores: list[float] = []
    reference_judge, reference_cost = comparison_reference(comparison)
    for entry in requests:
        costs += _number(entry.get("cost_cents")) or 0.0
        searches += _number(entry.get("web_search_requests")) or 0.0
        for criterion in _mapping(_mapping(entry.get("judge")).get("scores")).values():
            score = _number(_mapping(criterion).get("score"))
            if score is not None:
                scores.append(score)
    return RunMetrics(
        requests_total=len(requests),
        requests_accepted=sum(1 for entry in requests if entry.get("status") == "ready"),
        checks_passed=sum(1 for entry in requests if entry.get("checks_passed") is True),
        blocking_failures_count=sum(
            len(cast(list[Any], entry["blocking_failures"]))
            for entry in requests
            if isinstance(entry.get("blocking_failures"), list)
        ),
        total_cost_cents=round(costs),
        web_search_requests=round(searches),
        judge_mean=round(sum(scores) / len(scores), 3) if scores else None,
        compare_status=comparison_status(comparison),
        reference_judge_mean=reference_judge,
        reference_cost_per_plan_cents=reference_cost,
        blocking_findings=blocking_findings(requests, comparison),
    )


# --- service ------------------------------------------------------------------------------------


async def store_eval_run(
    db: AsyncSession,
    *,
    results: Mapping[str, Any],
    comparison: Mapping[str, Any] | None = None,
    workflow_run_url: str | None = None,
) -> StoredEvalRun:
    """Validate and store a run, committing. Idempotent per `run_key`: a repeat keeps the
    stored results, and only a comparison or workflow link that it brings replaces the stored
    one (a repeat without them never erases them). Raises `InvalidEvalResultsError`."""
    try:
        results = cast(Mapping[str, Any], clean_json(results))
        comparison = cast("Mapping[str, Any] | None", clean_json(comparison))
    except RecursionError:
        raise _invalid("(body)", "nested too deeply") from None
    head = validate_results(results)
    validate_comparison(comparison)
    link = validate_workflow_run_url(workflow_run_url)
    key = run_key(head.profile, head.git_sha, head.started_at)
    metrics = summarize_run(head.requests, comparison)
    comparison_doc: JsonObject | None = dict(comparison) if comparison is not None else None

    inserted = await db.scalar(
        pg_insert(EvalRunRecord)
        .values(
            id=uuid.uuid4(),
            run_key=key,
            profile=head.profile,
            git_sha=head.git_sha,
            started_at=head.started_at,
            finished_at=head.finished_at,
            aborted=head.aborted,
            summary=metrics.model_dump(mode="json"),
            results=dict(results),
            comparison=comparison_doc,
            workflow_run_url=link,
        )
        .on_conflict_do_nothing(index_elements=[EvalRunRecord.run_key])
        .returning(EvalRunRecord.id)
    )
    if inserted is not None:
        await db.commit()
        log.info("eval_run_stored", eval_run_id=str(inserted), profile=head.profile, created=True)
        return StoredEvalRun(id=inserted, created=True)

    record = await db.scalar(
        select(EvalRunRecord).where(EvalRunRecord.run_key == key).with_for_update()
    )
    if record is None:  # deleted between the insert and the select: store it again
        await db.rollback()
        return await store_eval_run(
            db, results=results, comparison=comparison, workflow_run_url=workflow_run_url
        )
    if comparison_doc is not None:
        record.comparison = comparison_doc
        # What comes from the comparison is recomputed against the stored requests (titles).
        derived = summarize_run(_sequence(_mapping(record.results).get("requests")), comparison_doc)
        record.summary = {
            **record.summary,
            **derived.model_dump(
                mode="json",
                include={
                    "compare_status",
                    "reference_judge_mean",
                    "reference_cost_per_plan_cents",
                    "blocking_findings",
                },
            ),
        }
    if link is not None:
        record.workflow_run_url = link
    await db.commit()
    log.info("eval_run_stored", eval_run_id=str(record.id), profile=head.profile, created=False)
    return StoredEvalRun(id=record.id, created=False)


def _summary_of(
    *,
    run_id: uuid.UUID,
    profile: str,
    git_sha: str | None,
    started_at: dt.datetime,
    finished_at: dt.datetime | None,
    aborted: bool,
    metrics: Mapping[str, Any],
    workflow_run_url: str | None,
) -> EvalRunSummary:
    return EvalRunSummary(
        id=run_id,
        profile=profile,
        git_sha=git_sha,
        started_at=started_at,
        finished_at=finished_at,
        aborted=aborted,
        workflow_run_url=workflow_run_url,
        **RunMetrics.model_validate(metrics).model_dump(),
    )


async def list_eval_runs(
    db: AsyncSession, *, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0
) -> list[EvalRunSummary]:
    """The `limit` most recent runs after the newest `offset`, newest first. Reads the columns
    and the summary only, never the stored documents."""
    rows = await db.execute(
        select(
            EvalRunRecord.id,
            EvalRunRecord.profile,
            EvalRunRecord.git_sha,
            EvalRunRecord.started_at,
            EvalRunRecord.finished_at,
            EvalRunRecord.aborted,
            EvalRunRecord.summary,
            EvalRunRecord.workflow_run_url,
        )
        .order_by(EvalRunRecord.started_at.desc(), EvalRunRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        _summary_of(
            run_id=run_id,
            profile=profile,
            git_sha=git_sha,
            started_at=started_at,
            finished_at=finished_at,
            aborted=aborted,
            metrics=metrics,
            workflow_run_url=link,
        )
        for run_id, profile, git_sha, started_at, finished_at, aborted, metrics, link in rows
    ]


async def count_eval_runs(db: AsyncSession) -> int:
    """How many runs the history holds."""
    return (await db.execute(select(func.count()).select_from(EvalRunRecord))).scalar_one()


_SUMMARY_COLUMNS = (
    EvalRunRecord.id,
    EvalRunRecord.profile,
    EvalRunRecord.git_sha,
    EvalRunRecord.started_at,
    EvalRunRecord.finished_at,
    EvalRunRecord.aborted,
    EvalRunRecord.summary,
    EvalRunRecord.workflow_run_url,
)


def _summary_row(row: Any) -> EvalRunSummary:
    run_id, profile, git_sha, started_at, finished_at, aborted, metrics, link = row
    return _summary_of(
        run_id=run_id,
        profile=profile,
        git_sha=git_sha,
        started_at=started_at,
        finished_at=finished_at,
        aborted=aborted,
        metrics=metrics,
        workflow_run_url=link,
    )


async def get_eval_run(db: AsyncSession, run_id: uuid.UUID) -> EvalRunDetail | None:
    """A run with its stored results and comparison, and the runs just before and after it in
    the list's order (started_at, then created_at), or None."""
    record = await db.get(EvalRunRecord, run_id)
    if record is None:
        return None
    position = tuple_(EvalRunRecord.started_at, EvalRunRecord.created_at)
    here = tuple_(literal(record.started_at), literal(record.created_at))
    before = (
        await db.execute(
            select(*_SUMMARY_COLUMNS)
            .where(position < here)
            .order_by(EvalRunRecord.started_at.desc(), EvalRunRecord.created_at.desc())
            .limit(1)
        )
    ).first()
    after = (
        await db.execute(
            select(*_SUMMARY_COLUMNS)
            .where(position > here)
            .order_by(EvalRunRecord.started_at.asc(), EvalRunRecord.created_at.asc())
            .limit(1)
        )
    ).first()
    summary = _summary_row(
        (
            record.id,
            record.profile,
            record.git_sha,
            record.started_at,
            record.finished_at,
            record.aborted,
            record.summary,
            record.workflow_run_url,
        )
    )
    return EvalRunDetail(
        **summary.model_dump(),
        results=record.results,
        comparison=record.comparison,
        previous_run=_summary_row(before) if before is not None else None,
        next_run=_summary_row(after) if after is not None else None,
    )
