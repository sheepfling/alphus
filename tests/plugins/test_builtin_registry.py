"""Verify standard entry-point discovery and deferred built-in imports."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from importlib.metadata import Distribution, EntryPoint
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.plugins import builtin_registry
from alphus.plugins.builtin import BuiltinFeature
from alphus.plugins.builtin_registry import (
    BUILTIN_CHECK_ENTRY_POINT_GROUP,
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
                "assert points['file-size'].group == 'alphus.builtin_checks.v1'; "
                "feature = load_builtin_feature('file-size'); "
                "assert feature.runner.__module__ == 'alphus.gates.hygiene.file_size'; "
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
    first = EntryPoint(
        name="duplicate-check",
        value="alphus.gates.hygiene.file_size:ALPHUS_FEATURE",
        group=BUILTIN_CHECK_ENTRY_POINT_GROUP,
    )
    second = EntryPoint(
        name="duplicate-check",
        value="alphus.gates.hygiene.line_length:ALPHUS_FEATURE",
        group=BUILTIN_CHECK_ENTRY_POINT_GROUP,
    )
    fake_distribution = SimpleNamespace(
        metadata={"Name": "alphus"}, entry_points=(first, second)
    )
    monkeypatch.setattr(
        builtin_registry,
        "distribution",
        lambda _name: cast(Distribution, fake_distribution),
    )
    builtin_check_entry_points.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="duplicate built-in check"):
            builtin_check_entry_points()
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
