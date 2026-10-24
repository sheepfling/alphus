"""Route JSON-decoding checks to the owning source language."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import SourceScanPolicy
from alphus.findings import Finding, SourceFinding
from alphus.gates.languages.javascript.json_decoding import (
    json_findings as js_json_findings,
)
from alphus.gates.languages.python.json_decoding import (
    json_findings as python_json_findings,
)
from alphus.support.inventory import matches_path


def check_json_structure(
    root: Path, paths: Iterable[Path], policy: SourceScanPolicy
) -> list[Finding]:
    """Report raw JSON decodes in the configured source and path scope."""
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
        source_findings: list[SourceFinding]
        if suffix == ".py":
            source_findings = python_json_findings(source)
        else:
            source_findings = js_json_findings(source)
        findings.extend(
            Finding(
                rule_id="data.json-structure",
                path=name,
                line=source_finding.line,
                message=source_finding.message,
            )
            for source_finding in source_findings
        )
    return findings
