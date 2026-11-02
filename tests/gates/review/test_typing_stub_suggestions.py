import json
import shutil
import subprocess
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from alphus.config import TypingStubCandidate, TypingStubSuggestionPolicy
from alphus.gates.review import typing_stub_suggestions as gate


def _policy() -> TypingStubSuggestionPolicy:
    return TypingStubSuggestionPolicy(
        extensions=(".py",),
        typing_groups=("typing",),
        checkers=("mypy",),
        candidates=(
            TypingStubCandidate(
                import_name="yaml",
                runtime_distribution="PyYAML",
                stub_distribution="types-PyYAML",
                supported_runtime_versions=">=6,<7",
                supported_python_versions=">=3.11,<4",
                checkers=("mypy",),
                package_path="yaml",
                stub_version_specifier=">=6,<7",
            ),
        ),
    )


def _default_policy(
    *, disabled_imports: tuple[str, ...] = ()
) -> TypingStubSuggestionPolicy:
    return TypingStubSuggestionPolicy(
        extensions=(".py",),
        typing_groups=("dev",),
        disabled_imports=disabled_imports,
    )


def _checkout(tmp_path: Path, dependencies: Iterable[str] | None = None) -> None:
    (tmp_path / "yaml").mkdir()
    (tmp_path / "app.py").write_text("import yaml\n", encoding="utf-8")
    deps = dependencies or []
    group = ", ".join(value.strip('"') for value in deps)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["PyYAML>=6,<7"]\n'
        f'[project.optional-dependencies]\ntyping = ["{group}"]\n',
        encoding="utf-8",
    )


def _python_sources(tmp_path: Path) -> tuple[Path, ...]:
    return tuple(path.relative_to(tmp_path) for path in tmp_path.glob("*.py"))


def test_checker_installation_reports_versions_and_absent_metadata(
    monkeypatch: MonkeyPatch,
) -> None:
    def version(name: str) -> str:
        if name == "mypy":
            raise metadata.PackageNotFoundError(name)
        return "1.1.414"

    monkeypatch.setattr(gate.metadata, "version", version)

    assert gate._checker_installation(("pyright", "mypy")) == (
        "pyright 1.1.414, mypy: not installed"
    )


def test_installed_pyright_observes_a_controlled_module_stub(
    tmp_path: Path,
) -> None:
    pyright = shutil.which("pyright")
    if pyright is None:
        pytest.skip("Pyright executable is not installed in this test environment")
    package = tmp_path / "stub_probe"
    package.mkdir()
    (package / "__init__.py").write_text(
        "def __getattr__(name: str) -> object:\n    return 1\n", encoding="utf-8"
    )
    stub = package / "__init__.pyi"
    stub.write_text("def get_value() -> int: ...\n", encoding="utf-8")
    (tmp_path / "client.py").write_text(
        "from stub_probe import get_value\nget_value().upper()\n",
        encoding="utf-8",
    )
    (tmp_path / "pyrightconfig.json").write_text(
        '{"typeCheckingMode":"strict","include":["client.py"]}\n',
        encoding="utf-8",
    )

    with_stub = subprocess.run(
        [pyright, "--outputjson"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    stub_diagnostics = json.loads(with_stub.stdout)["generalDiagnostics"]
    assert any('for class "int"' in item["message"] for item in stub_diagnostics)

    stub.unlink()
    without_stub = subprocess.run(
        [pyright, "--outputjson"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    source_diagnostics = json.loads(without_stub.stdout)["generalDiagnostics"]
    assert not any('for class "int"' in item["message"] for item in source_diagnostics)


class _Distribution:
    version = "6.0.2"
    files = ()


class _PyYAMLStubDistribution:
    version = "6.0.12.20261030"
    files = ()


class _ScipyStubDistribution:
    version = "1.18.1.0"
    files = ()


class _OldStubDistribution:
    version = "5.9.0"
    files = ()


def _distribution(name: str) -> object:
    if name == "types-PyYAML":
        return _PyYAMLStubDistribution()
    if name == "scipy-stubs":
        return _ScipyStubDistribution()
    if name == "scipy":
        return _ScipyDistribution()
    return _Distribution()


def test_suggests_only_explicit_stub_candidate_for_observed_import(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)
    monkeypatch.setattr(gate, "_checker_installation", lambda checkers: "mypy 2.3")

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )

    assert len(findings) == 1
    assert "types-PyYAML" in findings[0].message
    assert "yaml" in findings[0].message
    assert "already installed at compatible version" in findings[0].message
    assert "Selected checker distribution metadata: mypy 2.3" in findings[0].message
    assert "no checker was run" in findings[0].message
    assert findings[0].path == "app.py"
    assert findings[0].line == 1


def test_unparseable_source_is_not_reported_as_executed_zero(
    tmp_path: Path,
) -> None:
    _checkout(tmp_path)
    (tmp_path / "app.py").write_text("import yaml\nif\n", encoding="utf-8")
    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )
    assert len(findings) == 1
    assert findings[0].path == "app.py"
    assert "syntax could not be parsed" in findings[0].message


def test_runtime_distribution_must_be_declared_before_stub_need_is_evaluated(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\ndependencies = []\n[project.optional-dependencies]\ntyping = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)
    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )
    assert len(findings) == 1
    assert "not declared in PEP 621 project.dependencies" in findings[0].message
    assert "not evaluated" in findings[0].message


def test_does_not_suggest_when_stub_is_declared(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path, ['"types-PyYAML>=6"'])
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )


