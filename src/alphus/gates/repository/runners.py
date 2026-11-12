"""Register repository architecture and packaging rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput

RepositoryRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


REPOSITORY_RULE_RUNNERS: Mapping[QualityRuleName, RepositoryRunner] = MappingProxyType(
    {}
)
