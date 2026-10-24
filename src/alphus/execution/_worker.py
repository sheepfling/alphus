"""Private JSON protocol for isolated built-in quality work."""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import cast

from alphus.cli import run_profile_rule
from alphus.config import load_config
from alphus.gates.source.cyclomatic_complexity import (
    build_cyclomatic_plan,
    run_cyclomatic_backend,
)
from alphus.policy.base import QualityRuleName


def _dispatch(request: dict[str, object]) -> dict[str, object]:
    if request.get("version") != 1:
        raise ValueError("unsupported worker protocol version")
    root = Path(str(request["root"])).resolve(strict=True)
    config_path = Path(str(request["config_path"])).resolve(strict=True)
    config = load_config(config_path)
    fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
    if fingerprint != request.get("config_fingerprint"):
        raise ValueError("quality policy changed during parallel execution")
    if request.get("kind") == "rule":
        rule = str(request["rule"])
        result = run_profile_rule(
            root,
            config_path,
            cast(QualityRuleName, rule),
            bool(request.get("verbose", False)),
            config,
        )
        return {
            "version": 1,
            "kind": "rule",
            "findings": [item.to_wire() for item in result.findings],
            "execution_failure": result.execution_failure,
            "exit_code": int(result.exit_code),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "report": result.report,
        }
    if request.get("kind") == "cyclomatic_backend":
        language = str(request["language"])
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
        if json.dumps(asdict(selected), sort_keys=True) != json.dumps(
            request.get("expected_plan"), sort_keys=True
        ):
            raise ValueError("cyclomatic backend plan changed during execution")
        result, records, findings = run_cyclomatic_backend(
            root, policy, binding, selected
        )
        return {
            "version": 1,
            "kind": "cyclomatic_backend",
            "result": asdict(result),
            "records": [asdict(record) for record in records],
            "findings": [finding.to_wire() for finding in findings],
        }
    raise ValueError("unknown worker request kind")


def main() -> int:
    """Keep stdout reserved for one protocol value, including failures."""
    captured_output = StringIO()
    captured_error = StringIO()
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise TypeError("worker request must be an object")
        with redirect_stdout(captured_output), redirect_stderr(captured_error):
            response = _dispatch(cast(dict[str, object], request))
        if captured_output.getvalue() or captured_error.getvalue():
            raise ValueError("worker emitted unexpected output")
    except Exception as error:  # noqa: BLE001 - protocol reports worker failures.
        response = {"error": f"{type(error).__name__}: {error}"}
    json.dump(response, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
