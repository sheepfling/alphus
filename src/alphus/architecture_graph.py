"""Synchronize a Mermaid dependency diagram with configured package edges."""

from __future__ import annotations

import re
from pathlib import Path

from alphus.config import ArchitectureGraphPolicy, PackageBoundaryPolicy
from alphus.findings import Finding


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
                rule_id="architecture.graph-missing",
                path=graph.path,
                message="Mermaid graph is missing",
            )
        ]
    if not path.is_file():
        return [
            Finding(
                rule_id="architecture.graph-missing",
                path=graph.path,
                message="Mermaid graph is missing",
            )
        ]
    source = path.read_text(encoding="utf-8")
    parts = source.split("```mermaid\n", 1)
    if len(parts) != 2 or "\n```" not in parts[1]:
        return [
            Finding(
                rule_id="architecture.graph-missing",
                path=graph.path,
                message="Mermaid graph is missing",
            )
        ]
    diagram = parts[1].split("\n```", 1)[0]
    observed = set(
        re.findall(
            r"^\s*(\w+)\s+-->\|[^|]+\|\s+(\w+)\s*$",
            diagram,
            re.MULTILINE,
        )
    )
    node_names = dict(graph.node_names)
    allowed = dict(package_policy.allowed_dependencies)
    missing_nodes = set(allowed) - node_names.keys()
    findings = [
        Finding(
            rule_id="architecture.node-missing",
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
            rule_id="architecture.edge-missing",
            path=graph.path,
            message=f"Mermaid graph lacks {origin} -> {target}",
        )
        for origin, target in sorted(expected - observed)
    )
    findings.extend(
        Finding(
            rule_id="architecture.edge-forbidden",
            path=graph.path,
            message=f"Mermaid graph has forbidden {origin} -> {target}",
        )
        for origin, target in sorted(observed - expected)
    )
    return findings
