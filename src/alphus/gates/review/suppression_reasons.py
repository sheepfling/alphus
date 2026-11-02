"""Audit selected inline Ruff suppressions for consumer-required reasons."""

from __future__ import annotations

import io
import json
import re
import tokenize
import tomllib
from collections.abc import Collection, Iterable, MutableSequence
from pathlib import Path
from typing import cast

from alphus.config import SuppressionReasonPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source, read_utf8_text

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.STYLE, "missing-suppression-reason"
)
_DIRECTIVE = re.compile(r"^#\s*noqa\s*:\s*(?P<body>.*)$", re.IGNORECASE)
_FILE_DIRECTIVE = re.compile(r"^#\s*ruff\s*:\s*noqa\s*:\s*(?P<body>.*)$", re.IGNORECASE)
_BLANKET_DIRECTIVE = re.compile(r"^#\s*(?:ruff\s*:\s*)?noqa\s*$", re.IGNORECASE)
_CODE = re.compile(r"\b[A-Z]+[0-9]{3,4}\b")


def suppression_reason_findings(
    source: str, policy: SuppressionReasonPolicy, *, path: str = "<source>"
) -> list[Finding]:
    """Find selected inline ``noqa`` codes without the configured reason marker."""
    findings: list[Finding] = []
    required_codes = set(policy.rule_codes)
    exceptions = {
        (exception.path, exception.rule_code, exception.line): exception
        for exception in policy.exceptions
        if exception.path == path
    }
    used_exceptions: set[tuple[str, str, int]] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        comments = (token for token in tokens if token.type == tokenize.COMMENT)
        for token in comments:
            comment = token.string.strip()
            if _BLANKET_DIRECTIVE.fullmatch(comment):
                findings.append(
                    Finding(
                        rule_id=_RULE_ID,
                        path=path,
                        line=token.start[0],
                        severity=policy.severity,
                        message=(
                            "Blanket Ruff suppression has no selected rule code, so "
                            "its reason obligation is unknown to this audit. Review "
                            "the native Ruff blanket-suppression diagnostics; no "
                            "reason status was inferred."
                        ),
                    )
                )
                continue
            inline = bool(token.line[: token.start[1]].strip())
            directive = (
                _DIRECTIVE.fullmatch(comment)
                if inline
                else _FILE_DIRECTIVE.fullmatch(comment)
            )
            if directive is None:
                continue
            body = directive.group("body")
            code_list, separator, reason = body.partition(policy.reason_delimiter)
            selected = sorted(
                required_codes.intersection(
                    code.upper() for code in _CODE.findall(code_list)
                )
            )
            if not selected:
                continue
            unaudited = [
                code
                for code in selected
                if (path, code, token.start[0]) not in exceptions
            ]
            used_exceptions.update(
                (path, code, token.start[0])
                for code in selected
                if code not in unaudited
            )
            if not unaudited or (separator and reason.strip()):
                continue
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=path,
                    line=token.start[0],
                    severity=policy.severity,
                    message=(
                        f"Selected Ruff suppression {', '.join(unaudited)} has no rationale "
                        f"after {policy.reason_delimiter!r}. Add a concise reason to this "
                        "comment. This audit checks documentation only; Ruff still owns "
                        "whether the suppression is valid or used."
                    ),
                )
            )
    except (IndentationError, tokenize.TokenError) as error:
        return [
            Finding(
                rule_id=_RULE_ID,
                path=path,
                severity=policy.severity,
                message=(
                    "Suppression reasons were not evaluated because Python comment "
                    f"tokenization failed: {type(error).__name__}."
                ),
            )
        ]
    for key, exception in exceptions.items():
        if key in used_exceptions:
            continue
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=exception.path,
                line=exception.line,
                severity=policy.severity,
                message=(
                    f"Approved Ruff suppression exception for {exception.rule_code} "
                    "does not match a selected directive at this path and line; "
                    "review or remove the stale exception."
                ),
            )
        )
    return findings


