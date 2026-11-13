"""Machine output stays parseable for setup and execution failures."""

from __future__ import annotations

import json
import subprocess
from collections.abc import MutableSequence, Sequence
from pathlib import Path

import pytest

from alphus.gates.stubs import verify
from alphus.gates.stubs.checker_reports import FixtureReport


@pytest.mark.parametrize(
    "arguments, error_text",
    [
        ([], "--root"),
        (["--root", ".", "--output", "human"], "at most once"),
        (["--root", ".", "--checkers", "unknown"], "invalid choice"),
        (["--root", ".", "--checkers", "ty", "ty"], "unique"),
    ],
)
def test_json_argument_failures_have_one_structured_report(
    arguments: Sequence[str], error_text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert verify.main([*arguments, "--output", "json"]) == 2
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["schema_version"] == 1
    assert report["kind"] == "stub-verification"
    assert not report["passed"]
    assert error_text in " ".join(report["errors"])


def test_json_preflight_failure_replaces_stale_passed_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "result.json"
    report.write_text('{"passed": true}', encoding="utf-8")
    assert (
        verify.main(
            ["--root", str(tmp_path), "--report", str(report), "--output", "json"]
        )
        != 0
    )
    output = capsys.readouterr()
    assert json.loads(output.out) == json.loads(report.read_text())
    assert not json.loads(output.out)["passed"]
    assert "stub-quality.json" in json.loads(output.out)["errors"][0]


@pytest.mark.parametrize(
    "checkers", [("ty",), ("mypy", "pyright"), ("mypy", "pyright", "ty")]
)
def test_json_cli_preserves_exact_checker_selection_and_routes_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    checkers: tuple[str, ...],
) -> None:
    def run(
        options: verify.VerificationOptions,
        reports: MutableSequence[verify.VerificationReport],
    ) -> int:
        assert options.checkers == checkers
        print("progress belongs on stderr")
        reports.append(
            verify.VerificationReport(passed=True, typing_checkers=options.checkers)
        )
        return 0

    monkeypatch.setattr(verify, "_run_verification", run)
    assert (
        verify.main(
            ["--root", str(tmp_path), "--checkers", *checkers, "--output", "json"]
        )
        == 0
    )
    output = capsys.readouterr()
    assert json.loads(output.out)["typing_checkers"] == list(checkers)
    assert "progress belongs on stderr" in output.err


@pytest.mark.parametrize(
    "stdout, code",
    [
        ("garbled", 0),
        (FixtureReport(passed=False, errors=("missing tool",)).model_dump_json(), 0),
    ],
)
def test_stage_machine_evidence_cannot_silently_disagree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    code: int,
) -> None:
    monkeypatch.setattr(
        verify.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], code, stdout, ""),
    )
    stages: list[verify.VerificationStage] = []
    with pytest.raises(SystemExit):
        verify.run_step(
            "fixtures",
            ["python", "-m", "alphus.gates.stubs.typing_fixtures", "--output", "json"],
            tmp_path,
            {},
            stages=stages,
        )
    assert stages[0].exit_code == 1
    assert "invalid structured stage result" in (stages[0].error or "")


def test_stage_embeds_typed_evidence_without_double_encoded_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = FixtureReport(passed=False, errors=("missing tool",))
    monkeypatch.setattr(
        verify.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 1, evidence.model_dump_json(), ""
        ),
    )
    stages: list[verify.VerificationStage] = []
    with pytest.raises(SystemExit):
        verify.run_step(
            "fixtures",
            ["python", "-m", "alphus.gates.stubs.typing_fixtures", "--output", "json"],
            tmp_path,
            {},
            stages=stages,
        )
    payload = json.loads(stages[0].model_dump_json())
    assert payload["evidence"]["kind"] == "stub-typing-fixtures"
    assert payload["evidence"]["errors"] == ["missing tool"]


def test_stage_rejects_checker_selection_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = FixtureReport(
        passed=False, checkers=("pyright",), errors=("missing tool",)
    )
    monkeypatch.setattr(
        verify.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 1, evidence.model_dump_json(), ""
        ),
    )
    stages: list[verify.VerificationStage] = []
    with pytest.raises(SystemExit):
        verify.run_step(
            "fixtures",
            [
                "python",
                "-m",
                "alphus.gates.stubs.typing_fixtures",
                "--output",
                "json",
                "--checkers",
                "mypy",
                "pyright",
                "ty",
            ],
            tmp_path,
            {},
            stages=stages,
        )
    assert "checkers disagree" in (stages[0].error or "")
