"""Shared RuleTag contracts for composite repository checks."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, TypeAlias

from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag

RepositoryComplaintEmitter: TypeAlias = Literal["package-boundaries"]
RepositoryComplaintContractName: TypeAlias = Literal["package-boundaries-composite"]
_RepositoryComplaintEntry: TypeAlias = tuple[RepositoryComplaintEmitter, str]
_RepositoryComplaintContract: TypeAlias = tuple[
    RepositoryComplaintContractName,
    tuple[RepositoryComplaintEmitter, ...],
    tuple[_RepositoryComplaintEntry, ...],
]

# The package-boundaries gate combines findings from four engine modules. This
# static contract gives those engines one declared owner and preserves every ID.
ALPHUS_COMPLAINT_CONTRACTS: Final[tuple[_RepositoryComplaintContract, ...]] = (
    (
        "package-boundaries-composite",
        ("package-boundaries",),
        (
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "file-backed-module-loading",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "forbidden-import",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "forbidden-import-root",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "loose-module-import",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "opaque-dynamic-import",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "undeclared-import",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CONFIGURATION,
                    "duplicate-package-import-root",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CONFIGURATION,
                    "package-contract-missing",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CONFIGURATION,
                    "package-import-root-missing",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.DEPENDENCIES,
                    "forbidden-package-dependency",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.DEPENDENCIES,
                    "missing-package-dependency",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.DEPENDENCIES,
                    "package-dependency-cycle",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.DEPENDENCIES,
                    "unknown-package-dependency",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.METADATA,
                    "package-entry-point-invalid",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.METADATA,
                    "package-metadata-invalid",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.METADATA,
                    "package-metadata-path-invalid",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.SECURITY,
                    "python-path-mutation",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "edge-forbidden",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "edge-missing",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "graph-missing",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "graph-syntax-mismatch",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "node-missing",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.METADATA,
                    "version-mismatch",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "callable-mapping-missing",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "callable-mapping-not-literal",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "callable-registry-file-missing",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "public-callable-unregistered",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "callable-key-not-literal",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "callable-key-target-mismatch",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "duplicate-callable",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "unknown-callable",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.TYPING,
                    "callable-mapping-untyped",
                ),
            ),
            (
                "package-boundaries",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.TYPING,
                    "callable-protocol-untyped",
                ),
            ),
        ),
    ),
)


def _tag_index() -> Mapping[tuple[Scope, Framework, Category, str], str]:
    return MappingProxyType(
        {
            (
                tag.scope,
                tag.framework,
                tag.category,
                tag.complaint,
            ): tag.rule_id
            for _, _, entries in ALPHUS_COMPLAINT_CONTRACTS
            for _, rule_id in entries
            for tag in (RuleTag.parse(rule_id),)
        }
    )


_RULE_TAGS_BY_CLASSIFICATION = _tag_index()


def package_boundary_rule_tag(
    scope: Scope, framework: Framework, category: Category, complaint: str
) -> str:
    """Resolve a composite complaint through its feature-owned stable-ID contract."""
    try:
        return _RULE_TAGS_BY_CLASSIFICATION[(scope, framework, category, complaint)]
    except KeyError as error:
        raise ValueError(
            f"undeclared package-boundaries complaint: "
            f"{scope}/{framework}/{category}/{complaint}"
        ) from error
