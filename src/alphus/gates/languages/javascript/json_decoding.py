"""JavaScript checks for unvalidated JSON decoder results."""

from __future__ import annotations

import re
from collections.abc import Mapping
from re import Pattern
from types import MappingProxyType

from alphus.contracts.findings import SourceFinding

DECODERS: Mapping[str, Pattern[str]] = MappingProxyType(
    {
        "JSON.parse returns an unvalidated value": re.compile(r"\bJSON\.parse\s*\("),
        "response.json() returns an unvalidated value": re.compile(
            r"(?:\b(?:response|res|[A-Za-z_$][\w$]*Response)|\))\.json\s*\("
        ),
    }
)


def json_findings(source: str) -> list[SourceFinding]:
    """Locate common JavaScript JSON decoding calls."""
    findings: set[SourceFinding] = set()
    for reason, pattern in DECODERS.items():
        for match in pattern.finditer(source):
            findings.add(
                SourceFinding(source.count("\n", 0, match.start()) + 1, reason)
            )
    return sorted(findings)
