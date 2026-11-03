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


def test_plain_bash_echo_on_off_is_not_cmd_syntax(tmp_path: Path) -> None:
    findings = _check(tmp_path, "```bash\necho on\necho off\n````\n")

    assert findings == []


def test_cmd_at_echo_off_remains_strong_evidence(tmp_path: Path) -> None:
    findings = _check(tmp_path, "```bash\n@echo off\n````\n")

    assert len(findings) == 1
    assert findings[0].line == 2
    assert "cmd syntax" in findings[0].message


def test_date_format_percent_tokens_are_not_cmd_environment_evidence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\nRUN_ID=$(date -u +%Y%m%dT%H%M%SZ)\necho %PATH%\n```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 3
    assert "cmd syntax" in findings[0].message


def test_url_percent_escapes_are_not_cmd_environment_evidence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\ncurl https://example.com/%E2%82%AC\necho %PATH%\n````\n",
    )

    assert [finding.line for finding in findings] == [3]
    assert findings[0].message.endswith(
        'cmd syntax "%PATH%"; verify the intended shell with the author'
    )


@pytest.mark.parametrize(
    "date_command",
    [
        "RUN_ID=$(date -u \\\n  +%Y%m%dT%H%M%SZ)",
        "RUN_ID=$(date -u +%Y_%m_%d)",
    ],
)
def test_date_formats_across_bash_continuations_are_not_cmd_syntax(
    tmp_path: Path, date_command: str
) -> None:
    findings = _check(tmp_path, f"```bash\n{date_command}\n```\n")

    assert findings == []


def test_date_formats_and_real_cmd_environment_syntax_stay_distinguishable(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\nRUN_ID=$(date -u +%Y_%m_%d)\necho %PATH%\n```\n"
        "```bash\ndate; echo %PATH%\n```\n",
    )

    assert [finding.line for finding in findings] == [3, 6]
    assert all("cmd syntax" in finding.message for finding in findings)


def test_printf_format_directives_are_not_cmd_environment_evidence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        '```bash\nprintf %s%s "$prefix" "$suffix"\n````\n',
    )

    assert findings == []


def test_printf_arguments_preserve_real_cmd_environment_evidence(
    tmp_path: Path,
) -> None:
    findings = _check(tmp_path, "```bash\nprintf %s %PATH%\n````\n")

    assert len(findings) == 1
    assert findings[0].line == 2
    assert "cmd syntax" in findings[0].message


def test_quoted_printf_format_preserves_cmd_environment_arguments(
    tmp_path: Path,
) -> None:
    findings = _check(tmp_path, "```bash\nprintf '%s' %userprofile%\n````\n")

    assert len(findings) == 1
    assert findings[0].line == 2
    assert "cmd syntax" in findings[0].message


def test_printf_options_and_backslash_continuation_keep_format_context(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        'printf -- %s%s "$prefix" "$suffix"\n'
        "printf \\\n"
        "  %s%s \\\n"
        '  "$prefix" \\\n'
        '  "$suffix"\n'
        "````\n",
    )

    assert findings == []


def test_printf_command_prefixes_preserve_formats_and_real_cmd_arguments(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        'command printf %s%s "$prefix" "$suffix"\n'
        'builtin printf %s%s "$prefix" "$suffix"\n'
        'true; printf %s%s "$prefix" "$suffix"\n'
        "````\n"
        "```bash\n"
        "command printf '%s' %PATH%\n"
        "````\n"
        "```bash\n"
        "true; builtin printf '%s' %userprofile%\n"
        "````\n",
    )

    assert [finding.line for finding in findings] == [7, 10]
    assert all("cmd syntax" in finding.message for finding in findings)


def test_indented_and_sequential_printf_formats_are_not_cmd_evidence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        "  printf %s%s a b\n"
        "\tprintf %s%s c d\n"
        "printf %s%s a b; printf %s%s c d\n"
        "````\n"
        "```bash\n"
        "printf %s%s a b; printf '%s' %PATH%\n"
        "````\n",
    )

    assert [finding.line for finding in findings] == [7]
    assert findings[0].message.endswith(
        'cmd syntax "%PATH%"; verify the intended shell with the author'
    )


def test_bash_ansi_c_escaped_apostrophe_keeps_scanning_following_lines(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\nprintf $'It\\'s ready\\n'\n$env:APP_HOME = value\n````\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 3
    assert "PowerShell" in findings[0].message


def test_bash_ansi_c_quoted_loop_text_is_not_shell_evidence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        "message=$'It\\'s ready\\nfor item in values; do echo $item; done'\n"
        "````\n",
    )

    assert findings == []


def test_escaped_bash_backtick_does_not_hide_later_evidence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\necho " + chr(92) + "`\n$env:APP_HOME = value\n````\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 3
    assert "PowerShell" in findings[0].message


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


def test_flags_bash_while_loop_with_separate_do_line_in_powershell_fence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```powershell\nwhile true\ndo\n  echo ok\ndone\n```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 2
    assert "Bash loop syntax" in findings[0].message


def test_accepts_bash_while_loop_with_separate_do_line_in_bash_fence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\nwhile true\ndo\n  echo ok\ndone\n```\n",
    )

    assert findings == []


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


def test_escaped_bash_heredoc_delimiter_hides_its_document_body(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\ncat <<\\END\n$env:APP_HOME = heredoc-data\nEND\necho %PATH%\n```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 5
    assert "cmd syntax" in findings[0].message


def test_bash_heredocs_accept_punctuated_and_numeric_delimiters(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        "cat <<EOF-JSON\n"
        "$env:APP_HOME = heredoc-data\n"
        "EOF-JSON\n"
        "$env:APP_HOME = after-heredoc\n"
        "````\n"
        "```bash\n"
        "cat <<123\n"
        "$env:APP_HOME = numeric-heredoc-data\n"
        "123\n"
        "````\n",
    )

    assert [finding.line for finding in findings] == [5]
    assert "PowerShell" in findings[0].message


