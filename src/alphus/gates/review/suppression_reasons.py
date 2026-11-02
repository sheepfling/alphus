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
_CODE = re.compile(r"\b[A-Z]+[0-9]{3,4}\b", re.IGNORECASE)


def suppression_reason_findings(
    source: str, policy: SuppressionReasonPolicy, *, path: str = "<source>"
) -> list[Finding]:
    """Find selected inline ``noqa`` codes without the configured reason marker."""
    findings: list[Finding] = []
    required_codes = set(policy.rule_codes)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        if not token.line[: token.start[1]].strip():
            # Ruff line-level noqa directives apply to the statement they
            # trail. File-level directives use a different native spelling.
            continue
        directive = _DIRECTIVE.fullmatch(token.string.strip())
        if directive is None:
            continue
        body = directive.group("body")
        code_list, separator, reason = body.partition(policy.reason_delimiter)
        selected = sorted(
            required_codes.intersection(
                code.upper() for code in _CODE.findall(code_list)
            )
        )
        if not selected or (separator and reason.strip()):
            continue
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=path,
                line=token.start[0],
                severity=policy.severity,
                message=(
                    f"Selected Ruff suppression {', '.join(selected)} has no rationale "
                    f"after {policy.reason_delimiter!r}. Add a concise reason to this "
                    "comment. This audit checks documentation only; Ruff still owns "
                    "whether the suppression is valid or used."
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
        findings.extend(
            suppression_reason_findings(
                read_python_source(checkout / relative), policy, path=name
            )
        )
    return sorted(findings, key=lambda item: (item.path, item.line or 0, item.message))
