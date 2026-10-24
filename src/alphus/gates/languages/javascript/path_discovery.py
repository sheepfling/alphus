"""JavaScript path and URL discovery checks."""

from __future__ import annotations

import re
from collections.abc import Mapping
from re import Pattern
from types import MappingProxyType

from alphus.findings import SourceFinding

JS_PATTERNS: Mapping[str, Pattern[str]] = MappingProxyType(
    {
        "module URL used as an implicit path root": re.compile(
            r"\b(?:path\.)?dirname\s*\(\s*fileURLToPath\s*\(\s*import\.meta\.url\s*\)\s*\)"
        ),
        "module directory used as an implicit path root": re.compile(
            r"\bimport\.meta\.(?:dirname|filename)\b"
        ),
        "current working directory used as an implicit path root": re.compile(
            r"\b(?:process\.cwd|path\.resolve)\s*\(\s*\)"
        ),
        "Git checkout discovery used as an implicit path root": re.compile(
            r"(?:--show-toplevel|show-toplevel)"
        ),
    }
)
JS_INSPECTION_PATTERNS: Mapping[str, Pattern[str]] = MappingProxyType(
    {
        "slash prefix test; parse the declared path flavor": re.compile(
            r"\.startsWith\s*\(\s*['\"](?:/|\\\\)"
        ),
        "URL prefix test; parse with URL": re.compile(
            r"\.startsWith\s*\(\s*['\"]https?://"
        ),
        "URL scheme substring test; parse with URL": re.compile(
            r"\.includes\s*\(\s*['\"]://['\"]\s*\)"
        ),
        "separator rewrite; parse the declared path flavor": re.compile(
            r"\.replace(?:All)?\s*\(\s*['\"]\\\\['\"]\s*,\s*['\"]/['\"]"
        ),
    }
)


def js_path_findings(source: str) -> list[SourceFinding]:
    """Locate ESM module-file, cwd, and Git root discovery in JS source."""
    findings: set[SourceFinding] = set()
    for label, pattern in JS_PATTERNS.items():
        for match in pattern.finditer(source):
            findings.add(SourceFinding(source.count("\n", 0, match.start()) + 1, label))
    return sorted(findings)


def js_inspection_findings(source: str) -> list[SourceFinding]:
    """Find obvious JavaScript path and URL string heuristics."""
    findings: set[SourceFinding] = set()
    for reason, pattern in JS_INSPECTION_PATTERNS.items():
        for match in pattern.finditer(source):
            findings.add(
                SourceFinding(source.count("\n", 0, match.start()) + 1, reason)
            )
    return sorted(findings)
