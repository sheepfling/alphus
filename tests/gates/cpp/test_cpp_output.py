"""Installed C++ artifact command supports human and machine output."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from alphus.gates.cpp import artifact_scan
from alphus.gates.cpp.artifact_contracts import (
    ArtifactScanDocument,
    ArtifactScanOptions,
    SectionMetrics,
    validate_artifact_report,
)
from alphus.gates.cpp.cpp_artifact_quality import main
from alphus.support.tool_probe import ToolProbe


def test_artifact_scan_supports_explicit_output_formats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["scan", str(tmp_path), "--no-sections", "--format", "plain"]) == 0
    assert "artifacts: PASS" in capsys.readouterr().out

    assert main(["scan", str(tmp_path), "--no-sections", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["count"] == 0

    assert main(["scan", str(tmp_path), "--no-sections", "--format", "rich"]) == 0
    assert "artifacts: PASS" in capsys.readouterr().out


def test_artifact_scan_options_control_review_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "sample.exe"
    executable.write_bytes(b"MZ" + b"x" * 98)
    monkeypatch.setattr(
        artifact_scan,
        "probe_command",
        lambda _tool: ToolProbe("command", "objdump", True, "objdump"),
    )
    monkeypatch.setattr(
        artifact_scan,
        "_section_metrics",
        lambda _path, _tool, *, timeout_seconds: SectionMetrics(
            "measured", debug_bytes=80, text_bytes=10
        ),
    )
    report = artifact_scan.scan_directory(
        tmp_path,
        options=ArtifactScanOptions(
            debug_dominance_min_bytes=60,
            max_review_examples=0,
            section_timeout_seconds=2.0,
        ),
    )
    assert report.review_signals[0].count == 1
    assert report.review_signals[0].examples == []
    assert report.to_wire()["artifacts"][0]["debug_bytes"] == 80


def test_artifact_scanner_preserves_full_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "sample.exe"
    executable.write_bytes(b"MZ")
    message = "tool failure " * 30
    monkeypatch.setattr(
        artifact_scan.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", message),
    )
    metrics = artifact_scan._section_metrics(executable, "objdump", timeout_seconds=2.0)
    assert metrics.error == message


def test_artifact_scan_rejects_invalid_runtime_settings(tmp_path: Path) -> None:
    assert (
        main(["scan", str(tmp_path), "--no-sections", "--max-review-examples", "-1"])
        == 2
    )
    assert (
        main(["scan", str(tmp_path), "--no-sections", "--section-timeout-seconds", "0"])
        == 2
    )


def test_artifact_policy_scan_settings_and_cli_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema": 1,
                "limits": {"min_executable_count": 0},
                "scan": {
                    "debug_dominance_min_bytes": 10,
                    "max_review_examples": 2,
                    "section_timeout_seconds": 5,
                },
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "check",
                str(tmp_path),
                "--policy",
                str(policy),
                "--no-sections",
                "--max-review-examples",
                "0",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["totals"]["count"] == 0


def test_artifact_scan_rejects_nonfinite_timeout() -> None:
    with pytest.raises(ValueError, match="section_timeout_seconds"):
        ArtifactScanOptions(section_timeout_seconds=float("nan"))


def test_artifact_report_boundary_rejects_invalid_totals(
    tmp_path: Path,
) -> None:
    report = artifact_scan.scan_directory(tmp_path, measure_sections=False).to_wire()
    report["totals"]["count"] = -1
    with pytest.raises(ValueError, match="totals.count"):
        validate_artifact_report(report)


def test_saved_artifact_report_loads_with_public_pydantic_model(tmp_path: Path) -> None:
    destination = tmp_path / "report.json"
    assert (
        main(
            [
                "scan",
                str(tmp_path),
                "--no-sections",
                "--output",
                str(destination),
                "--format",
                "json",
            ]
        )
        == 0
    )
    report = ArtifactScanDocument.model_validate_json(
        destination.read_text(encoding="utf-8")
    )
    assert report.schema_version == 1
    assert report.totals.count == 0
