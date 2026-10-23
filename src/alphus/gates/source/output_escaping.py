"""Portable checks for hand-written text escaping."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from alphus.config import SourceScanPolicy
from alphus.contracts.findings import Finding
from alphus.support.inventory import matches_path

_OUTPUT_PUNCTUATION = frozenset("\\|*_<>&\"'{}[]#%$~^/")
_HTML_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);")
_JS_REPLACEMENT = re.compile(r"\.replace(?:All)?\s*\(")
_JS_BACKSLASH_ESCAPE = re.compile(r"\\+[|*_<>{}\[\]#%\"']")


def _literal_text(node: ast.expr) -> str | None:
    """Read a literal string without evaluating source code."""
    match node:
        case ast.Constant(value=str() as value):
            return value
        case _:
            return None


def _is_manual_escape(source: str, replacement: str) -> bool:
    """Recognize format punctuation mapped to an escape sequence or entity."""
    if not source or not set(source) <= _OUTPUT_PUNCTUATION:
        return source in {"\n", "\r", "\t"} and replacement in {"\\n", "\\r", "\\t"}
    return (
        bool(replacement)
        and replacement[0] == "\\"
        or (_HTML_ENTITY.fullmatch(replacement) is not None)
    )


def python_escape_findings(source: str) -> list[tuple[int, str]]:
    """Find Python literal replacement calls and character escape tables."""
    findings: set[tuple[int, str]] = set()
    for node in ast.walk(ast.parse(source)):
        match node:
            case ast.Call(func=ast.Attribute(attr=attribute), args=arguments) if (
                attribute in {"replace", "replaceAll"} and len(arguments) >= 2
            ):
                original = _literal_text(arguments[0])
                replacement = _literal_text(arguments[1])
                if (
                    original is not None
                    and replacement is not None
                    and _is_manual_escape(original, replacement)
                ):
                    findings.add((node.lineno, "manual output escape replacement"))
            case ast.Dict(keys=keys, values=values):
                for key, value in zip(keys, values):
                    if key is None:
                        continue
                    original = _literal_text(key)
                    replacement = _literal_text(value)
                    if (
                        original is not None
                        and replacement is not None
                        and _is_manual_escape(original, replacement)
                    ):
                        findings.add((node.lineno, "manual output escape table"))
                        break
            case _:
                pass
    return sorted(findings)


def js_escape_findings(source: str) -> list[tuple[int, str]]:
    """Find JavaScript replace calls with literal output escape sequences."""
    findings: set[tuple[int, str]] = set()
    for match in _JS_REPLACEMENT.finditer(source):
        arguments = source[match.end() : match.end() + 180].split(")", 1)[0]
        if "," not in arguments:
            continue
        replacement = arguments.split(",", 1)[1]
        if _HTML_ENTITY.search(replacement) or _JS_BACKSLASH_ESCAPE.search(replacement):
            line = source.count("\n", 0, match.start()) + 1
            findings.add((line, "manual output escape replacement"))
    return sorted(findings)


def check_output_escaping(
    root: Path, paths: Iterable[Path], policy: SourceScanPolicy
) -> list[Finding]:
    """Report configured source files that hand-write output escaping."""
    findings: list[Finding] = []
    checkout = root.resolve(strict=True)
    for relative in sorted(paths):
        name = relative.as_posix()
        if any(matches_path(name, pattern) for pattern in policy.exclude):
            continue
        suffix = relative.suffix.lower()
        if suffix not in policy.extensions:
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8-sig")
        source_findings = (
            python_escape_findings(source)
            if suffix == ".py"
            else js_escape_findings(source)
        )
        findings.extend(
            Finding(
                rule_id="output.manual-escaping",
                path=name,
                line=line,
                message=f"{message}; use a library or tested shared utility",
            )
            for line, message in source_findings
        )
    return findings
