import json
import shutil
import subprocess
import sys
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from alphus.config import (
    TypingStubCandidate,
    TypingStubSuggestionPolicy,
    load_config,
)
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


def test_alphus_check_profile_executes_typing_stub_suggestions() -> None:
    config = load_config(Path("quality-gates.toml"))
    assert config.orchestration is not None
    plan = config.orchestration.resolve_profile("check")

    assert plan is not None
    assert "Typing stub suggestions" in plan.steps
    assert config.checks.typing_stub_suggestions is not None
    assert config.checks.typing_stub_suggestions.typing_groups == ("python",)
    assert config.checks.typing_stub_suggestions.checkers == ("pyright",)
    assert config.checks.typing_stub_suggestions.disabled_imports == ()


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


def test_pyright_consumes_installed_real_package_stubs(
    tmp_path: Path,
) -> None:
    pyright = shutil.which("pyright")
    if pyright is None:
        pytest.skip("Pyright executable is not installed in this test environment")
    distributions = (
        "PyYAML",
        "types-PyYAML",
        "scipy",
        "scipy-stubs",
        "python-dateutil",
        "types-python-dateutil",
        "toml",
        "types-toml",
    )
    try:
        for distribution in distributions:
            metadata.version(distribution)
    except metadata.PackageNotFoundError:
        pytest.skip("All catalog runtime/stub packages are not installed")

    (tmp_path / "client.py").write_text(
        "import scipy.linalg\n"
        "import yaml\n"
        "import toml\n"
        "from dateutil.parser import parse\n"
        "\n"
        "yaml_output: str = yaml.safe_dump({'value': 1})\n"
        "yaml_bad: int = yaml.safe_dump({'value': 1})\n"
        "scipy_output = scipy.linalg.norm([3.0, 4.0])\n"
        "reveal_type(scipy_output)\n"
        "scipy_bad: str = scipy_output\n"
        "date_value = parse('2026-01-01')\n"
        "reveal_type(date_value)\n"
        "date_bad: str = date_value\n"
        "toml_output: str = toml.dumps({'value': 1})\n"
        "toml_bad: int = toml.dumps({'value': 1})\n",
        encoding="utf-8",
    )
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps(
            {
                "typeCheckingMode": "strict",
                "include": ["client.py"],
                "pythonVersion": f"{sys.version_info.major}.{sys.version_info.minor}",
                "venvPath": str(Path(sys.prefix).parent),
                "venv": Path(sys.prefix).name,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [pyright, "--outputjson"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    diagnostics = json.loads(result.stdout)["generalDiagnostics"]
    errors = [item for item in diagnostics if item["severity"] == "error"]
    assert any('"str" is not assignable to "int"' in item["message"] for item in errors)
    assert any(
        '"float" is not assignable to "str"' in item["message"] for item in errors
    )
    assert any(
        '"datetime" is not assignable to "str"' in item["message"] for item in errors
    )
    assert any('"str" is not assignable to "int"' in item["message"] for item in errors)
    assert any(
        'Type of "scipy_output" is "float"' in item["message"] for item in diagnostics
    )
    assert any(
        'Type of "date_value" is "datetime"' in item["message"] for item in diagnostics
    )


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


class _DateutilDistribution:
    version = "2.9.0.post0"
    files = ()


class _DateutilStubDistribution:
    version = "2.9.0.20261021"
    files = ()


class _TomlDistribution:
    version = "0.10.2"
    files = ()


class _TomlStubDistribution:
    version = "0.10.8.20260518"
    files = ()


class _RequestsDistribution:
    version = "2.33.1"
    files = ()


class _TypedRequestsDistribution:
    version = "2.34.2"
    files = (Path("requests/py.typed"),)


class _OldRequestsDistribution:
    version = "2.32.5"
    files = ()


class _RedisDistribution:
    version = "4.6.0"
    files = ()


class _RedisStubDistribution:
    version = "4.6.0.20241004"
    files = ()


class _TypedRedisDistribution:
    version = "5.0.0"
    files = (Path("redis/py.typed"),)


class _UnverifiedRedisDistribution:
    version = "4.7.0"
    files = ()


class _PandasDistribution:
    version = "3.1.0"
    files = (Path("pandas/_libs/tslibs/timestamps.pyi"),)


class _TypedPandasDistribution:
    version = "3.1.0"
    files = (Path("pandas/py.typed"),)


class _PandasInitStubDistribution:
    version = "3.1.0"
    files = (Path("pandas/__init__.pyi"),)


class _PandasStubDistribution:
    version = "3.1.0.261029"
    files = ()


class _UnverifiedPandasDistribution:
    version = "3.0.3"
    files = ()


def _distribution(name: str) -> object:
    if name == "types-PyYAML":
        return _PyYAMLStubDistribution()
    if name == "scipy-stubs":
        return _ScipyStubDistribution()
    if name == "scipy":
        return _ScipyDistribution()
    if name == "python-dateutil":
        return _DateutilDistribution()
    if name == "types-python-dateutil":
        return _DateutilStubDistribution()
    if name == "toml":
        return _TomlDistribution()
    if name == "types-toml":
        return _TomlStubDistribution()
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from .yaml import local_helper\n", ()),
        ("from ..yaml.submodule import local_helper\n", ()),
        ("from yaml import safe_load\n", (("yaml", 1),)),
    ],
)
def test_relative_imports_are_not_treated_as_external_yaml_imports(
    source: str, expected: tuple[tuple[str, int], ...]
) -> None:
    assert gate._imports(source) == expected


def test_relative_yaml_import_does_not_recommend_external_stub(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "app.py").write_text(
        "from .yaml import local_helper\n", encoding="utf-8"
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )


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


def test_selected_extra_marker_uses_the_optional_group_context(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        """[project]
dependencies = ["PyYAML>=6,<7"]
[project.optional-dependencies]
typing = ["types-PyYAML>=6; extra == 'typing'"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )


def test_selected_extra_marker_rejects_an_unselected_extra_name(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        """[project]
dependencies = ["PyYAML>=6,<7"]
[project.optional-dependencies]
typing = ["types-PyYAML>=6; extra == 'dev'"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _policy()
    )

    assert len(findings) == 1
    assert "already installed at compatible version" in findings[0].message
    assert "not declared in typing group(s) typing" in findings[0].message


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


def test_builtin_requests_mapping_recommends_current_stub_for_dev_group(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2.33,<2.34"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )

    def distributions(name: str) -> object:
        if name == "requests":
            return _RequestsDistribution()
        if name == "types-requests":
            raise metadata.PackageNotFoundError(name)
        return _distribution(name)

    monkeypatch.setattr(gate.metadata, "distribution", distributions)

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )

    assert len(findings) == 1
    assert "types-requests" in findings[0].message
    assert "requests 2.33.1" in findings[0].message
    assert "typing group(s) dev" in findings[0].message


def test_builtin_requests_skips_versions_with_inline_typing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2.34,<3"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _TypedRequestsDistribution()
    )

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )


