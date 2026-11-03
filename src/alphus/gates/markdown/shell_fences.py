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
_HERE_DOCUMENT_OPERATOR = re.compile(r"(?<!<)<<(?P<tabs>-)?[ \t]*(?!<)")
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
    r"-Command[ \t]+[^'\"]*(?P<quote>['\"])"
)
_CMD_ENV = re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%")
_URL_TOKEN = re.compile(r"(?i)\b(?:https?://|ftp://|www\.)[^\s'\"<>]+")
_URL_PERCENT_ESCAPE = re.compile(r"%[0-9a-f]{2}", re.IGNORECASE)
_PRINTF_FORMAT_COMMAND = re.compile(
    r"(?:^[ \t]*|(?:&&|\|\||[;&|()])[ \t]*)"
    r"(?:(?:command|builtin)[ \t]+)?"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=[^ \t;&|()]+[ \t]+)*"
    r"(?:env[ \t]+(?:[A-Za-z_][A-Za-z0-9_]*=[^ \t;&|()]+[ \t]+)*)?"
    r"(?P<command>printf)\b"
)
_PRINTF_FORMAT_DIRECTIVE = re.compile(
    r"%(?:%|[-+#0 ']*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|L|z|j|t)?[bcdeEfFgGiosuxXq])"
)
_FIND_FORMAT_DIRECTIVE = re.compile(
    r"%(?:%|[-]?\d*(?:\.\d+)?[aAbBcCdDfFgGhHkKlLmMnNpPsStTuUwWxXyYZA])"
)
_FIND_COMMAND = re.compile(r"(?:^[ \t]*|(?:&&|\|\||[;&|()])[ \t]*)(?P<command>find)\b")
_DATE_COMMAND = re.compile(r"(?i)\bdate(?:\s|$)")
_DATE_FORMAT_DIRECTIVE = r"%(?:[-_0^#]*\d{0,2})?(?:E|O)?[A-Za-z+]"
_DATE_FORMAT_SEQUENCE = re.compile(
    _DATE_FORMAT_DIRECTIVE + rf"(?:(?:[-_./:T])?{_DATE_FORMAT_DIRECTIVE})+"
)
_POWERSHELL_COMMAND = re.compile(
    r"(?i)^\s*(?:&\s*)?(?:Write-Host|Write-Output|Get-ChildItem|Set-Location|"
    r"Remove-Item|New-Item|Test-Path|Invoke-Expression|Get-Content|Set-Content|"
    r"Copy-Item|Move-Item|Where-Object|ForEach-Object)(?:\s|$)"
)
_POWERSHELL_PIPE_COMMAND = re.compile(
    r"(?i)\|\s*(?:Where-Object|ForEach-Object|Select-Object|Sort-Object)\b"
)
_CMD_COMMAND = re.compile(
    r"(?i)^\s*(?:@?set\s+[A-Za-z_][A-Za-z0-9_]*\s*=|if\s+errorlevel\b|"
    r"cd\s+/d\b|call\s+\S+\.bat\b|@echo\s+(?:off|on)\b|"
    r"for\s+%%?[A-Za-z]\s+in\b.*\bdo\b)"
)
_BASH_LOOP = re.compile(r"(?i)^\s*(?:for|select)\s+\$?[A-Za-z_][A-Za-z0-9_]*\s+in\b")
_BASH_WHILE_LOOP = re.compile(r"(?i)^\s*while\b")
_POWERSHELL_WHILE_LOOP = re.compile(r"(?i)^\s*while\s*\(")
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
    ansi_c_quote: bool = False
    block_comment: bool = False
    here_string: str | None = None


