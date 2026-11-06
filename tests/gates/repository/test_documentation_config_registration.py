"""Verify feature-owned registration for the documentation/config heuristic."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.execution.dispatch import RULE_RUNNERS, run_builtin_rule
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS
from alphus.support.git import run_git


def _config() -> QualityGateConfig:
    return QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "documentation_config": {
                    "source_patterns": ["src/**/*.py"],
                    "documentation_patterns": ["docs/**/*.md"],
                }
            },
        },
        strict=True,
    )


def test_documentation_config_definition_owns_heuristic_and_runner() -> None:
    definition = FEATURE_DEFINITIONS["documentation-config"]
    spec = RULE_SPECS["documentation-config"]

    assert definition.policy_field == spec.policy_field == "documentation_config"
    assert definition.policy_inputs == ("documentation_config",)
    assert definition.output_shape == spec.output_shape.value == "findings"
    assert definition.summary == (
        "Checks documentation links and repository-specific documentation "
        "configuration."
    )
    assert definition.runner_module == "alphus.gates.repository.documentation_config"
    assert definition.runner_name == "run_documentation_config_gate"
    assert RULE_RUNNERS["documentation-config"].__module__ == (
        "alphus.execution._generated_dispatch"
    )


def test_direct_dispatch_preserves_advisory_conflict_finding(tmp_path: Path) -> None:
    source = tmp_path / "src" / "settings.py"
    guide = tmp_path / "docs" / "guide.md"
    source.parent.mkdir()
    guide.parent.mkdir()
    source.write_text("MAX_WORKERS = 4\n", encoding="utf-8")
    guide.write_text("MAX_WORKERS is 9.\n", encoding="utf-8")
    assert run_git(tmp_path, "init", "--quiet").returncode == 0
    assert run_git(tmp_path, "add", "src/settings.py", "docs/guide.md").returncode == 0

    findings = cast(
        list[Finding],
        run_builtin_rule("documentation-config", tmp_path, (), _config()),
    )

    assert [
        (item.rule_id, item.path, item.line, item.severity) for item in findings
    ] == [
        (
            "alphus/repository/none/configuration/documented-config-conflict",
            "docs/guide.md",
            1,
            "warning",
        )
    ]
    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {
                    "documentation_config": {
                        "source_patterns": [],
                        "documentation_patterns": [],
                        "unknown_setting": True,
                    }
                },
            },
            strict=True,
        )


def test_unselected_documentation_runner_remains_unimported(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule

module = "alphus.gates.repository.documentation_config"
config = QualityGateConfig.model_validate({
    "schema_version": 1,
    "checks": {"file_size": {
        "code_extensions": [".py"],
        "code_limit": 100,
        "hard_limit": 200,
        "initializer_name": "__init__.py",
        "initializer_limit": 100,
    }},
}, strict=True)
run_builtin_rule("file-size", Path.cwd(), (), config)
print(module in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
