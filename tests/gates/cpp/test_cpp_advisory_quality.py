"""Focused regression coverage for opt-in C++ impact and advisory gates."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from alphus.gates.cpp import cpp_advisory_quality as advisory
from alphus.gates.cpp import cpp_common_quality as common
from alphus.support.data_access import require_json_array, require_json_object


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_style_review_is_nonblocking_unless_requested(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.cpp").write_text(
        '#include "unused.hpp"\nint main() { return 0; }\n',
        encoding="utf-8",
    )
    output = tmp_path / "style.json"
    args = ["style", str(tmp_path), "--max-file-lines", "1", "--output", str(output)]

    assert advisory.main(args) == 0
    report = require_json_object(
        json.loads(output.read_text(encoding="utf-8")), "style"
    )
    findings = require_json_array(report.get("findings"), "findings")
    assert report["status"] == "provisional"
    assert report["blocking"] is False
    assert findings
    assert all(
        require_json_object(item, "finding").get("blocking") is False
        for item in findings
    )
    assert advisory.main([*args, "--fail-on-findings"]) == 1


def test_style_scope_excludes_root_and_nested_cache_directories_by_default(
    tmp_path: Path,
) -> None:
    cache = tmp_path / ".cache"
    nested_cache = tmp_path / "src" / ".cache"
    cache.mkdir()
    nested_cache.mkdir(parents=True)
    (cache / "generated.cpp").write_text("int generated() { return 0; }\n")
    (nested_cache / "generated.hpp").write_text("int generated_nested();\n")
    (tmp_path / "src" / "main.cpp").write_text("int main() { return 0; }\n")
    output = tmp_path / "style.json"

    assert advisory.main(["style", str(tmp_path), "--output", str(output)]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["source_file_count"] == 1
    assert report["scope"]["include_patterns"] == list(advisory._DEFAULT_INCLUDE)
    assert ".cache/**" in report["scope"]["exclude_patterns"]
    assert "**/.cache/**" in report["scope"]["exclude_patterns"]


def test_style_report_exposes_effective_custom_scope_patterns(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("int main() { return 0; }\n")
    output = tmp_path / "style.json"

    assert (
        advisory.main(
            [
                "style",
                str(tmp_path),
                "--include",
                "src/**",
                "--exclude",
                "src/private/**",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["scope"]["include_patterns"] == ["src/**"]
    assert report["scope"]["exclude_patterns"][-1] == "src/private/**"
    assert report["metrics"]["source_file_count"] == 1


def test_style_setup_failure_writes_versioned_incomplete_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "reports" / "style-failure.json"

    assert (
        advisory.main(
            ["style", str(tmp_path / "missing-root"), "--output", str(output)]
        )
        == 2
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "alphus.execution-failure"
    assert report["schema_version"] == 1
    assert report["component"] == "cpp-advisory"
    assert report["status"] == "execution_failure"
    assert report["execution_failure"]["exit_code"] == 2
    assert report["findings"] == []
    assert report["confidence"] is None
    assert report["enforcement"] is None
    assert report["raw_child_exit"] is None
    assert report["evidence_complete"] is False
    assert report["artifact_paths"] == [str(output)]
    captured = capsys.readouterr()
    assert "cpp advisory quality:" in captured.err
    assert str(tmp_path / "missing-root") not in captured.err


def test_style_setup_failure_without_output_emits_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert advisory.main(["style", str(tmp_path / "missing-root")]) == 2

    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == "alphus.execution-failure"
    assert report["status"] == "execution_failure"
    assert report["evidence_complete"] is False


def test_style_failure_redacts_source_text_from_json_and_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_secret = "PRIVATE_SOURCE_SENTINEL_94AC"
    with mock.patch.object(
        advisory,
        "_style_report",
        side_effect=ValueError(f"invalid source excerpt: {source_secret}"),
    ):
        assert advisory.main(["style", str(tmp_path)]) == 2

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["execution_failure"]["kind"] == "operational_error"
    assert report["execution_failure"]["message"] == (
        "C++ advisory style analysis failed because an option or input value is invalid."
    )
    assert source_secret not in captured.out
    assert source_secret not in captured.err


def test_style_failure_redacts_source_text_from_interactive_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_secret = "PRIVATE_INTERACTIVE_SOURCE_SENTINEL_9B3E"
    with (
        mock.patch.object(
            advisory,
            "_style_report",
            side_effect=ValueError(f"source excerpt: {source_secret}"),
        ),
        mock.patch.object(advisory.sys.stdout, "isatty", return_value=True),
    ):
        assert advisory.main(["style", str(tmp_path)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "style analysis" in captured.err
    assert source_secret not in captured.err


def test_style_failure_artifact_write_error_redacts_exception_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sentinel = "PRIVATE_ARTIFACT_ERROR_SENTINEL_658D"
    output = tmp_path / "failure.json"
    with (
        mock.patch.object(
            advisory,
            "_style_report",
            side_effect=ValueError(f"source excerpt: {sentinel}"),
        ),
        mock.patch.object(
            advisory,
            "emit_execution_failure",
            side_effect=OSError(f"private output path: {sentinel}"),
        ),
    ):
        assert advisory.main(["style", str(tmp_path), "--output", str(output)]) == 2

    captured = capsys.readouterr()
    assert "could not write failure report artifact" in captured.err
    assert sentinel not in captured.out
    assert sentinel not in captured.err


def test_impact_uses_measured_fanout_report(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    (tmp_path / "src" / "main.cpp").write_text(
        '#include "../include/api.hpp"\nint main() { return 0; }\n',
        encoding="utf-8",
    )
    (tmp_path / "include" / "api.hpp").write_text(
        "#pragma once\nint api();\n", encoding="utf-8"
    )
    compile_report = tmp_path / "compile.json"
    _write_json(
        compile_report,
        {
            "run_id": "fixture",
            "records": [{"file": "src/main.cpp"}],
            "header_fanout": [{"path": "include/api.hpp", "translation_units": 2}],
        },
    )

    with mock.patch.object(
        common,
        "_files",
        return_value=[tmp_path / "src" / "main.cpp", tmp_path / "include" / "api.hpp"],
    ):
        report = common.check_impact(
            tmp_path,
            {"include": ["**/*"], "min_files": 2},
            compile_report,
            "fixture",
        )
    metrics = require_json_object(report["metrics"], "metrics")
    rows = require_json_array(metrics.get("highest_translation_unit_fanout"), "fanout")
    assert report["passed"] is True, report["findings"]
    assert require_json_object(rows[0], "fanout row") == {
        "path": "include/api.hpp",
        "translation_units": 2,
    }


def test_trend_only_compares_matching_build_contexts(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    context = {
        "configuration": "Debug",
        "toolchain": "fixture-compiler",
        "selected_targets": ["app"],
        "expected_executables": ["app"],
        "inputs": [{"path": "CMakeLists.txt", "sha256": "a"}],
    }
    for number, radius in enumerate((1, 3), start=1):
        _write_json(
            snapshots / f"{number}.json",
            {
                "gate": "impact",
                "run_id": f"run-{number}",
                "created_at_utc": f"2026-10-0{number}T12:00:00Z",
                "comparison_context": context,
                "metrics": {"impact_summary": {"avg_blast_radius": radius}},
            },
        )
    output = tmp_path / "trend.json"
    args = ["trend", str(snapshots), "--output", str(output)]

    assert advisory.main(args) == 0
    report = require_json_object(
        json.loads(output.read_text(encoding="utf-8")), "trend"
    )
    findings = require_json_array(report.get("findings"), "findings")
    assert report["status"] == "provisional"
    assert len(findings) == 1
    assert advisory.main([*args, "--fail-on-worsening"]) == 1
