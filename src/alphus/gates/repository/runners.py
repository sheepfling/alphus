"""Register repository architecture and packaging rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.python.module_roles import check_module_roles
from alphus.gates.repository.dependency_locks import check_dependency_locks
from alphus.gates.repository.documentation_config import check_documentation_config
from alphus.gates.repository.repository_layout import check_repository_layout
from alphus.policy.base import require_policy
from alphus.support.inventory import tracked_files

RepositoryRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


REPOSITORY_RULE_RUNNERS: Mapping[QualityRuleName, RepositoryRunner] = MappingProxyType(
    {
        "module-roles": lambda root, _files, config: check_module_roles(
            root, require_policy(config.checks.module_roles, "module_roles")
        ),
        "dependency-locks": lambda root, _files, config: check_dependency_locks(
            root,
            require_policy(config.checks.dependency_locks, "dependency_locks"),
        ),
        "repository-layout": lambda root, _files, config: check_repository_layout(
            root,
            require_policy(config.checks.repository_layout, "repository_layout"),
            tracked_files(root),
        ),
        "documentation-config": lambda root, _files, config: check_documentation_config(
            root,
            require_policy(config.checks.documentation_config, "documentation_config"),
        ),
    }
)
