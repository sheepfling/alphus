"""The profile CLI exposes manifest completion separately from gate status."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.cli import main
from alphus.execution.audit_manifest import AuditManifestCheck


def _write_manifest(
    root: Path, profile: str, checks: Sequence[AuditManifestCheck]
) -> None:
    (root / "audit.json").write_text(
        json.dumps(
            {
                "format": "alphus.audit-manifest",
                "schema_version": 1,
                "profile": profile,
                "checks": [check.model_dump(mode="json") for check in checks],
            }
        ),
        encoding="utf-8",
    )


def test_profile_cli_reports_not_selected_and_does_not_exit_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[orchestration]
default_profile = "check"
[[orchestration.steps]]
kind = "command"
name = "Smoke"
argv = ["{python}", "-c", "print(1)"]
[[orchestration.steps]]
kind = "command"
name = "Optional ANN"
argv = ["{python}", "-c", "print(1)"]
[[orchestration.profiles]]
name = "check"
steps = ["Smoke"]
""",
        encoding="utf-8",
    )
    _write_manifest(
        tmp_path,
        "check",
        [
            AuditManifestCheck(check_id="smoke", step="Smoke", expected_files=None),
            AuditManifestCheck(
                check_id="annotations", step="Optional ANN", expected_files=None
            ),
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["exit_code"] == 0
    assert exit_code == 2
    assert payload["audit_completion"]["status"] == "incomplete"
    checks = {
        check["check_id"]: check for check in payload["audit_completion"]["checks"]
    }
    assert checks["smoke"]["status"] == "executed"
    assert checks["smoke"]["findings_state"] == "unknown"
    assert checks["annotations"]["status"] == "not_selected"


def test_profile_cli_marks_manifest_incomplete_on_missing_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[checks.numeric_literals]
extensions = [".py"]
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "rule"
name = "Numeric"
rule = "numeric-literals"
[[orchestration.profiles]]
name = "audit"
steps = ["Numeric"]
""",
        encoding="utf-8",
    )
    (tmp_path / "source.py").write_text("value = 1\n", encoding="utf-8")
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="numeric",
                step="Numeric",
                expected_files=("source.py",),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "alphus.execution-failure"
    assert payload["evidence_complete"] is False
    assert payload["audit_completion"]["status"] == "incomplete"
    assert payload["audit_completion"]["checks"][0]["status"] == "incomplete"