def check_suppression_reasons(
    root: Path, paths: Iterable[Path], policy: SuppressionReasonPolicy
) -> list[Finding]:
    """Scan only selected configured Python files without importing them."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    selected_files: set[str] = set()
    for relative in sorted(set(paths)):
        name = relative.as_posix()
        if relative.suffix != ".py" or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        selected_files.add(name)
        try:
            source = read_python_source(checkout / relative)
        except (OSError, UnicodeError, SyntaxError) as error:
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    severity=policy.severity,
                    message=(
                        "Suppression reasons were not evaluated because the Python "
                        f"source could not be read: {type(error).__name__}."
                    ),
                )
            )
            continue
        findings.extend(suppression_reason_findings(source, policy, path=name))
    findings.extend(_missing_exception_file_findings(checkout, selected_files, policy))
    findings.extend(_ruff_config_suppression_findings(checkout, selected_files, policy))
    return sorted(findings, key=lambda item: (item.path, item.line or 0, item.message))


def _missing_exception_file_findings(
    root: Path, selected_files: set[str], policy: SuppressionReasonPolicy
) -> list[Finding]:
    """Report approved source/config sites whose file was deleted or moved."""
    findings: list[Finding] = []
    for exception in policy.exceptions:
        extension = Path(exception.path).suffix
        if (
            exception.path in selected_files
            or extension not in {*policy.extensions, ".toml"}
            or extension != ".toml"
            and any(matches_path(exception.path, pattern) for pattern in policy.exclude)
        ):
            continue
        try:
            source_path = (root / exception.path).resolve(strict=True)
            source_path.relative_to(root)
        except (OSError, ValueError):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=exception.path,
                    line=exception.line,
                    severity=policy.severity,
                    message=(
                        f"Approved Ruff exception for {exception.rule_code} "
                        "points to a missing or out-of-root file; the exception "
                        "site is stale after a move or deletion."
                    ),
                )
            )
            continue
        if not source_path.is_file():
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=exception.path,
                    line=exception.line,
                    severity=policy.severity,
                    message=(
                        f"Approved Ruff exception for {exception.rule_code} "
                        "does not point to a regular file; the exception site "
                        "is stale."
                    ),
                )
            )
    return findings


_RUFF_PER_FILE_TABLES = frozenset(
    {
        "tool.ruff.lint.per-file-ignores",
        "tool.ruff.lint.extend-per-file-ignores",
        "tool.ruff.per-file-ignores",
        "tool.ruff.extend-per-file-ignores",
        "lint.per-file-ignores",
        "lint.extend-per-file-ignores",
        "per-file-ignores",
        "extend-per-file-ignores",
    }
)
_RUFF_NORMAL_PER_FILE_TABLES = frozenset(
    table for table in _RUFF_PER_FILE_TABLES if "extend-per-file-ignores" not in table
)


def _split_toml_comment(value: str) -> tuple[str, str]:
    """Split a TOML assignment at its first unquoted comment marker."""
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quote == '"':
            escaped = True
        elif quote is not None:
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == "#":
            return value[:index].rstrip(), value[index + 1 :].strip()
    return value.rstrip(), ""


def _toml_string_list(value: object) -> list[str] | None:
    """Return a parsed TOML array only when each item is a string."""
    match value:
        case list():
            values = cast(list[object], value)
        case _:
            return None
    result: list[str] = []
    for item in values:
        match item:
            case str() as text:
                result.append(text)
            case _:
                return None
    return result


def _toml_per_file_map(value: object) -> dict[str, list[str]] | None:
    """Return only a string-pattern to string-code mapping."""
    match value:
        case dict():
            entries = cast(dict[object, object], value)
        case _:
            return None
    result: dict[str, list[str]] = {}
    for pattern, raw_codes in entries.items():
        match pattern:
            case str() as text:
                codes = _toml_string_list(raw_codes)
            case _:
                return None
        if codes is None:
            return None
        result[text] = codes
    return result


def _normalize_multiline_inline_map(
    lines: MutableSequence[str], start: int
) -> tuple[str, int, list[str]] | None:
    """Normalize Ruff's multiline inline map using its string/list subset."""
    entries: dict[str, list[str]] = {}
    comments: list[str] = []
    index = start + 1
    while index < len(lines):
        value_text, comment = _split_toml_comment(lines[index])
        if comment:
            comments.append(comment)
        stripped = value_text.strip()
        if stripped in {"", ","}:
            index += 1
            continue
        if stripped == "}":
            rendered = (
                "{ "
                + ", ".join(
                    f"{json.dumps(pattern)} = {json.dumps(codes)}"
                    for pattern, codes in entries.items()
                )
                + " }"
            )
            return rendered, index, comments
        assignment = re.match(r"(?P<key>[^=]+?)\s*=\s*(?P<value>.*)$", stripped)
        if assignment is None:
            return None
        try:
            pattern = tomllib.loads(f"key = {assignment.group('key')}")["key"]
        except tomllib.TOMLDecodeError:
            return None
        match pattern:
            case str() as pattern_text:
                pass
            case _:
                return None
        fragments: list[str] = []
        code_end = index
        while True:
            code_text = assignment.group("value") if not fragments else lines[code_end]
            code_value, code_comment = _split_toml_comment(code_text)
            if code_comment:
                comments.append(code_comment)
            fragments.append(code_value.strip())
            expression = "\n".join(fragments).rstrip()
            if expression.endswith(","):
                expression = expression[:-1].rstrip()
            try:
                parsed = tomllib.loads(f"codes = {expression}")["codes"]
            except tomllib.TOMLDecodeError:
                code_end += 1
                if code_end >= len(lines):
                    return None
                continue
            codes = _toml_string_list(parsed)
            if codes is None:
                return None
            entries[pattern_text] = codes
            index = code_end + 1
            break
    return None


