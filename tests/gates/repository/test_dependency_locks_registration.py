"""Verify feature-owned registration for dependency-lock checks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.execution.dispatch import run_builtin_rule
from alphus.plugins.builtin_registry import builtin_check_entry_points
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS


def _config() -> QualityGateConfig:
    return QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "dependency_locks": {
                    "pairs": [
                        {
                            "input_file": "requirements.txt",
                            "lock_file": "locks.txt",
                        }
                    ]
                }
            },
        },
        strict=True,
    )


def test_dependency_lock_definition_owns_its_policy_and_runner() -> None:
    definition = FEATURE_DEFINITIONS["dependency-locks"]
    spec = RULE_SPECS["dependency-locks"]

    assert definition.policy_field == spec.policy_field == "dependency_locks"
    assert definition.policy_inputs == ("dependency_locks",)
    assert definition.output_shape == spec.output_shape.value == "findings"
    assert definition.summary == (
        "Checks consistency and pairing of configured dependency lockfiles."
    )
    assert builtin_check_entry_points()["dependency-locks"].value == (
        "alphus.gates.repository.dependency_locks:ALPHUS_FEATURE"
    )


def test_dependency_lock_dispatch_keeps_strict_config_and_finding_id(
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements.txt").write_text("sample-lib>=1.0\n", encoding="utf-8")
    (tmp_path / "locks.txt").write_text("sample-lib==0.5.0\n", encoding="utf-8")
    findings = cast(
        list[Finding],
        run_builtin_rule("dependency-locks", tmp_path, (), _config()),
    )

    assert [(item.rule_id, item.path, item.message) for item in findings] == [
        (
            "alphus/repository/none/dependencies/requirement-pin-unsatisfied",
            "locks.txt",
            "sample-lib pin does not satisfy requirements.txt",
        )
    ]
    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {
                    "dependency_locks": {
                        "pairs": [],
                        "unknown_setting": True,
                    }
                },
            },
            strict=True,
        )


def test_unselected_dependency_lock_runner_remains_unimported(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule

module = "alphus.gates.repository.dependency_locks"
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
