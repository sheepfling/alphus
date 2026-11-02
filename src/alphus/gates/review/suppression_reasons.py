"""Audit selected inline Ruff suppressions for consumer-required reasons."""

from __future__ import annotations

import io
import re
import tokenize
import tomllib
from collections.abc import Collection, Iterable
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
    findings.extend(_ruff_config_suppression_findings(checkout, selected_files, policy))
    return sorted(findings, key=lambda item: (item.path, item.line or 0, item.message))


_RUFF_PER_FILE_TABLES = frozenset(
    {
        "tool.ruff.lint.per-file-ignores",
        "tool.ruff.per-file-ignores",
        "lint.per-file-ignores",
        "per-file-ignores",
    }
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


def _ruff_config_suppression_findings(
    root: Path, selected_files: Collection[str], policy: SuppressionReasonPolicy
) -> list[Finding]:
    """Audit simple Ruff per-file-ignore table entries without executing Ruff."""
    findings: list[Finding] = []
    config_name = next(
        (
            name
            for name in ("ruff.toml", ".ruff.toml", "pyproject.toml")
            if (root / name).is_file()
        ),
        None,
    )
    if config_name is None:
        return findings
    config_path = root / config_name
    try:
        source = read_utf8_text(config_path)
        tomllib.loads(source)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=config_name,
                severity=policy.severity,
                message=(
                    "Ruff per-file-ignore settings were not evaluated because "
                    f"the TOML configuration could not be read: {type(error).__name__}."
                ),
            )
        )
        return findings
    table = ""
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        section = re.fullmatch(r"\[([^]]+)\]", stripped)
        if section:
            table = section.group(1).strip()
            continue
        if table in {"", "tool.ruff", "tool.ruff.lint", "lint"} and re.match(
            r"\s*per-file-ignores\s*=", line
        ):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=config_name,
                    line=line_number,
                    severity=policy.severity,
                    message=(
                        "Ruff per-file-ignore settings use an inline or otherwise "
                        "unsupported form; suppression reasons were not evaluated."
                    ),
                )
            )
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
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=config_name,
                line=line_number,
                severity=policy.severity,
                message=(
                    f"Selected Ruff per-file-ignore code(s) {', '.join(selected_codes)} "
                    f"apply to {', '.join(sorted(applicable)[:3])} via {pattern!r} "
                    f"but have no rationale after {policy.reason_delimiter!r}; "
                    "add a TOML comment with the configured reason delimiter. "
                    "Ruff retains ownership of whether the suppression is valid or used."
                ),
            )
        )
    return findings
