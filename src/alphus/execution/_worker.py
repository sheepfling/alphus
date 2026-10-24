"""Private JSON protocol for isolated built-in quality work."""

from __future__ import annotations

import hashlib
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from alphus.cli import run_profile_rule
from alphus.config import load_config
from alphus.execution.worker_protocol import (
    BackendWorkerResponse,
    DiagnosticPayload,
    ErrorWorkerResponse,
    FindingPayload,
    RuleWorkerResponse,
    WorkerRequest,
    WorkerResponse,
)
from alphus.gates.source.cyclomatic_complexity import (
    build_cyclomatic_plan,
    run_cyclomatic_backend,
)


def _dispatch(request: WorkerRequest) -> WorkerResponse:
    root = Path(request.root).resolve(strict=True)
    config_path = Path(request.config_path).resolve(strict=True)
    config = load_config(config_path)
    fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
    if fingerprint != request.config_fingerprint:
        raise ValueError("quality policy changed during parallel execution")
    if request.kind == "rule":
        rule = request.rule
        assert rule is not None
        result = run_profile_rule(
            root,
            config_path,
            rule,
            request.verbose,
            config,
        )
        return RuleWorkerResponse(
            findings=tuple(
                DiagnosticPayload.from_diagnostic(item) for item in result.findings
            ),
            execution_failure=result.execution_failure,
            exit_code=int(result.exit_code),
            stdout=result.stdout,
            stderr=result.stderr,
            report=dict(result.report) if result.report is not None else None,
        )
    if request.kind == "cyclomatic_backend":
        language = request.language
        assert language is not None
        policy = config.checks.cyclomatic_complexity
        if policy is None:
            raise ValueError("cyclomatic complexity policy is missing")
        plan = build_cyclomatic_plan(root, policy)
        choices = {
            item.language: (item, binding)
            for item, binding in zip(
                plan.backends,
                sorted(policy.backends, key=lambda entry: entry.language),
                strict=True,
            )
        }
        selected, binding = choices[language]
        if selected != request.expected_plan:
            raise ValueError("cyclomatic backend plan changed during execution")
        result, records, findings = run_cyclomatic_backend(
            root, policy, binding, selected
        )
        return BackendWorkerResponse(
            result=result,
            records=tuple(records),
            findings=tuple(FindingPayload.from_finding(item) for item in findings),
        )
    raise ValueError("unknown worker request kind")


def main() -> int:
    """Keep stdout reserved for one protocol value, including failures."""
    captured_output = StringIO()
    captured_error = StringIO()
    try:
        request = WorkerRequest.model_validate_json(sys.stdin.read())
        with redirect_stdout(captured_output), redirect_stderr(captured_error):
            response = _dispatch(request)
        if captured_output.getvalue() or captured_error.getvalue():
            raise ValueError("worker emitted unexpected output")
    except Exception as error:  # noqa: BLE001 - protocol reports worker failures.
        response = ErrorWorkerResponse(error=f"{type(error).__name__}: {error}")
    sys.stdout.write(response.model_dump_json() + "\n")
    return 0
