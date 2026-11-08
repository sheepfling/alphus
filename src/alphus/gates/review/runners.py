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
from alphus.gates.review.ci_workflows import check_ci_workflows
from alphus.gates.review.repeated_numeric_limits import (
    check_repeated_numeric_limits,
)
from alphus.gates.review.run_artifacts import check_run_artifacts
from alphus.gates.review.source_families import check_source_families
from alphus.gates.review.source_test_coverage import check_source_test_coverage
from alphus.gates.review.suppression_reasons import check_suppression_reasons
from alphus.gates.review.typing_stub_suggestions import check_typing_stub_suggestions
from alphus.policy.base import require_policy

ReviewRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]

__all__ = ["REVIEW_RULE_RUNNERS"]

REVIEW_RULE_RUNNERS: Mapping[QualityRuleName, ReviewRunner] = MappingProxyType(
    {
        "repeated-numeric-limits": lambda root, files, config: (
            check_repeated_numeric_limits(
                root,
                files,
                require_policy(
                    config.checks.repeated_numeric_limits,
                    "repeated_numeric_limits",
                ),
            )
        ),
        "typing-stub-suggestions": lambda root, files, config: (
            check_typing_stub_suggestions(
                root,
                files,
                require_policy(
                    config.checks.typing_stub_suggestions, "typing_stub_suggestions"
                ),
            )
        ),
        "run-artifacts": lambda root, files, config: check_run_artifacts(
            root,
            files,
            require_policy(config.checks.run_artifacts, "run_artifacts"),
        ),
        "ci-workflows": lambda root, files, config: check_ci_workflows(
            root,
            files,
            require_policy(config.checks.ci_workflows, "ci_workflows"),
        ),
        "source-test-coverage": lambda root, files, config: check_source_test_coverage(
            root,
            files,
            require_policy(config.checks.source_test_coverage, "source_test_coverage"),
        ),
        "source-families": lambda root, files, config: check_source_families(
            root,
            files,
            require_policy(config.checks.source_families, "source_families"),
        ),
        "suppression-reasons": lambda root, files, config: check_suppression_reasons(
            root,
            files,
            require_policy(config.checks.suppression_reasons, "suppression_reasons"),
        ),
    }
)
