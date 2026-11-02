"""Register the advisory review theme's built-in quality rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.review.frameworks.fastapi_practices import check_fastapi_practices
from alphus.gates.review.frameworks.pydantic_practices import check_pydantic_practices
from alphus.gates.review.frameworks.sqlalchemy_practices import (
    check_sqlalchemy_practices,
)
from alphus.gates.review.input_contracts import check_input_contracts
from alphus.gates.review.numeric_literals import check_numeric_literals
from alphus.gates.review.positional_interfaces import check_positional_interfaces
from alphus.gates.review.scipy_constants import check_scipy_constants
from alphus.gates.review.source_families import check_source_families
from alphus.gates.review.test_quality import check_test_quality
from alphus.gates.review.typing_stub_suggestions import check_typing_stub_suggestions
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
        "typing-stub-suggestions": lambda root, files, config: (
            check_typing_stub_suggestions(
                root,
                files,
                require_policy(
                    config.checks.typing_stub_suggestions, "typing_stub_suggestions"
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
