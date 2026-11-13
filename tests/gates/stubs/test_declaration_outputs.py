"""Declaration checker selection, native coverage and stdout contracts."""

from __future__ import annotations

import json
import subprocess
import venv
from pathlib import Path

import pytest

from alphus.gates.stubs import declarations
from alphus.gates.stubs.checker_reports import parse_checker_diagnostics
from alphus.gates.stubs.declarations import (
    DeclarationReport,
    run_declaration_checker,
)
from alphus.support.platform_utils import is_windows
from alphus.support.python_runtime import current_python_executable
from alphus.support.tool_probe import ToolProbe


@pytest.fixture
def installed_namespace(tmp_path: Path) -> tuple[Path, Path]:
    """Install a synthetic partial namespace package using real target metadata."""
    target = tmp_path / "target"
    venv.EnvBuilder(with_pip=False).create(target)
    python = target / ("Scripts/python.exe" if is_windows() else "bin/python")
    result = subprocess.run(
        [str(python), "-I", "-c", "import site; print(site.getsitepackages()[0])"],
        capture_output=True,
        text=True,
        check=True,
    )
    site = Path(result.stdout.strip())
    runtime = site / "namespace" / "widget"
    runtime.mkdir(parents=True)
    (runtime / "__init__.py").write_text("class Value: pass\n", encoding="utf-8")
    package = site / "namespace" / "widget-stubs"
    package.mkdir()
    (package / "py.typed").write_text("partial\n", encoding="utf-8")
    (package / "api.pyi").write_text(
        "from . import Value\nfrom namespace.widget import Value as AbsoluteValue\n"
        "def relative() -> Value: ...\ndef absolute() -> AbsoluteValue: ...\n",
        encoding="utf-8",
    )
    unused = package / "unused.pyi"
    unused.write_text("value: int\n", encoding="utf-8")
    # Distribution names are not import names and must not drive normalization.
    metadata = site / "unrelated_distribution-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: unrelated-distribution\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "RECORD").write_text(
        "namespace/widget-stubs/api.pyi,,\nnamespace/widget-stubs/unused.pyi,,\n"
        "namespace/widget-stubs/py.typed,,\n",
        encoding="utf-8",
    )
    return python, unused


@pytest.mark.parametrize(
    "checkers",
    [
        ("mypy",),
        ("pyright",),
        ("ty",),
        ("mypy", "ty"),
        ("mypy", "pyright"),
        ("pyright", "ty"),
        (),
    ],
)
@pytest.mark.parametrize("invalid", [False, True])
def test_native_namespace_all_single_and_subset_checkers(
    installed_namespace: tuple[Path, Path],
    checkers: tuple[str, ...],
    invalid: bool,
    tmp_path: Path,
) -> None:
    requested = checkers or ("mypy", "pyright", "ty")
    for checker in requested:
        pytest.importorskip(checker)
    python, unused = installed_namespace
    if invalid:
        unused.write_text("value: UndefinedType\n", encoding="utf-8")
    command = [
        current_python_executable(),
        "-m",
        "alphus.gates.stubs.declarations",
        "--distribution",
        "unrelated-distribution",
        "--target-python",
        str(python),
        "--output",
        "json",
    ]
    if checkers:
        command.extend(("--checkers", *checkers))
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    report = DeclarationReport.model_validate_json(result.stdout)
    assert result.stderr == ""
    assert result.returncode == int(invalid), result.stdout
    assert report.passed is not invalid
    assert report.checkers == requested
    assert len(report.inventory) == 2
    assert tuple(item.checker for item in report.results) == requested
    for item in report.results:
        assert len(item.submitted_paths) == 2
        assert item.passed is not invalid
        assert all("widget-stubs" not in path for path in item.submitted_paths)
        if item.checker == "pyright":
            assert item.analyzed_files == 2
            assert item.coverage_kind == "native-count"
        else:
            assert item.analyzed_files is None
            assert item.coverage_kind == "explicit-inputs"
        if invalid:
            assert any(
                "UndefinedType" in diagnostic.message for diagnostic in item.diagnostics
            )
        else:
            assert item.diagnostics == ()


def test_missing_selected_checker_fails_without_invocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unavailable(python: str, module: str) -> ToolProbe:
        return ToolProbe("module", module, False, detail="synthetic missing tool")

    monkeypatch.setattr(declarations, "probe_python_module", unavailable)
    result = run_declaration_checker(
        "ty", (tmp_path / "a.pyi",), tmp_path, current_python_executable(), "3.12"
    )
    assert not result.passed
    assert result.returncode == 127
    assert result.analyzed_files is None
    assert (
        result.validation_error
        and "selected checker ty unavailable" in result.validation_error
    )


