"""Register Git-specific repository gates separately from portable layout gates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput

VcsRunner: TypeAlias = Callable[[Path, Sequence[Path], QualityGateConfig], RuleOutput]

VCS_RULE_RUNNERS: Mapping[QualityRuleName, VcsRunner] = MappingProxyType({})
