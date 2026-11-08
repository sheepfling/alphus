"""Verify typed feature registration and lazy dispatch for line length."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.hygiene.line_length import check_line_length, run_line_length_feature
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.plugins.builtin_registry import load_builtin_feature
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS


def _config() -> QualityGateConfig:
    return QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {"line_length": {"limits": {".py": 3}}},
        },
        strict=True,
    )


def test_line_length_registers_a_typed_finding_runner() -> None:
    definition = FEATURE_DEFINITIONS["line-length"]
    spec = RULE_SPECS["line-length"]
    feature = load_builtin_feature("line-length")

    assert isinstance(feature, FindingBuiltinFeature)
    assert feature.runner is run_line_length_feature
    assert definition.policy_field == spec.policy_field == "line_length"
    assert definition.output_shape == spec.output_shape.value == "findings"
    assert definition.summary == spec.summary
    assert definition.policy_model.__name__ == "LineLengthPolicy"


def test_line_length_typed_dispatch_preserves_findings(tmp_path: Path) -> None:
    relative = Path("src/example.py")
    (tmp_path / relative).parent.mkdir()
    (tmp_path / relative).write_text("value = 1\n", encoding="utf-8")
    config = _config()

    registered = run_builtin_rule("line-length", tmp_path, [relative], config)
    direct: list[Finding] = check_line_length(tmp_path, [relative], config)

    assert registered == direct
    assert [(finding.rule_id, finding.path, finding.line) for finding in direct] == [
        ("alphus/any/none/style/line-too-long", "src/example.py", 1)
    ]


def test_line_length_policy_remains_strict() -> None:
    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {"line_length": {"unexpected": True}},
            },
            strict=True,
        )


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
