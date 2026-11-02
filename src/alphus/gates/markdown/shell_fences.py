"""Find high-confidence shell and fence-label conflicts in Markdown."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from markdown_it import MarkdownIt

from alphus.config import MarkdownShellFencesPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import git_files, matches_path
from alphus.support.source_text import read_utf8_text

_RULE_ID = rule_tag(
    Scope.MARKDOWN, Framework.NONE, Category.PORTABILITY, "shell-fence-mismatch"
)
_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "bash": "bash",
        "sh": "bash",
        "zsh": "bash",
        "dash": "bash",
        "ash": "bash",
        "powershell": "powershell",
        "pwsh": "powershell",
        "ps": "powershell",
        "ps1": "powershell",
        "cmd": "cmd",
        "cmd.exe": "cmd",
        "bat": "cmd",
        "batch": "cmd",
    }
)
_HERE_DOCUMENT = re.compile(
    r"(?<!<)<<(?P<tabs>-)?[ \t]*(?:"
    r"'(?P<single>[^']+)'|\"(?P<double>[^\"]+)\"|"
    r"\\(?P<escaped>[A-Za-z_][A-Za-z0-9_]*)|"
    r"(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)
_WINDOWS_PATH = re.compile(
    r"(?<![\w'\"])(?:[A-Za-z]:\\(?:[^\\/:*?\"<>| \t]+\\)*[^\\/:*?\"<>| \t]+|"
    r"(?:\.?\\)?\.venv\\Scripts\\(?:python(?:\.exe)?|activate(?:\.bat)?))"
)
_POWERSHELL_ENV = re.compile(r"\$env:[A-Za-z_][A-Za-z0-9_]*\s*=")
_POWERSHELL_DELEGATION = re.compile(
    r"(?i)^\s*(?:pwsh|powershell)(?:\.exe)?\s+(?:-[A-Za-z][A-Za-z-]*\s+)*"
    r"-Command(?:\s|$)"
)
_QUOTED_POWERSHELL_DELEGATION = re.compile(
    r"(?i)^\s*(?:pwsh|powershell)(?:\.exe)?\s+(?:-[A-Za-z][A-Za-z-]*\s+)*"
    r"-Command[ \t]+(?P<quote>['\"])"
)
_CMD_ENV = re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%")
_PRINTF_FORMAT_COMMAND = re.compile(
    r"(?:^|(?:&&|\|\||[;&|()])[ \t]*)"
    r"(?:(?:command|builtin)[ \t]+)?(?P<command>printf)\b"
)
_SHELL_WORD = re.compile(r"(?:'[^']*'|\"(?:\\.|[^\"])*\"|\\.|[^\s])+")
_PRINTF_FORMAT_DIRECTIVE = re.compile(
    r"%(?:%|[-+#0 ']*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|L|z|j|t)?[bcdeEfFgGiosuxXq])"
)
_DATE_COMMAND = re.compile(r"(?i)\bdate(?:\s|$)")
_DATE_FORMAT_DIRECTIVE = r"%(?:[-_0^#]*\d{0,2})?(?:E|O)?[A-Za-z+]"
_DATE_FORMAT_SEQUENCE = re.compile(
    _DATE_FORMAT_DIRECTIVE + rf"(?:(?:[-_./:T])?{_DATE_FORMAT_DIRECTIVE})+"
)
_POWERSHELL_COMMAND = re.compile(
    r"(?i)^(?:\s*&\s*)?(?:Write-Host|Write-Output|Get-ChildItem|Set-Location|"
    r"Remove-Item|New-Item|Test-Path|Invoke-Expression|Get-Content|Set-Content|"
    r"Copy-Item|Move-Item|Where-Object|ForEach-Object)(?:\s|$)"
)
_POWERSHELL_PIPE_COMMAND = re.compile(
    r"(?i)\|\s*(?:Where-Object|ForEach-Object|Select-Object|Sort-Object)\b"
)
_CMD_COMMAND = re.compile(
    r"(?i)^\s*(?:@?set\s+[A-Za-z_][A-Za-z0-9_]*\s*=|if\s+errorlevel\b|"
    r"cd\s+/d\b|call\s+\S+\.bat\b|echo\s+(?:off|on)\b|"
    r"for\s+%%?[A-Za-z]\s+in\b.*\bdo\b)"
)
_BASH_LOOP = re.compile(r"(?i)^\s*(?:for|select)\s+\$?[A-Za-z_][A-Za-z0-9_]*\s+in\b")
_BASH_WHILE_LOOP = re.compile(r"(?i)^\s*while\b.*\bdo\b")
_TRANSCRIPT_PROMPT = re.compile(
    r"^[ \t]*(?:\$[ \t]+|PS(?:[ \t]+[^>\r\n]*)?>[ \t]+|"
    r"[A-Za-z]:\\[^>\r\n]*>[ \t]+|>>>[ \t]+)"
)


@dataclass(frozen=True, slots=True)
class _SourceLine:
    number: int
    text: str
    raw_text: str | None = None


@dataclass(frozen=True, slots=True)
class _Fence:
    label: str
    opening_line: int
    body: tuple[_SourceLine, ...]


@dataclass(slots=True)
class _LexState:
    quote: str | None = None
    block_comment: bool = False


@dataclass(frozen=True, slots=True)
class _Evidence:
    shell: str
    line: int
    text: str
    candidate: bool = False


def _fence_label(info: str) -> str:
    match = re.match(r"\s*(?:\{\.?([A-Za-z0-9_+.-]+)[^}]*\}|([A-Za-z0-9_+.-]+))", info)
    if match is None:
        return ""
    return (match.group(1) or match.group(2)).lower()


def _markdown_fences(text: str) -> tuple[_Fence, ...]:
    """Read CommonMark fenced-code tokens with source-line locations."""
    fences: list[_Fence] = []
    for token in MarkdownIt("commonmark").parse(text):
        if token.type != "fence" or token.map is None:
            continue
        opening_index = token.map[0]
        body = tuple(
            _SourceLine(opening_index + index + 2, line)
            for index, line in enumerate(token.content.splitlines())
        )
        fences.append(
            _Fence(
                _fence_label(token.info),
                opening_index + 1,
                body,
            )
        )
    return tuple(fences)


def _mask_shell_line(line: str, shell: str, state: _LexState) -> str:
    """Blank comments and quoted data while preserving source columns."""
    visible = list(line)
    index = 0
    while index < len(line):
        if state.block_comment:
            end = line.find("#>", index)
            stop = len(line) if end < 0 else end + 2
            for offset in range(index, stop):
                visible[offset] = " "
            if end < 0:
                return "".join(visible)
            state.block_comment = False
            index = stop
            continue

        if state.quote is not None:
            character = line[index]
            visible[index] = " "
            if (
                shell == "bash"
                and state.quote == '"'
                and character == "\\"
                and index + 1 < len(line)
            ):
                visible[index + 1] = " "
                index += 2
                continue
            if (
                shell == "powershell"
                and state.quote == "'"
                and character == "'"
                and index + 1 < len(line)
                and line[index + 1] == "'"
            ):
                visible[index + 1] = " "
                index += 2
                continue
            if (
                shell == "powershell"
                and state.quote == '"'
                and character == "`"
                and index + 1 < len(line)
            ):
                visible[index + 1] = " "
                index += 2
                continue
            if character == state.quote:
                state.quote = None
            index += 1
            continue

        if shell == "powershell" and line.startswith("<#", index):
            state.block_comment = True
            visible[index] = visible[index + 1] = " "
            index += 2
            continue

        character = line[index]
        if character in "'\"`":
            if shell == "powershell" and character == "`":
                visible[index] = " "
                if index + 1 < len(line):
                    visible[index + 1] = " "
                    index += 2
                else:
                    index += 1
                continue
            state.quote = character
            visible[index] = " "
            index += 1
            continue
        if character == "#" and (
            shell == "powershell"
            or shell == "bash"
            and (index == 0 or line[index - 1].isspace())
        ):
            for offset in range(index, len(line)):
                visible[offset] = " "
            break
        if character == "\\" and index + 1 < len(line) and line[index + 1] in "'\"":
            visible[index] = visible[index + 1] = " "
            index += 2
            continue
        index += 1
    return "".join(visible)


def _heredoc_delimiters(raw: str, visible: str) -> tuple[tuple[str, bool], ...]:
    """Return real here-document delimiters, excluding quoted and commented text."""
    delimiters: list[tuple[str, bool]] = []
    for match in _HERE_DOCUMENT.finditer(raw):
        if visible[match.start() : match.start() + 2] != "<<":
            continue
        delimiter = (
            match.group("single")
            or match.group("double")
            or match.group("escaped")
            or match.group("bare")
        )
        if delimiter is not None:
            delimiters.append((delimiter, match.group("tabs") is not None))
    return tuple(delimiters)


def _visible_shell_lines(fence: _Fence, shell: str) -> tuple[_SourceLine, ...]:
    """Remove comments, strings and Bash here-document bodies from a fence."""
    if _looks_like_transcript(fence, shell):
        return ()

    state = _LexState()
    pending_heredocs: deque[tuple[str, bool]] = deque()
    output: list[_SourceLine] = []
    for source in fence.body:
        if pending_heredocs:
            delimiter, strip_tabs = pending_heredocs[0]
            candidate = source.text.lstrip("\t") if strip_tabs else source.text
            if candidate == delimiter:
                pending_heredocs.popleft()
            continue
        if (
            shell == "bash"
            and _POWERSHELL_DELEGATION.match(source.text)
            and _QUOTED_POWERSHELL_DELEGATION.match(source.text) is None
        ):
            output.append(_SourceLine(source.number, " " * len(source.text)))
            continue
        visible = _mask_shell_line(source.text, shell, state)
        if shell == "bash":
            pending_heredocs.extend(_heredoc_delimiters(source.text, visible))
        if visible.strip():
            output.append(_SourceLine(source.number, visible, source.text))
    return tuple(output)


def _looks_like_transcript(fence: _Fence, shell: str) -> bool:
    """Recognize an interactive prompt before scanning shell-labeled output."""
    for source in fence.body:
        stripped = source.text.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return _TRANSCRIPT_PROMPT.match(source.text) is not None
    return False


def _first_match(
    lines: Sequence[_SourceLine], expression: re.Pattern[str], shell: str
) -> _Evidence | None:
    for source in lines:
        match = expression.search(source.text)
        if match is not None:
            return _Evidence(shell, source.number, match.group(0).strip())
    return None


def _cmd_environment_evidence(lines: Sequence[_SourceLine]) -> _Evidence | None:
    """Find cmd expansion without mistaking date and printf format directives."""
    in_date_continuation = False
    in_printf_continuation = False
    for source in lines:
        raw_line = source.raw_text if source.raw_text is not None else source.text
        candidate, printf_format_found = _mask_printf_format_argument(
            source.text, raw_line, continued=in_printf_continuation
        )
        trailing_backslashes = len(raw_line) - len(raw_line.rstrip("\\"))
        in_printf_continuation = (
            not printf_format_found
            and trailing_backslashes % 2 == 1
            and (
                _PRINTF_FORMAT_COMMAND.search(source.text) is not None
                or in_printf_continuation
            )
        )
        if _DATE_COMMAND.search(candidate) or in_date_continuation:
            candidate = _DATE_FORMAT_SEQUENCE.sub(
                lambda match: " " * len(match.group()), candidate
            )
            trailing_backslashes = len(source.text) - len(source.text.rstrip("\\"))
            in_date_continuation = trailing_backslashes % 2 == 1
        else:
            in_date_continuation = False
        match = _CMD_ENV.search(candidate)
        if match is not None:
            return _Evidence("cmd", source.number, match.group(0))
    return None


def _mask_printf_format_argument(
    line: str, raw_line: str, *, continued: bool = False
) -> tuple[str, bool]:
    """Mask conversions only when they occupy printf's unquoted format word."""
    offset = 0
    if continued:
        indentation = len(raw_line) - len(raw_line.lstrip())
        raw_command = f"printf {raw_line.lstrip()}"
        visible_command = f"printf {line.lstrip()}"
        offset = len("printf ") - indentation
    else:
        visible_command = line
        raw_command = raw_line

    command_match = _PRINTF_FORMAT_COMMAND.search(visible_command)
    if command_match is None:
        return line, False
    if command_match.start("command") + offset > len(raw_command):
        return line, False
    command_text = raw_command[command_match.start("command") :]
    words = list(_SHELL_WORD.finditer(command_text))
    if not words:
        return line, False
    index = 1  # printf command name
    while index < len(words):
        word = words[index].group()
        if word == "--":
            index += 1
            break
        if word == "-v":
            index += 2
            continue
        if word.startswith("-") and word != "-":
            index += 1
            continue
        break
    if index >= len(words):
        return line, False

    match = words[index]
    format_word = match.group()
    if format_word == "\\":
        return line, False
    if format_word.startswith(("'", '"')):
        return line, True
    directives = list(_PRINTF_FORMAT_DIRECTIVE.finditer(format_word))
    percent_positions = [i for i, char in enumerate(format_word) if char == "%"]
    covered = {
        position for directive in directives for position in range(*directive.span())
    }
    if not percent_positions or not all(
        position in covered for position in percent_positions
    ):
        return line, True
    start, end = match.span()
    start += command_match.start("command") - offset
    end += command_match.start("command") - offset
    if start < 0 or end > len(line):
        return line, True
    masked = _PRINTF_FORMAT_DIRECTIVE.sub(
        lambda conversion: " " * len(conversion.group()), line[start:end]
    )
    return f"{line[:start]}{masked}{line[end:]}", True


