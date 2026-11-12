"""Installed declaration inventory, base paths and native scan coverage."""

from __future__ import annotations

import json
import subprocess
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
        InstalledDeclarations(distribution="sample", files=(str(valid),))
    ) == (valid.resolve(),)
    for paths in (
        (str(valid), str(valid)),
        ("relative.pyi",),
        (str(tmp_path / "missing.pyi"),),
    ):
        with pytest.raises(ValueError):
            declaration_paths(InstalledDeclarations(distribution="sample", files=paths))


def test_snapshot_and_config_keep_all_files_and_canonical_base(tmp_path: Path) -> None:
    package = tmp_path / "site-packages" / "sample-stubs"
    package.mkdir(parents=True)
    first = package / "__init__.pyi"
    second = package / "nested" / "unused.pyi"
    second.parent.mkdir()
    first.write_bytes(b"from .nested import unused\n")
    second.write_bytes(b"value: int\n")
    destination = tmp_path / "project" / "declarations"
    copied = snapshot_declarations((first, second), destination)
    assert tuple(p.read_bytes() for p in copied) == (
        first.read_bytes(),
        second.read_bytes(),
    )
    assert copied[1].relative_to(destination) == Path("nested/unused.pyi")
    config = declaration_config(copied, tmp_path / "project", "3.12")
    assert config.include == (
        "declarations/__init__.pyi",
        "declarations/nested/unused.pyi",
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
