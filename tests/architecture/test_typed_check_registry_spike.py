from __future__ import annotations

import subprocess
import sys
from importlib import metadata
from importlib.metadata import EntryPoint
from pathlib import Path
from types import SimpleNamespace

import pytest

from alphus.contracts.cyclomatic import CyclomaticReport
from alphus.plugins import registry as plugin_registry
from alphus.plugins.api import (
    PLUGIN_API_VERSION,
    PLUGIN_ENTRY_POINT_GROUP,
    PluginFinding,
)
from alphus.support.git import run_git
from scripts import typed_registry_spike
from scripts.registry_spike.toy_policy import ToyPolicy
from scripts.registry_spike.toy_registration import register_toy_check
from scripts.typed_registry_spike import _validated_plugin_findings


def _own_distribution(points: tuple[EntryPoint, ...]) -> SimpleNamespace:
    return SimpleNamespace(entry_points=points)


def _git(root: Path, *arguments: str) -> bytes:
    result = run_git(root, *arguments)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _toy_entry_points() -> tuple[EntryPoint, ...]:
    return (
        EntryPoint(
            name="toy-complexity",
            value="scripts.registry_spike.toy_registration:register_toy_check",
            group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
        ),
    )


def test_typed_toy_registration_lazily_returns_specialized_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(
        sys.modules, "scripts.registry_spike.toy_analyzer", raising=False
    )
    monkeypatch.setattr(
        typed_registry_spike,
        "distribution",
        lambda name: _own_distribution(_toy_entry_points()),
    )
    definition = register_toy_check()
    assert "scripts.registry_spike.toy_analyzer" not in sys.modules

    report = definition.execute_typed(
        Path("."), (Path("src/sample.py"),), ToyPolicy(marker="x")
    )

    assert isinstance(report, CyclomaticReport)
    assert report.metric == "cyclomatic-complexity"
    assert report.outcome == "clean"
    assert "scripts.registry_spike.toy_analyzer" in sys.modules


def test_cold_registry_and_registration_import_load_no_gates_or_analyzer() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import scripts.typed_registry_spike; "
                "import scripts.registry_spike.toy_registration; "
                "assert not any(name.startswith('alphus.gates') "
                "for name in sys.modules); "
                "assert 'scripts.registry_spike.toy_analyzer' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_entry_point_discovery_is_deterministic_and_provider_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(
        sys.modules, "scripts.registry_spike.toy_analyzer", raising=False
    )
    points = _toy_entry_points() + (
        EntryPoint(
            name="alpha-check",
            value="scripts.registry_spike.alpha_registration:register_alpha_check",
            group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
        ),
    )
    monkeypatch.setattr(
        typed_registry_spike, "distribution", lambda name: _own_distribution(points)
    )

    registry = typed_registry_spike.CheckRegistry.discover()

    assert tuple(registry.definitions) == ("alpha-check", "toy-complexity")
    assert "scripts.registry_spike.toy_analyzer" not in sys.modules
    entry = registry.definitions["toy-complexity"]
    with pytest.raises(TypeError, match="requires ToyPolicy settings"):
        entry.execute(
            Path("."), (Path("src/sample.py"),), {"marker": "x", "unknown": 1}
        )
    report = entry.execute(Path("."), (Path("src/sample.py"),), ToyPolicy(marker="x"))
    assert isinstance(report, CyclomaticReport)


