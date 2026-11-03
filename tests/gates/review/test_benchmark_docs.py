from __future__ import annotations

import json
import shutil
from io import StringIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import BenchmarkDocPolicy, load_config_stream
from alphus.execution.dispatch import run_builtin_rule
from alphus.execution.results import diagnostics_from_output
from alphus.gates.review.benchmark_docs import benchmark_doc_findings

FIXTURE_BASE = Path("tests/fixtures/benchmark_docs")


def _copy_fixtures(tmp_path: Path, *names: str) -> tuple[Path, list[Path]]:
    selected: list[Path] = []
    for name in names:
        relative = Path("docs") / name
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE_BASE / name, destination)
        selected.append(relative)
    return tmp_path, selected


def test_quatops_style_prose_is_one_section_level_candidate(tmp_path: Path) -> None:
    root, paths = _copy_fixtures(tmp_path, "quatops-style.md")
    findings = benchmark_doc_findings(
        root,
        paths,
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert len(findings) == 1
    assert findings[0].path == "docs/quatops-style.md"
    assert findings[0].line == 1
    assert findings[0].severity == "warning"
    assert "Possible benchmark-heavy prose" in findings[0].message
    assert "3 timing, throughput, or comparison expressions" in findings[0].message
    assert "Review candidate only" in findings[0].message
    assert "were not assessed" in findings[0].message


def test_detects_throughput_and_comparison_sections_deterministically(
    tmp_path: Path,
) -> None:
    root, paths = _copy_fixtures(tmp_path, "throughput.md", "quatops-style.md")
    policy = BenchmarkDocPolicy(include=("docs/**",))

    first = benchmark_doc_findings(root, paths, policy)
    second = benchmark_doc_findings(root, reversed(paths), policy)

    assert [(item.path, item.message) for item in first] == [
        (item.path, item.message) for item in second
    ]
    assert len(first) == 2
    encoded = json.dumps(
        [item.to_wire() for item in diagnostics_from_output("benchmark-docs", first)],
        sort_keys=True,
    )
    repeated = json.dumps(
        [item.to_wire() for item in diagnostics_from_output("benchmark-docs", second)],
        sort_keys=True,
    )
    assert encoded == repeated


@pytest.mark.parametrize(
    "name",
    (
        "ordinary-waits.md",
        "software-versions.md",
        "fenced-example.md",
        "linked-method.md",
        "benchmark-reports/dated-benchmark-report.md",
    ),
)
def test_false_positive_boundaries_are_suppressed(name: str, tmp_path: Path) -> None:
    root, paths = _copy_fixtures(tmp_path, name)
    findings = benchmark_doc_findings(
        root,
        paths,
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert findings == []


def test_exact_reasoned_exception_suppresses_only_its_section(
    tmp_path: Path,
) -> None:
    root, paths = _copy_fixtures(tmp_path, "quatops-style.md")
    policy = BenchmarkDocPolicy(
        include=("docs/**",),
        exceptions=(
            {
                "path": "docs/quatops-style.md",
                "section": "Quaternion operations",
                "reason": "This dated section is retained for the release archive.",
            },
        ),
    )

    assert benchmark_doc_findings(root, paths, policy) == []


def test_inventory_and_finding_limits_are_explicit(tmp_path: Path) -> None:
    root, paths = _copy_fixtures(tmp_path, "throughput.md", "quatops-style.md")
    policy = BenchmarkDocPolicy(include=("docs/**",), max_files=1)

    findings = benchmark_doc_findings(root, paths, policy)

    assert len(findings) == 2
    assert findings[-1].severity == "info"
    assert "only the lexically first files were analyzed" in findings[-1].message

    output_capped = benchmark_doc_findings(
        root,
        paths,
        BenchmarkDocPolicy(include=("docs/**",), max_findings=1),
    )
    assert len(output_capped) == 1
    assert output_capped[0].severity == "info"
    assert "exceeded max_findings" in output_capped[0].message


def test_oversized_selected_document_reports_incomplete_scope(tmp_path: Path) -> None:
    document = tmp_path / "README.md"
    document.write_text("# Notes\n" + "x" * 1_025, encoding="utf-8")

    findings = benchmark_doc_findings(
        tmp_path,
        [Path("README.md")],
        BenchmarkDocPolicy(include=("README.md",), max_file_bytes=1_024),
    )

    assert len(findings) == 1
    assert findings[0].severity == "info"
    assert "was not analyzed" in findings[0].message


def test_benchmark_docs_policy_is_opt_in_and_scope_is_required() -> None:
    config = load_config_stream(StringIO("schema_version = 1\n"))
    assert config.checks.benchmark_docs is None

    with pytest.raises(ValidationError):
        BenchmarkDocPolicy.model_validate({})
    with pytest.raises(ValidationError):
        BenchmarkDocPolicy(include=("../README.md",))


def test_rule_runs_through_the_policy_and_runner_catalog(tmp_path: Path) -> None:
    root, paths = _copy_fixtures(tmp_path, "quatops-style.md")
    config = load_config_stream(
        StringIO(
            "schema_version = 1\n"
            "[checks.benchmark_docs]\n"
            'include = ["docs/quatops-style.md"]\n'
        )
    )

    findings = run_builtin_rule("benchmark-docs", root, paths, config)

    assert isinstance(findings, list)
    assert len(findings) == 1
