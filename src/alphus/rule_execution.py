"""Dispatch built-in rules without mixing checker selection into CLI rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from alphus.architecture_graph import check_architecture_graph
from alphus.callable_registry import check_callable_registry
from alphus.cli_policy import policy_issues as cli_policy_issues
from alphus.config import QualityGateConfig, QualityRuleName
from alphus.config_base import require_policy
from alphus.dependency_locks import check_dependency_locks
from alphus.findings import Finding
from alphus.gates.review.runners import REVIEW_RULE_RUNNERS
from alphus.inventory import tracked_files
from alphus.json_structure import check_json_structure
from alphus.module_roles import check_module_roles
from alphus.output_escaping import check_output_escaping
from alphus.package_boundaries import check_package_boundaries
from alphus.path_discovery import check_path_discovery
from alphus.python_style import findings_for as python_style_findings
from alphus.repository_layout import check_repository_layout
from alphus.rule_results import RuleOutput
from alphus.rules import check_file_size, check_line_length
from alphus.runtime_types import policy_issues as runtime_type_issues
from alphus.script_policy import policy_issues as script_policy_issues
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
        "json-structure": lambda root, files, config: check_json_structure(
            root,
            files,
            require_policy(config.checks.json_structure, "json_structure"),
        ),
        "output-escaping": lambda root, files, config: check_output_escaping(
            root,
            files,
            require_policy(config.checks.output_escaping, "output_escaping"),
        ),
        "path-discovery": lambda root, files, config: check_path_discovery(
            root,
            files,
            require_policy(config.checks.path_discovery, "path_discovery"),
        ),
        "shared-utilities": lambda root, files, config: check_shared_utilities(
            root,
            files,
            require_policy(config.checks.shared_utilities, "shared_utilities"),
        ),
        "module-roles": lambda root, _files, config: check_module_roles(
            root, require_policy(config.checks.module_roles, "module_roles")
        ),
        "python-style": lambda root, files, config: python_style_findings(
            root,
            files,
            require_policy(config.checks.python_style, "python_style"),
        ),
        "runtime-types": lambda root, files, config: runtime_type_issues(
            root,
            files,
            require_policy(config.checks.runtime_types, "runtime_types"),
        ),
        "cli": lambda root, files, config: cli_policy_issues(
            root, files, require_policy(config.checks.cli, "cli")
        ),
        "script-policy": lambda root, files, config: script_policy_issues(
            root,
            files,
            require_policy(config.checks.script_policy, "script_policy"),
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