def test_two_feature_declaration_files_merge_without_shared_registry_edits(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Alphus Test")
    _git(tmp_path, "config", "user.email", "alphus-test@example.invalid")
    _git(tmp_path, "branch", "-M", "main")
    shared_registry = tmp_path / "registry.py"
    shared_registry.write_text("registry = {}\n", encoding="utf-8")
    _git(tmp_path, "add", "registry.py")
    _git(tmp_path, "commit", "--quiet", "-m", "base")

    _git(tmp_path, "checkout", "--quiet", "-b", "feature/toy")
    toy_module = tmp_path / "features" / "toy_registration.py"
    toy_module.parent.mkdir()
    toy_module.write_text("selector = 'toy-complexity'\n", encoding="utf-8")
    _git(tmp_path, "add", "features/toy_registration.py")
    _git(tmp_path, "commit", "--quiet", "-m", "add toy feature")

    _git(tmp_path, "checkout", "--quiet", "main")
    _git(tmp_path, "checkout", "--quiet", "-b", "feature/alpha")
    alpha_module = tmp_path / "features" / "alpha_registration.py"
    alpha_module.parent.mkdir(parents=True, exist_ok=True)
    alpha_module.write_text("selector = 'alpha-check'\n", encoding="utf-8")
    _git(tmp_path, "add", "features/alpha_registration.py")
    _git(tmp_path, "commit", "--quiet", "-m", "add alpha feature")
    _git(tmp_path, "merge", "--quiet", "--no-edit", "feature/toy")

    assert toy_module.is_file()
    assert alpha_module.is_file()
    assert shared_registry.read_text(encoding="utf-8") == "registry = {}\n"
    assert _git(tmp_path, "status", "--porcelain") == b""


def test_builtin_discovery_ignores_unrelated_distributions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_point = EntryPoint(
        name="toy-complexity",
        value="scripts.registry_spike.toy_registration:register_toy_check",
        group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
    )
    unrelated_point = EntryPoint(
        name="hostile-check",
        value="missing_package:register_check",
        group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
    )
    monkeypatch.setattr(
        typed_registry_spike,
        "distribution",
        lambda name: _own_distribution((owned_point,)),
    )
    monkeypatch.setattr(metadata, "entry_points", lambda **kwargs: (unrelated_point,))

    registry = typed_registry_spike.CheckRegistry.discover(enabled_plugins=())

    assert tuple(registry.definitions) == ("toy-complexity",)


def test_duplicate_metadata_names_fail_before_loading_any_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    points = (
        EntryPoint(
            name="duplicate",
            value="missing:first",
            group="alphus.builtin_checks.spike.v1",
        ),
        EntryPoint(
            name="duplicate",
            value="missing:second",
            group="alphus.builtin_checks.spike.v1",
        ),
    )
    monkeypatch.setattr(
        typed_registry_spike, "distribution", lambda name: _own_distribution(points)
    )

    with pytest.raises(ValueError, match="duplicate built-in check entry points"):
        typed_registry_spike.CheckRegistry.discover()


def test_factory_must_return_an_executable_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point = EntryPoint(
        name="invalid-check",
        value="scripts.registry_spike.toy_registration:register_invalid_check",
        group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
    )
    monkeypatch.setattr(
        typed_registry_spike,
        "distribution",
        lambda name: _own_distribution((point,)),
    )

    with pytest.raises(TypeError, match="must return an executable check"):
        typed_registry_spike.CheckRegistry.discover()


def test_factory_execute_signature_is_validated_during_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point = EntryPoint(
        name="invalid-check",
        value="scripts.registry_spike.toy_registration:register_invalid_execute",
        group=typed_registry_spike.BUILTIN_SPIKE_ENTRY_POINT_GROUP,
    )
    monkeypatch.setattr(
        typed_registry_spike,
        "distribution",
        lambda name: _own_distribution((point,)),
    )

    with pytest.raises(TypeError, match="accepting root, files, and settings"):
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
        typed_registry_spike,
        "distribution",
        lambda name: _own_distribution((builtin_point,)),
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


def test_plugin_registry_result_boundary_rejects_non_findings() -> None:
    with pytest.raises(TypeError, match="PluginFinding records"):
        _validated_plugin_findings(["not-a-finding"])

    finding = PluginFinding(rule_id="example", message="Example finding")
    assert _validated_plugin_findings([finding]) == [finding]


def test_conventional_first_party_entry_point_loads_only_on_selection() -> None:
    sys.modules.pop("scripts.registry_spike.toy_analyzer", None)
    point = EntryPoint(
        name="toy-provider",
        value="scripts.registry_spike.toy_analyzer:ToyAnalyzer",
        group="alphus.first_party_checks.spike.v1",
    )

    provider_type = point.load()

    assert "scripts.registry_spike.toy_analyzer" in sys.modules
    assert provider_type.__name__ == "ToyAnalyzer"
