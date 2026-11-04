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
from alphus.gates.review.benchmark_docs import check_benchmark_docs
from alphus.gates.review.ci_workflows import check_ci_workflows
from alphus.gates.review.document_style import check_document_style
from alphus.gates.review.embedded_semantic_overrides import (
    check_embedded_semantic_overrides,
)
from alphus.gates.review.frameworks.fastapi_practices import check_fastapi_practices
from alphus.gates.review.frameworks.pydantic.practices import check_pydantic_practices
from alphus.gates.review.frameworks.sqlalchemy_practices import (
    check_sqlalchemy_practices,
)
from alphus.gates.review.heuristic_total_consumption import (
    check_heuristic_total_consumption,
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
from alphus.gates.review.parallel_normalization import check_parallel_normalization
from alphus.gates.review.patch_cascade import check_patch_cascade
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
from alphus.gates.review.run_artifacts import check_run_artifacts
from alphus.gates.review.scipy_constants import check_scipy_constants
from alphus.gates.review.semantic_work_presentation import (
    check_semantic_work_presentation,
)
from alphus.gates.review.source_families import check_source_families
from alphus.gates.review.suppression_reasons import check_suppression_reasons
from alphus.gates.review.test_quality import check_test_quality
from alphus.gates.review.typing_stub_suggestions import check_typing_stub_suggestions
from alphus.gates.review.unexplained_empty_results import (
    check_unexplained_empty_results,
)
from alphus.policy.base import require_policy

ReviewRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]

__all__ = ["REVIEW_RULE_RUNNERS"]

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
        "semantic-work-in-presentation": lambda root, files, config: (
            check_semantic_work_presentation(
                root,
                files,
                require_policy(
                    config.checks.semantic_work_presentation,
                    "semantic_work_presentation",
                ),
            )
        ),
        "parallel-normalization": lambda root, files, config: (
            check_parallel_normalization(
                root,
                files,
                require_policy(
                    config.checks.parallel_normalization, "parallel_normalization"
                ),
            )
        ),
        "patch-cascade": lambda root, files, config: check_patch_cascade(
            root,
            files,
            require_policy(config.checks.patch_cascade, "patch_cascade"),
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
        "document-style": lambda root, files, config: check_document_style(
            root, files, require_policy(config.checks.document_style, "document_style")
        ),
        "suppression-reasons": lambda root, files, config: check_suppression_reasons(
            root,
            files,
            require_policy(config.checks.suppression_reasons, "suppression_reasons"),
        ),
    }
)
