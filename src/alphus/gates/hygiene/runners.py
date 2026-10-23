"""Register general source-size and shared-utility rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.hygiene.rules import check_file_size, check_line_length
from alphus.gates.hygiene.shared_utilities import check_shared_utilities
from alphus.policy.base import require_policy

HygieneRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]

HYGIENE_RULE_RUNNERS: Mapping[QualityRuleName, HygieneRunner] = MappingProxyType(
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
    }
)
