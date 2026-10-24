"""Route source-file path checks to the owning language implementation."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import PathDiscoveryPolicy
from alphus.findings import Finding, SourceFinding
from alphus.gates.languages.javascript.path_discovery import (
    js_inspection_findings,
    js_path_findings,
)
from alphus.gates.languages.python.path_discovery import (
    python_inspection_findings,
    python_path_findings,
)
from alphus.support.inventory import matches_path


def check_path_discovery(
    root: Path, paths: Iterable[Path], policy: PathDiscoveryPolicy
) -> list[Finding]:
    """Report configured implicit path roots and string-based path inspection."""
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
        inspect_strings = not any(
            matches_path(name, pattern) for pattern in policy.inspection_exclude
        )
        language_findings: list[SourceFinding]
        if suffix == ".py":
            language_findings = python_path_findings(source)
            if inspect_strings:
                language_findings += python_inspection_findings(source)
        else:
            language_findings = js_path_findings(source)
            if inspect_strings:
                language_findings += js_inspection_findings(source)
        findings.extend(
            Finding(
                rule_id="paths.implicit-root",
                path=name,
                line=source_finding.line,
                message=source_finding.message,
            )
            for source_finding in language_findings
        )
    return findings
