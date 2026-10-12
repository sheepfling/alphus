"""Python owns ordered profile execution across rules and native tools."""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus import orchestration
from alphus.config import (
    CommandRunStep,
    FileInventoryPolicy,
    OrchestrationPolicy,
    OrchestrationProfile,
    RuleRunStep,
)
from alphus.orchestration import _windows_shell_required, run_orchestration


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


def test_windows_batch_detection_uses_the_shared_platform_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestration, "is_windows", lambda: False)
    assert not _windows_shell_required(("npm.cmd",))

    monkeypatch.setattr(orchestration, "is_windows", lambda: True)
    monkeypatch.setattr(orchestration.shutil, "which", lambda _: "npm.cmd")
    assert _windows_shell_required(("npm.cmd",))


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
        stdout=output,
        stderr=StringIO(),
    )

    assert result == 0
    assert (tmp_path / "native.txt").read_text(encoding="utf-8") == "ok"
    assert called_rules == ["line-length"]
    assert output.getvalue().splitlines() == [
        "==> native command",
        "PASS native command",
        "==> portable rule",
        "PASS portable rule",
        "Quality profile check: 2 passed, 0 failed",
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
        "steps": [
            {
                "diagnostics": ["diagnostic"],
                "exit_code": 7,
                "name": "failing command",
                "status": "failed",
            },
            {
                "diagnostics": ["rule line-length"],
                "exit_code": 1,
                "name": "failing rule",
                "status": "failed",
            },
        ],
    }


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


def test_file_scoped_command_receives_only_configured_repository_files(
    tmp_path: Path,
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
    assert json.loads((tmp_path / "seen.json").read_text(encoding="utf-8")) == [
        "docs/guide.md"
    ]


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
    assert "PASS Markdown formatter (no files matched)" in output.getvalue()


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
