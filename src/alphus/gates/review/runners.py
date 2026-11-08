"""Register explicit, deterministic adapters for advisory review rules.

The theme registry is intentionally hand-composed; architecture tests ensure its
selectors remain complete as the public rule catalog evolves.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.review.source_families import check_source_families
from alphus.gates.review.typing_stub_suggestions import check_typing_stub_suggestions
from alphus.policy.base import require_policy

ReviewRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]

__all__ = ["REVIEW_RULE_RUNNERS"]

REVIEW_RULE_RUNNERS: Mapping[QualityRuleName, ReviewRunner] = MappingProxyType(
    {
        "typing-stub-suggestions": lambda root, files, config: (
            check_typing_stub_suggestions(
                root,
                files,
                require_policy(
                    config.checks.typing_stub_suggestions, "typing_stub_suggestions"
                ),
            )
        ),
        "source-families": lambda root, files, config: check_source_families(
            root,
            files,
            require_policy(config.checks.source_families, "source_families"),
        ),
    }
)
