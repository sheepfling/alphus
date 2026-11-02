"""Conformance tests for the versioned third-party rule API."""

from __future__ import annotations

import importlib
import json
import tomllib
from collections.abc import Sequence
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import load_config_stream
from alphus.contracts.model import StrictModel
from alphus.plugins import PluginFinding, PluginRuleSpec, RulePlugin, registry
from alphus.plugins.api import PLUGIN_ENTRY_POINT_GROUP
from alphus.plugins.registry import load_enabled_plugins
from alphus.policy.plugins import PluginPolicy

EXAMPLE_ROOT = (
    Path(__file__).parents[2] / "examples" / "plugins" / "alphus-example-rules"
)


class _EntryPoint:
    def __init__(self, name: str, factory: Any) -> None:
        self.name = name
        self.dist = None
        self._factory = factory

    def load(self) -> Any:
        return self._factory


@pytest.fixture
def example_entry_point(monkeypatch: pytest.MonkeyPatch) -> _EntryPoint:
    monkeypatch.syspath_prepend(str(EXAMPLE_ROOT / "src"))
    module = importlib.import_module("alphus_example_rules")
    entry = _EntryPoint("example", module.register)

    def discover(*, group: str) -> tuple[_EntryPoint, ...]:
        assert group == PLUGIN_ENTRY_POINT_GROUP
        return (entry,)

    load_enabled_plugins.cache_clear()
    monkeypatch.setattr(registry, "entry_points", discover)
    return entry


def _plugin_policy() -> str:
    return """
schema_version = 1

[files]
include = ["*.md"]

[plugins]
enabled = ["example"]

[plugins.rules."example:markdown-title"]
extensions = [".md"]
heading_level = 1

[orchestration]
default_profile = "docs"
[[orchestration.steps]]
kind = "rule"
name = "Markdown titles"
rule = "example:markdown-title"

[[orchestration.profiles]]
name = "docs"
steps = ["Markdown titles"]
"""


def test_disabled_plugins_are_not_discovered_or_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def should_not_discover(**kwargs: object) -> object:
        pytest.fail("disabled plugins must not trigger entry point discovery")

    load_enabled_plugins.cache_clear()
    monkeypatch.setattr(registry, "entry_points", should_not_discover)

    assert dict(load_enabled_plugins(())) == {}


def test_separate_example_package_advertises_api_v1() -> None:
    metadata = tomllib.loads((EXAMPLE_ROOT / "pyproject.toml").read_text())

    assert metadata["project"]["entry-points"][PLUGIN_ENTRY_POINT_GROUP] == {
        "example": "alphus_example_rules:register"
    }


def test_example_plugin_runs_as_a_profile_rule(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    example_entry_point: _EntryPoint,
) -> None:
    del example_entry_point
    import subprocess

    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("No heading here.\n", encoding="utf-8")
    config_path = tmp_path / "quality.toml"
    config_path.write_text(_plugin_policy(), encoding="utf-8")

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--config",
                str(config_path),
                "--run",
                "--profile",
                "docs",
                "--json",
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    diagnostics = [
        diagnostic
        for step in result["steps"]
        for diagnostic in step.get("findings", [])
    ]
    assert diagnostics == [
        {
            "line": 1,
            "message": "document has no level 1 heading",
            "path": "README.md",
            "rule_id": "example:markdown-title/missing-title",
            "severity": "warning",
            "source": "plugin:example",
        }
    ]


def test_catalog_lists_only_enabled_plugin_rules(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    example_entry_point: _EntryPoint,
) -> None:
    del example_entry_point
    config_path = tmp_path / "quality.toml"
    config_path.write_text(_plugin_policy(), encoding="utf-8")

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--config",
                str(config_path),
                "--catalog",
                "--json",
            ]
        )
        == 0
    )
    catalog = json.loads(capsys.readouterr().out)

    plugin_rule = next(
        rule
        for rule in catalog["rules"]
        if rule["selector"] == "example:markdown-title"
    )
    assert plugin_rule["domains"] == ["documentation-publishing"]
    assert catalog["plugins"] == [
        {"enabled": True, "name": "example", "rules_loaded": True}
    ]


def test_plugin_rule_settings_require_explicit_plugin_enablement() -> None:
    with pytest.raises(ValidationError, match="require enabled plugins"):
        PluginPolicy.model_validate(
            {"rules": {"example:markdown-title": {"extensions": [".md"]}}}
        )


def test_enabled_plugins_must_match_the_entry_point_name(
    example_entry_point: _EntryPoint,
) -> None:
    from alphus_example_rules import register

    example_entry_point._factory = lambda: replace(register(), name="other")
    load_enabled_plugins.cache_clear()

    with pytest.raises(ValueError, match="does not match entry point"):
        load_enabled_plugins(("example",))


def test_plugin_api_version_must_match_the_host(
    example_entry_point: _EntryPoint,
) -> None:
    from alphus_example_rules import register

    example_entry_point._factory = lambda: replace(register(), api_version=2)
    load_enabled_plugins.cache_clear()

    with pytest.raises(ValueError, match="uses API version 2"):
        load_enabled_plugins(("example",))


def test_enabled_entry_points_are_sorted_and_duplicate_names_rejected(
    monkeypatch: pytest.MonkeyPatch,
    example_entry_point: _EntryPoint,
) -> None:
    class EmptySettings(StrictModel):
        pass

    def no_findings(
        root: Path, files: Sequence[Path], settings: EmptySettings
    ) -> tuple[PluginFinding, ...]:
        del root, files, settings
        return ()

    analytics = _EntryPoint(
        "analytics",
        lambda: RulePlugin(
            name="analytics",
            rules=(
                PluginRuleSpec(
                    name="summary",
                    config_model=EmptySettings,
                    check=no_findings,
                    summary="Example analytics rule.",
                    applies_to=("python",),
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda **kwargs: (example_entry_point, analytics),
    )
    load_enabled_plugins.cache_clear()

    assert tuple(load_enabled_plugins(("example", "analytics"))) == (
        "analytics:summary",
        "example:markdown-title",
    )

    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda **kwargs: (example_entry_point, _EntryPoint("example", lambda: None)),
    )
    load_enabled_plugins.cache_clear()
    with pytest.raises(ValueError, match="multiple Alphus rule plugins"):
        load_enabled_plugins(("example",))


def test_plugin_settings_reject_extra_fields(
    example_entry_point: _EntryPoint,
) -> None:
    del example_entry_point

    with pytest.raises(ValueError, match="invalid settings for plugin rule"):
        load_config_stream(
            StringIO(
                _plugin_policy().replace(
                    "heading_level = 1", "heading_level = 1\nunknown = true"
                )
            )
        )
