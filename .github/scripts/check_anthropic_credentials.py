"""Guard: Anthropic credentials stay out of pull requests (ci-backend.yml, job `workflows`).

    python .github/scripts/check_anthropic_credentials.py [GITHUB_DIR]   check .github/ (default)
    python .github/scripts/check_anthropic_credentials.py --self-test    prove the guard fails

CI authenticates to Anthropic in one of two modes (docs/deploy.md, "Anthropic credentials in
CI"): Workload Identity Federation, or the environment secret ANTHROPIC_API_KEY. Both reach a
job only through ./.github/actions/anthropic-auth in a job that declares a GitHub environment.
GitHub enforces the rest (the `production` environment accepts `main` only and needs Michele's
approval); this guard keeps the workflows from drifting away from that design. It checks:

  1. No workflow uses the pull_request_target trigger.
  2. A workflow a pull request can run (pull_request, workflow_call, workflow_run) has no job in
     the `production` environment (an expression that can resolve to it counts), and no
     workflow-level `id-token: write`.
  3. Any job that uses the anthropic-auth action, reads secrets.ANTHROPIC_API_KEY or requests
     `id-token: write` declares an environment: `development` in a workflow a pull request can
     run, `development` or `production` in the others. Repository-level secrets are never used
     for Anthropic. A job that only calls a reusable workflow (`uses:`) is exempt: the called
     workflow's own jobs are checked as workflow_call.
  4. `id-token: write` is requested only by jobs that call Anthropic (the action, or a reusable
     workflow), and a job that uses the action requests it (federation needs it).
  5. secrets.ANTHROPIC_API_KEY appears only as the `api-key` input of the anthropic-auth action,
     written exactly `${{ secrets.ANTHROPIC_API_KEY }}`. No other secrets.ANTHROPIC_* exists, and
     no secret is read inside the action or its scripts. `secrets: inherit` only in a workflow
     no pull request can run, on a call to a workflow of this repository (./.github/workflows/):
     without it a called workflow's job does not see its environment's secrets.
  6. No reference to the retired names ANTHROPIC_API_KEY_DEV / ANTHROPIC_API_KEY_PROD anywhere
     under .github/.
  7. Nothing sets ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or ANTHROPIC_IDENTITY_TOKEN in an
     `env:` (workflow, job or step): a static credential wins over federation, and the action
     is the only place that exports a key.

Needs PyYAML. Exit 0 when clean, 1 with one `::error::` line per problem.
"""

from __future__ import annotations

import re
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

# Split, so that this file's own text doesn't match itself.
RETIRED_KEYS = re.compile("ANTHROPIC_API_KEY_" + "(PROD|DEV)")
ANTHROPIC_SECRET = re.compile(r"secrets(?:\.|\[\s*['\"])(ANTHROPIC_[A-Za-z0-9_]*)")
STATIC_ENV_KEYS = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_IDENTITY_TOKEN"}
AUTH_ACTION = "actions/anthropic-auth"
ALLOWED_KEY_EXPRESSION = "${{ secrets.ANTHROPIC_API_KEY }}"
# Triggers that run code from a pull request, or that a pull request workflow can call.
UNTRUSTED = {"pull_request", "pull_request_target", "workflow_call", "workflow_run"}
INPUT_EXPRESSION = re.compile(r"^\$\{\{\s*(?:github\.event\.)?inputs\.([A-Za-z0-9_-]+)\s*\}\}$")


def requests_id_token(permissions: Any) -> bool:
    return isinstance(permissions, dict) and permissions.get("id-token") == "write"


def uses_auth_action(job: dict[str, Any]) -> bool:
    return any(AUTH_ACTION in str(step.get("uses", "")) for step in job.get("steps") or [])


def inherit_allowed(job: dict[str, Any], untrusted: list[str]) -> bool:
    """`secrets: inherit` only from a workflow no pull request can run, to a workflow of this
    repository: a called workflow's job reads its environment's secrets only when the caller
    passes them (deploy-agents.yml -> evals.yml found the development key empty without it)."""
    return not untrusted and str(job.get("uses", "")).startswith("./.github/workflows/")


