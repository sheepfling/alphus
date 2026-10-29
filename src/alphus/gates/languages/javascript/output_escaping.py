"""JavaScript checks for hand-written output escaping."""

from __future__ import annotations

import re

_HTML_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);")
_REPLACEMENT = re.compile(r"\.replace(?:All)?\s*\(")
_BACKSLASH_ESCAPE = re.compile(r"\\+[|*_<>{}\[\]#%\"']")


def escape_findings(source: str) -> list[tuple[int, str]]:
    """Find JavaScript replace calls with literal output escape sequences."""
    findings: set[tuple[int, str]] = set()
    for match in _REPLACEMENT.finditer(source):
        arguments = source[match.end() : match.end() + 180].split(")", 1)[0]
        if "," not in arguments:
            continue
        replacement = arguments.split(",", 1)[1]
        if _HTML_ENTITY.search(replacement) or _BACKSLASH_ESCAPE.search(replacement):
            line = source.count("\n", 0, match.start()) + 1
            findings.add((line, "manual output escape replacement"))
    return sorted(findings)
