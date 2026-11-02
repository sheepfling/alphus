"""The opt-in Markdown shell check reports reviewable syntax conflicts."""

from __future__ import annotations

import subprocess
from io import StringIO
from pathlib import Path

import pytest

from alphus.config import (
    MarkdownShellFencesPolicy,
    MarkdownShellFenceSuppression,
    load_config_stream,
)
from alphus.contracts.findings import Finding
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.markdown.shell_fences import check_markdown_shell_fences
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape


def _check(
    root: Path,
    markdown: str,
    *,
    name: str = "guide.md",
    policy: MarkdownShellFencesPolicy | None = None,
) -> list[Finding]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return check_markdown_shell_fences(
        root,
        policy or MarkdownShellFencesPolicy(),
        files=(Path(name),),
    )


def test_flags_the_windows_commands_from_issue_60(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        "# Windows example\n"
        "```bash\n"
        ".venv\\Scripts\\python truss.py C:\\dev\\MyPlugin\\Source -o out\n"
        ".venv\\Scripts\\python truss.py C:\\dev\\titan -o docs\\architecture "
        "--module-depth 2 --exclude external release\n"
        "```\n",
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.path == "guide.md"
    assert finding.line == 3
    assert "bash fence" in finding.message
    assert ".venv\\Scripts\\python" in finding.message
    assert "verify the shell with the author" in finding.message
    assert finding.severity == "info"


def test_flags_power_shell_and_cmd_syntax_in_bash_aliases(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        "```sh\n$env:APP_HOME = 'C:\\app'\n```\n```bash\necho %PATH%\n```\n",
    )

    assert len(findings) == 2
    assert findings[0].line == 2
    assert "PowerShell syntax" in findings[0].message
    assert findings[1].line == 5
    assert "cmd syntax" in findings[1].message


def test_flags_bash_loop_in_indented_blockquote_pwsh_fence(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        "> - Example\n"
        ">   ~~~pwsh title=loop\n"
        ">   for name in one two; do\n"
        '>     echo "$name"\n'
        ">   done\n"
        ">   ~~~\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 3
    assert "Bash loop syntax" in findings[0].message
    assert "Git Bash or WSL" in findings[0].message


def test_ignores_correct_labels_shell_neutral_and_quoted_windows_data(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        "echo 'C:\\dev\\source'\n"
        "pwsh -Command '$env:APP_HOME = \"C:\\app\"'\n"
        "pwsh -Command { $env:APP_HOME = 'C:\\app' }\n"
        "git status --short\n"
        "```\n"
        "```powershell\n$env:APP_HOME = 'C:\\app'\n```\n"
        "```bat\necho %PATH%\n```\n"
        "```text\n$env:APP_HOME = x\n```\n"
        "```console\n$env:APP_HOME = x\n```\n"
        "```\n$env:APP_HOME = x\n```\n"
        "````markdown\n```bash\n$env:APP_HOME = x\n```\n````\n"
        "<!--\n```bash\necho %PATH%\n```\n-->\n",
    )

    assert findings == []


def test_ignores_comments_heredocs_and_command_transcripts(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        "# $env:APP_HOME = comment\n"
        "cat <<'SCRIPT'\n"
        "$env:APP_HOME = heredoc\n"
        "%PATH%\n"
        "SCRIPT\n"
        "```\n"
        "```pwsh\n"
        "# for name in values; do\n"
        "<#\nfor other in values; do\n#>\n"
        "Write-Output 'neutral'\n"
        "```\n"
        "```bash\n"
        "# Recorded shell transcript\n"
        "$ .venv\\Scripts\\python truss.py C:\\dev\\repo\n"
        "C:\\dev\\repo\n"
        "```\n",
    )

    assert findings == []


def test_bash_continuations_and_msys_paths_are_reviewed_conservatively(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        "python script.py \\\n"
        "  --directory '/mnt/c/dev/project' \\\n"
        "  --output result.json\n"
        "```\n",
    )

    assert findings == []


def test_path_selection_and_suppression_use_fence_opener(tmp_path: Path) -> None:
    policy = MarkdownShellFencesPolicy(
        include=("docs/**/*.md",),
        exclude=("docs/generated/**",),
        suppressions=(
            MarkdownShellFenceSuppression(
                path="docs/windows.md",
                line=1,
                reason="This example intentionally contrasts Windows and Bash paths.",
            ),
        ),
    )
    findings = _check(
        tmp_path,
        "```bash\necho %PATH%\n```\n",
        name="docs/windows.md",
        policy=policy,
    )
    _check(
        tmp_path,
        "```bash\necho %PATH%\n```\n",
        name="docs/generated/example.md",
        policy=policy,
    )

    assert findings == []


def test_policy_is_configurable_and_rule_uses_findings_output() -> None:
    config = load_config_stream(
        StringIO(
            "schema_version = 1\n"
            "[checks.markdown_shell_fences]\n"
            'include = ["docs/**/*.md"]\n'
            'exclude = ["docs/generated/**"]\n'
            "[[checks.markdown_shell_fences.suppressions]]\n"
            'path = "docs/windows.md"\n'
            "line = 12\n"
            'reason = "This example intentionally shows both shell syntaxes."\n'
        )
    )

    assert config.checks.markdown_shell_fences is not None
    assert config.checks.markdown_shell_fences.include == ("docs/**/*.md",)
    assert config.checks.markdown_shell_fences.suppressions[0].line == 12
    assert RULE_SPECS["markdown-shell-fences"].output_shape is RuleOutputShape.FINDINGS


def test_rule_runner_uses_git_inventory_without_a_files_policy(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("```bash\necho %PATH%\n```\n", encoding="utf-8")
    config = load_config_stream(
        StringIO("schema_version = 1\n[checks.markdown_shell_fences]\n")
    )

    findings = run_builtin_rule("markdown-shell-fences", tmp_path, (), config)

    assert len(findings) == 1
    assert findings[0].path == "README.md"
    assert findings[0].line == 2
    assert not RULE_SPECS["markdown-shell-fences"].requires_files


@pytest.mark.parametrize(
    "policy",
    [
        {"include": ["../private.md"]},
        {
            "suppressions": [
                {"path": "guide.md", "line": 0, "reason": "Long enough reason text."}
            ]
        },
    ],
)
def test_rejects_unsafe_patterns_and_suppression_lines(
    policy: object,
) -> None:
    with pytest.raises(ValueError):
        MarkdownShellFencesPolicy.model_validate(policy)
