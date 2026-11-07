"""Register Markdown-specific built-in rule runners."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput

MarkdownRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


MARKDOWN_RULE_RUNNERS: Mapping[QualityRuleName, MarkdownRunner] = MappingProxyType({})
