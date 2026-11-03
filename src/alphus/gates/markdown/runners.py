"""Register Markdown-specific built-in rule runners."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.markdown.shell_fences import check_markdown_shell_fences
from alphus.policy.base import require_policy

MarkdownRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


MARKDOWN_RULE_RUNNERS: Mapping[QualityRuleName, MarkdownRunner] = MappingProxyType(
    {
        "markdown-shell-fences": lambda root, _files, config: (
            check_markdown_shell_fences(
                root,
                require_policy(
                    config.checks.markdown_shell_fences, "markdown_shell_fences"
                ),
            )
        ),
    }
)
