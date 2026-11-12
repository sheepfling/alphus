"""Installed declaration inventory, base paths and native scan coverage."""

from __future__ import annotations

import json
import os
import subprocess
import venv
from pathlib import Path

import pytest

from alphus.gates.stubs.declarations import (
    InstalledDeclarations,
    declaration_config,
    declaration_paths,
    snapshot_declarations,
    validate_declaration_report,
)
from alphus.support.python_runtime import current_python_executable


def test_inventory_requires_existing_unique_absolute_declarations(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "module.pyi"
    valid.write_text("value: int\n", encoding="utf-8")
    assert declaration_paths(
        InstalledDeclarations(
            distribution="sample", installation_root=str(tmp_path), files=(str(valid),)
        )
    ) == (valid.resolve(),)
    for paths in (
        (str(valid), str(valid)),
        ("relative.pyi",),
        (str(tmp_path / "missing.pyi"),),
    ):
        with pytest.raises(ValueError):
            declaration_paths(
                InstalledDeclarations(
                    distribution="sample", installation_root=str(tmp_path), files=paths
                )
            )


def test_snapshot_and_config_keep_all_files_and_canonical_base(tmp_path: Path) -> None:
    package = tmp_path / "site-packages" / "sample-stubs"
    package.mkdir(parents=True)
    first = package / "__init__.pyi"
    second = package / "nested" / "unused.pyi"
    second.parent.mkdir()
    first.write_bytes(b"from .nested import unused\n")
    second.write_bytes(b"value: int\n")
    destination = tmp_path / "project" / "declarations"
    copied = snapshot_declarations((first, second), destination, package.parent)
    assert tuple(p.read_bytes() for p in copied) == (
        first.read_bytes(),
        second.read_bytes(),
    )
    assert copied[1].relative_to(destination) == Path("sample/nested/unused.pyi")
    config = declaration_config(copied, tmp_path / "project", "3.12")
    assert config.include == (
        str(Path("declarations/sample/__init__.pyi")),
        str(Path("declarations/sample/nested/unused.pyi")),
    )


@pytest.mark.parametrize("count", [0, 1, 3, True, None])
def test_report_rejects_incomplete_analysis(count: object) -> None:
    report = json.dumps(
        {"summary": {"filesAnalyzed": count, "errorCount": 0}, "generalDiagnostics": []}
    )
    with pytest.raises(ValueError):
        validate_declaration_report(report, 0, 2)


def test_report_requires_zero_exit_and_consistent_errors() -> None:
    report = json.dumps(
        {"summary": {"filesAnalyzed": 2, "errorCount": 0}, "generalDiagnostics": []}
    )
    validate_declaration_report(report, 0, 2)
    with pytest.raises(ValueError):
        validate_declaration_report(report, 1, 2)


def test_native_scan_catches_unused_invalid_declaration(tmp_path: Path) -> None:
    pytest.importorskip("pyright")
    declarations = tmp_path / "installed snapshot"
    declarations.mkdir()
    good = declarations / "__init__.pyi"
    bad = declarations / "unused.pyi"
    good.write_text("value: int\n", encoding="utf-8")
    bad.write_text("value: UndefinedType\n", encoding="utf-8")
    config = tmp_path / "pyrightconfig.json"
    config.write_text(
        declaration_config((good, bad), tmp_path, "3.12").model_dump_json(
            by_alias=True
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            current_python_executable(),
            "-m",
            "pyright",
            "--project",
            str(config),
            "--outputjson",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    with pytest.raises(ValueError, match="declaration check failed"):
        validate_declaration_report(result.stdout, result.returncode, 2)
    assert "UndefinedType" in result.stdout


@pytest.mark.parametrize("invalid_unused", [False, True])
def test_installed_partial_stub_retains_runtime_and_package_context(
    tmp_path: Path, invalid_unused: bool
) -> None:
    """A lone nested partial declaration keeps its parent's runtime imports."""
    pytest.importorskip("pyright")
    target = tmp_path / "target"
    venv.EnvBuilder(with_pip=False).create(target)
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    result = subprocess.run(
        [str(python), "-I", "-c", "import site; print(site.getsitepackages()[0])"],
        check=True,
        capture_output=True,
        text=True,
    )
    site = Path(result.stdout.strip())
    runtime = site / "sample"
    runtime.mkdir()
    (runtime / "__init__.py").write_text("class Foo: pass\n", encoding="utf-8")
    (runtime / "sub.py").write_text(
        "from . import Foo\ndef factory() -> Foo: return Foo()\n", encoding="utf-8"
    )
    package = site / "sample-stubs"
    package.mkdir()
    (package / "py.typed").write_text("partial\n", encoding="utf-8")
    (package / "sub.pyi").write_text(
        "from . import Foo\nfrom sample import Foo as AbsoluteFoo\n"
        "def factory() -> Foo: ...\ndef absolute() -> AbsoluteFoo: ...\n",
        encoding="utf-8",
    )
    (package / "unused.pyi").write_text(
        "value: UndefinedType\n"
        if invalid_unused
        else "from . import Foo\nvalue: Foo\n",
        encoding="utf-8",
    )
    metadata = site / "sample_stubs-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: sample-stubs\nVersion: 1.0\n", encoding="utf-8"
    )
    (metadata / "RECORD").write_text(
        "sample-stubs/sub.pyi,,\nsample-stubs/unused.pyi,,\nsample-stubs/py.typed,,\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            current_python_executable(),
            "-m",
            "alphus.gates.stubs.declarations",
            "--distribution",
            "sample-stubs",
            "--target-python",
            str(python),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == int(invalid_unused), result.stdout + result.stderr
    if invalid_unused:
        assert "UndefinedType" in result.stdout
    else:
        assert "Verified 2 installed declarations for sample-stubs" in result.stdout
    assert 'Import "." could not be resolved' not in result.stdout
    assert (
        (package / "sub.pyi")
        .read_text(encoding="utf-8")
        .startswith("from . import Foo")
    )


@pytest.mark.parametrize("root_kind", ["relative", "missing", "file"])
def test_snapshot_rejects_invalid_installation_root(
    tmp_path: Path, root_kind: str
) -> None:
    declaration = tmp_path / "sample.pyi"
    declaration.write_text("value: int\n", encoding="utf-8")
    roots = {
        "relative": Path("site-packages"),
        "missing": tmp_path / "missing",
        "file": declaration,
    }
    with pytest.raises(ValueError, match="absolute directory"):
        snapshot_declarations((declaration,), tmp_path / "copy", roots[root_kind])
    assert not (tmp_path / "copy").exists()


def test_snapshot_rejects_declaration_outside_inventory_root(tmp_path: Path) -> None:
    root = tmp_path / "site-packages"
    root.mkdir()
    outside = tmp_path / "outside.pyi"
    outside.write_text("value: int\n", encoding="utf-8")
    with pytest.raises(ValueError):
        snapshot_declarations((outside,), tmp_path / "copy", root)
    assert not (tmp_path / "copy").exists()


def test_snapshot_rejects_colliding_normalized_module_paths(tmp_path: Path) -> None:
    root = tmp_path / "site-packages"
    paths: list[Path] = []
    for package in ("sample", "sample-stubs"):
        path = root / package / "__init__.pyi"
        path.parent.mkdir(parents=True)
        path.write_text("value: int\n", encoding="utf-8")
        paths.append(path)
    with pytest.raises(ValueError, match="duplicate modules"):
        snapshot_declarations(paths, tmp_path / "copy", root)


def test_snapshot_preserves_single_nested_module_and_literal_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "installed space # ;"
    declaration = root / "sample-stubs" / "nested" / "module.pyi"
    declaration.parent.mkdir(parents=True)
    declaration.write_bytes(b"value: int\n")
    destination = tmp_path / "snapshot space # ;"
    copied = snapshot_declarations((declaration,), destination, root)
    assert copied == (destination / "sample" / "nested" / "module.pyi",)
    assert copied[0].read_bytes() == declaration.read_bytes()
    config = declaration_config(copied, tmp_path, "3.12", destination)
    assert config.include == (str(Path("snapshot space # ;/sample/nested/module.pyi")),)
    assert config.extra_paths == ("snapshot space # ;",)
