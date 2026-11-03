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


def test_long_static_inline_script_is_configurable_and_suppressible() -> None:
    script = """echo prepare
python -m pip install -e .
ruff check src
mypy src
python -m pytest -q
"""
    source = """jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo prepare
          python -m pip install -e .
          ruff check src
          mypy src
          python -m pytest -q
"""
    configured = policy(maximum_inline_run_lines=5)
    findings = workflow_run_findings(source, ".github/workflows/ci.yml", configured)
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/long-inline-workflow-script")
    assert "5 nonblank lines" in findings[0].message
    assert "job 'checks' (line 5)" in findings[0].message

    assert (
        workflow_run_findings(
            source,
            ".github/workflows/ci.yml",
            policy(maximum_inline_run_lines=6),
        )
        == []
    )
    assert (
        workflow_run_findings(
            source,
            ".github/workflows/ci.yml",
            policy(maximum_inline_run_lines=5, ignore_run_blocks=(script,)),
        )
        == []
    )


def test_inline_script_threshold_is_independent_of_duplicate_block_threshold() -> None:
    commands = [f"echo step-{index}" for index in range(1, 26)]
    source = (
        "jobs:\n  checks:\n    runs-on: ubuntu-latest\n    steps:\n      - run: |\n"
    )
    source += "".join(f"          {command}\n" for command in commands)

    findings = workflow_run_findings(
        source,
        ".github/workflows/ci.yml",
        policy(minimum_run_lines=50, maximum_inline_run_lines=20),
    )

    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/long-inline-workflow-script")
    assert "25 nonblank lines" in findings[0].message


def test_folded_yaml_script_counts_physical_nonblank_source_lines() -> None:
    commands = [f"echo step-{index}" for index in range(1, 22)]
    source = (
        "jobs:\n  checks:\n    runs-on: ubuntu-latest\n    steps:\n      - run: >\n"
    )
    source += "".join(f"          {command}\n" for command in commands)

    findings = workflow_run_findings(
        source,
        ".github/workflows/ci.yml",
        policy(minimum_run_lines=50, maximum_inline_run_lines=20),
    )

    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/long-inline-workflow-script")
    assert "21 nonblank lines" in findings[0].message


def test_long_script_review_skips_contextual_and_unallowlisted_matrix_commands() -> (
    None
):
    matrix = """jobs:
  checks:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.11', '3.12']
    steps:
      - run: |
          echo prepare
          python -m pip install -e .
          ruff check src
          mypy src
          python -m pytest --python ${{ matrix.python }}
"""
    conditional = matrix.replace(
        "      - run: |", "      - if: runner.os == 'Linux'\n        run: |"
    ).replace("    strategy:\n      matrix:\n        python: ['3.11', '3.12']\n", "")
    configured = policy(maximum_inline_run_lines=5)
    assert workflow_run_findings(matrix, ".github/workflows/ci.yml", configured) == []
    assert (
        workflow_run_findings(conditional, ".github/workflows/ci.yml", configured) == []
    )


def test_long_azure_inline_script_uses_the_same_threshold() -> None:
    source = """jobs:
- job: checks
  pool: ubuntu-latest
  steps:
  - bash: |
      echo prepare
      python -m pip install -e .
      ruff check src
      mypy src
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'
"""
    findings = workflow_run_findings(
        source,
        "azure-pipelines.yml",
        policy(
            azure_workflow_paths=("azure-pipelines.yml",),
            maximum_inline_run_lines=4,
        ),
    )
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/long-inline-workflow-script")
    assert "4 nonblank lines" in findings[0].message


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


def test_matrix_invariant_allowlist_does_not_turn_single_job_into_a_matrix() -> None:
    script = "ruff check src\nmypy src\n"
    source = """jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ruff check src
          mypy src
"""

    assert (
        workflow_run_findings(
            source,
            ".github/workflows/ci.yml",
            policy(matrix_invariant_run_blocks=(script,)),
        )
        == []
    )


def test_singleton_matrix_does_not_report_one_run_as_repetition() -> None:
    script = "ruff check src\nmypy src\n"
    source = """jobs:
  checks:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.11']
    steps:
      - run: |
          ruff check src
          mypy src
"""

    assert (
        workflow_run_findings(
            source,
            ".github/workflows/ci.yml",
            policy(matrix_invariant_run_blocks=(script,)),
        )
        == []
    )


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


