from pathlib import Path

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
                package_path="yaml",
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


def _checkout(tmp_path: Path, dependencies: list[str] | None = None) -> None:
    (tmp_path / "yaml").mkdir()
    (tmp_path / "app.py").write_text("import yaml\n", encoding="utf-8")
    deps = dependencies or []
    group = ", ".join(value.strip('"') for value in deps)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["PyYAML>=6,<7"]\n'
        f'[project.optional-dependencies]\ntyping = ["{group}"]\n',
        encoding="utf-8",
    )


class _Distribution:
    version = "6.0.2"
    files = ()


def test_suggests_only_explicit_stub_candidate_for_observed_import(
    tmp_path: Path, monkeypatch
) -> None:
    _checkout(tmp_path)
    monkeypatch.setattr(gate.metadata, "distribution", lambda _: _Distribution())

    findings = gate.check_typing_stub_suggestions(tmp_path, [Path("app.py")], _policy())

    assert len(findings) == 1
    assert "types-PyYAML" in findings[0].message
    assert "yaml" in findings[0].message


def test_does_not_suggest_when_stub_is_declared(tmp_path: Path, monkeypatch) -> None:
    _checkout(tmp_path, ['"types-PyYAML>=6"'])
    monkeypatch.setattr(gate.metadata, "distribution", lambda _: _Distribution())

    assert not gate.check_typing_stub_suggestions(tmp_path, [Path("app.py")], _policy())


def test_skips_candidate_outside_configured_runtime_version(
    tmp_path: Path, monkeypatch
) -> None:
    _checkout(tmp_path)
    monkeypatch.setattr(gate.metadata, "distribution", lambda _: _Distribution())
    policy = _policy()
    candidate = policy.candidates[0].model_copy(
        update={"supported_runtime_versions": ">=7"}
    )
    policy = policy.model_copy(update={"candidates": (candidate,)})
    assert not gate.check_typing_stub_suggestions(tmp_path, [Path("app.py")], policy)


def test_missing_runtime_metadata_is_unknown_not_missing_stub(
    tmp_path: Path, monkeypatch
) -> None:
    _checkout(tmp_path)

    def unavailable(_: str):
        raise gate.metadata.PackageNotFoundError

    monkeypatch.setattr(gate.metadata, "distribution", unavailable)
    findings = gate.check_typing_stub_suggestions(tmp_path, [Path("app.py")], _policy())
    assert len(findings) == 1
    assert "not evaluated" in findings[0].message
    assert "types-PyYAML" not in findings[0].message


def test_suppresses_inline_typed_package(tmp_path: Path, monkeypatch) -> None:
    _checkout(tmp_path)
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _DistributionWithFiles()
    )
    assert not gate.check_typing_stub_suggestions(tmp_path, [Path("app.py")], _policy())


class _DistributionWithFiles(_Distribution):
    files = (Path("yaml/py.typed"),)


def test_builtin_yaml_mapping_works_with_dev_group(tmp_path: Path, monkeypatch) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["PyYAML>=6,<7"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", lambda _: _Distribution())

    findings = gate.check_typing_stub_suggestions(
        tmp_path, [Path("app.py")], _default_policy()
    )
    assert len(findings) == 1
    assert "types-PyYAML" in findings[0].message
    assert "dev" in findings[0].message


def test_builtin_yaml_mapping_skips_duplicate_dev_stubs(
    tmp_path: Path, monkeypatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["PyYAML>=6,<7"]\n'
        '[project.optional-dependencies]\ndev = ["types-PyYAML>=6", "types-pyyaml>=6"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", lambda _: _Distribution())

    assert not gate.check_typing_stub_suggestions(
        tmp_path, [Path("app.py")], _default_policy()
    )


def test_builtin_scipy_mapping_recommends_matching_release(
    tmp_path: Path, monkeypatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "app.py").write_text("import scipy\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["scipy>=1.18.1,<1.19"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", lambda _: _ScipyDistribution())
    monkeypatch.setattr(gate.sys, "version_info", (3, 12, 0, "final", 0))

    findings = gate.check_typing_stub_suggestions(
        tmp_path, [Path("app.py")], _default_policy()
    )
    assert len(findings) == 1
    assert "scipy-stubs==1.18.1.*" in findings[0].message


def test_builtin_scipy_mapping_reports_unverified_runtime_version(
    tmp_path: Path, monkeypatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "app.py").write_text("import scipy\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["scipy>=1.18,<1.19"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate.metadata, "distribution", lambda _: _OldScipyDistribution()
    )
    monkeypatch.setattr(gate.sys, "version_info", (3, 12, 0, "final", 0))

    findings = gate.check_typing_stub_suggestions(
        tmp_path, [Path("app.py")], _default_policy()
    )
    assert len(findings) == 1
    assert "outside that verified range" in findings[0].message
    assert "no stub recommendation was made" in findings[0].message


def test_builtin_scipy_mapping_reports_unsupported_python(
    tmp_path: Path, monkeypatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "app.py").write_text("import scipy\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["scipy>=1.18.1,<1.19"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", lambda _: _ScipyDistribution())
    monkeypatch.setattr(gate.sys, "version_info", (3, 11, 0, "final", 0))

    findings = gate.check_typing_stub_suggestions(
        tmp_path, [Path("app.py")], _default_policy()
    )
    assert len(findings) == 1
    assert "Python >=3.12,<4" in findings[0].message
    assert "no stub recommendation was made" in findings[0].message


def test_builtin_catalog_can_be_disabled_per_import(
    tmp_path: Path, monkeypatch
) -> None:
    _checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["PyYAML>=6,<7"]\n'
        "[project.optional-dependencies]\ndev = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate.metadata, "distribution", lambda _: _Distribution())

    assert not gate.check_typing_stub_suggestions(
        tmp_path, [Path("app.py")], _default_policy(disabled_imports=("yaml",))
    )


class _ScipyDistribution:
    version = "1.18.1"
    files = ()


class _OldScipyDistribution:
    version = "1.18.0"
    files = ()
