"""Register Git-specific repository gates separately from portable layout gates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.contracts.findings import Finding
from alphus.gates.vcs.git_quality import check_attributes, check_history, check_ignores
from alphus.policy.base import require_policy

VcsRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], list[Finding]
]

VCS_RULE_RUNNERS: Mapping[QualityRuleName, VcsRunner] = MappingProxyType(
    {
        "git-ignores": lambda root, _files, config: check_ignores(
            root, require_policy(config.checks.git, "git").languages
        ),
        "git-attributes": lambda root, _files, config: check_attributes(
            root, require_policy(config.checks.git, "git").attributes
        ),
        "git-history": lambda root, _files, config: check_history(
            root, require_policy(config.checks.git, "git").max_blob_mib
        ),
    }
)