def _bash_loop_evidence(lines: Sequence[_SourceLine]) -> _Evidence | None:
    for index, source in enumerate(lines):
        if not (_BASH_LOOP.match(source.text) or _BASH_WHILE_LOOP.match(source.text)):
            continue
        combined = source.text
        last = index
        while last < min(len(lines), index + 4):
            if re.search(r";\s*do\b|\n[ \t]*do\b", combined, re.IGNORECASE):
                evidence = re.sub(r"\s+", " ", combined).strip()
                return _Evidence("bash", source.number, evidence[:120])
            last += 1
            if last < len(lines):
                combined += "\n" + lines[last].text
    return None


def _fence_evidence(fence: _Fence) -> tuple[_Evidence, ...]:
    shell = _LABELS.get(fence.label)
    if shell is None:
        return ()
    if shell == "cmd":
        return ()
    lines = _visible_shell_lines(fence, shell)
    if shell == "bash":
        evidence: list[_Evidence] = []
        powershell = _first_match(lines, _POWERSHELL_ENV, "PowerShell")
        if powershell is None:
            powershell = next(
                (
                    _Evidence("PowerShell", line.number, line.text.strip())
                    for line in lines
                    if _POWERSHELL_COMMAND.match(line.text)
                    or _POWERSHELL_PIPE_COMMAND.search(line.text)
                ),
                None,
            )
        cmd = _cmd_environment_evidence(lines)
        if cmd is None:
            cmd = _first_match(lines, _CMD_COMMAND, "cmd")
        candidate = _first_match(
            lines,
            _WINDOWS_PATH,
            "Windows path review",
        )
        if powershell is not None:
            evidence.append(powershell)
        if cmd is not None:
            evidence.append(cmd)
        if candidate is not None:
            evidence.append(
                _Evidence(candidate.shell, candidate.line, candidate.text, True)
            )
        return tuple(evidence)

    if shell == "powershell":
        return tuple(
            evidence
            for evidence in (_bash_loop_evidence(lines),)
            if evidence is not None
        )
    return ()


