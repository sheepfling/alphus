"""Register the advisory review theme's built-in quality rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.review.benchmark_docs import check_benchmark_docs
from alphus.gates.review.ci_workflows import check_ci_workflows
from alphus.gates.review.frameworks.fastapi_practices import check_fastapi_practices
from alphus.gates.review.frameworks.pydantic.practices import check_pydantic_practices
from alphus.gates.review.frameworks.sqlalchemy_practices import (
    check_sqlalchemy_practices,
)
from alphus.gates.review.input_contracts import check_input_contracts
from alphus.gates.review.numeric_literals import check_numeric_literals
from alphus.gates.review.numerical.frames.ecef_enu_transform import (
    check_ecef_enu_transform,
)
from alphus.gates.review.numerical.frames.ecef_ned_matrix_transform import (
    check_ecef_ned_matrix_transform,
)
from alphus.gates.review.numerical.frames.ned_basis_vectors import (
    check_ned_basis_vectors,
)
from alphus.gates.review.numerical.linear_algebra.array_representation import (
    check_array_representation,
)
from alphus.gates.review.numerical.linear_algebra.cholesky_recurrence import (
    check_cholesky_recurrence,
)
from alphus.gates.review.numerical.linear_algebra.manual_elimination import (
    check_manual_elimination,
)
from alphus.gates.review.numerical.linear_algebra.manual_matrix_kernels import (
    check_manual_matrix_kernels,
)
from alphus.gates.review.numerical.quaternions.manual_quaternion_conjugation import (
    check_manual_quaternion_conjugation,
)
from alphus.gates.review.numerical.quaternions.manual_quaternion_inversion import (
    check_manual_quaternion_inversion,
)
from alphus.gates.review.numerical.quaternions.manual_quaternion_matrix_conversion import (
    check_manual_quaternion_matrix_conversion,
)
from alphus.gates.review.numerical.quaternions.manual_quaternion_normalization import (
    check_manual_quaternion_normalization,
)
from alphus.gates.review.numerical.quaternions.manual_quaternion_product import (
    check_manual_quaternion_products,
)
from alphus.gates.review.numerical.quaternions.manual_quaternion_vector_rotation import (
    check_manual_quaternion_vector_rotation,
)
from alphus.gates.review.positional_interfaces import check_positional_interfaces
from alphus.gates.review.scipy_constants import check_scipy_constants
from alphus.gates.review.source_families import check_source_families
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
        "manual-matrix-kernels": lambda root, files, config: (
            check_manual_matrix_kernels(
                root,
                files,
                require_policy(
                    config.checks.manual_matrix_kernels, "manual_matrix_kernels"
                ),
            )
        ),
        "manual-elimination": lambda root, files, config: check_manual_elimination(
            root,
            files,
            require_policy(config.checks.manual_elimination, "manual_elimination"),
        ),
        "array-representation-churn": lambda root, files, config: (
            check_array_representation(
                root,
                files,
                require_policy(
                    config.checks.array_representation_churn,
                    "array_representation_churn",
                ),
            )
        ),
        "cholesky-recurrence": lambda root, files, config: check_cholesky_recurrence(
            root,
            files,
            require_policy(config.checks.cholesky_recurrence, "cholesky_recurrence"),
        ),
        "manual-quaternion-products": lambda root, files, config: (
            check_manual_quaternion_products(
                root,
                files,
                require_policy(
                    config.checks.manual_quaternion_products,
                    "manual_quaternion_products",
                ),
            )
        ),
        "manual-quaternion-conjugation": lambda root, files, config: (
            check_manual_quaternion_conjugation(
                root,
                files,
                require_policy(
                    config.checks.manual_quaternion_conjugation,
                    "manual_quaternion_conjugation",
                ),
            )
        ),
        "manual-quaternion-normalization": lambda root, files, config: (
            check_manual_quaternion_normalization(
                root,
                files,
                require_policy(
                    config.checks.manual_quaternion_normalization,
                    "manual_quaternion_normalization",
                ),
            )
        ),
        "manual-quaternion-inversion": lambda root, files, config: (
            check_manual_quaternion_inversion(
                root,
                files,
                require_policy(
                    config.checks.manual_quaternion_inversion,
                    "manual_quaternion_inversion",
                ),
            )
        ),
        "manual-quaternion-vector-rotation": lambda root, files, config: (
            check_manual_quaternion_vector_rotation(
                root,
                files,
                require_policy(
                    config.checks.manual_quaternion_vector_rotation,
                    "manual_quaternion_vector_rotation",
                ),
            )
        ),
        "manual-quaternion-matrix-conversion": lambda root, files, config: (
            check_manual_quaternion_matrix_conversion(
                root,
                files,
                require_policy(
                    config.checks.manual_quaternion_matrix_conversion,
                    "manual_quaternion_matrix_conversion",
                ),
            )
        ),
        "ecef-enu-transform": lambda root, files, config: check_ecef_enu_transform(
            root,
            files,
            require_policy(config.checks.ecef_enu_transform, "ecef_enu_transform"),
        ),
        "ecef-ned-matrix-transform": lambda root, files, config: (
            check_ecef_ned_matrix_transform(
                root,
                files,
                require_policy(
                    config.checks.ecef_ned_matrix_transform,
                    "ecef_ned_matrix_transform",
                ),
            )
        ),
        "ned-basis-vectors": lambda root, files, config: check_ned_basis_vectors(
            root,
            files,
            require_policy(config.checks.ned_basis_vectors, "ned_basis_vectors"),
        ),
        "scipy-constants": lambda root, files, config: check_scipy_constants(
            root,
            files,
            require_policy(config.checks.scipy_constants, "scipy_constants"),
        ),
        "ci-workflows": lambda root, files, config: check_ci_workflows(
            root,
            files,
            require_policy(config.checks.ci_workflows, "ci_workflows"),
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
        "benchmark-docs": lambda root, files, config: check_benchmark_docs(
            root,
            files,
            require_policy(config.checks.benchmark_docs, "benchmark_docs"),
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
