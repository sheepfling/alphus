"""Validated semantic intents remain explicit about native coverage."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import (
    CommandRunStep,
    FileInventoryPolicy,
    NativeCapabilityBinding,
    OrchestrationPolicy,
    OrchestrationProfile,
    SharedQualityIntent,
    load_config,
)
from alphus.policy.intents import intent_bindings_for_steps

_EXAMPLE = Path("examples/shared-intents/quality-gates.toml")


def _binding(
    *,
    mapping: str = "exact",
    metric: str = "cyclomatic_complexity",
    unit: str = "decision_paths",
    count_method: str = "McCabe decision count starting at one",
    threshold: int = 10,
    step: str | None = "Complexity",
) -> NativeCapabilityBinding:
    return NativeCapabilityBinding(
        language="python",
        backend="ruff",
        version_range=">=0.16,<1",
        native_rule="C901",
        metric=metric,
        unit=unit,
        count_method=count_method,
        mapping=mapping,  # type: ignore[arg-type]
        step=step,
        supported_options=("max-complexity",),
        threshold_option="max-complexity",
        effective_configuration=(("max-complexity", threshold),),
        violation_exit_codes=(1,),
        configuration_exit_codes=(2,),
    )


def _intent(
    binding: NativeCapabilityBinding | None = None,
    *,
    threshold: int | None = 10,
    overrides: tuple[dict[str, object], ...] = (),
) -> SharedQualityIntent:
    return SharedQualityIntent.model_validate(
        {
            "rule_id": "alphus/any/none/maintainability/function-complexity-review",
            "summary": "Review functions that exceed a complexity limit.",
            "metric": "cyclomatic_complexity",
            "unit": "decision_paths",
            "count_method": "McCabe decision count starting at one",
            "threshold": threshold,
            "rollout": "provisional",
            "profiles": ["check"],
            "files": {"include": ["**/*.py"], "exclude": ["**/generated/**"]},
            "overrides": overrides,
            "bindings": [binding or _binding(threshold=threshold or 10)],
        }
    )


def _policy(intent: SharedQualityIntent) -> OrchestrationPolicy:
    return OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="Complexity",
                argv=("ruff", "check", "{files}"),
                files=FileInventoryPolicy(
                    include=("**/*.py",), exclude=("**/generated/**",)
                ),
                rollout="provisional",
            ),
        ),
        profiles=(OrchestrationProfile(name="check", steps=("Complexity",)),),
        intents=(intent,),
    )


def test_polyglot_example_documents_exact_and_comparable_mappings() -> None:
    config = load_config(_EXAMPLE)
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    assert check is not None

    rows = intent_bindings_for_steps(policy.intents, check.steps, "check")
    assert [(row["language"], row["mapping"]) for row in rows] == [
        ("cpp", "comparable"),
        ("javascript", "comparable"),
        ("python", "exact"),
    ]
    assert [row["threshold"] for row in rows] == [6, 10, 12]
    assert all(row["status"] == "supported" for row in rows)
    assert all(row["evidence_step"] == row["step"] for row in rows)
    assert rows[0]["files"] == {
        "include": ("cpp/**/*.cpp",),
        "exclude": ("**/generated/**",),
    }
    assert rows[0]["threshold_values"] == {6: "6"}
    warning_rows = intent_bindings_for_steps(
        policy.intents,
        check.steps,
        "check",
        default_failure_threshold="warning",
    )
    assert {row["failure_threshold"] for row in warning_rows} == {"warning"}
    assert json.dumps(rows, sort_keys=True) == json.dumps(
        intent_bindings_for_steps(policy.intents, check.steps, "check"),
        sort_keys=True,
    )


def test_polyglot_example_cli_plan_shows_commands_and_native_provenance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _EXAMPLE.parent.resolve()
    assert (
        main(
            [
                "--root",
                str(root),
                "--config",
                "quality-gates.toml",
                "--plan",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert [step["name"] for step in payload["steps"]] == [
        "Python cyclomatic complexity",
        "C++ function branches",
        "JavaScript cyclomatic complexity",
    ]
    rows = payload["intents"]
    assert [(row["language"], row["native_rule"]) for row in rows] == [
        ("cpp", "readability-function-size.BranchThreshold"),
        ("javascript", "complexity"),
        ("python", "C901"),
    ]
    assert all(row["selected_files"] for row in rows)
    assert all(row["expanded_argv"] for row in rows)
    assert rows[2]["evidence_format"] == "json-array"


def test_installed_example_backend_versions_fit_declared_ranges() -> None:
    config = load_config(_EXAMPLE)
    assert config.orchestration is not None
    executables = {"ruff": "ruff", "clang-tidy": "clang-tidy", "eslint": "eslint"}
    checked = 0
    for intent in config.orchestration.intents:
        for binding in intent.bindings:
            executable = executables[binding.backend]
            path = shutil.which(executable)
            if path is None:
                continue
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            version_text = f"{result.stdout} {result.stderr}"
            match = re.search(r"(?<![0-9])v?(\d+\.\d+(?:\.\d+)?)", version_text)
            assert match is not None, version_text
            assert Version(match.group(1)) in SpecifierSet(binding.version_range)
            checked += 1
    if not checked:
        pytest.skip("none of the example's optional native tools are installed")


def test_installed_ruff_runs_the_python_example_without_installing_tools() -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff is an optional native checker")
    result = subprocess.run(
        [ruff, "check", "--output-format=json", "python/function_complexity.py"],
        cwd=_EXAMPLE.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_exact_mapping_requires_the_same_measurement_and_count_method() -> None:
    binding = _binding(metric="branch_count")
    with pytest.raises(ValidationError, match="exact mapping"):
        _intent(binding)


def test_comparable_mapping_requires_explicit_language_threshold() -> None:
    binding = _binding(
        mapping="comparable",
        metric="branch_count",
        unit="branches",
        count_method="Count control-flow branches",
    )
    with pytest.raises(ValidationError, match="requires exact mappings"):
        _intent(binding)


def test_comparable_mapping_can_use_an_explicit_local_threshold() -> None:
    binding = _binding(
        mapping="comparable",
        metric="branch_count",
        unit="branches",
        count_method="Count control-flow branches",
        threshold=8,
    )
    intent = _intent(
        binding,
        threshold=10,
        overrides=({"language": "python", "threshold": 8},),
    )
    assert intent.threshold_for("python") == 8


def test_effective_native_threshold_conflicts_are_rejected() -> None:
    binding = _binding(threshold=9)
    with pytest.raises(ValidationError, match="conflicts with configured threshold"):
        _intent(binding, threshold=10)


def test_native_threshold_values_translate_to_tool_specific_types() -> None:
    binding = NativeCapabilityBinding.model_validate(
        {
            **_binding().model_dump(mode="python"),
            "threshold_values": {"10": "10"},
            "effective_configuration": {"max-complexity": "10"},
        }
    )
    assert binding.threshold_values == ((10, "10"),)
    intent = _intent(binding)
    assert intent.threshold_for("python") == 10

    boolean_threshold = NativeCapabilityBinding.model_validate(
        {
            **_binding(threshold=1).model_dump(mode="python"),
            "effective_configuration": (("max-complexity", True),),
        }
    )
    with pytest.raises(ValidationError, match="conflicts with configured threshold"):
        _intent(boolean_threshold, threshold=1)


def test_invalid_version_ranges_and_undeclared_native_options_fail_validation() -> None:
    with pytest.raises(ValidationError, match="version range"):
        NativeCapabilityBinding.model_validate(
            {
                **_binding().model_dump(mode="python"),
                "version_range": "not-a-version-range",
            }
        )

    with pytest.raises(ValidationError, match="undeclared native options"):
        NativeCapabilityBinding(
            language="python",
            backend="ruff",
            version_range=">=0.16,<1",
            native_rule="C901",
            metric="cyclomatic_complexity",
            unit="decision_paths",
            count_method="McCabe decision count starting at one",
            mapping="exact",
            step="Complexity",
            supported_options=("max-complexity",),
            threshold_option="max-complexity",
            effective_configuration=(("other-option", True),),
        )


def test_unsupported_capability_is_explicit_in_a_plan() -> None:
    supported = _binding()
    unsupported = NativeCapabilityBinding(
        language="cpp",
        backend="clang-tidy",
        version_range=">=18,<23",
        native_rule="not-mapped",
        metric="cyclomatic_complexity",
        unit="decision_paths",
        count_method="No native rule is selected for this measurement.",
        mapping="unsupported",
    )
    intent = SharedQualityIntent.model_validate(
        {
            **_intent(supported, threshold=None).model_dump(mode="python"),
            "threshold": None,
            "bindings": [supported, unsupported],
            "overrides": [],
        }
    )
    rows = intent_bindings_for_steps((intent,), ("Complexity",), "check")
    cpp = next(row for row in rows if row["language"] == "cpp")
    assert cpp["mapping"] == "unsupported"
    assert cpp["status"] == "unsupported"
    assert cpp["step"] is None


def test_supported_mapping_must_match_command_inventory_and_rollout() -> None:
    intent = _intent()
    policy = _policy(intent)
    assert policy.intents == (intent,)

    mismatched = CommandRunStep(
        kind="command",
        name="Complexity",
        argv=("ruff", "check", "{files}"),
        files=FileInventoryPolicy(include=("src/**/*.py",), exclude=()),
        rollout="provisional",
    )
    with pytest.raises(ValidationError, match="same file inventory"):
        OrchestrationPolicy(
            steps=(mismatched,),
            profiles=(OrchestrationProfile(name="check", steps=("Complexity",)),),
            intents=(intent,),
        )


def test_intent_command_steps_cannot_enable_native_fixers() -> None:
    intent = _intent()
    base = _policy(intent).steps[0]
    assert isinstance(base, CommandRunStep)
    fixer = CommandRunStep.model_validate(
        {
            **base.model_dump(mode="python"),
            "fix_argv": ("ruff", "check", "--fix", "{files}"),
        }
    )
    with pytest.raises(ValidationError, match="cannot use an automatic fixer"):
        OrchestrationPolicy(
            steps=(fixer,),
            profiles=(OrchestrationProfile(name="check", steps=("Complexity",)),),
            intents=(intent,),
        )


def test_language_override_precedence_is_explicit_and_deterministic() -> None:
    binding = _binding(threshold=8)
    intent = _intent(
        binding,
        threshold=10,
        overrides=(
            {
                "language": "python",
                "enabled": False,
                "threshold": 8,
                "severity": "warning",
                "failure_threshold": "info",
                "files": {
                    "include": ["src/api/**/*.py"],
                    "exclude": ["src/api/gen/**"],
                },
            },
        ),
    )
    assert intent.is_enabled_for("python") is False
    assert intent.threshold_for("python") == 8
    assert intent.severity_for("python") == "warning"
    assert intent.failure_threshold_for("python") == "info"
    files = intent.files_for("python")
    assert files.include == ("src/api/**/*.py",)
    assert files.exclude == ("**/generated/**", "src/api/gen/**")


def test_duplicate_intent_bindings_and_unknown_profiles_are_rejected() -> None:
    binding = _binding()
    with pytest.raises(ValidationError, match="one active binding per language"):
        SharedQualityIntent.model_validate(
            {
                **_intent().model_dump(mode="python"),
                "bindings": (binding, binding),
            }
        )

    invalid = SharedQualityIntent.model_validate(
        {
            **_intent().model_dump(mode="python"),
            "profiles": ("missing",),
        }
    )
    with pytest.raises(ValidationError, match="unknown profiles"):
        OrchestrationPolicy(
            steps=_policy(_intent()).steps,
            profiles=_policy(_intent()).profiles,
            intents=(invalid,),
        )
