"""Register repository architecture and packaging rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.python.module_roles import check_module_roles
from alphus.policy.base import require_policy

RepositoryRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


REPOSITORY_RULE_RUNNERS: Mapping[QualityRuleName, RepositoryRunner] = MappingProxyType(
    {
        "module-roles": lambda root, _files, config: check_module_roles(
            root, require_policy(config.checks.module_roles, "module_roles")
        ),
    }
)
