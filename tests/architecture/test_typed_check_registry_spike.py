from __future__ import annotations

import sys
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from alphus.contracts.cyclomatic import CyclomaticReport
from alphus.plugins import registry as plugin_registry
from alphus.plugins.api import PLUGIN_API_VERSION, PLUGIN_ENTRY_POINT_GROUP
from scripts import typed_registry_spike
from scripts.registry_spike.toy_policy import ToyPolicy
from scripts.registry_spike.toy_registration import register_toy_check


def test_typed_toy_registration_lazily_returns_specialized_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(
        sys.modules, "scripts.registry_spike.toy_analyzer", raising=False
    )
    definition = register_toy_check()
    assert "scripts.registry_spike.toy_analyzer" not in sys.modules

    provider_point = EntryPoint(
        name="toy-complexity",
        value="scripts.registry_spike.toy_analyzer:ToyAnalyzer",
        group=typed_registry_spike.PROVIDER_SPIKE_ENTRY_POINT_GROUP,
    )
    monkeypatch.setattr(
        typed_registry_spike, "entry_points", lambda *, group: (provider_point,)
    )
    report = definition.execute(
        Path("."), (Path("src/sample.py"),), ToyPolicy(marker="x")
    )

    assert isinstance(report, CyclomaticReport)
    assert report.metric == "cyclomatic-complexity"
    assert report.outcome == "clean"


def test_entry_point_discovery_is_sorted_and_does_not_load_analyzers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(
        sys.modules, "scripts.registry_spike.toy_analyzer", raising=False
    )
    points = (
        EntryPoint(
            name="toy-complexity",
            value="scripts.registry_spike.toy_registration:register_toy_check",
            group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
        ),
        EntryPoint(
            name="alpha-check",
            value="scripts.registry_spike.toy_registration:register_alpha_check",
            group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
        ),
    )
    monkeypatch.setattr(typed_registry_spike, "entry_points", lambda *, group: points)

    registry = typed_registry_spike.CheckRegistry.discover()

    assert tuple(registry.definitions) == ("alpha-check", "toy-complexity")
    assert "scripts.registry_spike.toy_analyzer" not in sys.modules
    assert registry.definitions["toy-complexity"].selector == "toy-complexity"


def test_entry_point_duplicate_is_rejected_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    points = (
        EntryPoint(
            name="toy-complexity",
            value="scripts.registry_spike.toy_registration:register_toy_check",
            group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
        ),
        EntryPoint(
            name="toy-complexity",
            value="scripts.registry_spike.toy_registration:register_toy_check",
            group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
        ),
    )
    monkeypatch.setattr(typed_registry_spike, "entry_points", lambda *, group: points)

    with pytest.raises(ValueError, match="duplicate built-in check entry point"):
        typed_registry_spike.CheckRegistry.discover()


def test_plugin_v1_contract_remains_a_separate_public_boundary() -> None:
    assert PLUGIN_API_VERSION == 1
    assert PLUGIN_ENTRY_POINT_GROUP == "alphus.rules.v1"


def test_shared_registry_keeps_plugin_v1_bindings_namespaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(
        sys.modules, "scripts.registry_spike.toy_analyzer", raising=False
    )
    builtin_point = EntryPoint(
        name="toy-complexity",
        value="scripts.registry_spike.toy_registration:register_toy_check",
        group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
    )
    plugin_point = EntryPoint(
        name="typed-registry-spike",
        value="scripts.registry_spike.toy_plugin:register_toy_plugin",
        group="alphus.rules.v1",
    )
    monkeypatch.setattr(
        typed_registry_spike, "entry_points", lambda *, group: (builtin_point,)
    )
    monkeypatch.setattr(
        plugin_registry, "entry_points", lambda *, group: (plugin_point,)
    )

    registry = typed_registry_spike.CheckRegistry.discover(
        enabled_plugins=("typed-registry-spike",)
    )

    assert set(registry.definitions) == {
        "toy-complexity",
        "typed-registry-spike:toy-rule",
    }
    assert "scripts.registry_spike.toy_analyzer" not in sys.modules


def test_conventional_first_party_entry_point_loads_provider_only_when_selected() -> (
    None
):
    sys.modules.pop("scripts.registry_spike.toy_analyzer", None)
    point = EntryPoint(
        name="toy-provider",
        value="scripts.registry_spike.toy_analyzer:ToyAnalyzer",
        group="alphus.first_party_checks.spike.v1",
    )

    provider_type = point.load()

    assert "scripts.registry_spike.toy_analyzer" in sys.modules
    assert provider_type.__name__ == "ToyAnalyzer"
