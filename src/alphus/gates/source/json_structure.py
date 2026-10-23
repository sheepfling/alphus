"""Portable checks for unvalidated JSON decoding."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from re import Pattern
from types import MappingProxyType

from alphus.config import SourceScanPolicy
from alphus.contracts.findings import Finding, SourceFinding
from alphus.contracts.rule_tags import rule_tag
from alphus.support.inventory import matches_path

DECODER_MODULES: frozenset[str] = frozenset({"json", "orjson", "ujson", "rapidjson"})
JS_DECODERS: Mapping[str, Pattern[str]] = MappingProxyType(
    {
        "JSON.parse returns an unvalidated value": re.compile(r"\bJSON\.parse\s*\("),
        "response.json() returns an unvalidated value": re.compile(
            r"(?:\b(?:response|res|[A-Za-z_$][\w$]*Response)|\))\.json\s*\("
        ),
    }
)


def python_json_findings(source: str) -> list[SourceFinding]:
    """Locate standard and alternate Python JSON decoder calls."""
    tree = ast.parse(source)
    modules: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                modules.update(
                    alias.asname or alias.name
                    for alias in names
                    if alias.name in DECODER_MODULES
                )
            case ast.ImportFrom(module=module, names=names) if (
                module in DECODER_MODULES
            ):
                for alias in names:
                    if alias.name in {"load", "loads"}:
                        functions.add(alias.asname or alias.name)
            case _:
                pass
    findings: set[SourceFinding] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Call(func=ast.Name(id=name)) if name in functions:
                findings.add(
                    SourceFinding(
                        node.lineno, "raw JSON decode; validate into a named model"
                    )
                )
            case ast.Call(func=ast.Attribute(attr=attr, value=ast.Name(id=name))) if (
                attr in {"load", "loads"} and name in modules
            ):
                findings.add(
                    SourceFinding(
                        node.lineno, "raw JSON decode; validate into a named model"
                    )
                )
            case _:
                pass
    return sorted(findings)


def js_json_findings(source: str) -> list[SourceFinding]:
    """Locate common JavaScript JSON decoding calls."""
    findings: set[SourceFinding] = set()
    for reason, pattern in JS_DECODERS.items():
        for match in pattern.finditer(source):
            findings.add(
                SourceFinding(source.count("\n", 0, match.start()) + 1, reason)
            )
    return sorted(findings)


def check_json_structure(
    root: Path, paths: Iterable[Path], policy: SourceScanPolicy
) -> list[Finding]:
    """Report raw decodes in the configured source and path scope."""
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
            python_json_findings(source)
            if suffix == ".py"
            else js_json_findings(source)
        )
        scope = "python" if suffix == ".py" else "javascript"
        findings.extend(
            Finding(
                rule_id=rule_tag(
                    scope, "none", "validation", "unvalidated-json-decode"
                ),
                path=name,
                line=source_finding.line,
                message=source_finding.message,
            )
            for source_finding in source_findings
        )
    return findings