@pytest.mark.parametrize("output", ["human", "json"])
def test_cli_output_and_preflight_failure_contract(
    output: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        declarations.main(
            [
                "--distribution",
                "sample",
                "--target-python",
                "/does/not/exist",
                "--output",
                output,
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    if output == "json":
        report = DeclarationReport.model_validate_json(captured.out)
        assert not report.passed
        assert report.errors
        assert report.results == ()
    else:
        assert "ERROR:" in captured.out
        assert not captured.out.lstrip().startswith("{")


@pytest.mark.parametrize(
    "checker, output",
    [
        ("pyright", "{}"),
        ("mypy", "not-json"),
        ("ty", "{}"),
        ("ty", ""),
    ],
)
def test_native_diagnostic_parsers_reject_malformed_reports(
    checker: str, output: str
) -> None:
    with pytest.raises(ValueError):
        parse_checker_diagnostics(checker, output)


def test_report_rejects_success_without_evidence() -> None:
    with pytest.raises(ValueError, match="outcome disagrees"):
        DeclarationReport.model_validate_json(
            json.dumps(
                {
                    "distribution": "sample",
                    "passed": True,
                }
            )
        )


@pytest.mark.parametrize(
    "arguments",
    [
        ("--output", "json"),
        ("--output=json", "--distribution", "sample"),
        ("--output", "json", "--unknown"),
        (
            "--distribution",
            "sample",
            "--target-python",
            "python",
            "--checkers",
            "bad",
            "--output",
            "json",
        ),
    ],
)
def test_missing_or_invalid_arguments_are_json_when_requested(
    arguments: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert declarations.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    report = DeclarationReport.model_validate_json(captured.out)
    assert not report.passed
    assert report.errors


def test_report_rejects_missing_selected_checker_or_inventory_coverage() -> None:
    successful = declarations.DeclarationCheckerResult(
        checker="mypy",
        argv=("mypy", "a.pyi"),
        passed=True,
        returncode=0,
        submitted_paths=("a.pyi",),
        coverage_kind="explicit-inputs",
    )
    with pytest.raises(ValueError, match="results do not match"):
        DeclarationReport(
            distribution="sample",
            inventory=("installed/a.pyi",),
            checkers=("mypy", "ty"),
            results=(successful,),
            passed=True,
        )
    with pytest.raises(ValueError, match="do not cover inventory"):
        DeclarationReport(
            distribution="sample",
            inventory=("installed/a.pyi", "installed/b.pyi"),
            checkers=("mypy",),
            results=(successful,),
            passed=True,
        )


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("invalid_unused", [False, True])
def test_ty_snapshot_keeps_installed_stub_package_precedence(
    installed_namespace: tuple[Path, Path],
    tmp_path: Path,
    partial: bool,
    invalid_unused: bool,
) -> None:
    """Owned __init__.pyi must resolve its siblings, not the installed overlay."""
    pytest.importorskip("ty")
    python, namespace_unused = installed_namespace
    site = namespace_unused.parents[2]
    runtime = site / "toppackage"
    runtime.mkdir()
    (runtime / "__init__.py").write_text("value = 1\n", encoding="utf-8")
    package = site / "toppackage-stubs"
    (package / "nested").mkdir(parents=True)
    files = {
        "__init__.pyi": "from .api import factory as factory\n",
        "api.pyi": "from .nested import Value\ndef factory() -> Value: ...\n",
        "nested/__init__.pyi": "class Value: ...\n",
        "unused.pyi": "value: UndefinedType\n" if invalid_unused else "value: int\n",
        "py.typed": "partial\n" if partial else "",
    }
    for filename, source in files.items():
        (package / filename).write_text(source, encoding="utf-8")
    metadata = site / "top_fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: top-fixture\nVersion: 1.0\n", encoding="utf-8"
    )
    (metadata / "RECORD").write_text(
        "".join(f"toppackage-stubs/{filename},,\n" for filename in files),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            current_python_executable(),
            "-m",
            "alphus.gates.stubs.declarations",
            "--distribution",
            "top-fixture",
            "--target-python",
            str(python),
            "--checkers",
            "ty",
            "--output",
            "json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    report = DeclarationReport.model_validate_json(result.stdout)
    assert result.returncode == int(invalid_unused), result.stdout + result.stderr
    assert report.passed is not invalid_unused
    evidence = report.results[0]
    assert len(evidence.submitted_paths) == 4
    assert all("toppackage-stubs" in path for path in evidence.submitted_paths)
    assert all(item.rule != "import-not-found" for item in evidence.diagnostics)
    if invalid_unused:
        assert any("UndefinedType" in item.message for item in evidence.diagnostics)
