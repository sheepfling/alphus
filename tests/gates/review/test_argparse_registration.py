"""Feature-owned argparse registration preserves the opt-in AST-only contract."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review.argparse_precedence import (
    ALPHUS_FEATURE,
    ALPHUS_MORPHOLOGY,
    resolve_argparse_precedence_policy,
    run_argparse_precedence_feature,
)
from alphus.plugins.builtin_registry import builtin_check_entry_points
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS
from alphus.policy.morphology import EvaluationMaturity
from alphus.policy.review import ArgparsePrecedencePolicy


def test_argparse_feature_owns_strict_policy_and_entry_point() -> None:
    definition = FEATURE_DEFINITIONS["argparse-precedence"]
    spec = RULE_SPECS["argparse-precedence"]
    assert definition.policy_field == spec.policy_field == "argparse_precedence"
    assert definition.policy_inputs == ("argparse_precedence",)
    assert definition.output_shape == spec.output_shape.value == "findings"
    assert definition.summary == spec.summary
    assert definition.input_mode == "configured-source-scan"
    assert ALPHUS_FEATURE.definition.policy_model is ArgparsePrecedencePolicy
    assert ALPHUS_MORPHOLOGY.evaluation_maturity is EvaluationMaturity.SYNTHETIC_ONLY
    assert builtin_check_entry_points()["argparse-precedence"].value == (
        "alphus.gates.review.argparse_precedence:ALPHUS_FEATURE"
    )


def test_registered_argparse_runner_matches_direct_result_without_execution(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "must-not-exist"
    source = tmp_path / "cli.py"
    source.write_text(
        "import argparse\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--output', default='root.txt')\n"
        "commands = parser.add_subparsers()\n"
        "child = commands.add_parser('run')\n"
        "child.add_argument('--output', default='child.txt')\n"
        "def never_call():\n"
        f"    open({str(sentinel)!r}, 'w').write('executed')\n",
        encoding="utf-8",
    )
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "argparse_precedence": {
                    "extensions": [".py"],
                    "source_paths": ["*.py"],
                }
            },
        },
        strict=True,
    )
    policy = resolve_argparse_precedence_policy(config)
    selected = (Path("cli.py"),)
    direct = run_argparse_precedence_feature(tmp_path, selected, policy)
    assert direct
    assert run_builtin_rule("argparse-precedence", tmp_path, selected, config) == direct
    assert all(item.rule_id.endswith("argparse-default-overwrite") for item in direct)
    assert not sentinel.exists()


def test_argparse_policy_is_optional_and_rejects_unknown_fields() -> None:
    assert (
        QualityGateConfig.model_validate(
            {"schema_version": 1}
        ).checks.argparse_precedence
        is None
    )
    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {
                    "argparse_precedence": {
                        "extensions": [".py"],
                        "source_paths": ["*.py"],
                        "unexpected": True,
                    }
                },
            },
            strict=True,
        )
