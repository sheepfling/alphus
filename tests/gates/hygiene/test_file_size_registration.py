"""Verify feature-owned hygiene registration and lazy provider loading."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus import check_file_size, check_line_length
from alphus.config import QualityGateConfig
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS


def test_feature_definition_generates_the_existing_catalog_contract() -> None:
    definition = FEATURE_DEFINITIONS["file-size"]
    spec = RULE_SPECS["file-size"]

    assert definition.policy_field == spec.policy_field == "file_size"
    assert definition.output_shape == spec.output_shape.value == "findings"
    assert definition.summary == spec.summary
    assert definition.runner_module == "alphus.gates.hygiene.file_size"
    assert definition.runner_name == "check_file_size"
    assert check_file_size.__module__ == definition.runner_module
    line_definition = FEATURE_DEFINITIONS["line-length"]
    line_spec = RULE_SPECS["line-length"]
    assert line_definition.policy_field == line_spec.policy_field == "line_length"
    assert line_definition.output_shape == line_spec.output_shape.value == "findings"
    assert (
        line_definition.summary
        == line_spec.summary
        == ("Reports source lines that exceed configured per-extension limits.")
    )
    assert line_definition.policy_model == "alphus.policy.sources.LineLengthPolicy"
    assert line_definition.runner_module == "alphus.gates.hygiene.line_length"
    assert line_definition.runner_name == "check_line_length"
    assert check_line_length.__module__ == line_definition.runner_module


def test_feature_owned_policies_remain_strict() -> None:
    valid = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {"line_length": {"limits": {".py": 88}}},
        },
        strict=True,
    )

    assert valid.checks.line_length is not None
    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {"line_length": {"unexpected": True}},
            },
            strict=True,
        )


def test_unselected_file_size_provider_imports_only_after_dispatch(
    pytestconfig: pytest.Config,
) -> None:
    root = Path(pytestconfig.rootpath)
    script = """
import sys
from pathlib import Path
from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule

provider = "alphus.gates.hygiene.file_size"
print("before", provider in sys.modules)
config = QualityGateConfig.model_validate({
    "schema_version": 1,
    "checks": {
        "file_size": {
            "code_extensions": [".py"],
            "code_limit": 100,
            "hard_limit": 200,
            "initializer_name": "__init__.py",
            "initializer_limit": 100,
        }
    },
})
run_builtin_rule("file-size", Path.cwd(), (), config)
print("after", provider in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["before False", "after True"]


def test_line_length_provider_is_lazy_and_selected_by_generated_dispatch(
    pytestconfig: pytest.Config,
) -> None:
    root = Path(pytestconfig.rootpath)
    script = """
import sys
from pathlib import Path
from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule

provider = "alphus.gates.hygiene.line_length"
other_provider = "alphus.gates.hygiene.file_size"
print("before", provider in sys.modules, other_provider in sys.modules)
config = QualityGateConfig.model_validate({
    "schema_version": 1,
    "checks": {"line_length": {"limits": {".py": 88}}},
})
run_builtin_rule("line-length", Path.cwd(), (), config)
print("after", provider in sys.modules, other_provider in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "before False False",
        "after True False",
    ]