def test_builtin_requests_does_not_recommend_outside_verified_runtime_range(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2.32,<2.33"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _OldRequestsDistribution()
    )

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )

    assert len(findings) == 1
    assert "outside that verified range" in findings[0].message
    assert "no stub recommendation was made" in findings[0].message


def test_builtin_redis_mapping_recommends_matching_stubs_for_dev_group(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import redis\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["redis==4.6.0"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )

    def distributions(name: str) -> object:
        if name == "redis":
            return _RedisDistribution()
        if name == "types-redis":
            raise metadata.PackageNotFoundError(name)
        return _distribution(name)

    monkeypatch.setattr(gate.metadata, "distribution", distributions)

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )

    assert len(findings) == 1
    assert "types-redis" in findings[0].message
    assert "redis 4.6.0" in findings[0].message
    assert "typing group(s) dev" in findings[0].message


def test_builtin_redis_suppresses_external_stubs_when_runtime_is_inline_typed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import redis\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["redis>=5,<6"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _TypedRedisDistribution()
    )

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )


def test_builtin_redis_skips_stub_already_declared_in_selected_dev_group(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import redis\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["redis==4.6.0"]\n'
        '[project.optional-dependencies]\ndev = ["types-redis==4.6.0.20241004"]\n',
        encoding="utf-8",
    )

    def distributions(name: str) -> object:
        if name == "redis":
            return _RedisDistribution()
        if name == "types-redis":
            return _RedisStubDistribution()
        return _distribution(name)

    monkeypatch.setattr(gate.metadata, "distribution", distributions)

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )


def test_builtin_pandas_mapping_recommends_matching_stubs_for_dev_group(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import pandas\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pandas==3.1.0"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )

    def distributions(name: str) -> object:
        if name == "pandas":
            return _PandasDistribution()
        if name == "pandas-stubs":
            raise metadata.PackageNotFoundError(name)
        return _distribution(name)

    monkeypatch.setattr(gate.metadata, "distribution", distributions)

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )

    assert len(findings) == 1
    assert "pandas-stubs" in findings[0].message
    assert "pandas 3.1.0" in findings[0].message
    assert "typing group(s) dev" in findings[0].message


def test_builtin_pandas_reports_matching_stub_as_installed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import pandas\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pandas==3.1.0"]\n'
        '[project.optional-dependencies]\ndev = ["pandas-stubs==3.1.0.261029"]\n',
        encoding="utf-8",
    )

    def distributions(name: str) -> object:
        if name == "pandas":
            return _PandasDistribution()
        if name == "pandas-stubs":
            return _PandasStubDistribution()
        return _distribution(name)

    monkeypatch.setattr(gate.metadata, "distribution", distributions)

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )


