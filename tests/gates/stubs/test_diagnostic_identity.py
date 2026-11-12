"""Identity and analysis witnesses for installed consumer fixture checks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from alphus.gates.stubs.typing_fixtures import CHECKERS, check_result, run_case


def test_same_basename_elsewhere_cannot_satisfy_marker(tmp_path: Path) -> None:
    fixture = tmp_path / "negative.py"
    fixture.write_text("bad()  # expect-error\n")
    assert check_result(
        fixture,
        1,
        f"{tmp_path / 'other' / fixture.name}:1: error: bad",
        expect_errors=True,
    )
    assert check_result(
        fixture, 1, "other/negative.py:1: error: bad", expect_errors=True, root=tmp_path
    )
    assert not check_result(
        fixture, 1, "negative.py:1: error: bad", expect_errors=True, root=tmp_path
    )


def test_count_only_contract_rejects_foreign_file(tmp_path: Path) -> None:
    fixture = tmp_path / "negative.py"
    fixture.write_text("bad()\n")
    assert check_result(
        fixture, 1, "foreign.py:1: error: bad", expect_errors=True, expected_count=1
    )


def test_symlink_identity_is_accepted(tmp_path: Path) -> None:
    fixture = tmp_path / "negative.py"
    fixture.write_text("bad()  # expect-error\n")
    alias = tmp_path / "alias.py"
    alias.symlink_to(fixture)
    assert not check_result(fixture, 1, f"{alias}:1: error: bad", expect_errors=True)


@pytest.mark.parametrize(
    "count,expected", [(0, False), (1, True), (2, False), (True, False), (None, False)]
)
def test_pyright_requires_one_analyzed_file(
    tmp_path: Path, count: object, expected: bool
) -> None:
    fixture = tmp_path / "positive.py"
    fixture.write_text("x = 1\n")
    report = json.dumps(
        {"generalDiagnostics": [], "summary": {"filesAnalyzed": count, "errorCount": 0}}
    )

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert "--outputjson" in command
        return subprocess.CompletedProcess(command, 0, report, "")

    assert (
        run_case(
            CHECKERS[1],
            fixture,
            root=tmp_path,
            expect_errors=False,
            process_runner=runner,
        )
        is expected
    )


@pytest.mark.parametrize(
    "report",
    [
        json.dumps(
            {
                "summary": {"filesAnalyzed": 1, "errorCount": 0},
                "generalDiagnostics": [{"severity": "unexpected"}],
            }
        ),
        "not json",
        "[]",
        '{"summary": {"filesAnalyzed": 1, "errorCount": 1}, "generalDiagnostics": []}',
    ],
)
def test_pyright_rejects_malformed_or_inconsistent_report(
    tmp_path: Path, report: str
) -> None:
    fixture = tmp_path / "positive.py"
    fixture.write_text("x = 1\n")

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, report, "")

    assert not run_case(
        CHECKERS[1], fixture, root=tmp_path, expect_errors=False, process_runner=runner
    )


def test_pyright_json_foreign_diagnostic_cannot_satisfy_negative(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "negative.py"
    fixture.write_text("bad()  # expect-error\n")
    report = json.dumps(
        {
            "summary": {"filesAnalyzed": 1, "errorCount": 1},
            "generalDiagnostics": [
                {
                    "severity": "error",
                    "file": str(tmp_path / "foreign" / "negative_typecheck.py"),
                    "range": {"start": {"line": 0}},
                    "message": "wrong type",
                }
            ],
        }
    )

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, report, "")

    assert not run_case(
        CHECKERS[1], fixture, root=tmp_path, expect_errors=True, process_runner=runner
    )
