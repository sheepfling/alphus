"""Audit selected inline Ruff suppressions for consumer-required reasons."""

from __future__ import annotations

import io
import re
import tokenize
from collections.abc import Iterable
from pathlib import Path

from alphus.config import SuppressionReasonPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

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
    for relative in sorted(set(paths)):
        name = relative.as_posix()
        if relative.suffix != ".py" or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
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
    return sorted(findings, key=lambda item: (item.path, item.line or 0, item.message))
