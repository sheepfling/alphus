"""Machine fixture results remain one structured document without console logs."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.gates.stubs import typing_fixtures
from alphus.gates.stubs.checker_reports import FixtureReport, PyrightSummary
from alphus.gates.stubs.typing_fixtures import Checker, evaluate_case
from alphus.support.python_runtime import current_python_executable
from alphus.support.tool_probe import ToolProbe


def test_fixture_machine_evidence_preserves_pyright_rule_and_output(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "positive.py"
    fixture.write_text('value: int = "wrong"\n', encoding="utf-8")
    output = json.dumps(
        {
            "summary": {"filesAnalyzed": 1, "errorCount": 1},
            "generalDiagnostics": [
                {
                    "severity": "error",
                    "file": str(fixture),
                    "message": "wrong type",
                    "range": {"start": {"line": 0}},
                    "rule": "reportAssignmentType",
                }
            ],
        }
    )

    def runner(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, output, "")

    result = evaluate_case(
        Checker("pyright", "pyright"),
        fixture,
        root=tmp_path,
        expect_errors=False,
        process_runner=runner,
    )
    report = FixtureReport(passed=result.passed, checkers=("pyright",), cases=(result,))
    parsed = json.loads(report.model_dump_json())
    assert parsed["schema_version"] == 1
    assert parsed["kind"] == "stub-typing-fixtures"
    assert not parsed["passed"]
    assert parsed["cases"][0]["stdout"] == output
    assert "reportAssignmentType" in parsed["cases"][0]["diagnostics"]
    assert parsed["cases"][0]["returncode"] == 1


@pytest.mark.parametrize(
    "args", [[], ["--checkers", "unknown"], ["--expected-count", "nope"], ["--output"]]
)
def test_json_argument_errors_are_one_document(
    args: Sequence[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert typing_fixtures.main(["--output", "json", *args]) == 2
    captured = capsys.readouterr()
    report = FixtureReport.model_validate_json(captured.out)
    assert not report.passed
    assert report.errors
    assert captured.err == ""


def test_json_missing_files_are_failed_case_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("pyright")
    args = [
        "--output=json",
        "--root",
        str(tmp_path),
        "--positive-fixture",
        str(tmp_path / "missing.py"),
        "--negative-fixture",
        str(tmp_path / "negative.py"),
        "--checkers",
        "pyright",
    ]
    assert typing_fixtures.main(args) == 1
    captured = capsys.readouterr()
    report = FixtureReport.model_validate_json(captured.out)
    assert not report.passed
    assert len(report.cases) == 2
    assert all(case.issues for case in report.cases)
    assert captured.err == ""


@pytest.mark.parametrize("checker", ["mypy", "pyright", "ty"])
def test_json_explicit_subset_has_native_success_and_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], checker: str
) -> None:
    pytest.importorskip(checker)
    positive = tmp_path / "positive.py"
    negative = tmp_path / "negative.py"
    positive.write_text("value: int = 1\n", encoding="utf-8")
    negative.write_text('value: int = "wrong"  # expect-error\n', encoding="utf-8")
    args = [
        "--output",
        "json",
        "--root",
        str(tmp_path),
        "--positive-fixture",
        str(positive),
        "--negative-fixture",
        str(negative),
        "--checkers",
        checker,
    ]
    assert typing_fixtures.main(args) == 0
    captured = capsys.readouterr()
    report = FixtureReport.model_validate_json(captured.out)
    assert report.passed
    assert report.checkers == (checker,)
    assert [case.returncode for case in report.cases] == [0, 1]
    assert report.cases[1].native_diagnostics
    assert report.cases[1].fixture == str(negative.resolve())
    assert captured.err == ""


@pytest.mark.parametrize("value", [-1, True, "1"])
def test_nonnegative_report_counts_remain_strict(value: object) -> None:
    with pytest.raises(ValueError):
        PyrightSummary.model_validate({"filesAnalyzed": value, "errorCount": 0})


def test_json_missing_selected_checker_never_silently_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observed: list[str] = []

    def probe(python: str, module: str) -> ToolProbe:
        observed.append(module)
        return ToolProbe("module", module, module != "ty")

    monkeypatch.setattr(typing_fixtures, "probe_python_module", probe)
    assert (
        typing_fixtures.main(
            [
                "--output",
                "json",
                "--root",
                str(tmp_path),
                "--positive-fixture",
                str(tmp_path / "p.py"),
                "--negative-fixture",
                str(tmp_path / "n.py"),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    report = FixtureReport.model_validate_json(captured.out)
    assert observed == ["mypy", "pyright", "ty"]
    assert not report.passed
    assert "ty is not installed" in report.errors[0]
    assert captured.err == ""


@pytest.mark.parametrize("stdout", ["not JSON", '{"severity": "error"}'])
def test_malformed_native_mypy_evidence_cannot_pass(
    tmp_path: Path, stdout: str
) -> None:
    fixture = tmp_path / "positive.py"
    fixture.write_text("value: int = 1\n", encoding="utf-8")

    def runner(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout, "")

    result = evaluate_case(
        Checker("mypy", "mypy"),
        fixture,
        root=tmp_path,
        expect_errors=False,
        process_runner=runner,
    )
    assert not result.passed
    assert result.issues
    assert result.stdout == stdout


@pytest.mark.parametrize(
    "change", ["empty", "missing", "error", "mismatch", "identity", "process"]
)
def test_forged_fixture_success_is_rejected(change: str) -> None:
    positive = {
        "checker": "pyright",
        "fixture": "/positive.py",
        "analyzed_fixture": "/positive.py",
        "expect_errors": False,
        "passed": True,
        "command": ["pyright"],
        "returncode": 0,
    }
    negative = {
        "checker": "pyright",
        "fixture": "/negative.py",
        "analyzed_fixture": "/temporary.py",
        "expect_errors": True,
        "passed": True,
        "command": ["pyright"],
        "returncode": 1,
        "native_diagnostics": [
            {
                "path": "/temporary.py",
                "line": 1,
                "severity": "error",
                "message": "wrong",
            }
        ],
    }
    report = {"passed": True, "checkers": ["pyright"], "cases": [positive, negative]}
    if change == "empty":
        report["cases"] = []
    elif change == "missing":
        report["cases"] = [positive]
    elif change == "error":
        report["errors"] = ["failed"]
    elif change == "mismatch":
        report["checkers"] = ["ty"]
    elif change == "identity":
        report["checkers"] = ["pyright", "ty"]
        report["cases"] = [
            positive,
            negative,
            dict(positive, checker="ty", fixture="/different.py"),
            dict(negative, checker="ty"),
        ]
    elif change == "process":
        positive["returncode"] = 1
    with pytest.raises(ValueError):
        FixtureReport.model_validate_json(json.dumps(report))


def test_partial_fixture_failure_remains_serializable(tmp_path: Path) -> None:
    # This is a real producer/consumer process boundary, not model reconstruction.
    producer = subprocess.run(
        [
            current_python_executable(),
            "-I",
            "-c",
            (
                "from alphus.gates.stubs.checker_reports import FixtureReport; "
                "print(FixtureReport(passed=False, checkers=('pyright',), "
                "errors=('setup failed',)).model_dump_json())"
            ),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    report = FixtureReport.model_validate_json(producer.stdout)
    assert not report.passed
    assert report.checkers == ("pyright",)
    assert report.errors == ("setup failed",)
    assert not report.cases


def test_duplicate_output_selector_is_rejected_before_execution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = typing_fixtures.main(
        [
            "--output",
            "human",
            "--output=json",
            "--root",
            str(tmp_path),
            "--positive-fixture",
            str(tmp_path / "p.py"),
            "--negative-fixture",
            str(tmp_path / "n.py"),
        ]
    )
    captured = capsys.readouterr()
    report = FixtureReport.model_validate_json(captured.out)
    assert result == 2
    assert report.errors == ("--output must be supplied at most once",)
    assert captured.err == ""


def test_native_mypy_rule_keeps_bracketed_required_diagnostic(tmp_path: Path) -> None:
    fixture = tmp_path / "negative.py"
    fixture.write_text("bad()  # expect-error\n", encoding="utf-8")

    def runner(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        diagnostic = json.dumps(
            {
                "file": command[-1],
                "line": 1,
                "severity": "error",
                "message": "Argument has incompatible type",
                "code": "arg-type",
            }
        )
        return subprocess.CompletedProcess(command, 1, diagnostic, "")

    result = evaluate_case(
        Checker("mypy", "mypy"),
        fixture,
        root=tmp_path,
        expect_errors=True,
        required_diagnostics=("[arg-type]",),
        process_runner=runner,
    )
    assert result.passed, result.issues
    assert "[arg-type]" in result.diagnostics
    assert "(arg-type)" not in result.diagnostics
    assert result.native_diagnostics[0].rule == "arg-type"


def test_native_ty_rule_keeps_required_concise_diagnostic(tmp_path: Path) -> None:
    pytest.importorskip("ty")
    fixture = tmp_path / "negative.py"
    fixture.write_text(
        'def takes_int(value: int) -> None: ...\ntakes_int("wrong")  # expect-error\n',
        encoding="utf-8",
    )
    result = evaluate_case(
        Checker("ty", "ty"),
        fixture,
        root=tmp_path,
        expect_errors=True,
        required_diagnostics=("error[invalid-argument-type] Argument to function",),
    )
    assert result.passed, result.issues
    assert "error[invalid-argument-type] Argument to function" in result.diagnostics
    assert result.native_diagnostics[0].rule == "invalid-argument-type"
    assert result.native_diagnostics[0].message.startswith("invalid-argument-type: ")
