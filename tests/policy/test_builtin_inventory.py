"""Keep the generated current built-in inventory aligned with runtime contracts."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast, get_args

import pytest
from pydantic import TypeAdapter
from pydantic.fields import FieldInfo

from alphus.execution.dispatch import BUILTIN_RULES
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.base import QualityRuleName
from alphus.policy.catalog import RULE_SPECS
from alphus.policy.orchestration import CheckPolicies, RuleRunStep
from scripts.generate_builtin_inventory import (
    BuiltinInventory,
    quality_rule_selectors,
)

_REFERENCE_INVENTORY = "architecture/builtin-check-baseline-c880093.json"
_REFERENCE_REVISION = "c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e"
_INVENTORY_ADAPTER: TypeAdapter[BuiltinInventory] = TypeAdapter(BuiltinInventory)
_CHECK_POLICY_FIELDS: Mapping[str, FieldInfo] = cast(
    Mapping[str, FieldInfo], CheckPolicies.model_fields
)


def _inventory(path: Path) -> BuiltinInventory:
    return _INVENTORY_ADAPTER.validate_json(path.read_bytes())


def test_generated_inventory_covers_runtime_builtins(
    pytestconfig: pytest.Config,
) -> None:
    root = pytestconfig.rootpath
    inventory = _inventory(
        root / "docs" / "architecture" / "builtin-check-inventory.json"
    )
    assert inventory.selector_count == len(BUILTIN_RULES) == len(RULE_SPECS)
    assert {check.selector for check in inventory.checks} == set(BUILTIN_RULES)
    assert set(get_args(QualityRuleName)) == set(BUILTIN_RULES)
    assert inventory.shared_selection_surfaces.direct_cli == "--rule SELECTOR"
    assert inventory.shared_selection_surfaces.profile == "RuleRunStep.rule"
    assert (
        inventory.shared_reporting_surfaces.direct_cli
        == "alphus.cli shape-dispatched legacy renderer"
    )
    assert (
        inventory.shared_reporting_surfaces.profile
        == "RuleEvaluation diagnostics and threshold decision"
    )
    assert (
        inventory.shared_reporting_surfaces.catalog
        == "alphus --catalog and --catalog --json"
    )
    profile_steps = tuple(
        RuleRunStep(kind="rule", name=selector, rule=selector)
        for selector in sorted(BUILTIN_RULES)
    )
    assert {step.rule for step in profile_steps} == set(BUILTIN_RULES)

    for check in inventory.checks:
        spec = RULE_SPECS[check.selector]
        binding = BUILTIN_RULES[check.selector]
        field_names = {field.name for field in check.policy_fields}
        assert spec.policy_field in check.policy_inputs_observed
        assert set(check.policy_inputs_observed) == field_names
        assert all(name in _CHECK_POLICY_FIELDS for name in field_names)
        feature = FEATURE_DEFINITIONS.get(check.selector)
        expected_runner = (
            f"{feature.runner_module}:{feature.runner_name}"
            if feature is not None
            else f"{binding.runner.__module__}:{binding.runner.__qualname__}"
        )
        assert check.runner == expected_runner
        assert check.output_shape == spec.output_shape.value
        assert check.requires_files is spec.requires_files
        assert check.result_adapter.endswith(f"/{spec.output_shape.value}")

    composite = next(
        check for check in inventory.checks if check.selector == "package-boundaries"
    )
    assert composite.policy_inputs_observed == (
        "architecture_graph",
        "callable_registry",
        "package_boundaries",
        "version_sync",
    )


def test_current_registration_contract_matches_pinned_mainline_baseline(
    pytestconfig: pytest.Config,
) -> None:
    root = pytestconfig.rootpath
    current = _inventory(
        root / "docs" / "architecture" / "builtin-check-inventory.json"
    )
    baseline = _inventory(root / "docs" / _REFERENCE_INVENTORY)
    assert current.selector_count == baseline.selector_count
    assert current.shared_selection_surfaces == baseline.shared_selection_surfaces
    assert current.shared_reporting_surfaces == baseline.shared_reporting_surfaces
    assert len(current.checks) == len(baseline.checks)
    for current_check, baseline_check in zip(
        current.checks, baseline.checks, strict=True
    ):
        assert current_check.selector == baseline_check.selector
        assert current_check.policy_field == baseline_check.policy_field
        assert current_check.policy_fields == baseline_check.policy_fields
        assert current_check.policy_inputs_observed == (
            baseline_check.policy_inputs_observed
        )
        assert current_check.output_shape == baseline_check.output_shape
        assert current_check.requires_files is baseline_check.requires_files


def test_committed_baseline_matches_its_pinned_source(
    pytestconfig: pytest.Config,
    tmp_path: Path,
) -> None:
    root = pytestconfig.rootpath
    archive_path = tmp_path / "reference.tar"
    with archive_path.open("wb") as archive:
        archived = subprocess.run(
            ["git", "archive", "--format=tar", _REFERENCE_REVISION, "src"],
            cwd=root,
            stdout=archive,
            stderr=subprocess.PIPE,
            check=False,
        )
    assert archived.returncode == 0, archived.stderr.decode(errors="replace")
    reference_root = tmp_path / "reference"
    reference_root.mkdir()
    unpacked = subprocess.run(
        ["tar", "-xf", str(archive_path), "-C", str(reference_root)],
        cwd=root,
        capture_output=True,
        check=False,
    )
    assert unpacked.returncode == 0, unpacked.stderr.decode(errors="replace")

    reference_inventory = tmp_path / "reference-inventory.json"
    generated = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "generate_builtin_inventory.py"),
            "--root",
            str(reference_root),
            "--output",
            str(reference_inventory),
        ],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    assert generated.returncode == 0, generated.stderr
    committed_baseline = root / "docs" / _REFERENCE_INVENTORY
    assert reference_inventory.read_bytes() == committed_baseline.read_bytes()


def test_inventory_generator_check_mode_is_current(
    pytestconfig: pytest.Config,
) -> None:
    root = pytestconfig.rootpath
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "generate_builtin_inventory.py"),
            "--root",
            str(root),
            "--check",
        ],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_selector_literal_rejects_duplicate_names(tmp_path: Path) -> None:
    base_module = tmp_path / "src" / "alphus" / "policy" / "base.py"
    base_module.parent.mkdir(parents=True)
    base_module.write_text(
        "from typing import Literal, TypeAlias\n"
        'QualityRuleName: TypeAlias = Literal["duplicate", "duplicate"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate selectors"):
        quality_rule_selectors(tmp_path)
