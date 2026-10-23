"""Synchronize a Mermaid dependency diagram with configured package edges."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from re import Pattern
from types import MappingProxyType

from alphus.config import ArchitectureGraphPolicy, PackageBoundaryPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import rule_tag

_EDGE_PATTERNS: Mapping[str, Pattern[str]] = MappingProxyType(
    {
        "flowchart": re.compile(
            r"^\s*(?P<origin>\w+)\s*(?:-->\s*(?:\|[^|]*\|\s*)?"
            r"|--\s+[^\n]+?\s+-->\s*)(?P<target>\w+)\s*;?\s*$",
            re.MULTILINE,
        ),
        "architecture": re.compile(
            r"^\s*(?P<origin>\w+)(?:\{group\})?:[TBLR]\s+-->\s+"
            r"[TBLR]:(?P<target>\w+)(?:\{group\})?\s*$",
            re.MULTILINE,
        ),
    }
)


_MERMAID_OPEN = re.compile(
    r"^(?:(?P<fence>`{3,})\s*mermaid|:::\s*mermaid)$", re.IGNORECASE
)


def _mermaid_diagram(source: str) -> str | None:
    """Extract GitHub fences or Azure DevOps Mermaid containers."""
    lines = source.splitlines()
    for index, line in enumerate(lines):
        opener = _MERMAID_OPEN.fullmatch(line.strip())
        if opener is None:
            continue
        closing = opener.group("fence") or ":::"
        for end in range(index + 1, len(lines)):
            if lines[end].strip() == closing:
                return "\n".join(lines[index + 1 : end])
    return None


def check_architecture_graph(
    root: Path,
    graph: ArchitectureGraphPolicy,
    package_policy: PackageBoundaryPolicy,
) -> list[Finding]:
    """Require the configured Mermaid graph to match package metadata policy."""
    checkout = root.resolve(strict=True)
    path = checkout / graph.path
    try:
        path.resolve(strict=True).relative_to(checkout)
    except (OSError, ValueError):
        return [
            Finding(
                rule_id=rule_tag("repository", "none", "architecture", "graph-missing"),
                path=graph.path,
                message="Mermaid graph is missing",
            )
        ]
    if not path.is_file():
        return [
            Finding(
                rule_id=rule_tag("repository", "none", "architecture", "graph-missing"),
                path=graph.path,
                message="Mermaid graph is missing",
            )
        ]
    source = path.read_text(encoding="utf-8")
    diagram = _mermaid_diagram(source)
    if diagram is None:
        return [
            Finding(
                rule_id=rule_tag("repository", "none", "architecture", "graph-missing"),
                path=graph.path,
                message="Mermaid graph is missing",
            )
        ]
    header = (
        r"architecture-beta\b"
        if graph.syntax == "architecture"
        else r"(?:flowchart|graph)\b"
    )
    if re.match(header, diagram.lstrip()) is None:
        return [
            Finding(
                rule_id=rule_tag(
                    "repository", "none", "architecture", "graph-syntax-mismatch"
                ),
                path=graph.path,
                message=f"Mermaid graph must use {graph.syntax} syntax",
            )
        ]
    observed = {
        (match.group("origin"), match.group("target"))
        for match in _EDGE_PATTERNS[graph.syntax].finditer(diagram)
    }
    node_names = dict(graph.node_names)
    allowed = dict(package_policy.allowed_dependencies)
    missing_nodes = set(allowed) - node_names.keys()
    findings = [
        Finding(
            rule_id=rule_tag("repository", "none", "architecture", "node-missing"),
            path=graph.path,
            message=f"no Mermaid node for {name}",
        )
        for name in sorted(missing_nodes)
    ]
    expected = {
        (node_names[name], node_names[dependency])
        for name, dependencies in allowed.items()
        for dependency in dependencies
        if name in node_names and dependency in node_names
    }
    expected.update(graph.extra_edges)
    findings.extend(
        Finding(
            rule_id=rule_tag("repository", "none", "architecture", "edge-missing"),
            path=graph.path,
            message=f"Mermaid graph lacks {origin} -> {target}",
        )
        for origin, target in sorted(expected - observed)
    )
    findings.extend(
        Finding(
            rule_id=rule_tag("repository", "none", "architecture", "edge-forbidden"),
            path=graph.path,
            message=f"Mermaid graph has forbidden {origin} -> {target}",
        )
        for origin, target in sorted(observed - expected)
    )
    return findings
