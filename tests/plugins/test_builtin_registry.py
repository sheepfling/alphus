"""Verify standard entry-point discovery and deferred built-in imports."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import Distribution, EntryPoint
from types import SimpleNamespace
from typing import cast

import pytest

from alphus.plugins import builtin_registry
from alphus.plugins.builtin_registry import (
    BUILTIN_CHECK_ENTRY_POINT_GROUP,
    builtin_check_entry_points,
)
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS


def test_installed_entry_points_match_feature_selectors_and_load_lazily() -> None:
    points = builtin_check_entry_points()
    assert set(points) == set(FEATURE_DEFINITIONS)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from alphus.plugins.builtin_registry import "
                "builtin_check_entry_points, load_builtin_runner; "
                "points = builtin_check_entry_points(); "
                "assert 'alphus.gates.hygiene.file_size' not in sys.modules; "
                "assert points['file-size'].group == 'alphus.builtin_checks.v1'; "
                "runner = load_builtin_runner('file-size'); "
                "assert runner.__module__ == 'alphus.gates.hygiene.file_size'; "
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
        value="alphus.gates.hygiene.file_size:check_file_size",
        group=BUILTIN_CHECK_ENTRY_POINT_GROUP,
    )
    second = EntryPoint(
        name="duplicate-check",
        value="alphus.gates.hygiene.line_length:check_line_length",
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


def test_loaded_runner_must_accept_the_builtin_execution_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point = SimpleNamespace(load=lambda: lambda: 42)
    monkeypatch.setattr(
        builtin_registry, "builtin_check_entry_points", lambda: {"invalid": point}
    )
    builtin_registry.load_builtin_runner.cache_clear()
    try:
        with pytest.raises(TypeError, match="must accept root, files, and config"):
            builtin_registry.load_builtin_runner("invalid")
    finally:
        builtin_registry.load_builtin_runner.cache_clear()
