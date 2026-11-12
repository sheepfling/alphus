"""Register source and launcher quality rules with their validated policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput

SourceRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


SOURCE_RULE_RUNNERS: Mapping[QualityRuleName, SourceRunner] = MappingProxyType({})
