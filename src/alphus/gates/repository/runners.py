"""Register repository architecture and packaging rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.contracts.findings import Finding
from alphus.execution.results import RuleOutput
from alphus.gates.repository.architecture_graph import check_architecture_graph
from alphus.gates.repository.callable_registry import check_callable_registry
from alphus.gates.repository.dependency_locks import check_dependency_locks
from alphus.gates.repository.git_hygiene import check_history, check_ignores
from alphus.gates.repository.module_roles import check_module_roles
from alphus.gates.repository.package_boundaries import check_package_boundaries
from alphus.gates.repository.repository_layout import check_repository_layout
from alphus.gates.repository.version_sync import check_version_sync
from alphus.policy.base import require_policy
from alphus.support.inventory import tracked_files

RepositoryRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


def _package_boundary_findings(
    root: Path, _files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    policy = require_policy(config.checks.package_boundaries, "package_boundaries")
    findings = check_package_boundaries(root, policy)
    graph_policy = config.checks.architecture_graph
    if graph_policy is not None and graph_policy.graph is not None:
        findings.extend(check_architecture_graph(root, graph_policy.graph, policy))
    version_policy = config.checks.version_sync
    if version_policy is not None:
        findings.extend(check_version_sync(root, version_policy))
    registry_policy = config.checks.callable_registry
    if registry_policy is not None:
        findings.extend(check_callable_registry(root, registry_policy))
    return findings


REPOSITORY_RULE_RUNNERS: Mapping[QualityRuleName, RepositoryRunner] = MappingProxyType(
    {
        "module-roles": lambda root, _files, config: check_module_roles(
            root, require_policy(config.checks.module_roles, "module_roles")
        ),
        "package-boundaries": _package_boundary_findings,
        "dependency-locks": lambda root, _files, config: check_dependency_locks(
            root,
            require_policy(config.checks.dependency_locks, "dependency_locks"),
        ),
        "repository-layout": lambda root, _files, config: check_repository_layout(
            root,
            require_policy(config.checks.repository_layout, "repository_layout"),
            tracked_files(root),
        ),
        "git-ignores": lambda root, _files, config: check_ignores(
            root, require_policy(config.checks.git, "git").languages
        ),
        "git-history": lambda root, _files, config: check_history(
            root, require_policy(config.checks.git, "git").max_blob_mib
        ),
    }
)
