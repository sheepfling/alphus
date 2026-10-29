"""Focused regression coverage for opt-in C++ impact and advisory gates."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

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
