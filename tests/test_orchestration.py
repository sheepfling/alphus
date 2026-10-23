"""Python owns ordered profile execution across rules and native tools."""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from alphus.config import (
    CommandRunStep,
    FileInventoryPolicy,
    OrchestrationPolicy,
    OrchestrationProfile,
    RuleRunStep,
)
from alphus.contracts.findings import SEVERITY_ORDER, Diagnostic, Severity
from alphus.execution import commands
from alphus.execution.commands import windows_shell_required
from alphus.execution.orchestration import (
    RuleRunResult,
    run_orchestration,
)
from alphus.support import platform_utils


def _policy() -> OrchestrationPolicy:
    return OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="native command",
                argv=(
                    "{python}",
                    "-c",
                    "from pathlib import Path; Path('native.txt').write_text('ok')",
                ),
            ),
            RuleRunStep(kind="rule", name="portable rule", rule="line-length"),
        ),
        profiles=(
            OrchestrationProfile(
                name="check", steps=("native command", "portable rule")
            ),
            OrchestrationProfile(name="lint", steps=("portable rule",)),
        ),
        default_profile="check",
    )


def test_severity_ranks_leave_space_for_future_levels() -> None:
    assert SEVERITY_ORDER["warning"] - SEVERITY_ORDER["info"] >= 10
    assert SEVERITY_ORDER["error"] - SEVERITY_ORDER["warning"] >= 10


def test_provisional_gate_reports_findings_without_blocking_profile(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            RuleRunStep(
                kind="rule",
                name="candidate rule",
                rule="line-length",
                rollout="provisional",
            ),
        ),
        profiles=(OrchestrationProfile(name="check", steps=("candidate rule",)),),
        default_profile="check",
    )
    output = StringIO()
    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda _: RuleRunResult(
            findings=(
                Diagnostic(
                    source="alphus",
                    rule_id="alphus/any/none/style/line-too-long",
                    path="src/example.py",
                    message="line is long",
                ),
            ),
            exit_code=1,
        ),
        json_output=True,
        stdout=output,
        stderr=StringIO(),
    )

    report = json.loads(output.getvalue())
    assert result == report["exit_code"] == 0
    assert (report["passed"], report["failed"]) == (0, 0)
    assert report["provisional"] == {"passed": 0, "failed": 1}
    assert report["steps"][0]["status"] == "failed"
    assert report["steps"][0]["rollout"] == "provisional"
    assert (
        report["steps"][0]["findings"][0]["rule_id"]
        == "alphus/any/none/style/line-too-long"
    )


def test_provisional_native_command_reports_failure_without_blocking_profile(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="candidate tool",
                argv=("{python}", "-c", "raise SystemExit(7)"),
                rollout="provisional",
            ),
        ),
        profiles=(OrchestrationProfile(name="check", steps=("candidate tool",)),),
        default_profile="check",
    )
    output = StringIO()
    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda _: 0,
        json_output=True,
        stdout=output,
        stderr=StringIO(),
    )

    report = json.loads(output.getvalue())
    assert result == report["exit_code"] == 0
    assert report["provisional"] == {"passed": 0, "failed": 1}
    assert report["steps"][0]["exit_code"] == 7
    assert report["steps"][0]["rollout"] == "provisional"


def test_windows_batch_detection_uses_the_shared_platform_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(commands, "is_windows", lambda: False)
    assert not windows_shell_required(("npm.cmd",))

    monkeypatch.setattr(commands, "is_windows", lambda: True)
    monkeypatch.setattr(commands.shutil, "which", lambda _: "npm.cmd")
    assert windows_shell_required(("npm.cmd",))


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", (True, False, False)),
        ("linux", (False, True, False)),
        ("darwin", (False, False, True)),
    ],
)
def test_platform_probes(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expected: tuple[bool, bool, bool],
) -> None:
    monkeypatch.setattr(platform_utils, "sys", SimpleNamespace(platform=platform))
    assert (
        platform_utils.is_windows(),
        platform_utils.is_linux(),
        platform_utils.is_macos(),
    ) == expected


def test_python_orchestrator_runs_profile_without_node_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "")
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    called_rules: list[str] = []
    output = StringIO()

    result = run_orchestration(
        tmp_path,
        config_path,
        _policy(),
        "check",
        lambda rule: called_rules.append(rule) or 0,
        json_output=True,
        stdout=output,
        stderr=StringIO(),
    )

    assert result == 0
    assert (tmp_path / "native.txt").read_text(encoding="utf-8") == "ok"
    assert called_rules == ["line-length"]
    report = json.loads(output.getvalue())
    assert report["passed"] == 2
    assert report["failed"] == 0
    assert [(step["name"], step["status"]) for step in report["steps"]] == [
        ("native command", "passed"),
        ("portable rule", "passed"),
    ]