@dataclass(slots=True)
class _ArithmeticState:
    depth: int = 0


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
    escaped_shell_characters = "'\"`\\" if shell == "bash" else ""
    index = 0
    while index < len(line):
        if state.here_string is not None:
            delimiter = state.here_string
            if line.startswith(delimiter):
                state.here_string = None
            return " " * len(line)

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
                and (state.quote == '"' or state.ansi_c_quote)
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
                state.ansi_c_quote = False
            index += 1
            continue

        if shell == "powershell" and line.startswith("<#", index):
            state.block_comment = True
            visible[index] = visible[index + 1] = " "
            index += 2
            continue

        if shell == "powershell" and line.startswith(("@'", '@"'), index):
            state.here_string = "'@" if line[index + 1] == "'" else '"@'
            return " " * len(line)

        if shell == "bash" and line.startswith("$'", index):
            state.quote = "'"
            state.ansi_c_quote = True
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
            and (
                index == 0 or line[index - 1].isspace() or line[index - 1] in ";|&()<>"
            )
        ):
            for offset in range(index, len(line)):
                visible[offset] = " "
            break
        if (
            character == "\\"
            and index + 1 < len(line)
            and line[index + 1] in escaped_shell_characters
        ):
            visible[index] = visible[index + 1] = " "
            index += 2
            continue
        index += 1
    return "".join(visible)


def _heredoc_delimiters(
    raw: str, visible: str, arithmetic: _ArithmeticState
) -> tuple[tuple[str, bool], ...]:
    """Return real here-document delimiters, excluding quoted and commented text."""
    delimiters: list[tuple[str, bool]] = []
    heredoc_visible = _mask_arithmetic_shifts(visible, arithmetic)
    for match in _HERE_DOCUMENT_OPERATOR.finditer(raw):
        if heredoc_visible[match.start() : match.start() + 2] != "<<":
            continue
        delimiter = _heredoc_word(raw, match.end())
        if delimiter is not None:
            delimiters.append((delimiter, match.group("tabs") is not None))
    return tuple(delimiters)


def _heredoc_word(raw: str, start: int) -> str | None:
    """Read one here-document word with shell quote removal, without expansion."""
    result: list[str] = []
    quote: str | None = None
    ansi_c_quote = False
    word_started = False
    index = start
    while index < len(raw):
        character = raw[index]
        if quote is not None:
            if ansi_c_quote and character == "\\":
                escape = _ansi_c_escape(raw, index)
                if escape is None:
                    return None
                value, index = escape
                result.append(value)
                continue
            if character == quote:
                quote = None
                ansi_c_quote = False
                index += 1
                continue
            if character == "\\" and quote == '"' and index + 1 < len(raw):
                following = raw[index + 1]
                if following in '$`"\\':
                    result.append(following)
                    index += 2
                    continue
                result.append("\\")
                index += 1
                continue
            result.append(character)
            index += 1
            continue

        if character in "'\"":
            word_started = True
            quote = character
            index += 1
            continue
        if raw.startswith("$'", index):
            word_started = True
            quote = "'"
            ansi_c_quote = True
            index += 2
            continue
        if character == "\\":
            if index + 1 >= len(raw):
                return None
            word_started = True
            result.append(raw[index + 1])
            index += 2
            continue
        if character.isspace() or character in ";&|()<>":
            break
        word_started = True
        result.append(character)
        index += 1

    if quote is not None or not word_started:
        return None
    return "".join(result)


def _ansi_c_escape(raw: str, index: int) -> tuple[str, int] | None:
    """Decode one Bash ANSI-C escape, returning its value and next offset."""
    if index + 1 >= len(raw):
        return None
    following = raw[index + 1]
    if following == "a":
        return "\a", index + 2
    if following == "b":
        return "\b", index + 2
    if following in {"e", "E"}:
        return "\x1b", index + 2
    if following == "f":
        return "\f", index + 2
    if following == "n":
        return "\n", index + 2
    if following == "r":
        return "\r", index + 2
    if following == "t":
        return "\t", index + 2
    if following == "v":
        return "\v", index + 2
    if following in {"\\", "'", '"', "?"}:
        return following, index + 2
    if following == "\n":
        return "", index + 2
    if following == "c" and index + 2 < len(raw):
        return chr(ord(raw[index + 2]) & 0x1F), index + 3
    if following in "01234567":
        end = index + 1
        while end < len(raw) and end < index + 4 and raw[end] in "01234567":
            end += 1
        return chr(int(raw[index + 1 : end], 8)), end
    if following == "x":
        end = index + 2
        while (
            end < len(raw) and end < index + 4 and raw[end] in "0123456789abcdefABCDEF"
        ):
            end += 1
        if end == index + 2:
            return None
        value = int(raw[index + 2 : end], 16)
        if value > 0x10FFFF:
            return None
        return chr(value), end
    if following in "uU":
        width = 4 if following == "u" else 8
        end = index + 2 + width
        digits = raw[index + 2 : end]
        if len(digits) != width or any(
            character not in "0123456789abcdefABCDEF" for character in digits
        ):
            return None
        value = int(digits, 16)
        if value > 0x10FFFF:
            return None
        return chr(value), end
    return "\\" + following, index + 2


