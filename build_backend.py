"""Generate standard built-in entry points before delegating to setuptools."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

from setuptools import build_meta as _setuptools_build_meta

_ConfigSettings = Mapping[str, str | list[str] | None] | None


def _write_builtin_entry_points() -> None:
    root = Path(__file__).resolve().parent
    source = root / "src"
    for path in (str(root), str(source)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)

    from scripts.generate_morphology_manifest import (
        feature_registrations,
    )
    from scripts.generate_morphology_manifest import (
        main as generate_morphology_views,
    )

    has_catalog = (source / "alphus" / "policy" / "catalog.py").is_file()
    has_theme_runners = any((source / "alphus" / "gates").glob("*/runners.py"))
    if has_catalog and has_theme_runners:
        from scripts.generate_runner_manifest import main as generate_runner_view

        arguments = ("--root", str(root))
        if generate_morphology_views(arguments) != 0:
            raise RuntimeError("could not generate built-in morphology views")
        if generate_runner_view(arguments) != 0:
            raise RuntimeError("could not generate built-in dispatch view")

    features = feature_registrations(root)
    metadata = root / ".registry-build"
    metadata.mkdir(parents=True, exist_ok=True)
    lines = ["[alphus.builtin_checks.v1]"]
    lines.extend(
        f"{feature.selector} = {feature.registration_module}:ALPHUS_FEATURE"
        for feature in features
    )
    (metadata / "entry_points.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def get_requires_for_build_wheel(config_settings: _ConfigSettings = None) -> list[str]:
    return _setuptools_build_meta.get_requires_for_build_wheel(config_settings)


def get_requires_for_build_sdist(config_settings: _ConfigSettings = None) -> list[str]:
    return _setuptools_build_meta.get_requires_for_build_sdist(config_settings)


def prepare_metadata_for_build_wheel(
    metadata_directory: str, config_settings: _ConfigSettings = None
) -> str:
    _write_builtin_entry_points()
    return _setuptools_build_meta.prepare_metadata_for_build_wheel(
        metadata_directory, config_settings
    )


def prepare_metadata_for_build_editable(
    metadata_directory: str, config_settings: _ConfigSettings = None
) -> str:
    _write_builtin_entry_points()
    return _setuptools_build_meta.prepare_metadata_for_build_editable(
        metadata_directory, config_settings
    )


def build_wheel(
    wheel_directory: str,
    config_settings: _ConfigSettings = None,
    metadata_directory: str | None = None,
) -> str:
    _write_builtin_entry_points()
    return _setuptools_build_meta.build_wheel(
        wheel_directory, config_settings, metadata_directory
    )


def build_editable(
    wheel_directory: str,
    config_settings: _ConfigSettings = None,
    metadata_directory: str | None = None,
) -> str:
    _write_builtin_entry_points()
    return _setuptools_build_meta.build_editable(
        wheel_directory, config_settings, metadata_directory
    )


def build_sdist(sdist_directory: str, config_settings: _ConfigSettings = None) -> str:
    _write_builtin_entry_points()
    return _setuptools_build_meta.build_sdist(sdist_directory, config_settings)
