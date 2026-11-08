"""Register source and launcher quality rules with their validated policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.languages.python.style import findings_for as python_style_findings
from alphus.policy.base import require_policy

SourceRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


SOURCE_RULE_RUNNERS: Mapping[QualityRuleName, SourceRunner] = MappingProxyType(
    {
        "python-style": lambda root, files, config: python_style_findings(
            root,
            files,
            require_policy(config.checks.python_style, "python_style"),
        ),
    }
)
