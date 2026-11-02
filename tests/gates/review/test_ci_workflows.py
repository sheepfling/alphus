from __future__ import annotations

from pathlib import Path

import pytest

from alphus.config import CiWorkflowPolicy
from alphus.gates.review.ci_workflows import check_ci_workflows, workflow_run_findings


def policy(**updates: object) -> CiWorkflowPolicy:
    return CiWorkflowPolicy.model_validate(
        {"extensions": (".yml", ".yaml"), "exclude": (), **updates}
    )


def test_identical_static_multiline_blocks_across_matching_jobs() -> None:
    source = """name: CI
on: [push]
jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - name: Static checks
        run: |
          ruff check src
          mypy src
  audit:
    name: Audit
    runs-on: ubuntu-latest
    steps:
      - name: Static checks
        run: |
          ruff check src
          mypy src
"""
    findings = workflow_run_findings(source, ".github/workflows/ci.yml", policy())
    assert len(findings) == 1
    assert findings[0].line == 9
    assert "lint (line 9)" in findings[0].message
    assert "audit (line 17)" in findings[0].message
    assert "not proof" in findings[0].message


def test_identical_setup_action_and_inputs_across_jobs_are_reported_with_suppression() -> (
    None
):
    source = """jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          cache: pip
          python-version: '3.12'
"""
    findings = workflow_run_findings(source, ".github/workflows/ci.yml", policy())
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/repeated-workflow-setup-action")
    assert "actions/setup-python@v5" in findings[0].message
    assert "lint (line 5)" in findings[0].message
    assert "audit (line 12)" in findings[0].message
    assert "Jobs have isolated environments" in findings[0].message
    assert (
        workflow_run_findings(
            source,
            ".github/workflows/ci.yml",
            policy(ignore_setup_actions=("actions/setup-python@v5",)),
        )
        == []
    )


def test_setup_action_review_preserves_version_context_and_skips_conditions() -> None:
    versions_differ = """jobs:
  py311:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
  py312:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
"""
    assert (
        workflow_run_findings(versions_differ, ".github/workflows/ci.yml", policy())
        == []
    )

    conditional = versions_differ.replace(
        "      - uses: actions/setup-python@v5",
        "      - if: runner.os == 'Linux'\n        uses: actions/setup-python@v5",
        1,
    )
    assert (
        workflow_run_findings(conditional, ".github/workflows/ci.yml", policy()) == []
    )


def test_matrix_conditions_context_and_expressions_are_excluded() -> None:
    source = """jobs:
  linux:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.11', '3.12']
    steps:
      - run: |
          ruff check src
          mypy src
      - run: |
          python -m pytest
          python -m pytest
  linux-other-version:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.13', '3.14']
    steps:
      - run: |
          python -m pytest
          python -m pytest
  mac:
    runs-on: macos-latest
    steps:
      - if: runner.os == 'macOS'
        run: |
          ruff check src
          mypy src
  dynamic:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check ${{ inputs.path }}
          mypy src
  test:
    runs-on: ubuntu-latest
    steps:
      - run: |
          python -m pytest
          python -m pytest
"""
    assert workflow_run_findings(source, ".github/workflows/ci.yml", policy()) == []


def test_aliases_are_skipped_and_exact_script_suppression_is_supported() -> None:
    aliased = """jobs:
  one:
    runs-on: ubuntu-latest
    steps:
      - run: &checks |
          ruff check src
          mypy src
  two:
    runs-on: ubuntu-latest
    steps:
      - run: *checks
"""
    assert workflow_run_findings(aliased, ".github/workflows/ci.yml", policy()) == []

    identical = """jobs:
  one:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
  two:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
"""
    assert (
        workflow_run_findings(
            identical,
            ".github/workflows/ci.yml",
            policy(ignore_run_blocks=("ruff check src\nmypy src\n",)),
        )
        == []
    )


def test_severity_is_configurable_and_tagged_yaml_is_not_constructed() -> None:
    source = """jobs:
  one:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
  two:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
"""
    finding = workflow_run_findings(
        source, ".github/workflows/ci.yml", policy(severity="warning")
    )[0]
    assert finding.severity == "warning"
    tagged = "!!python/object/apply:os.system ['touch /tmp/not-run']"
    assert workflow_run_findings(tagged, ".github/workflows/ci.yml", policy()) == []


def test_single_line_runs_and_other_workflow_formats_are_ignored() -> None:
    source = """jobs:
  one:
    runs-on: ubuntu-latest
    steps:
      - run: ruff check src
  two:
    runs-on: ubuntu-latest
    steps:
      - run: ruff check src
"""
    assert workflow_run_findings(source, ".github/workflows/ci.yml", policy()) == []

    multiline = """jobs:
  one:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
  two:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
"""
    assert (
        workflow_run_findings(
            multiline, ".github/workflows/ci.yml", policy(minimum_run_lines=3)
        )
        == []
    )


def test_malformed_yaml_is_an_explicit_error() -> None:
    with pytest.raises(ValueError, match="cannot parse GitHub Actions workflow"):
        workflow_run_findings("jobs: [", ".github/workflows/bad.yml", policy())


def test_inventory_scope_and_exclusions_are_respected(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml")
    (tmp_path / workflow).parent.mkdir(parents=True)
    source = """jobs:
  one:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
  two:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
"""
    (tmp_path / workflow).write_text(source, encoding="utf-8")
    configured = policy(exclude=(".github/workflows/ci.yml",))
    assert check_ci_workflows(tmp_path, [workflow], configured) == []
    assert check_ci_workflows(tmp_path, [workflow], policy())


def test_explicit_matrix_invariant_allowlist_reports_only_static_repo_checks() -> None:
    script = "ruff check src\nmypy src\n"
    source = """jobs:
  checks:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.11', '3.12']
    steps:
      - run: |
          ruff check src
          mypy src
      - run: |
          python -m pytest --python ${{ matrix.python }}
          python -m pytest --python ${{ matrix.python }}
"""
    assert workflow_run_findings(source, ".github/workflows/ci.yml", policy()) == []
    result = workflow_run_findings(
        source,
        ".github/workflows/ci.yml",
        policy(matrix_invariant_run_blocks=(script,)),
    )
    assert len(result) == 1
    assert "each matrix leg" in result[0].message


def test_azure_static_scripts_match_only_when_job_context_is_simple() -> None:
    source = """jobs:
- job: lint
  pool: ubuntu-latest
  steps:
  - bash: |
      ruff check src
      mypy src
- job: audit
  pool: ubuntu-latest
  steps:
  - bash: |
      ruff check src
      mypy src
"""
    configured = policy(azure_workflow_paths=("azure-pipelines.yml",))
    assert len(workflow_run_findings(source, "azure-pipelines.yml", configured)) == 1
    conditional = source.replace(
        "  pool: ubuntu-latest", "  condition: succeeded()\n  pool: ubuntu-latest", 1
    )
    assert workflow_run_findings(conditional, "azure-pipelines.yml", configured) == []
