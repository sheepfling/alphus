"""Register the advisory review theme's built-in quality rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.review.embedded_semantic_overrides import (
    check_embedded_semantic_overrides,
)
from alphus.gates.review.frameworks.fastapi_practices import check_fastapi_practices
from alphus.gates.review.frameworks.pydantic_practices import check_pydantic_practices
from alphus.gates.review.frameworks.sqlalchemy_practices import (
    check_sqlalchemy_practices,
)
from alphus.gates.review.heuristic_total_consumption import (
    check_heuristic_total_consumption,
)
from alphus.gates.review.input_contracts import check_input_contracts
from alphus.gates.review.numeric_literals import check_numeric_literals
from alphus.gates.review.positional_interfaces import check_positional_interfaces
from alphus.gates.review.positional_semantic_overrides import (
    check_positional_semantic_overrides,
)
from alphus.gates.review.prose_as_control import (
    check_lossy_text_rewrite,
    check_prose_as_control,
)
from alphus.gates.review.provenance_ownership import check_provenance_ownership
from alphus.gates.review.rendered_value_reparsed import (
    check_rendered_value_reparsed,
)
from alphus.gates.review.scipy_constants import check_scipy_constants
from alphus.gates.review.source_families import check_source_families
from alphus.gates.review.test_quality import check_test_quality
from alphus.gates.review.unexplained_empty_results import (
    check_unexplained_empty_results,
)
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
        "prose-as-control": lambda root, files, config: (
            check_prose_as_control(
                root,
                files,
                require_policy(config.checks.prose_as_control, "prose_as_control"),
            )
            + check_lossy_text_rewrite(
                root,
                files,
                require_policy(config.checks.prose_as_control, "prose_as_control"),
            )
            + check_rendered_value_reparsed(
                root,
                files,
                require_policy(config.checks.prose_as_control, "prose_as_control"),
            )
        ),
        "rendered-value-reparsed": lambda root, files, config: (
            check_rendered_value_reparsed(
                root,
                files,
                require_policy(config.checks.prose_as_control, "prose_as_control"),
            )
        ),
        "positional-semantic-overrides": lambda root, files, config: (
            check_positional_semantic_overrides(
                root,
                files,
                require_policy(
                    config.checks.positional_semantic_overrides,
                    "positional_semantic_overrides",
                ),
            )
        ),
        "unexplained-empty-results": lambda root, files, config: (
            check_unexplained_empty_results(
                root,
                files,
                require_policy(
                    config.checks.unexplained_empty_results,
                    "unexplained_empty_results",
                ),
            )
        ),
        "embedded-semantic-overrides": lambda root, files, config: (
            check_embedded_semantic_overrides(
                root,
                files,
                require_policy(
                    config.checks.embedded_semantic_overrides,
                    "embedded_semantic_overrides",
                ),
            )
        ),
        "heuristic-total-consumption": lambda root, files, config: (
            check_heuristic_total_consumption(
                root,
                files,
                require_policy(
                    config.checks.heuristic_total_consumption,
                    "heuristic_total_consumption",
                ),
            )
        ),
        "provenance-as-ownership": lambda root, files, config: (
            check_provenance_ownership(
                root,
                files,
                require_policy(
                    config.checks.provenance_ownership, "provenance_ownership"
                ),
            )
        ),
        "scipy-constants": lambda root, files, config: check_scipy_constants(
            root,
            files,
            require_policy(config.checks.scipy_constants, "scipy_constants"),
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
        "source-families": lambda root, files, config: check_source_families(
            root,
            files,
            require_policy(config.checks.source_families, "source_families"),
        ),
        "positional-interfaces": lambda root, files, config: (
            check_positional_interfaces(
                root,
                files,
                require_policy(
                    config.checks.positional_interfaces, "positional_interfaces"
                ),
            )
        ),
        "pydantic-practices": lambda root, files, config: check_pydantic_practices(
            root,
            files,
            require_policy(config.checks.pydantic_practices, "pydantic_practices"),
        ),
        "fastapi-practices": lambda root, files, config: check_fastapi_practices(
            root,
            files,
            require_policy(config.checks.fastapi_practices, "fastapi_practices"),
        ),
        "sqlalchemy-practices": lambda root, files, config: check_sqlalchemy_practices(
            root,
            files,
            require_policy(config.checks.sqlalchemy_practices, "sqlalchemy_practices"),
        ),
    }
)
