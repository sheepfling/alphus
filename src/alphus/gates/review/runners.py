"""Register the advisory review theme's built-in quality rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.review.input_contracts import check_input_contracts
from alphus.gates.review.numeric_literals import check_numeric_literals
from alphus.gates.review.test_quality import check_test_quality
from alphus.policy.base import require_policy

ReviewRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]

REVIEW_RULE_RUNNERS: Mapping[QualityRuleName, ReviewRunner] = MappingProxyType(
    {
        "numeric-literals": lambda root, files, config: check_numeric_literals(
            root,
            files,
            require_policy(config.checks.numeric_literals, "numeric_literals"),
        ),
        "test-quality": lambda root, files, config: check_test_quality(
            root,
            files,
            require_policy(config.checks.test_quality, "test_quality"),
        ),
        "input-contracts": lambda root, files, config: check_input_contracts(
            root,
            files,
            require_policy(config.checks.input_contracts, "input_contracts"),
        ),
    }
)
