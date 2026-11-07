"""Verify composite package-boundaries feature registration contracts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.plugins.builtin_registry import builtin_check_entry_points
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS


def _config() -> QualityGateConfig:
    return QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "package_boundaries": {
                    "metadata_patterns": ["**/pyproject.toml"],
                    "source_directory": "src",
                    "allowed_dependencies": {"workspace": []},
                }
            },
        },
        strict=True,
    )


def test_composite_definition_owns_its_registration_and_policy_inputs() -> None:
    definition = FEATURE_DEFINITIONS["package-boundaries"]
    spec = RULE_SPECS["package-boundaries"]

    assert definition.policy_field == spec.policy_field == "package_boundaries"
    assert definition.policy_inputs == (
        "package_boundaries",
        "architecture_graph",
        "version_sync",
        "callable_registry",
    )
    assert spec.output_shape.value == definition.output_shape == "findings"
    assert spec.summary == definition.summary
    assert builtin_check_entry_points()["package-boundaries"].value == (
        "alphus.gates.repository.package_boundaries:ALPHUS_FEATURE"
    )


def test_composite_config_is_strict_and_dispatch_preserves_finding_contract(
    tmp_path: Path,
) -> None:
    config = _config()
    assert config.checks.package_boundaries is not None
    findings = run_builtin_rule("package-boundaries", tmp_path, (), config)
    assert findings == []

    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {"package_boundaries": {"unexpected": True}},
            },
            strict=True,
        )


def test_unselected_composite_providers_remain_unimported(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule

providers = (
    "alphus.gates.repository.package_boundaries",
    "alphus.gates.repository.architecture_graph",
    "alphus.gates.repository.version_sync",
    "alphus.gates.repository.callable_registry",
)
print("before", tuple(name in sys.modules for name in providers))
run_builtin_rule("file-size", Path.cwd(), (), QualityGateConfig.model_validate({
    "schema_version": 1,
    "checks": {"file_size": {
        "code_extensions": [".py"],
        "code_limit": 100,
        "hard_limit": 200,
        "initializer_name": "__init__.py",
        "initializer_limit": 100,
    }},
}, strict=True))
print("unselected", tuple(name in sys.modules for name in providers))
package_config = QualityGateConfig.model_validate({
    "schema_version": 1,
    "checks": {"package_boundaries": {
        "metadata_patterns": ["**/pyproject.toml"],
        "source_directory": "src",
        "allowed_dependencies": {"workspace": []},
    }},
}, strict=True)
run_builtin_rule("package-boundaries", Path.cwd(), (), package_config)
print("selected", tuple(name in sys.modules for name in providers))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "before (False, False, False, False)",
        "unselected (False, False, False, False)",
        "selected (True, False, False, False)",
    ]