def test_azure_matrix_repository_checks_require_an_explicit_static_allowlist() -> None:
    script = "ruff check src\nmypy src\n"
    source = """jobs:
- job: checks
  pool:
    vmImage: ubuntu-latest
  strategy:
    matrix:
      python311:
        PYTHON_VERSION: '3.11'
      python312:
        PYTHON_VERSION: '3.12'
  steps:
  - bash: |
      ruff check src
      mypy src
  - task: UsePythonVersion@0
    inputs:
      versionSpec: $(PYTHON_VERSION)
"""
    configured = policy(azure_workflow_paths=("azure-pipelines.yml",))
    assert workflow_run_findings(source, "azure-pipelines.yml", configured) == []

    allowed = policy(
        azure_workflow_paths=("azure-pipelines.yml",),
        matrix_invariant_run_blocks=(script,),
    )
    findings = workflow_run_findings(source, "azure-pipelines.yml", allowed)
    assert len(findings) == 1
    assert "each matrix leg" in findings[0].message
    assert "not proof" in findings[0].message
    assert "UsePythonVersion" not in findings[0].message


@pytest.mark.parametrize(
    ("strategy", "script"),
    [
        (
            """      matrix:
        python311:
          PYTHON_VERSION: '3.11'
        python312:
          PYTHON_VERSION: '3.12'""",
            "ruff check $PYTHON_VERSION\nmypy src\n",
        ),
        (
            """      matrix:
        python311:
          PYTHON_VERSION: '3.11'
        python312:
          PYTHON_VERSION: '3.12'
      maxParallel: 2""",
            "ruff check src\nmypy src\n",
        ),
    ],
)
def test_azure_matrix_skips_variable_dependent_or_unrecognized_context(
    strategy: str, script: str
) -> None:
    source = f"""jobs:
- job: checks
  pool: ubuntu-latest
  strategy:
{strategy}
  steps:
  - bash: |
      {script.replace(chr(10), chr(10) + "      ").rstrip()}
"""
    configured = policy(
        azure_workflow_paths=("azure-pipelines.yml",),
        matrix_invariant_run_blocks=(script,),
    )
    assert workflow_run_findings(source, "azure-pipelines.yml", configured) == []


def test_azure_repeated_setup_tasks_require_matching_static_pool_and_inputs() -> None:
    source = """jobs:
- job: lint
  pool:
    vmImage: ubuntu-latest
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'
      addToPath: true
- job: audit
  pool:
    vmImage: ubuntu-latest
  steps:
  - task: UsePythonVersion@0
    inputs:
      addToPath: true
      versionSpec: '3.12'
"""
    findings = workflow_run_findings(
        source,
        "azure-pipelines.yml",
        policy(azure_workflow_paths=("azure-pipelines.yml",)),
    )

    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/repeated-workflow-setup-action")
    assert "UsePythonVersion@0" in findings[0].message
    assert "lint (line 6)" in findings[0].message
    assert "audit (line 14)" in findings[0].message
    assert "not a recommendation to remove setup" in findings[0].message


def test_azure_setup_task_advisory_skips_context_and_different_inputs() -> None:
    configured = policy(azure_workflow_paths=("azure-pipelines.yml",))
    versioned = """jobs:
- job: py311
  pool: ubuntu-latest
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.11'
- job: py312
  pool: ubuntu-latest
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'
"""
    assert workflow_run_findings(versioned, "azure-pipelines.yml", configured) == []

    different_pool = """jobs:
- job: linux
  pool:
    vmImage: ubuntu-latest
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'
- job: windows
  pool:
    vmImage: windows-latest
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'
"""
    assert (
        workflow_run_findings(different_pool, "azure-pipelines.yml", configured) == []
    )

    contextual = """jobs:
- job: one
  pool: ubuntu-latest
  condition: succeeded()
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'
- job: two
  pool: ubuntu-latest
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'
"""
    assert workflow_run_findings(contextual, "azure-pipelines.yml", configured) == []

    dynamic = """jobs:
- job: one
  pool:
    vmImage: $(agentImage)
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: $(pythonVersion)
- job: two
  pool:
    vmImage: $(agentImage)
  steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: $(pythonVersion)
"""
    assert workflow_run_findings(dynamic, "azure-pipelines.yml", configured) == []
