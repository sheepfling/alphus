"""The import smoke gate inventories packages and reports import failures."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.gates.python import importability


def test_discovers_every_module_in_nested_regular_packages(tmp_path: Path) -> None:
    source = tmp_path / "src"
    package = source / "sample"
    nested = package / "nested"
    nested.mkdir(parents=True)
    for relative in (
        "__init__.py",
        "__main__.py",
        "module.py",
        "nested/__init__.py",
        "nested/feature.py",
    ):
        (package / relative).write_text("", encoding="utf-8")

    inventory = importability.discover_modules(source)

    assert inventory.issues == ()
    assert inventory.modules == (
        "sample",
        "sample.__main__",
        "sample.module",
        "sample.nested",
        "sample.nested.feature",
    )


def test_missing_initializer_and_invalid_module_name_are_reported(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "sample"
    nested = package / "nested"
    nested.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (nested / "feature.py").write_text("", encoding="utf-8")
    (package / "bad-name.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "loose.py").write_text("", encoding="utf-8")

    inventory = importability.discover_modules(tmp_path / "src")

    assert "sample.nested.feature" in inventory.modules
    assert any(
        "nested/__init__.py" in issue.replace("\\", "/") for issue in inventory.issues
    )
    assert "invalid module path: sample/bad-name.py" in inventory.issues
    assert "Python file is outside a package: loose.py" in inventory.issues


def test_import_checks_use_a_fresh_interpreter_without_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", "do-not-use-source-tree")
    calls: list[Sequence[str]] = []

    def fake_run(
        argv: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert "PYTHONPATH" not in environment
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(argv, 0, "__ALPHUS_IMPORT_COMPLETE__\n", "")

    monkeypatch.setattr(importability.subprocess, "run", fake_run)
    assert importability.import_failures(tmp_path / "src", ["sample.module"]) == ()
    assert calls[0][-1] == "sample.module"


def test_import_failure_and_early_exit_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcomes = iter(
        (
            subprocess.CompletedProcess(
                [], 1, "", "ModuleNotFoundError: No module named 'missing'\n"
            ),
            subprocess.CompletedProcess([], 0, "", ""),
        )
    )

    def fake_run(
        _argv: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return next(outcomes)

    monkeypatch.setattr(importability.subprocess, "run", fake_run)
    failures = importability.import_failures(
        tmp_path / "src", ["sample.missing", "sample.exits"]
    )
    assert failures == (
        "sample.missing: ModuleNotFoundError: No module named 'missing'",
        "sample.exits: exit 0",
    )


def test_command_fails_for_missing_package_initializer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (package / "feature.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(importability, "import_failures", lambda *_args, **_kwargs: ())

    assert importability.main(["--source-root", str(tmp_path / "src")]) == 1
    assert "missing package initializer" in capsys.readouterr().out


def test_real_interpreter_reports_an_unavailable_module(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()

    assert importability.import_failures(source_root, ["email.parser"]) == ()
    failures = importability.import_failures(
        source_root, ["email.__alphus_missing_module__"]
    )
    assert len(failures) == 1
    assert failures[0].startswith(
        "email.__alphus_missing_module__: ModuleNotFoundError:"
    )