def _selected_files(
    root: Path,
    policy: MarkdownShellFencesPolicy,
    files: Sequence[Path] | None,
) -> tuple[Path, ...]:
    inventory = git_files(root) if files is None else files
    checkout = root.resolve(strict=True)
    selected: set[Path] = set()
    for path in inventory:
        if path.is_absolute() or ".." in path.parts or "\\" in path.as_posix():
            continue
        candidate = checkout / path
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if not candidate.resolve(strict=True).is_relative_to(checkout):
                continue
        except OSError:
            continue
        relative = path.as_posix()
        if any(
            matches_path(relative, pattern) for pattern in policy.include
        ) and not any(matches_path(relative, pattern) for pattern in policy.exclude):
            selected.add(path)
    return tuple(sorted(selected))


def _suppressed(path: str, fence: _Fence, policy: MarkdownShellFencesPolicy) -> bool:
    return any(
        item.path == path and item.line == fence.opening_line
        for item in policy.suppressions
    )


def _finding(path: str, fence: _Fence, evidence: _Evidence) -> Finding:
    if evidence.candidate:
        message = (
            f"{fence.label} fence contains an unquoted Windows-style path "
            f'"{evidence.text}"; review whether this is intended for PowerShell/cmd '
            "or is a Bash/MSYS/WSL path, and verify the shell with the author"
        )
    elif evidence.shell == "PowerShell":
        message = (
            f'{fence.label} fence contains PowerShell syntax "{evidence.text}"; '
            "verify the intended shell with the author"
        )
    elif evidence.shell == "cmd":
        message = (
            f'{fence.label} fence contains cmd syntax "{evidence.text}"; '
            "verify the intended shell with the author"
        )
    else:
        message = (
            f'{fence.label} fence contains Bash loop syntax "{evidence.text}"; '
            "verify the intended shell with the author, including Git Bash or WSL"
        )
    return Finding(
        rule_id=_RULE_ID,
        path=path,
        line=evidence.line,
        severity="info",
        message=message,
    )


def check_markdown_shell_fences(
    root: Path,
    policy: MarkdownShellFencesPolicy,
    files: Sequence[Path] | None = None,
) -> list[Finding]:
    """Report high-confidence shell-label conflicts as informational findings.

    The check is deliberately heuristic: Windows paths in Bash fences are review
    candidates, since Git Bash and WSL can accept paths that look Windows-like.
    It never executes commands or changes fence labels.
    """
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for path in _selected_files(checkout, policy, files):
        try:
            text = read_utf8_text(checkout / path)
        except (OSError, UnicodeError):
            continue
        relative = path.as_posix()
        for fence in _markdown_fences(text):
            if _suppressed(relative, fence, policy):
                continue
            findings.extend(
                _finding(relative, fence, evidence)
                for evidence in _fence_evidence(fence)
            )
    return findings
