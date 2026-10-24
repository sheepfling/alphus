"""Route output-escaping checks to the owning source language."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import SourceScanPolicy
from alphus.findings import Finding
from alphus.gates.languages.javascript.output_escaping import (
    escape_findings as js_escape_findings,
)
from alphus.gates.languages.python.output_escaping import (
    escape_findings as python_escape_findings,
)
from alphus.support.inventory import matches_path


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
