"""Verify feature-owned registration for the repository-layout check."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig, RepositoryLayoutPolicy
from alphus.contracts.findings import Finding
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.repository.repository_layout import (
    ALPHUS_FEATURE,
    check_repository_layout,
    resolve_repository_layout_policy,
    run_repository_layout_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.plugins.builtin_registry import builtin_check_entry_points
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS


def _config() -> QualityGateConfig:
    return QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "repository_layout": {
                    "required_paths": [
                        {"path": "src/required.py", "message": "required file missing"}
                    ]
                }
            },
        },
        strict=True,
    )


def test_repository_layout_definition_owns_strict_policy_and_runner() -> None:
    definition = FEATURE_DEFINITIONS["repository-layout"]
    spec = RULE_SPECS["repository-layout"]

    assert definition.policy_field == spec.policy_field == "repository_layout"
    assert definition.policy_inputs == ("repository_layout",)
    assert definition.output_shape == spec.output_shape.value == "findings"
    assert definition.summary == (
        "Checks configured repository paths, required files, and layout rules."
    )
    assert builtin_check_entry_points()["repository-layout"].value == (
        "alphus.gates.repository.repository_layout:ALPHUS_FEATURE"
    )


def test_repository_layout_dispatch_preserves_strict_config_and_finding_id(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    findings = cast(
        list[Finding],
        run_builtin_rule("repository-layout", tmp_path, (), _config()),
    )

    assert [(item.rule_id, item.path, item.message) for item in findings] == [
        (
            "alphus/repository/none/configuration/path-required",
            "src/required.py",
            "required file missing",
        )
    ]
    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {
                    "repository_layout": {
                        "required_paths": [],
                        "unknown_setting": True,
                    }
                },
            },
            strict=True,
        )


def test_unselected_repository_layout_runner_remains_unimported(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from alphus.config import QualityGateConfig, RepositoryLayoutPolicy
from alphus.execution.dispatch import run_builtin_rule

module = "alphus.gates.repository.repository_layout"
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


def test_typed_feature_runner_matches_legacy_repository_layout_result(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    policy = RepositoryLayoutPolicy.model_validate(
        {"required_paths": [{"path": "src/required.py", "message": "missing"}]}
    )
    config = QualityGateConfig.model_validate(
        {"schema_version": 1, "checks": {"repository_layout": policy}}, strict=True
    )

    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is RepositoryLayoutPolicy
    resolved = resolve_repository_layout_policy(config)
    assert type(resolved) is RepositoryLayoutPolicy
    expected = check_repository_layout(tmp_path, policy)
    assert expected
    assert run_repository_layout_feature(tmp_path, (), resolved) == expected
    assert run_builtin_rule("repository-layout", tmp_path, (), config) == expected
