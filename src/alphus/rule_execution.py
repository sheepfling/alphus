"""Dispatch built-in rules without mixing checker selection into CLI rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from alphus.architecture_graph import check_architecture_graph
from alphus.callable_registry import check_callable_registry
from alphus.config import QualityGateConfig, QualityRuleName
from alphus.config_base import require_policy
from alphus.dependency_locks import check_dependency_locks
from alphus.findings import Finding
from alphus.gates.review.runners import REVIEW_RULE_RUNNERS
from alphus.gates.source.runners import SOURCE_RULE_RUNNERS
from alphus.inventory import tracked_files
from alphus.module_roles import check_module_roles
from alphus.package_boundaries import check_package_boundaries
from alphus.repository_layout import check_repository_layout
from alphus.rule_results import RuleOutput
from alphus.rules import check_file_size, check_line_length
from alphus.shared_utilities import check_shared_utilities
from alphus.version_sync import check_version_sync

RuleRunner = Callable[[Path, Sequence[Path], QualityGateConfig], RuleOutput]


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


RULE_RUNNERS: Mapping[QualityRuleName, RuleRunner] = MappingProxyType(
    {
        "file-size": lambda root, files, config: check_file_size(root, files, config),
        "line-length": lambda root, files, config: check_line_length(
            root, files, config
        ),
        "shared-utilities": lambda root, files, config: check_shared_utilities(
            root,
            files,
            require_policy(config.checks.shared_utilities, "shared_utilities"),
        ),
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
        **REVIEW_RULE_RUNNERS,
        **SOURCE_RULE_RUNNERS,
    }
)


def run_builtin_rule(
    rule: QualityRuleName,
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> RuleOutput:
    """Run one selected checker after validating its required policy."""
    config.checks.require_rule(rule)
    return RULE_RUNNERS[rule](root, files, config)