def test_orchestrator_continues_after_a_failed_step(tmp_path: Path) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="failing command",
                argv=("{python}", "-c", "raise SystemExit(7)"),
            ),
            RuleRunStep(kind="rule", name="later rule", rule="line-length"),
        ),
        profiles=(
            OrchestrationProfile(name="check", steps=("failing command", "later rule")),
        ),
    )
    called_rules: list[str] = []
    output = StringIO()

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda rule: called_rules.append(rule) or 0,
        stdout=output,
        stderr=StringIO(),
    )

    assert result == 1
    assert called_rules == ["line-length"]
    assert "FAIL failing command (exit 7)" in output.getvalue()
    assert "PASS later rule" in output.getvalue()


def test_json_profile_emits_one_structured_summary(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Machine mode keeps stdout parseable and identifies failed steps."""
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="failing command",
                argv=("{python}", "-c", "print('diagnostic'); raise SystemExit(7)"),
            ),
            RuleRunStep(kind="rule", name="failing rule", rule="line-length"),
        ),
        profiles=(
            OrchestrationProfile(
                name="check", steps=("failing command", "failing rule")
            ),
        ),
        failure_threshold="info",
    )

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda rule: print(f"rule {rule}") or 1,
        json_output=True,
    )

    captured = capfd.readouterr()
    payload = json.loads(captured.out)
    assert result == 1
    assert captured.err == ""
    assert payload == {
        "exit_code": 1,
        "failed": 2,
        "passed": 0,
        "profile": "check",
        "failure_threshold": "info",
        "severity_counts": {"error": 2, "warning": 0, "info": 0},
        "steps": [
            {
                "diagnostics": ["diagnostic"],
                "exit_code": 7,
                "findings": [
                    {
                        "line": None,
                        "message": "command exited with status 7",
                        "path": None,
                        "rule_id": "alphus/any/none/orchestration/command-exited-nonzero",
                        "severity": "error",
                        "source": "failing command",
                    }
                ],
                "name": "failing command",
                "severity_counts": {"error": 1, "warning": 0, "info": 0},
                "stderr": "",
                "stdout": "diagnostic\n",
                "status": "failed",
            },
            {
                "diagnostics": ["rule line-length"],
                "exit_code": 1,
                "findings": [
                    {
                        "line": None,
                        "message": "rule runner exited with status 1",
                        "path": None,
                        "rule_id": "alphus/any/none/orchestration/rule-execution-failed",
                        "severity": "error",
                        "source": "alphus",
                    }
                ],
                "name": "failing rule",
                "severity_counts": {"error": 1, "warning": 0, "info": 0},
                "stderr": "",
                "stdout": "rule line-length\n",
                "status": "failed",
            },
        ],
    }


@pytest.mark.parametrize(
    ("severity", "threshold", "expected_exit"),
    [
        ("warning", "error", 0),
        ("warning", "warning", 1),
        ("info", "warning", 0),
        ("info", "info", 1),
    ],
)
def test_profile_applies_typed_severity_thresholds(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    severity: Severity,
    threshold: Severity,
    expected_exit: int,
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(RuleRunStep(kind="rule", name="advisory rule", rule="line-length"),),
        profiles=(OrchestrationProfile(name="check", steps=("advisory rule",)),),
        failure_threshold=threshold,
    )
    finding = Diagnostic(
        source="alphus",
        rule_id="alphus/any/none/style/line-too-long",
        path="src/example.py",
        line=4,
        message="line exceeds configured limit",
        severity=severity,
    )

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda _: RuleRunResult(findings=(finding,)),
        json_output=True,
    )

    payload = json.loads(capfd.readouterr().out)
    assert result == expected_exit
    assert payload["steps"][0]["status"] == ("failed" if expected_exit else "passed")
    assert payload["steps"][0]["findings"] == [
        {
            "source": "alphus",
            "rule_id": "alphus/any/none/style/line-too-long",
            "message": "line exceeds configured limit",
            "severity": severity,
            "path": "src/example.py",
            "line": 4,
        }
    ]
    level_prefix = "" if severity == "error" else f"{severity.upper()} "
    assert payload["steps"][0]["diagnostics"] == [
        f"{level_prefix}src/example.py:4: line exceeds configured limit"
    ]
    assert payload["severity_counts"] == {
        "error": 0,
        "warning": int(severity == "warning"),
        "info": int(severity == "info"),
    }


def test_mixed_profile_findings_keep_provenance_and_error_threshold(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(RuleRunStep(kind="rule", name="mixed rule", rule="line-length"),),
        profiles=(OrchestrationProfile(name="check", steps=("mixed rule",)),),
    )
    findings = (
        Diagnostic(
            source="alphus",
            rule_id="alphus/any/none/style/line-too-long",
            path="src/example.py",
            line=4,
            message="advisory line length",
            severity="warning",
        ),
        Diagnostic(
            source="alphus",
            rule_id="alphus/any/none/maintainability/file-too-large",
            path="src/example.py",
            message="file exceeds hard limit",
        ),
    )

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda _: RuleRunResult(findings=findings),
        json_output=True,
    )

    payload = json.loads(capfd.readouterr().out)
    assert result == 1
    assert payload["severity_counts"] == {"error": 1, "warning": 1, "info": 0}
    assert payload["steps"][0]["findings"] == [
        {
            "source": "alphus",
            "rule_id": "alphus/any/none/style/line-too-long",
            "message": "advisory line length",
            "severity": "warning",
            "path": "src/example.py",
            "line": 4,
        },
        {
            "source": "alphus",
            "rule_id": "alphus/any/none/maintainability/file-too-large",
            "message": "file exceeds hard limit",
            "severity": "error",
            "path": "src/example.py",
            "line": None,
        },
    ]


def test_successful_native_output_is_retained_without_severity_guessing(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="native tool",
                argv=(
                    "{python}",
                    "-c",
                    (
                        "import sys; print('WARNING: stdout text'); "
                        "print('WARNING: stderr text', file=sys.stderr)"
                    ),
                ),
            ),
        ),
        profiles=(OrchestrationProfile(name="check", steps=("native tool",)),),
        failure_threshold="info",
    )

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda _: 0,
        json_output=True,
    )

    payload = json.loads(capfd.readouterr().out)
    assert result == 0
    assert payload["steps"][0]["stdout"] == "WARNING: stdout text\n"
    assert payload["steps"][0]["stderr"] == "WARNING: stderr text\n"
    assert payload["steps"][0]["findings"] == []
    assert payload["severity_counts"] == {"error": 0, "warning": 0, "info": 0}

    text_output = StringIO()
    text_error = StringIO()
    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda _: 0,
        stdout=text_output,
        stderr=text_error,
    )
    assert result == 0
    assert "WARNING: stdout text" in text_output.getvalue()
    assert "WARNING: stderr text" in text_error.getvalue()
    assert "Diagnostic triage" not in text_output.getvalue()


def test_rule_execution_failures_remain_errors_at_info_threshold(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(RuleRunStep(kind="rule", name="broken rule", rule="line-length"),),
        profiles=(OrchestrationProfile(name="check", steps=("broken rule",)),),
        failure_threshold="info",
    )

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda _: RuleRunResult(execution_failure="cannot load checker", exit_code=127),
        json_output=True,
    )

    payload = json.loads(capfd.readouterr().out)
    assert result == 1
    assert payload["steps"][0]["status"] == "failed"
    assert payload["steps"][0]["findings"][0]["severity"] == "error"
    assert payload["severity_counts"] == {"error": 1, "warning": 0, "info": 0}


def test_json_profile_reports_launch_errors_and_continues(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="missing tool",
                argv=(str(tmp_path / "missing-tool"),),
            ),
            RuleRunStep(kind="rule", name="later rule", rule="line-length"),
        ),
        profiles=(
            OrchestrationProfile(name="check", steps=("missing tool", "later rule")),
        ),
        failure_threshold="info",
    )
    called_rules: list[str] = []

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda rule: called_rules.append(rule) or 0,
        json_output=True,
    )

    captured = capfd.readouterr()
    payload = json.loads(captured.out)
    assert result == 1
    assert called_rules == ["line-length"]
    assert payload["exit_code"] == 1
    assert payload["steps"][0]["exit_code"] == 127
    assert payload["steps"][0]["status"] == "failed"
    assert payload["steps"][0]["diagnostics"]
    assert "missing-tool" in payload["steps"][0]["diagnostics"][0]
    assert payload["steps"][1]["status"] == "passed"
    assert "missing-tool" in captured.err


def test_native_output_follows_its_profile_marker_when_stdout_is_captured(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="native output",
                argv=("{python}", "-c", "print('native output')"),
            ),
        ),
        profiles=(OrchestrationProfile(name="check", steps=("native output",)),),
    )

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "check",
        lambda rule: 0,
    )

    assert result == 0
    assert capfd.readouterr().out.splitlines() == [
        "==> native output",
        "native output",
        "PASS native output",
        "Quality profile check: 1 passed, 0 failed",
    ]


def test_orchestration_policy_rejects_unknown_profile_steps() -> None:
    with pytest.raises(ValidationError, match="unknown orchestration steps"):
        OrchestrationPolicy(
            steps=(RuleRunStep(kind="rule", name="known", rule="line-length"),),
            profiles=(OrchestrationProfile(name="check", steps=("missing",)),),
        )


@pytest.mark.parametrize(
    ("working_directory", "expected_file"),
    [
        (".", "docs/guide.md"),
        ("docs", "guide.md"),
        ("private", "../docs/guide.md"),
    ],
)
def test_file_scoped_command_receives_only_configured_repository_files(
    tmp_path: Path,
    working_directory: str,
    expected_file: str,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "private").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
    (tmp_path / "private" / "draft.md").write_text("draft\n", encoding="utf-8")
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="Markdown formatter",
                argv=(
                    "{python}",
                    "-c",
                    (
                        "import json,sys; "
                        "from pathlib import Path; "
                        "Path('seen.json').write_text(json.dumps(sys.argv[1:]))"
                    ),
                    "{files}",
                ),
                files=FileInventoryPolicy(
                    include=("**/*.md",), exclude=("private/**",)
                ),
                working_directory=working_directory,
            ),
        ),
        profiles=(
            OrchestrationProfile(name="markdown", steps=("Markdown formatter",)),
        ),
        default_profile="markdown",
    )

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "markdown",
        lambda rule: 0,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert result == 0
    assert json.loads(
        (tmp_path / working_directory / "seen.json").read_text(encoding="utf-8")
    ) == [expected_file]


def test_file_scoped_command_skips_when_no_files_match(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    config_path = tmp_path / "quality.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="Markdown formatter",
                argv=(
                    "{python}",
                    "-c",
                    "from pathlib import Path; Path('should-not-exist').touch()",
                    "{files}",
                ),
                files=FileInventoryPolicy(include=("**/*.md",)),
            ),
        ),
        profiles=(
            OrchestrationProfile(name="markdown", steps=("Markdown formatter",)),
        ),
        default_profile="markdown",
    )
    output = StringIO()

    result = run_orchestration(
        tmp_path,
        config_path,
        policy,
        "markdown",
        lambda rule: 0,
        stdout=output,
        stderr=StringIO(),
    )

    assert result == 0
    assert not (tmp_path / "should-not-exist").exists()
    assert "NOT APPLICABLE Markdown formatter: no files matched" in output.getvalue()
    json_output = StringIO()
    assert (
        run_orchestration(
            tmp_path,
            config_path,
            policy,
            "markdown",
            lambda rule: 0,
            json_output=True,
            stdout=json_output,
            stderr=StringIO(),
        )
        == 0
    )
    payload = json.loads(json_output.getvalue())
    assert payload["passed"] == 0
    assert payload["failed"] == 0
    assert payload["not_applicable"] == 1
    assert payload["steps"][0]["status"] == "not_applicable"


def test_command_file_policy_requires_one_complete_files_argument() -> None:
    scope = FileInventoryPolicy(include=("**/*.md",))
    with pytest.raises(ValidationError, match=r"requires one \{files\}"):
        CommandRunStep(
            kind="command",
            name="missing placeholder",
            argv=("rumdl", "fmt"),
            files=scope,
        )
    with pytest.raises(ValidationError, match="complete command argument"):
        CommandRunStep(
            kind="command",
            name="embedded placeholder",
            argv=("rumdl", "fmt", "--files={files}"),
            files=scope,
        )
    with pytest.raises(ValidationError, match="requires a command-step files policy"):
        CommandRunStep(
            kind="command",
            name="missing scope",
            argv=("rumdl", "fmt", "{files}"),
        )


def test_command_working_directory_cannot_traverse_checkout() -> None:
    with pytest.raises(ValidationError, match="relative POSIX path"):
        CommandRunStep(
            kind="command",
            name="unsafe path",
            argv=("tool",),
            working_directory="../outside",
        )