def test_arithmetic_shifts_are_not_treated_as_heredocs(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        "```bash\n(( mask = 1 << bits ))\n$env:APP_HOME = value\n````\n",
    )
    expansion_findings = _check(
        tmp_path,
        "```bash\nmask=$((1 << bits))\n$env:APP_HOME = value\n````\n",
        name="expansion.md",
    )
    continued_findings = _check(
        tmp_path,
        "```bash\n(( mask = 1 \\\n  << bits ))\n$env:APP_HOME = value\n````\n",
        name="continued.md",
    )

    assert len(findings) == 1
    assert findings[0].line == 3
    assert "PowerShell" in findings[0].message
    assert len(expansion_findings) == 1
    assert expansion_findings[0].line == 3
    assert "PowerShell" in expansion_findings[0].message
    assert len(continued_findings) == 1
    assert continued_findings[0].line == 4
    assert "PowerShell" in continued_findings[0].message


def test_multiline_quoted_pwsh_command_is_not_scanned_as_bash(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\npwsh -Command \"\n$env:APP_HOME = 'C:\\app'\n\"\necho %PATH%\n```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 5
    assert "cmd syntax" in findings[0].message


@pytest.mark.parametrize("quote", ["'", '"'])
def test_quoted_pwsh_command_with_opener_content_keeps_bash_lexing(
    tmp_path: Path, quote: str
) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        f"pwsh -Command {quote}$x = 1\n"
        "$env:HOME = data\n"
        f"{quote}\n"
        "echo %PATH%\n"
        "```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 5
    assert "cmd syntax" in findings[0].message


def test_indented_shell_transcript_prompts_are_ignored(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        "```bash\n    $ echo %PATH%\n    %PATH%\n```\n",
    )

    assert findings == []


@pytest.mark.parametrize("terminator", [" SCRIPT", "SCRIPT ", " SCRIPT "])
def test_heredoc_terminator_must_match_exactly(tmp_path: Path, terminator: str) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        "cat <<'SCRIPT'\n"
        "$env:APP_HOME = data\n"
        f"{terminator}\n"
        "$env:APP_HOME = still-heredoc-data\n"
        "SCRIPT\n"
        "```\n",
    )

    assert findings == []


def test_quoted_fence_ends_when_its_blockquote_container_ends(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "> ```bash\n"
        "> echo inside quoted fence\n"
        "Outside prose with PowerShell-looking text: $env:APP_HOME = data\n",
    )

    assert findings == []


def test_list_fence_ends_when_its_list_container_ends(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        "- ```bash\n"
        "  echo inside list fence\n"
        "Outside prose with PowerShell-looking text: $env:APP_HOME = data\n",
    )

    assert findings == []


def test_fence_opener_indentation_is_removed_from_heredoc_lines(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "  ```bash\n"
        "  cat <<'SCRIPT'\n"
        "  $env:APP_HOME = heredoc-data\n"
        "  SCRIPT\n"
        "  $env:APP_HOME = visible-command\n"
        "  ```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 5


def test_closing_fence_indent_is_not_reduced_by_opener_indent(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "  ~~~bash\n"
        "  echo inside\n"
        "    ~~~\n"
        "  $env:APP_HOME = still-inside-the-fence\n"
        "  ~~~\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 4


def test_tab_indented_list_fence_keeps_heredoc_and_closes_correctly(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "-\t```bash\n"
        "\tcat <<'SCRIPT'\n"
        "\t$env:APP_HOME = heredoc-data\n"
        "\tSCRIPT\n"
        "\t$env:APP_HOME = visible-command\n"
        "\t```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 5


def test_greater_than_in_top_level_heredoc_is_literal(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        "```bash\n"
        "cat <<'END'\n"
        "$env:APP_HOME = heredoc-data\n"
        ">END\n"
        "$env:APP_HOME = still-heredoc-data\n"
        "END\n"
        "```\n",
    )

    assert findings == []


def test_tab_after_blockquote_keeps_mixed_list_fence_indent(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "> - ```bash\n"
        ">\tcat <<'END'\n"
        ">\t$env:APP_HOME = heredoc-data\n"
        ">\tEND\n"
        ">\t$env:APP_HOME = visible-command\n"
        ">   ```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 5


def test_powershell_backtick_escape_does_not_hide_later_bash_loop(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```powershell\n"
        "Write-Output value`\n"
        "for name in values; do\n"
        '  echo "$name"\n'
        "done\n"
        "```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 3
    assert "Bash loop syntax" in findings[0].message


def test_powershell_here_string_quotes_do_not_end_quoted_data(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```powershell\n"
        "$script = @'\n"
        "It's still a here-string: the apostrophe doesn't close it.\n"
        "for file in *.txt; do\n"
        '  echo "$file"\n'
        "done\n"
        "'@\n"
        "for file in *.md; do\n"
        '  Write-Output "$file"\n'
        "done\n"
        "```\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 8
    assert "Bash loop syntax" in findings[0].message


def test_indented_powershell_command_is_detected_in_bash_fence(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        "```bash\nif ($true) {\n  Get-ChildItem\n}\n````\n",
    )

    assert len(findings) == 1
    assert findings[0].line == 3
    assert "PowerShell" in findings[0].message


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
