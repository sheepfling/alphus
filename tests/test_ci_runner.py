import json
import subprocess
from pathlib import Path

import pytest

from scripts import ci
from scripts.ci import dependency_floors


def test_ci_dependency_floors_follow_package_metadata() -> None:
    assert dependency_floors(Path("pyproject.toml")) == (
        "packaging==23",
        "pydantic==2.7",
        "rich==15.0.0",
        "typer==0.27.3",
        "pyright==1.1.414",
        "pytest==8",
        "ruff==0.16",
    )


def test_ci_stage_failure_has_context_in_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        ci.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["python", "-m", "alphus"], 3, "profile output", "missing tool"
        ),
    )
    with pytest.raises(subprocess.CalledProcessError):
        ci.run(Path("."), "python", "-m", "alphus", stage="Self profile", output="json")
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]["stage"] == "Self profile"
    assert events[1]["exit_code"] == 3
    assert events[1]["stderr"] == "missing tool"
    assert events[1]["stdout"] == "profile output"


def test_ci_stage_success_is_readable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        ci.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["python"], 0, "ok\n", ""
        ),
    )
    ci.run(Path("."), "python", stage="Import", output="plain")
    output = capsys.readouterr().out
    assert "==> Import:" in output
    assert "ok\n" in output
    assert "PASS Import (exit 0" in output


def test_json_ci_failure_bounds_captured_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        ci.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["tool"], 1, "x" * (ci.JSON_CAPTURE_LIMIT + 3), ""
        ),
    )
    with pytest.raises(subprocess.CalledProcessError):
        ci.run(Path("."), "tool", stage="Large failure", output="json")
    event = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert len(event["stdout"]) == ci.JSON_CAPTURE_LIMIT
    assert event["stdout_truncated"] is True