def walk(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Every (key path, value) of a parsed YAML document, mappings and lists alike."""
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from walk(item, (*path, str(index)))


def triggers_of(doc: dict[str, Any]) -> set[str]:
    raw = doc.get("on", doc.get(True))  # PyYAML reads the bare key `on` as True
    if isinstance(raw, dict | list):
        return {str(item) for item in raw}
    return {str(raw)}


def environment_names(doc: dict[str, Any], environment: Any) -> set[str] | None:
    """The environment names a job can run in; None when it declares none; {"?"} when unknown."""
    name = environment.get("name") if isinstance(environment, dict) else environment
    if name is None:
        return None
    if not isinstance(name, str):
        return {"?"}
    match = INPUT_EXPRESSION.match(name.strip())
    if match is None:
        return {name}
    # `environment: ${{ inputs.environment }}`: known only for a choice input of workflow_dispatch.
    raw = doc.get("on", doc.get(True))
    inputs = (
        ((raw or {}).get("workflow_dispatch") or {}).get("inputs")
        if isinstance(raw, dict)
        else None
    )
    spec = (inputs or {}).get(match.group(1)) or {}
    options = spec.get("options")
    if spec.get("type") == "choice" and isinstance(options, list) and options:
        return {str(option) for option in options}
    return {"?"}


def check_workflow(path: Path, doc: dict[str, Any], errors: list[str]) -> None:
    triggers = triggers_of(doc)
    untrusted = sorted(triggers & UNTRUSTED)
    if "pull_request_target" in triggers:
        errors.append(f"{path}: pull_request_target is not allowed")
    if requests_id_token(doc.get("permissions")):
        errors.append(
            f"{path}: workflow-level id-token: write; ask for it on the jobs that call Anthropic"
        )

    allowed_environments = {"development"} if untrusted else {"development", "production"}
    for job_id, job in (doc.get("jobs") or {}).items():
        where = f"{path}: job {job_id!r}"
        calls_workflow = "uses" in job
        uses_action = uses_auth_action(job)
        asks_id_token = requests_id_token(job.get("permissions"))
        secret_use = any(
            isinstance(value, str) and ANTHROPIC_SECRET.search(value) for _, value in walk(job)
        )
        names = environment_names(doc, job.get("environment"))

        if job.get("secrets") == "inherit" and not inherit_allowed(job, untrusted):
            errors.append(f"{where} passes `secrets: inherit` to a reusable workflow")
        if names is not None and untrusted and any("production" in name for name in names):
            errors.append(f"{where} can run in production from {untrusted}")
        if asks_id_token and not (uses_action or calls_workflow):
            errors.append(f"{where} requests id-token: write but does not call Anthropic")
        if uses_action and not asks_id_token:
            errors.append(
                f"{where} uses anthropic-auth without id-token: write (federation needs it)"
            )
        if calls_workflow:
            continue
        if uses_action or secret_use or asks_id_token:
            if names is None:
                errors.append(
                    f"{where} reaches Anthropic credentials without a GitHub environment "
                    "(repository-level secrets are not used)"
                )
            elif not names <= allowed_environments:
                errors.append(
                    f"{where} reaches Anthropic credentials in environment {sorted(names)} "
                    f"(allowed: {sorted(allowed_environments)}"
                    f"{', because the workflow is run by ' + str(untrusted) if untrusted else ''})"
                )


def check_secret_uses(path: Path, doc: dict[str, Any], errors: list[str]) -> None:
    """secrets.ANTHROPIC_API_KEY only as `with.api-key` of the auth action's step."""
    allowed: set[tuple[str, ...]] = set()
    for job_id, job in (doc.get("jobs") or {}).items():
        for index, step in enumerate(job.get("steps") or []):
            if AUTH_ACTION in str(step.get("uses", "")):
                allowed.add(("jobs", str(job_id), "steps", str(index), "with", "api-key"))
    for where, value in walk(doc):
        if not isinstance(value, str):
            continue
        for name in ANTHROPIC_SECRET.findall(value):
            if name != "ANTHROPIC_API_KEY":
                errors.append(
                    f"{path}: reads secrets.{name}; the only Anthropic secret is ANTHROPIC_API_KEY"
                )
        if ANTHROPIC_SECRET.search(value) and not (
            where in allowed and value.strip() == ALLOWED_KEY_EXPRESSION
        ):
            errors.append(
                f"{path}: {'.'.join(where)} reads an Anthropic secret outside the `api-key` "
                f"input of {AUTH_ACTION} (write it exactly {ALLOWED_KEY_EXPRESSION})"
            )


def check_static_env(path: Path, node: Any, errors: list[str]) -> None:
    for where, _ in walk(node):
        if where and where[-2:-1] == ("env",) and where[-1] in STATIC_ENV_KEYS:
            errors.append(
                f"{path}: sets {where[-1]} in env ({'.'.join(where)}); "
                "only the auth action exports it"
            )


def check_tree(github_dir: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(
        p
        for p in github_dir.rglob("*")
        if p.is_file() and (github_dir / "scripts") not in p.parents
    ):
        text = path.read_text(encoding="utf-8")
        if RETIRED_KEYS.search(text):
            errors.append(f"{path}: refers to a retired static Anthropic API key secret")
        if path.suffix not in {".yml", ".yaml"} and ANTHROPIC_SECRET.search(text):
            errors.append(
                f"{path}: reads an Anthropic secret; only workflows pass it, to the auth action"
            )
    for path in sorted((github_dir / "actions").rglob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for where, value in walk(doc):
            if isinstance(value, str) and ANTHROPIC_SECRET.search(value):
                errors.append(
                    f"{path}: {'.'.join(where)} reads an Anthropic secret; "
                    "actions get it as an input"
                )
        check_static_env(path, doc, errors)
    for path in sorted((github_dir / "workflows").glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        check_workflow(path, doc, errors)
        check_secret_uses(path, doc, errors)
        check_static_env(path, doc, errors)
    return errors


# ---- self-test: every rule must fail on a minimal workflow that breaks it -------------------

CLEAN_PR = """
name: t
on: {pull_request: {}}
jobs:
  j:
    runs-on: ubuntu-24.04
    environment: development
    permissions: {contents: read, id-token: write}
    steps:
      - uses: ./.github/actions/anthropic-auth
        with:
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
"""

CLEAN_DISPATCH = """
name: t
on:
  workflow_dispatch:
    inputs:
      environment: {type: choice, options: [development, production], default: development}
jobs:
  j:
    runs-on: ubuntu-24.04
    environment: ${{ inputs.environment }}
    permissions: {contents: read, id-token: write}
    steps:
      - uses: ./.github/actions/anthropic-auth
        with:
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
"""

# (name, workflow text, text that must appear in an error). None: the guard must stay quiet.
CASES: list[tuple[str, str, str | None]] = [
    ("clean PR workflow", CLEAN_PR, None),
    ("clean dispatch workflow with a choice of environment", CLEAN_DISPATCH, None),
    (
        "pull_request_target",
        CLEAN_PR.replace("{pull_request: {}}", "{pull_request_target: {}}"),
        "pull_request_target",
    ),
    (
        "production job in a PR workflow",
        CLEAN_PR.replace("environment: development", "environment: production"),
        "production",
    ),
    (
        "production through the choice input, in a workflow a PR can run",
        CLEAN_DISPATCH.replace("{type: choice", "{type: choice").replace(
            "on:\n  workflow_dispatch:", "on:\n  pull_request: {}\n  workflow_dispatch:"
        ),
        "production",
    ),
    (
        "no environment on a job that uses the action",
        CLEAN_PR.replace("    environment: development\n", ""),
        "without a GitHub environment",
    ),
    (
        "no environment on a job that only reads the secret",
        "name: t\non: {push: {}}\njobs:\n  j:\n    runs-on: x\n    steps:\n"
        "      - run: echo\n        env:\n          X: ${{ secrets.ANTHROPIC_API_KEY }}\n",
        "without a GitHub environment",
    ),
    (
        "no environment on a job that requests id-token",
        "name: t\non: {push: {}}\njobs:\n  j:\n    runs-on: x\n    permissions: {id-token: write}\n"
        "    steps:\n      - uses: ./.github/actions/anthropic-auth\n",
        "without a GitHub environment",
    ),
    (
        "id-token on a job that does not call Anthropic",
        "name: t\non: {push: {}}\njobs:\n  j:\n    runs-on: x\n    environment: development\n"
        "    permissions: {id-token: write}\n    steps:\n      - run: echo\n",
        "does not call Anthropic",
    ),
    (
        "workflow-level id-token",
        CLEAN_PR.replace("jobs:", "permissions: {id-token: write}\njobs:", 1),
        "workflow-level id-token",
    ),
    (
        "action without id-token",
        CLEAN_PR.replace("{contents: read, id-token: write}", "{contents: read}"),
        "without id-token: write",
    ),
    (
        "retired secret name",
        CLEAN_PR + "      - run: echo ${{ secrets." + "ANTHROPIC_API_KEY_" + "DEV }}\n",
        "retired",
    ),
    (
        "secret read in a run step",
        CLEAN_PR + "      - run: echo ${{ secrets.ANTHROPIC_API_KEY }}\n",
        "outside the `api-key` input",
    ),
    (
        "a different Anthropic secret",
        CLEAN_PR.replace("secrets.ANTHROPIC_API_KEY", "secrets.ANTHROPIC_KEY"),
        "secrets.ANTHROPIC_KEY",
    ),
    (
        "secret expression with extra text",
        CLEAN_PR.replace("${{ secrets.ANTHROPIC_API_KEY }}", "x${{ secrets.ANTHROPIC_API_KEY }}"),
        "outside the `api-key` input",
    ),
    (
        "workflow-level env ANTHROPIC_API_KEY",
        CLEAN_PR.replace("jobs:", "env:\n  ANTHROPIC_API_KEY: abc\njobs:", 1),
        "sets ANTHROPIC_API_KEY",
    ),
    (
        "job-level env ANTHROPIC_AUTH_TOKEN",
        CLEAN_PR.replace(
            "    environment: development\n",
            "    environment: development\n    env:\n      ANTHROPIC_AUTH_TOKEN: abc\n",
        ),
        "sets ANTHROPIC_AUTH_TOKEN",
    ),
    (
        "secrets: inherit from a pull request workflow",
        "name: t\non: {pull_request: {}}\njobs:\n  j:\n    uses: ./.github/workflows/other.yml\n"
        "    secrets: inherit\n",
        "secrets: inherit",
    ),
    (
        "secrets: inherit to another repository's workflow",
        "name: t\non: {push: {}}\njobs:\n  j:\n    uses: someone/else/.github/workflows/x.yml@v1\n"
        "    secrets: inherit\n",
        "secrets: inherit",
    ),
    (
        "secrets: inherit from a push workflow to a local one",
        "name: t\non: {push: {}, workflow_dispatch: {}}\njobs:\n  j:\n"
        "    uses: ./.github/workflows/other.yml\n    secrets: inherit\n",
        None,
    ),
]


def self_test() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, text, expected in CASES:
            github = Path(tmp) / "case" / ".github"
            workflows = github / "workflows"
            (github / "actions").mkdir(parents=True, exist_ok=True)
            for old in workflows.glob("*") if workflows.exists() else []:
                old.unlink()
            workflows.mkdir(parents=True, exist_ok=True)
            (workflows / "case.yml").write_text(text, encoding="utf-8")
            errors = check_tree(github)
            ok = not errors if expected is None else any(expected in e for e in errors)
            print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {errors}"))
            failures += 0 if ok else 1
    # The retired names also fail when they sit in an action script, not only in a workflow.
    with tempfile.TemporaryDirectory() as tmp:
        github = Path(tmp) / ".github"
        (github / "actions" / "x").mkdir(parents=True)
        (github / "workflows").mkdir()
        (github / "actions" / "x" / "run.sh").write_text("echo $ANTHROPIC_API_KEY_" + "PROD\n")
        ok = any("retired" in error for error in check_tree(github))
        print(f"{'ok  ' if ok else 'FAIL'} retired name in an action script")
        failures += 0 if ok else 1
    print(f"{len(CASES) + 1 - failures}/{len(CASES) + 1} self-test cases behave")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--self-test"]:
        return self_test()
    github_dir = Path(argv[0]) if argv else Path(".github")
    errors = check_tree(github_dir)
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print(f"Anthropic credentials guard: {github_dir} is clean.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