def _normalize_multiline_per_file_values(source: str) -> str:
    """Collapse valid multiline per-file-ignore arrays without losing line numbers."""
    lines = source.splitlines()
    table = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        section = re.fullmatch(r"\s*\[([^]]+)\]\s*", line)
        if section:
            table = section.group(1).strip()
            index += 1
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        assignment = re.match(r"(?P<key>[^=]+?)\s*=\s*(?P<value>.*)$", line)
        if assignment is None:
            index += 1
            continue
        key = assignment.group("key").strip()
        inline_map = table in {"", "tool.ruff", "tool.ruff.lint", "lint"} and key in {
            "per-file-ignores",
            "extend-per-file-ignores",
        }
        table_entry = table in _RUFF_PER_FILE_TABLES
        if not inline_map and not table_entry:
            index += 1
            continue
        value_text, comment = _split_toml_comment(assignment.group("value"))
        if inline_map and value_text.strip() == "{":
            normalized = _normalize_multiline_inline_map(lines, index)
            if normalized is not None:
                normalized_value, end_index, map_comments = normalized
                if comment:
                    map_comments.insert(0, comment)
                if map_comments:
                    normalized_value += " # " + " ".join(map_comments)
                lines[index] = f"{assignment.group('key')} = {normalized_value}"
                for skipped in range(index + 1, end_index + 1):
                    lines[skipped] = ""
                index = end_index + 1
                continue
        fragments = [value_text]
        comments = [comment] if comment else []
        end_index = index
        parsed: object | None = None
        while True:
            try:
                expression = "\n".join(fragments)
                parsed = tomllib.loads(f"value = {expression}")["value"]
            except tomllib.TOMLDecodeError:
                parsed = None
            opening_inline_map = (
                inline_map and end_index == index and value_text.strip() == "{"
            )
            if parsed is not None and not opening_inline_map:
                break
            end_index += 1
            if end_index >= len(lines):
                break
            next_value, next_comment = _split_toml_comment(lines[end_index])
            fragments.append(next_value)
            if next_comment:
                comments.append(next_comment)
        normalized_value: str | None = None
        if table_entry:
            parsed_values = _toml_string_list(parsed)
            if parsed_values is not None:
                normalized_value = json.dumps(parsed_values)
        elif inline_map:
            parsed_entries = _toml_per_file_map(parsed)
            if parsed_entries is not None:
                normalized_value = (
                    "{ "
                    + ", ".join(
                        f"{json.dumps(pattern)} = {json.dumps(codes)}"
                        for pattern, codes in parsed_entries.items()
                    )
                    + " }"
                )
        if end_index > index and normalized_value is not None:
            normalized = normalized_value
            if comments:
                normalized += " # " + " ".join(comments)
            lines[index] = f"{assignment.group('key')} = {normalized}"
            for skipped in range(index + 1, end_index + 1):
                lines[skipped] = ""
            index = end_index + 1
        else:
            index += 1
    return "\n".join(lines)


