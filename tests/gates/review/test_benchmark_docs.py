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
from alphus.gates.review.benchmark_docs import _sections, benchmark_doc_findings

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


def test_synthetic_quatops_style_prose_is_one_candidate(tmp_path: Path) -> None:
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


def test_benchmark_heading_provides_context_for_measurements(tmp_path: Path) -> None:
    root = tmp_path
    relative = Path("docs/benchmark-heading.md")
    source = root / relative
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Benchmarks\n\nScalar: 0.42 ms; vector: 0.13 ms.\n",
        encoding="utf-8",
    )

    findings = benchmark_doc_findings(
        root,
        [relative],
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert len(findings) == 1
    assert findings[0].path == "docs/benchmark-heading.md"
    assert findings[0].line == 1
    assert "2 timing, throughput, or comparison expressions" in findings[0].message


def test_benchmark_context_is_inherited_by_subsections(tmp_path: Path) -> None:
    root = tmp_path
    relative = Path("docs/benchmark-subsection.md")
    source = root / relative
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Benchmarks\n\n## Small input\n\nScalar: 0.42 ms; vector: 0.13 ms.\n",
        encoding="utf-8",
    )

    findings = benchmark_doc_findings(
        root,
        [relative],
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert len(findings) == 1
    assert findings[0].line == 3
    assert "Small input" in findings[0].message


def test_setext_headings_separate_methodology_from_benchmark_sections(
    tmp_path: Path,
) -> None:
    root = tmp_path
    relative = Path("docs/setext-benchmark.md")
    source = root / relative
    source.parent.mkdir(parents=True)
    source.write_text(
        "Setup\n=====\nSee [methodology](benchmark-method.md).\n\n"
        "Benchmarks\n==========\n"
        "Scalar: 0.42 ms; vector: 0.13 ms.\n",
        encoding="utf-8",
    )

    findings = benchmark_doc_findings(
        root,
        [relative],
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert len(findings) == 1
    assert findings[0].line == 5
    assert "Benchmarks" in findings[0].message


def test_setext_section_name_can_be_used_for_reasoned_exception(
    tmp_path: Path,
) -> None:
    root = tmp_path
    relative = Path("docs/setext-exception.md")
    source = root / relative
    source.parent.mkdir(parents=True)
    source.write_text(
        "Benchmarks\n==========\nScalar: 0.42 ms; vector: 0.13 ms.\n",
        encoding="utf-8",
    )

    findings = benchmark_doc_findings(
        root,
        [relative],
        BenchmarkDocPolicy(
            include=("docs/**",),
            exceptions=(
                {
                    "path": relative.as_posix(),
                    "section": "Benchmarks",
                    "reason": "This historical benchmark section remains useful.",
                },
            ),
        ),
    )

    assert findings == []


def test_heading_context_is_shared_across_many_subsections() -> None:
    parent = "Benchmark " + "context " * 1_000
    lines = [f"# {parent}"]
    for index in range(2_000):
        lines.extend((f"## Case {index}", "A short section."))

    sections = iter(_sections(lines))
    first = next(sections)
    second = next(sections)

    assert isinstance(first[3], tuple)
    assert len(first[3]) == 2
    assert first[3][0] is second[3][0]


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
        "quatops-real-procedure.md",
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


def test_reference_style_method_link_resolves_across_document(tmp_path: Path) -> None:
    root, paths = _copy_fixtures(tmp_path, "linked-method-reference.md")

    findings = benchmark_doc_findings(
        root,
        paths,
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert findings == []


def test_reference_definition_alone_does_not_suppress_benchmark_section(
    tmp_path: Path,
) -> None:
    root, paths = _copy_fixtures(
        tmp_path,
        "reference-definition-without-use.md",
    )

    findings = benchmark_doc_findings(
        root,
        paths,
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert len(findings) == 1
    assert findings[0].line == 5
    assert "2 timing, throughput, or comparison expressions" in findings[0].message


def test_many_unmatched_open_brackets_do_not_hide_benchmark_candidate(
    tmp_path: Path,
) -> None:
    root = tmp_path
    relative = Path("docs/unmatched-brackets.md")
    source = root / relative
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Benchmarks\n\nScalar: 0.42 ms; vector: 0.13 ms.\n" + "[" * 32_000,
        encoding="utf-8",
    )

    findings = benchmark_doc_findings(
        root,
        [relative],
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert len(findings) == 1
    assert findings[0].line == 1


@pytest.mark.parametrize("link", ("[methodology][missing]", "[method]"))
def test_undefined_method_reference_does_not_suppress_benchmark_candidate(
    link: str, tmp_path: Path
) -> None:
    root = tmp_path
    relative = Path("docs/undefined-method-reference.md")
    source = root / relative
    source.parent.mkdir(parents=True)
    source.write_text(
        f"# Benchmarks\n\nSee {link}.\n\nScalar: 0.42 ms; vector: 0.13 ms.\n",
        encoding="utf-8",
    )

    findings = benchmark_doc_findings(
        root,
        [relative],
        BenchmarkDocPolicy(include=("docs/**",)),
    )

    assert len(findings) == 1
    assert findings[0].line == 1


def test_exact_reasoned_exception_suppresses_only_its_section(
    tmp_path: Path,
) -> None:
    root, paths = _copy_fixtures(tmp_path, "quatops-style.md")
    policy = BenchmarkDocPolicy(
        include=("docs/**",),
        exceptions=(
            {
                "path": "docs/quatops-style.md",
                "section": "Synthetic QuatOps-style example (invented values)",
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
