"""Verify feature-owned hygiene registration and lazy provider loading."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from alphus.gates.hygiene.file_size import run_file_size_feature
from alphus.plugins.builtin_registry import load_builtin_feature
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS


def test_feature_definition_generates_the_existing_catalog_contract() -> None:
    definition = FEATURE_DEFINITIONS["file-size"]
    spec = RULE_SPECS["file-size"]

    assert definition.policy_field == spec.policy_field == "file_size"
    assert definition.output_shape == spec.output_shape.value == "findings"
    assert definition.summary == spec.summary
    assert load_builtin_feature("file-size").runner is run_file_size_feature


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