def _ruff_config_suppression_findings(
    root: Path,
    selected_files: Collection[str],
    policy: SuppressionReasonPolicy,
    *,
    config_path: Path | None = None,
    seen: frozenset[Path] = frozenset(),
    depth: int = 0,
    skip_inherited_normal_per_file: bool = False,
) -> list[Finding]:
    """Audit simple Ruff per-file-ignore table entries without executing Ruff."""
    findings: list[Finding] = []
    if config_path is None:
        config_path = next(
            (
                root / name
                for name in ("ruff.toml", ".ruff.toml", "pyproject.toml")
                if (root / name).is_file()
            ),
            None,
        )
    if config_path is None:
        return findings
    try:
        config_path = config_path.resolve(strict=True)
        config_name = config_path.relative_to(root).as_posix()
    except (OSError, ValueError):
        return [
            Finding(
                rule_id=_RULE_ID,
                path="ruff configuration",
                severity=policy.severity,
                message=(
                    "Ruff inherited configuration was not evaluated because its "
                    "path is missing or outside the selected repository root."
                ),
            )
        ]
    if depth >= 8 or config_path in seen:
        return [
            Finding(
                rule_id=_RULE_ID,
                path=config_name,
                severity=policy.severity,
                message=(
                    "Ruff inherited configuration was not evaluated because the "
                    "extension chain is cyclic or exceeds the depth limit."
                ),
            )
        ]
    seen = seen | {config_path}
    source = ""
    config_error: str | None = None
    unsupported_multiline_map = False
    try:
        source = read_utf8_text(config_path)
        source = _normalize_multiline_per_file_values(source)
        tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        unsupported_multiline_map = bool(
            re.search(r"(?m)^\s*(?:extend-)?per-file-ignores\s*=\s*\{\s*$", source)
        )
        config_error = "TOMLDecodeError"
    except (OSError, UnicodeError) as error:
        config_error = type(error).__name__
    if config_error is not None:
        detail = (
            "Ruff per-file-ignore settings use a multiline inline table that the "
            "Python TOML parser cannot read; suppression reasons were not evaluated."
            if unsupported_multiline_map
            else "Ruff per-file-ignore settings were not evaluated because the TOML "
            f"configuration could not be read: {config_error}."
        )
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=config_name,
                severity=policy.severity,
                message=detail,
            )
        )
        return findings
    table = ""
    used_exceptions: set[tuple[str, int]] = set()
    inherited_config: str | None = None
    local_normal_per_file = False
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        section = re.fullmatch(r"\[([^]]+)\]", stripped)
        if section:
            table = section.group(1).strip()
            if table in _RUFF_NORMAL_PER_FILE_TABLES:
                local_normal_per_file = True
            continue
        if table in {"", "tool.ruff"} and re.match(r"\s*extend\s*=", line):
            extension_value, _comment = _split_toml_comment(line.split("=", 1)[1])
            try:
                parsed_extension = tomllib.loads(f"extend = {extension_value}")
                raw_extension = parsed_extension["extend"]
            except (tomllib.TOMLDecodeError, KeyError):
                raw_extension = None
            match raw_extension:
                case str() as extension:
                    inherited_config = extension
                case _:
                    findings.append(
                        Finding(
                            rule_id=_RULE_ID,
                            path=config_name,
                            line=line_number,
                            severity=policy.severity,
                            message=(
                                "Ruff inherited configuration uses an unsupported "
                                "extension value; inherited per-file ignores were not evaluated."
                            ),
                        )
                    )
            continue
        if table in {"", "tool.ruff", "tool.ruff.lint", "lint"} and re.match(
            r"\s*(?:extend-)?per-file-ignores\s*=", line
        ):
            inline_value, inline_comment = _split_toml_comment(line.split("=", 1)[1])
            try:
                parsed_entries = tomllib.loads(f"value = {inline_value}")["value"]
            except tomllib.TOMLDecodeError:
                parsed_entries = None
            entries = _toml_per_file_map(parsed_entries)
            if entries is not None:
                normal_inline = not re.match(r"\s*extend-per-file-ignores\s*=", line)
                local_normal_per_file = local_normal_per_file or normal_inline
                if skip_inherited_normal_per_file and not normal_inline:
                    continue
                for pattern, code_values in entries.items():
                    selected_codes = sorted(
                        set(policy.rule_codes).intersection(code_values)
                    )
                    applicable = [
                        path for path in selected_files if matches_path(path, pattern)
                    ]
                    _, _, reason = inline_comment.partition(policy.reason_delimiter)
                    if not selected_codes or not applicable or reason.strip():
                        continue
                    exception_keys = {
                        (exception.rule_code, exception.line)
                        for exception in policy.exceptions
                        if exception.path == config_name
                    }
                    used_exceptions.update(
                        (code, line_number)
                        for code in selected_codes
                        if (code, line_number) in exception_keys
                    )
                    unaudited = [
                        code
                        for code in selected_codes
                        if (code, line_number) not in exception_keys
                    ]
                    if unaudited:
                        findings.append(
                            Finding(
                                rule_id=_RULE_ID,
                                path=config_name,
                                line=line_number,
                                severity=policy.severity,
                                message=(
                                    f"Selected Ruff per-file-ignore code(s) {', '.join(unaudited)} "
                                    f"apply to {', '.join(sorted(applicable)[:3])} via {pattern!r} "
                                    f"but have no rationale after {policy.reason_delimiter!r}; "
                                    "add a TOML comment with the configured reason delimiter. "
                                    "Ruff retains ownership of suppression validity and usage."
                                ),
                            )
                        )
            else:
                findings.append(
                    Finding(
                        rule_id=_RULE_ID,
                        path=config_name,
                        line=line_number,
                        severity=policy.severity,
                        message=(
                            "Ruff per-file-ignore settings use an unsupported inline form; "
                            "suppression reasons were not evaluated."
                        ),
                    )
                )
            continue
        if skip_inherited_normal_per_file and table in _RUFF_NORMAL_PER_FILE_TABLES:
            continue
        if (
            table not in _RUFF_PER_FILE_TABLES
            or not stripped
            or stripped.startswith("#")
        ):
            continue
        assignment = re.match(r"(?P<key>[^=]+?)\s*=\s*(?P<value>.+)$", line)
        if assignment is None:
            continue
        value_text, comment = _split_toml_comment(assignment.group("value"))
        try:
            parsed_key = tomllib.loads(f"key = {assignment.group('key').strip()}")[
                "key"
            ]
            parsed_codes = tomllib.loads(f"codes = {value_text}")["codes"]
        except (tomllib.TOMLDecodeError, KeyError):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=config_name,
                    line=line_number,
                    severity=policy.severity,
                    message=(
                        "A Ruff per-file-ignore entry uses unsupported or "
                        "unparseable syntax; its suppression reasons were not evaluated."
                    ),
                )
            )
            continue
        match parsed_key:
            case str() as pattern:
                pass
            case _:
                continue
        match parsed_codes:
            case list():
                # opaque-boundary: TOML arrays are heterogeneous until policy filtering.
                codes = cast(list[object], parsed_codes)
            case _:
                continue
        selected_candidates: list[str] = []
        for value in codes:
            match value:
                case str() as code:
                    selected_candidates.append(code)
                case _:
                    continue
        selected_codes = sorted(
            set(policy.rule_codes).intersection(selected_candidates)
        )
        applicable = [path for path in selected_files if matches_path(path, pattern)]
        if not selected_codes or not applicable:
            continue
        _, _, reason = comment.partition(policy.reason_delimiter)
        if reason.strip():
            continue
        exception_keys = {
            (exception.rule_code, exception.line)
            for exception in policy.exceptions
            if exception.path == config_name
        }
        used_exceptions.update(
            (code, line_number)
            for code in selected_codes
            if (code, line_number) in exception_keys
        )
        unaudited = [
            code for code in selected_codes if (code, line_number) not in exception_keys
        ]
        if not unaudited:
            continue
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=config_name,
                line=line_number,
                severity=policy.severity,
                message=(
                    f"Selected Ruff per-file-ignore code(s) {', '.join(unaudited)} "
                    f"apply to {', '.join(sorted(applicable)[:3])} via {pattern!r} "
                    f"but have no rationale after {policy.reason_delimiter!r}; "
                    "add a TOML comment with the configured reason delimiter. "
                    "Ruff retains ownership of whether the suppression is valid or used."
                ),
            )
        )
    for exception in policy.exceptions:
        if exception.path != config_name:
            continue
        key = (exception.rule_code, exception.line)
        if key in used_exceptions:
            continue
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=config_name,
                line=exception.line,
                severity=policy.severity,
                message=(
                    f"Approved Ruff config exception for {exception.rule_code} "
                    "does not match a selected per-file-ignore entry at this line; "
                    "review or remove the stale exception."
                ),
            )
        )
    if inherited_config is not None:
        parent_path = config_path.parent / inherited_config
        try:
            resolved_parent = parent_path.resolve(strict=True)
            resolved_parent.relative_to(root)
        except (OSError, ValueError):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=config_name,
                    severity=policy.severity,
                    message=(
                        "Ruff inherited configuration was not evaluated because "
                        "its target is missing or outside the repository root."
                    ),
                )
            )
        else:
            findings.extend(
                _ruff_config_suppression_findings(
                    root,
                    selected_files,
                    policy,
                    config_path=resolved_parent,
                    seen=seen,
                    depth=depth + 1,
                    skip_inherited_normal_per_file=(
                        skip_inherited_normal_per_file or local_normal_per_file
                    ),
                )
            )
    return findings
