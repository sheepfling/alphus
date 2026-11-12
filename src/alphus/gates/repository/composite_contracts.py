"""Shared RuleTag contracts for composite repository checks."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, TypeAlias

from alphus.contracts.complaints import ComplaintContract, ComplaintEntry
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope

RepositoryComplaintEmitter: TypeAlias = Literal["package-boundaries"]
RepositoryComplaintContractName: TypeAlias = Literal["package-boundaries-composite"]
# The package-boundaries gate combines findings from four engine modules. This
# static contract gives those engines one declared owner and preserves every ID.
ALPHUS_COMPLAINT_CONTRACTS: Final = (
    ComplaintContract(
        name="package-boundaries-composite",
        emitters=("package-boundaries",),
        entries=(
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "file-backed-module-loading",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "forbidden-import",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "forbidden-import-root",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "loose-module-import",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "opaque-dynamic-import",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "undeclared-import",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CONFIGURATION,
                    "duplicate-package-import-root",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CONFIGURATION,
                    "package-contract-missing",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CONFIGURATION,
                    "package-import-root-missing",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.DEPENDENCIES,
                    "forbidden-package-dependency",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.DEPENDENCIES,
                    "missing-package-dependency",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.DEPENDENCIES,
                    "package-dependency-cycle",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.DEPENDENCIES,
                    "unknown-package-dependency",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.METADATA,
                    "package-entry-point-invalid",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.METADATA,
                    "package-metadata-invalid",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.METADATA,
                    "package-metadata-path-invalid",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.SECURITY,
                    "python-path-mutation",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "edge-forbidden",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "edge-missing",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "graph-missing",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "graph-syntax-mismatch",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "node-missing",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.NONE,
                    Category.METADATA,
                    "version-mismatch",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "callable-mapping-missing",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "callable-mapping-not-literal",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "callable-registry-file-missing",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "public-callable-unregistered",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "callable-key-not-literal",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "callable-key-target-mismatch",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "duplicate-callable",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "unknown-callable",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.TYPING,
                    "callable-mapping-untyped",
                ),
            ),
            ComplaintEntry(
                emitter="package-boundaries",
                tag=RuleTag(
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
            for contract in ALPHUS_COMPLAINT_CONTRACTS
            for entry in contract.entries
            for tag in (entry.tag,)
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