def test_reports_a_declared_stub_missing_from_the_selected_interpreter(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path, ['"types-PyYAML>=6"'])

    def runtime_only(name: str) -> object:
        if name == "PyYAML":
            return _Distribution()
        raise gate.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(gate.metadata, "distribution", runtime_only)
    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )
    assert len(findings) == 1
    assert "declared in typing group(s) typing" in findings[0].message
    assert "not installed" in findings[0].message


def test_rejects_an_installed_stub_outside_its_configured_compatibility_range(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)

    def incompatible_stub(name: str) -> object:
        return _OldStubDistribution() if name == "types-PyYAML" else _Distribution()

    monkeypatch.setattr(gate.metadata, "distribution", incompatible_stub)
    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )
    assert len(findings) == 1
    assert "outside configured compatible range" in findings[0].message
    assert "no compatible stub was established" in findings[0].message


def test_skips_a_mapping_when_selected_checker_has_no_compatibility_evidence(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    policy = _policy().model_copy(update={"checkers": ("pyright",)})
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)
    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), policy
    )
    assert len(findings) == 1
    assert "none of the selected checkers" in findings[0].message
    assert "recommendation was not evaluated" in findings[0].message


def test_skips_candidate_outside_configured_runtime_version(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)
    policy = _policy()
    candidate = policy.candidates[0].model_copy(
        update={"supported_runtime_versions": ">=7"}
    )
    policy = policy.model_copy(update={"candidates": (candidate,)})
    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), policy
    )


def test_missing_runtime_metadata_is_unknown_not_missing_stub(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)

    def unavailable(_: str) -> None:
        raise gate.metadata.PackageNotFoundError

    monkeypatch.setattr(gate.metadata, "distribution", unavailable)
    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )
    assert len(findings) == 1
    assert "not evaluated" in findings[0].message
    assert "types-PyYAML" not in findings[0].message


def test_suppresses_inline_typed_package(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _DistributionWithFiles()
    )
    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )


class _DistributionWithFiles(_Distribution):
    files = (Path("yaml/py.typed"),)


class _ModuleStubDistribution(_Distribution):
    files = (Path("yaml.pyi"),)


def test_suppresses_a_bundled_single_module_stub(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _ModuleStubDistribution()
    )
    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )


def test_builtin_yaml_mapping_works_with_dev_group(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["PyYAML>=6,<7"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )
    assert len(findings) == 1
    assert "types-PyYAML" in findings[0].message
    assert "dev" in findings[0].message


def test_builtin_yaml_mapping_skips_duplicate_dev_stubs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["PyYAML>=6,<7"]\n'
        '[project.optional-dependencies]\ndev = ["types-PyYAML>=6", "types-pyyaml>=6"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )


def test_builtin_scipy_mapping_recommends_matching_release(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "app.py").write_text("import scipy\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["scipy>=1.18.1,<1.19"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)
    monkeypatch.setattr(gate.sys, "version_info", (3, 12, 0, "final", 0))

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )
    assert len(findings) == 1
    assert "scipy-stubs==1.18.1.*" in findings[0].message


def test_builtin_scipy_mapping_reports_unverified_runtime_version(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "app.py").write_text("import scipy\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["scipy>=1.18,<1.19"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda name: _OldScipyDistribution()
    )
    monkeypatch.setattr(gate.sys, "version_info", (3, 12, 0, "final", 0))

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )
    assert len(findings) == 1
    assert "outside that verified range" in findings[0].message
    assert "no stub recommendation was made" in findings[0].message


def test_builtin_scipy_mapping_reports_unsupported_python(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "app.py").write_text("import scipy\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["scipy>=1.18.1,<1.19"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)
    monkeypatch.setattr(gate.sys, "version_info", (3, 11, 0, "final", 0))

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )
    assert len(findings) == 1
    assert "Python >=3.12,<4" in findings[0].message
    assert "no stub recommendation was made" in findings[0].message


def test_builtin_catalog_can_be_disabled_per_import(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["PyYAML>=6,<7"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy(disabled_imports=("yaml",))
    )


class _ScipyDistribution:
    version = "1.18.1"
    files = ()


class _OldScipyDistribution:
    version = "1.18.0"
    files = ()