def _mask_arithmetic_shifts(line: str, state: _ArithmeticState) -> str:
    """Hide `<<` arithmetic shifts, retaining arithmetic context across lines."""
    visible = list(line)
    index = 0
    while index < len(line):
        if state.depth:
            if line.startswith("<<", index):
                visible[index : index + 2] = (" ", " ")
                index += 2
            elif line[index] == "(":
                state.depth += 1
                index += 1
            elif line[index] == ")":
                state.depth -= 1
                index += 1
            else:
                index += 1
            continue

        if line.startswith("$((", index):
            state.depth = 2
            index += 3
        elif line.startswith("((", index):
            state.depth = 2
            index += 2
        else:
            index += 1
    return "".join(visible)


def _visible_shell_lines(fence: _Fence, shell: str) -> tuple[_SourceLine, ...]:
    """Remove comments, strings and Bash here-document bodies from a fence."""
    if _looks_like_transcript(fence, shell):
        return ()

    state = _LexState()
    arithmetic = _ArithmeticState()
    pending_heredocs: deque[tuple[str, bool]] = deque()
    output: list[_SourceLine] = []
    for source in fence.body:
        if pending_heredocs:
            delimiter, strip_tabs = pending_heredocs[0]
            candidate = source.text.lstrip("\t") if strip_tabs else source.text
            if candidate == delimiter:
                pending_heredocs.popleft()
            continue
        if shell == "bash" and _POWERSHELL_DELEGATION.match(source.text):
            if _QUOTED_POWERSHELL_DELEGATION.match(source.text) is None:
                output.append(_SourceLine(source.number, " " * len(source.text)))
                continue
            # Update Bash quote state for multiline delegated text, but do not
            # interpret the PowerShell command line itself as Bash evidence.
            _mask_shell_line(source.text, shell, state)
            output.append(_SourceLine(source.number, " " * len(source.text)))
            continue
        visible = _mask_shell_line(source.text, shell, state)
        if shell == "bash":
            pending_heredocs.extend(
                _heredoc_delimiters(source.text, visible, arithmetic)
            )
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
    """Find cmd expansion without mistaking common percent-encoded text."""
    in_date_continuation = False
    in_printf_continuation = False
    for source in lines:
        raw_line = source.raw_text if source.raw_text is not None else source.text
        candidate, printf_format_found = _mask_printf_format_argument(
            source.text, raw_line, continued=in_printf_continuation
        )
        candidate = _mask_find_format_arguments(
            candidate,
            raw_line,
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
        candidate = _mask_url_percent_escapes(candidate)
        match = _CMD_ENV.search(candidate)
        if match is not None:
            return _Evidence("cmd", source.number, match.group(0))
    return None


def _mask_find_format_arguments(line: str, raw_line: str | None = None) -> str:
    """Mask known GNU find format words while retaining other arguments."""
    visible = list(line)
    source = raw_line if raw_line is not None else line
    spans: list[tuple[int, int]] = []
    for command_match in _FIND_COMMAND.finditer(line):
        command_start = command_match.start("command")
        command_end = _shell_command_end(source, command_start)
        words = _shell_words(source[command_start:command_end])
        index = 1
        while index < len(words):
            _, _, option = words[index]
            if option in {"-printf", "-fprintf"}:
                format_index = index + (2 if option == "-fprintf" else 1)
                if format_index < len(words):
                    format_start, format_end, format_word = words[format_index]
                    value = format_word
                    if (
                        len(value) >= 2
                        and value[0] == value[-1]
                        and value[0] in {"'", '"'}
                    ):
                        value = value[1:-1]
                    directives = list(_FIND_FORMAT_DIRECTIVE.finditer(value))
                    percent_positions = [
                        offset for offset, char in enumerate(value) if char == "%"
                    ]
                    covered = {
                        offset
                        for directive in directives
                        for offset in range(*directive.span())
                    }
                    if percent_positions and all(
                        offset in covered for offset in percent_positions
                    ):
                        spans.append(
                            (
                                command_start + format_start,
                                command_start + format_end,
                            )
                        )
                index += 1
            index += 1
    for start, end in spans:
        visible[start:end] = " " * (end - start)
    return "".join(visible)


def _mask_url_percent_escapes(line: str) -> str:
    """Ignore percent-encoded bytes inside URL-like tokens."""
    visible = list(line)
    for match in _URL_TOKEN.finditer(line):
        url = match.group()
        for escape in _URL_PERCENT_ESCAPE.finditer(url):
            start = match.start() + escape.start()
            visible[start : start + len(escape.group())] = " " * len(escape.group())
    return "".join(visible)


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

    spans: list[tuple[int, int]] = []
    format_found = False
    for command_match in _PRINTF_FORMAT_COMMAND.finditer(visible_command):
        command_start = command_match.start("command")
        if command_start + offset > len(raw_command):
            continue
        command_end = _shell_command_end(raw_command, command_start)
        command_text = raw_command[command_start:command_end]
        words = _shell_words(command_text)
        if not words:
            continue
        index = 1  # printf command name
        while index < len(words):
            word = words[index][2]
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
            continue

        start_in_command, end_in_command, format_word = words[index]
        if format_word == "\\":
            continue
        format_found = True
        if format_word.startswith(("'", '"')):
            continue
        directives = list(_PRINTF_FORMAT_DIRECTIVE.finditer(format_word))
        percent_positions = [i for i, char in enumerate(format_word) if char == "%"]
        covered = {
            position
            for directive in directives
            for position in range(*directive.span())
        }
        if not percent_positions or not all(
            position in covered for position in percent_positions
        ):
            continue
        start = start_in_command + command_start - offset
        end = end_in_command + command_start - offset
        if 0 <= start <= end <= len(line):
            spans.append((start, end))

    if not spans:
        return line, format_found
    masked_line = list(line)
    for start, end in spans:
        masked_line[start:end] = " " * (end - start)
    return "".join(masked_line), format_found


def _shell_words(source: str) -> list[tuple[int, int, str]]:
    """Split a shell line into words in linear time, retaining source spans.

    This is deliberately a small tokenizer for printf option/format context,
    not a shell parser. Unterminated quotes consume the rest of the line.
    """
    words: list[tuple[int, int, str]] = []
    index = 0
    while index < len(source):
        while index < len(source) and source[index].isspace():
            index += 1
        if index == len(source):
            break
        start = index
        quote: str | None = None
        while index < len(source):
            char = source[index]
            if quote is not None:
                if quote == '"' and char == "\\" and index + 1 < len(source):
                    index += 2
                    continue
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == "\\" and index + 1 < len(source):
                index += 2
                continue
            elif char.isspace():
                break
            index += 1
        end = index
        words.append((start, end, source[start:end]))
        while index < len(source) and source[index].isspace():
            index += 1
    return words


def _shell_command_end(source: str, start: int) -> int:
    """Find the next unquoted shell command separator from ``start``."""
    quote: str | None = None
    index = start
    while index < len(source):
        char = source[index]
        if quote is not None:
            if quote == '"' and char == "\\" and index + 1 < len(source):
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "\\" and index + 1 < len(source):
            index += 2
            continue
        elif char in ";|&)":
            return index
        index += 1
    return len(source)


def _bash_loop_evidence(lines: Sequence[_SourceLine]) -> _Evidence | None:
    for index, source in enumerate(lines):
        if not (_BASH_LOOP.match(source.text) or _BASH_WHILE_LOOP.match(source.text)):
            continue
        if _POWERSHELL_WHILE_LOOP.match(source.text):
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
