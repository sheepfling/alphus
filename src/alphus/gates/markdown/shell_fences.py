"""Find high-confidence shell and fence-label conflicts in Markdown."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

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
_OPEN_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_CLOSE_FENCE = re.compile(r"^( {0,3})(`+|~+)[ \t]*$")
_LIST_MARKER = re.compile(r"^( {0,3})([-+*]|[0-9]{1,9}[.)])([ \t]+)")
_HERE_DOCUMENT = re.compile(
    r"(?<!<)<<(?P<tabs>-)?[ \t]*(?:"
    r"'(?P<single>[^']+)'|\"(?P<double>[^\"]+)\"|"
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
_CMD_ENV = re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%")
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
    r"^(?:\$[ \t]+|PS(?:[ \t]+[^>\r\n]*)?>[ \t]+|"
    r"[A-Za-z]:\\[^>\r\n]*>[ \t]+|>>>[ \t]+)"
)


@dataclass(frozen=True, slots=True)
class _SourceLine:
    number: int
    text: str


def _new_source_lines() -> list[_SourceLine]:
    return []


def _new_indents() -> list[int]:
    return []


@dataclass(frozen=True, slots=True)
class _Fence:
    label: str
    marker: str
    marker_length: int
    opening_line: int
    container_indent: int
    body: tuple[_SourceLine, ...]


@dataclass(slots=True)
class _OpenFence:
    label: str
    marker: str
    marker_length: int
    opening_line: int
    container_indent: int
    body: list[_SourceLine] = field(default_factory=_new_source_lines)


@dataclass(slots=True)
class _MarkdownContainers:
    list_indents: list[int] = field(default_factory=_new_indents)


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


def _strip_blockquotes(line: str) -> str:
    """Remove source-level blockquote markers before fence parsing."""
    remaining = line
    while True:
        match = re.match(r"^ {0,3}>[ \t]?", remaining)
        if match is None:
            return remaining
        remaining = remaining[match.end() :]


def _normalise_markdown_line(
    line: str, containers: _MarkdownContainers
) -> tuple[str, int]:
    """Remove list indentation and markers while retaining their continuation width."""
    remaining = _strip_blockquotes(line)
    if not remaining.strip():
        return remaining, containers.list_indents[-1] if containers.list_indents else 0

    indent = len(remaining) - len(remaining.lstrip(" "))
    while containers.list_indents and indent < containers.list_indents[-1]:
        containers.list_indents.pop()

    consumed = containers.list_indents[-1] if containers.list_indents else 0
    if consumed:
        remaining = remaining[consumed:]

    marker = _LIST_MARKER.match(remaining)
    if marker is not None:
        padding = min(len(marker.group(3)), 4)
        item_indent = consumed + marker.start(1) + len(marker.group(2)) + padding
        containers.list_indents.append(item_indent)
        remaining = remaining[
            marker.start(1) + len(marker.group(1)) + len(marker.group(2)) + padding :
        ]
        consumed = item_indent

    return remaining, consumed


def _fence_label(info: str) -> str:
    match = re.match(r"\s*(?:\{\.?([A-Za-z0-9_+.-]+)[^}]*\}|([A-Za-z0-9_+.-]+))", info)
    if match is None:
        return ""
    return (match.group(1) or match.group(2)).lower()


def _fence_body_line(line: str, container_indent: int) -> str:
    remaining = _strip_blockquotes(line)
    indent = len(remaining) - len(remaining.lstrip(" "))
    if container_indent and indent >= container_indent:
        return remaining[container_indent:]
    return remaining


def _mask_markdown_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """Hide HTML comments so fenced examples inside them are not parsed."""
    visible = list(line)
    index = 0
    while index < len(line):
        if in_comment:
            end = line.find("-->", index)
            stop = len(line) if end < 0 else end + 3
            for offset in range(index, stop):
                visible[offset] = " "
            if end < 0:
                return "".join(visible), True
            in_comment = False
            index = stop
            continue

        start = line.find("<!--", index)
        if start < 0:
            break
        end = line.find("-->", start + 4)
        stop = len(line) if end < 0 else end + 3
        for offset in range(start, stop):
            visible[offset] = " "
        if end < 0:
            return "".join(visible), True
        index = stop
    return "".join(visible), in_comment


def _markdown_fences(text: str) -> tuple[_Fence, ...]:
    """Read fenced blocks, including fences in blockquotes and list items."""
    containers = _MarkdownContainers()
    fences: list[_Fence] = []
    opened: _OpenFence | None = None
    in_html_comment = False
    for number, original in enumerate(text.splitlines(), start=1):
        if opened is not None:
            content = _fence_body_line(original, opened.container_indent)
            closing = _CLOSE_FENCE.fullmatch(content)
            if (
                closing is not None
                and closing.group(2)[0] == opened.marker
                and len(closing.group(2)) >= opened.marker_length
            ):
                fences.append(
                    _Fence(
                        opened.label,
                        opened.marker,
                        opened.marker_length,
                        opened.opening_line,
                        opened.container_indent,
                        tuple(opened.body),
                    )
                )
                opened = None
            else:
                opened.body.append(_SourceLine(number, content))
            continue

        visible, in_html_comment = _mask_markdown_comments(original, in_html_comment)
        content, container_indent = _normalise_markdown_line(visible, containers)
        opening = _OPEN_FENCE.fullmatch(content)
        if opening is None:
            continue
        marker, info = opening.group(2), opening.group(3)
        if marker.startswith("`") and "`" in info:
            continue
        opened = _OpenFence(
            _fence_label(info),
            marker[0],
            len(marker),
            number,
            container_indent,
        )

    if opened is not None:
        fences.append(
            _Fence(
                opened.label,
                opened.marker,
                opened.marker_length,
                opened.opening_line,
                opened.container_indent,
                tuple(opened.body),
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
            match.group("single") or match.group("double") or match.group("bare")
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
            if candidate.strip() == delimiter:
                pending_heredocs.popleft()
            continue
        if shell == "bash" and _POWERSHELL_DELEGATION.match(source.text):
            output.append(_SourceLine(source.number, " " * len(source.text)))
            continue
        visible = _mask_shell_line(source.text, shell, state)
        if shell == "bash":
            pending_heredocs.extend(_heredoc_delimiters(source.text, visible))
        if visible.strip():
            output.append(_SourceLine(source.number, visible))
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
        cmd = _first_match(lines, _CMD_ENV, "cmd")
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