def test_builtin_pandas_suppresses_suggestion_for_package_marker(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import pandas\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pandas==3.1.0"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _TypedPandasDistribution()
    )

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )


def test_builtin_pandas_suppresses_suggestion_for_matching_root_stub(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import pandas\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pandas==3.1.0"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _PandasInitStubDistribution()
    )

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )


def test_builtin_pandas_counts_only_observed_leaf_runtime_stub(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = tmp_path / "app.py"
    source.write_text("import pandas._libs.tslibs.timestamps\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pandas==3.1.0"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )

    def distributions(name: str) -> object:
        if name == "pandas":
            return _PandasDistribution()
        if name == "pandas-stubs":
            raise metadata.PackageNotFoundError(name)
        return _distribution(name)

    monkeypatch.setattr(gate.metadata, "distribution", distributions)

    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )

    source.write_text(
        "import pandas\nimport pandas._libs.tslibs.timestamps\n",
        encoding="utf-8",
    )
    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )
    assert len(findings) == 1
    assert "pandas-stubs" in findings[0].message


def test_pyright_uses_matching_runtime_leaf_stub_without_package_marker(
    tmp_path: Path,
) -> None:
    pyright = shutil.which("pyright")
    if pyright is None:
        pytest.skip("Pyright executable is not installed in this test environment")
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    package = (
        tmp_path
        / "envs"
        / "runtime"
        / "lib"
        / version
        / "site-packages"
        / "pandas"
        / "_libs"
        / "tslibs"
    )
    package.mkdir(parents=True)
    for initializer in (
        package.parents[1] / "__init__.py",
        package.parents[0] / "__init__.py",
        package / "__init__.py",
    ):
        initializer.parent.mkdir(parents=True, exist_ok=True)
        initializer.write_text('"""Runtime fixture."""\n', encoding="utf-8")
    implementation = package / "timestamps.py"
    implementation.write_text("value = 1\n", encoding="utf-8")
    stub = package / "timestamps.pyi"
    stub.write_text("value: str\n", encoding="utf-8")
    project = tmp_path / "consumer"
    project.mkdir()
    (project / "client.py").write_text(
        "from pandas._libs.tslibs import timestamps\nvalue: int = timestamps.value\n",
        encoding="utf-8",
    )
    config = {
        "typeCheckingMode": "strict",
        "reportMissingTypeStubs": "none",
        "include": ["client.py"],
        "venvPath": str(tmp_path / "envs"),
        "venv": "runtime",
    }
    (project / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")

    with_stub = subprocess.run(
        [pyright, "--project", str(project / "pyrightconfig.json")],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert 'Type "str" is not assignable to declared type "int"' in with_stub.stdout

    stub.unlink()
    without_stub = subprocess.run(
        [pyright, "--project", str(project / "pyrightconfig.json")],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert without_stub.returncode == 0, without_stub.stdout


def test_builtin_pandas_does_not_recommend_outside_verified_runtime_line(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import pandas\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pandas==3.0.3"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )

    def distributions(name: str) -> object:
        if name == "pandas":
            return _UnverifiedPandasDistribution()
        return _distribution(name)

    monkeypatch.setattr(gate.metadata, "distribution", distributions)

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )

    assert len(findings) == 1
    assert "outside that verified range" in findings[0].message
    assert "no stub recommendation was made" in findings[0].message


def test_builtin_redis_does_not_recommend_for_unverified_runtime_versions(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("import redis\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["redis==4.7.0"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _UnverifiedRedisDistribution()
    )

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )

    assert len(findings) == 1
    assert "outside that verified range" in findings[0].message
    assert "no stub recommendation was made" in findings[0].message


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


@pytest.mark.parametrize(
    ("import_name", "runtime_requirement", "stub_requirement", "stub_name"),
    [
        (
            "dateutil",
            "python-dateutil==2.9.0.post0",
            "types-python-dateutil==2.9.0.20261021",
            "types-python-dateutil",
        ),
        (
            "toml",
            "toml==0.10.2",
            "types-toml==0.10.8.20260518",
            "types-toml",
        ),
    ],
)
def test_builtin_popular_mappings_respect_selected_dev_groups_and_duplicates(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    import_name: str,
    runtime_requirement: str,
    stub_requirement: str,
    stub_name: str,
) -> None:
    (tmp_path / "app.py").write_text(f"import {import_name}\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        f'dependencies = ["{runtime_requirement}"]\n'
        "[project.optional-dependencies]\n"
        "dev = []\n"
        f'test = ["{stub_requirement}"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", _distribution)

    findings = gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), _default_policy()
    )
    assert len(findings) == 1
    assert stub_name in findings[0].message
    assert "typing group(s) dev" in findings[0].message

    selected_groups = _default_policy().model_copy(
        update={"typing_groups": ("dev", "test")}
    )
    assert not gate.check_typing_stub_suggestions(
        tmp_path, _python_sources(tmp_path), selected_groups
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
