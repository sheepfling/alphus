"""Verify standard entry-point discovery and deferred built-in imports."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from importlib.metadata import Distribution
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from alphus.config import QualityGateConfig
from alphus.contracts.cli_policy import CliPolicyReport
from alphus.contracts.findings import Finding
from alphus.contracts.shared_utilities import SharedUtilitiesReport
from alphus.plugins import builtin_registry
from alphus.plugins.builtin import BuiltinFeature
from alphus.plugins.builtin_registry import (
    builtin_check_entry_points,
    load_builtin_feature,
)
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR


def test_installed_entry_points_match_feature_selectors_and_load_lazily() -> None:
    points = builtin_check_entry_points()
    assert set(points) == set(FEATURE_DEFINITIONS)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from alphus.plugins.builtin_registry import "
                "builtin_check_entry_points, load_builtin_feature; "
                "points = builtin_check_entry_points(); "
                "assert 'alphus.gates.hygiene.file_size' not in sys.modules; "
                "assert 'alphus.gates.languages.python.runtime_types' not in sys.modules; "
                "assert 'alphus.gates.languages.python.script_policy' not in sys.modules; "
                "assert 'alphus.gates.review.repeated_numeric_limits' not in sys.modules; "
                "assert 'alphus.gates.review.suppression_reasons' not in sys.modules; "
                "assert points['file-size'].group == 'alphus.builtin_checks.v1'; "
                "feature = load_builtin_feature('file-size'); "
                "assert feature.runner.__module__ == 'alphus.gates.hygiene.file_size'; "
                "numeric = load_builtin_feature('repeated-numeric-limits'); "
                "assert numeric.runner.__module__ == "
                "'alphus.gates.review.repeated_numeric_limits'; "
                "suppression = load_builtin_feature('suppression-reasons'); "
                "assert suppression.runner.__module__ == "
                "'alphus.gates.review.suppression_reasons'; "
                "assert 'alphus.gates.hygiene.line_length' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_duplicate_installed_entry_points_fail_before_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = tuple(builtin_check_entry_points().values())
    first = installed[0]
    fake_distribution = SimpleNamespace(
        metadata={"Name": "alphus"}, entry_points=(*installed, first)
    )
    monkeypatch.setattr(
        builtin_registry,
        "distributions",
        lambda **_kwargs: cast(Sequence[Distribution], (fake_distribution,)),
    )
    builtin_check_entry_points.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="duplicate built-in check"):
            builtin_check_entry_points()
    finally:
        builtin_check_entry_points.cache_clear()


def test_stale_source_metadata_does_not_shadow_matching_installed_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = tuple(builtin_check_entry_points().values())
    stale_distribution = SimpleNamespace(
        metadata={"Name": "alphus"},
        entry_points=tuple(
            point for point in installed if point.name != "module-roles"
        ),
    )
    current_distribution = SimpleNamespace(
        metadata={"Name": "alphus"}, entry_points=installed
    )
    monkeypatch.setattr(
        builtin_registry,
        "distributions",
        lambda **_kwargs: cast(
            Sequence[Distribution], (stale_distribution, current_distribution)
        ),
    )
    builtin_check_entry_points.cache_clear()
    try:
        points = builtin_check_entry_points()
        assert set(points) == set(FEATURE_DEFINITIONS)
    finally:
        builtin_check_entry_points.cache_clear()


def test_loaded_feature_rejects_invalid_runner_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def wrong_return(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> int:
        return 42

    async def asynchronous(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> list[Finding]:
        return []

    for selector, runner in (
        ("wrong-return", wrong_return),
        ("asynchronous", asynchronous),
    ):
        feature = BuiltinFeature(
            definition=FEATURE_DEFINITIONS["file-size"],
            morphology=MORPHOLOGY_BY_SELECTOR["file-size"],
            runner=cast("object", runner),  # type: ignore[arg-type]
        )
        point = SimpleNamespace(load=lambda feature=feature: feature)
        monkeypatch.setattr(
            builtin_registry,
            "builtin_check_entry_points",
            lambda selector=selector, point=point: {selector: point},
        )
        builtin_registry.load_builtin_feature.cache_clear()
        try:
            with pytest.raises(TypeError, match="typed synchronous feature"):
                load_builtin_feature(selector)
        finally:
            builtin_registry.load_builtin_feature.cache_clear()


def test_message_feature_requires_a_list_of_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def message_runner(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> list[str]:
        return []

    feature = BuiltinFeature(
        definition=FEATURE_DEFINITIONS["script-policy"],
        morphology=MORPHOLOGY_BY_SELECTOR["script-policy"],
        runner=message_runner,
    )
    point = SimpleNamespace(load=lambda: feature)
    monkeypatch.setattr(
        builtin_registry,
        "builtin_check_entry_points",
        lambda: {"script-policy": point},
    )
    builtin_registry.load_builtin_feature.cache_clear()
    try:
        assert load_builtin_feature("script-policy") is feature
    finally:
        builtin_registry.load_builtin_feature.cache_clear()

    def wrong_message_runner(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> list[Finding]:
        return []

    wrong_feature = BuiltinFeature(
        definition=FEATURE_DEFINITIONS["script-policy"],
        morphology=MORPHOLOGY_BY_SELECTOR["script-policy"],
        runner=cast("object", wrong_message_runner),  # type: ignore[arg-type]
    )
    wrong_point = SimpleNamespace(load=lambda: wrong_feature)
    monkeypatch.setattr(
        builtin_registry,
        "builtin_check_entry_points",
        lambda: {"script-policy": wrong_point},
    )
    builtin_registry.load_builtin_feature.cache_clear()
    try:
        with pytest.raises(TypeError, match="typed synchronous feature"):
            load_builtin_feature("script-policy")
    finally:
        builtin_registry.load_builtin_feature.cache_clear()


def test_shared_utilities_feature_requires_its_typed_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def report_runner(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> SharedUtilitiesReport:
        return SharedUtilitiesReport((), (), ())

    feature = BuiltinFeature(
        definition=FEATURE_DEFINITIONS["shared-utilities"],
        morphology=MORPHOLOGY_BY_SELECTOR["shared-utilities"],
        runner=report_runner,
    )
    point = SimpleNamespace(load=lambda: feature)
    monkeypatch.setattr(
        builtin_registry,
        "builtin_check_entry_points",
        lambda: {"shared-utilities": point},
    )
    builtin_registry.load_builtin_feature.cache_clear()
    try:
        assert load_builtin_feature("shared-utilities") is feature
    finally:
        builtin_registry.load_builtin_feature.cache_clear()

    def wrong_report_runner(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> list[str]:
        return []

    wrong_feature = BuiltinFeature(
        definition=FEATURE_DEFINITIONS["shared-utilities"],
        morphology=MORPHOLOGY_BY_SELECTOR["shared-utilities"],
        runner=cast("object", wrong_report_runner),  # type: ignore[arg-type]
    )
    wrong_point = SimpleNamespace(load=lambda: wrong_feature)
    monkeypatch.setattr(
        builtin_registry,
        "builtin_check_entry_points",
        lambda: {"shared-utilities": wrong_point},
    )
    builtin_registry.load_builtin_feature.cache_clear()
    try:
        with pytest.raises(TypeError, match="typed synchronous feature"):
            load_builtin_feature("shared-utilities")
    finally:
        builtin_registry.load_builtin_feature.cache_clear()


def test_cli_feature_preserves_its_registered_message_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def message_runner(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> list[str]:
        return []

    feature = BuiltinFeature(
        definition=FEATURE_DEFINITIONS["cli"],
        morphology=MORPHOLOGY_BY_SELECTOR["cli"],
        runner=message_runner,
    )
    point = SimpleNamespace(load=lambda: feature)
    monkeypatch.setattr(
        builtin_registry,
        "builtin_check_entry_points",
        lambda: {"cli": point},
    )
    builtin_registry.load_builtin_feature.cache_clear()
    try:
        assert load_builtin_feature("cli") is feature
    finally:
        builtin_registry.load_builtin_feature.cache_clear()

    def wrong_report_runner(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> CliPolicyReport:
        return CliPolicyReport(())

    wrong_feature = BuiltinFeature(
        definition=FEATURE_DEFINITIONS["cli"],
        morphology=MORPHOLOGY_BY_SELECTOR["cli"],
        runner=wrong_report_runner,
    )
    wrong_point = SimpleNamespace(load=lambda: wrong_feature)
    monkeypatch.setattr(
        builtin_registry,
        "builtin_check_entry_points",
        lambda: {"cli": wrong_point},
    )
    builtin_registry.load_builtin_feature.cache_clear()
    try:
        with pytest.raises(TypeError, match="typed synchronous feature"):
            load_builtin_feature("cli")
    finally:
        builtin_registry.load_builtin_feature.cache_clear()
