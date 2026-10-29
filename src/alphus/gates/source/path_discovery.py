"""Route path-discovery checks to the owning source language."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType

from alphus.config import PathDiscoveryPolicy
from alphus.contracts.findings import Finding, SourceFinding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.languages.javascript.path_discovery import (
    js_inspection_findings,
    js_path_findings,
)
from alphus.gates.languages.python.path_discovery import (
    python_inspection_findings,
    python_path_findings,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source, read_utf8_sig_text


_PATH_TAGS: Mapping[str, tuple[Category, str]] = MappingProxyType(
    {
        "module URL used as an implicit path root": (
            Category.PORTABILITY, "implicit-module-root"
        ),
        "module directory used as an implicit path root": (
            Category.PORTABILITY, "implicit-module-root"
        ),
        "current working directory used as an implicit path root": (
            Category.PORTABILITY, "implicit-working-directory"
        ),
        "Git checkout discovery used as an implicit path root": (
            Category.PORTABILITY, "implicit-git-root"
        ),
        "URL prefix test; parse with URL": (
            Category.CORRECTNESS, "url-string-inspection"
        ),
        "URL scheme substring test; parse with URL": (
            Category.CORRECTNESS, "url-string-inspection"
        ),
        "slash prefix test; parse the declared path flavor": (
            Category.PORTABILITY, "path-string-inspection"
        ),
        "separator rewrite; parse the declared path flavor": (
            Category.PORTABILITY, "path-string-inspection"
        ),
        "module __file__ used to infer a parent root": (
            Category.PORTABILITY, "implicit-module-root"
        ),
        "raw os.name comparison; use a shared platform probe": (
            Category.PORTABILITY, "raw-platform-detection"
        ),
        "sys.path mutated for local module discovery": (
            Category.ARCHITECTURE, "import-path-mutation"
        ),
        "sys.executable used to derive a path": (
            Category.PORTABILITY, "implicit-executable-root"
        ),
        "Path.cwd() used as an implicit path root": (
            Category.PORTABILITY, "implicit-working-directory"
        ),
        "os.getcwd() used as an implicit path root": (
            Category.PORTABILITY, "implicit-working-directory"
        ),
        "path string comparison; use as_posix() at the boundary": (
            Category.CORRECTNESS, "path-string-comparison"
        ),
        "URL prefix test; parse with urlsplit": (
            Category.CORRECTNESS, "url-string-inspection"
        ),
        "URL scheme substring test; parse with urlsplit": (
            Category.CORRECTNESS, "url-string-inspection"
        ),
    }
)


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
        source = (
            read_python_source(path) if suffix == ".py" else read_utf8_sig_text(path)
        )
        inspect_strings = not any(
            matches_path(name, pattern) for pattern in policy.inspection_exclude
        )
        source_findings: list[SourceFinding]
        if suffix == ".py":
            source_findings = python_path_findings(source)
            if inspect_strings:
                source_findings += python_inspection_findings(source)
            scope = Scope.PYTHON
        else:
            source_findings = js_path_findings(source)
            if inspect_strings:
                source_findings += js_inspection_findings(source)
            scope = Scope.JAVASCRIPT
        for source_finding in source_findings:
            category, complaint = _PATH_TAGS[source_finding.message]
            findings.append(
                Finding(
                    rule_id=rule_tag(scope, Framework.NONE, category, complaint),
                    path=name,
                    line=source_finding.line,
                    message=source_finding.message,
                )
            )
    return findings