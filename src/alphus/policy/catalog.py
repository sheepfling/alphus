"""Built-in rule contracts shared by policy validation and profile decoding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType

from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR
from alphus.policy.morphology import RuleMorphology


class RuleOutputShape(StrEnum):
    FINDINGS = "findings"
    MESSAGES = "messages"
    PYTHON_STYLE = "python-style"
    SHARED_UTILITIES = "shared-utilities"
    CYCLOMATIC_REPORT = "cyclomatic-report"


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Configuration, output, and discovery metadata for one built-in rule."""

    policy_field: str
    output_shape: RuleOutputShape
    summary: str
    applies_to: tuple[str, ...]
    domains: tuple[str, ...] = ()
    requires_files: bool = True
    morphology: RuleMorphology | None = None

    def __post_init__(self) -> None:
        """Reject incomplete or malformed metadata used by agent discovery."""
        if not self.summary.strip():
            raise ValueError("built-in rules need a non-empty summary")
        if not self.applies_to or any(not label.strip() for label in self.applies_to):
            raise ValueError("built-in rules need applicability labels")
        for labels, description in (
            (self.applies_to, "applicability labels"),
            (self.domains, "domain tags"),
        ):
            if len(labels) != len(set(labels)) or any(
                label != label.casefold()
                or not label
                or any(
                    not (character.isalnum() or character == "-") for character in label
                )
                for label in labels
            ):
                raise ValueError(
                    f"built-in rule {description} must be unique lowercase slugs"
                )


_LEGACY_RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {
        "shared-utilities": RuleSpec(
            "shared_utilities",
            RuleOutputShape.SHARED_UTILITIES,
            "Finds duplicated shared-helper implementations and direct Git calls.",
            ("python",),
        ),
        "python-style": RuleSpec(
            "python_style",
            RuleOutputShape.PYTHON_STYLE,
            "Runs configured Python source-style checks.",
            ("python",),
        ),
        "runtime-types": RuleSpec(
            "runtime_types",
            RuleOutputShape.MESSAGES,
            "Reviews configured Python runtime type-checking conventions.",
            ("python",),
        ),
        "cli": RuleSpec(
            "cli",
            RuleOutputShape.MESSAGES,
            "Reviews configured Python command-line interface contracts.",
            ("python",),
        ),
        "script-policy": RuleSpec(
            "script_policy",
            RuleOutputShape.MESSAGES,
            "Checks configured Python and Node launcher/script conventions.",
            ("python", "javascript"),
        ),
        "repeated-numeric-limits": RuleSpec(
            "repeated_numeric_limits",
            RuleOutputShape.FINDINGS,
            "Reviews repeated numeric thresholds in explicitly selected Python analysis paths.",
            ("python",),
        ),
        "source-test-coverage": RuleSpec(
            "source_test_coverage",
            RuleOutputShape.FINDINGS,
            "Audits caller-declared source-to-test relationships against "
            "revision-matched execution evidence; it does not infer relationships "
            "from filenames or assess test correctness.",
            ("repository",),
            requires_files=False,
        ),
        "source-families": RuleSpec(
            "source_families",
            RuleOutputShape.FINDINGS,
            "Flags flat similarly named source families for human architectural review.",
            ("configurable-source",),
        ),
        "typing-stub-suggestions": RuleSpec(
            "typing_stub_suggestions",
            RuleOutputShape.FINDINGS,
            "Suggests compatible typing stub packages for declared dependencies.",
            ("python", "typing"),
        ),
        "prose-as-control": RuleSpec(
            "prose_as_control",
            RuleOutputShape.FINDINGS,
            "Reviews prose that controls adjacent source behavior.",
            ("python", "documentation"),
        ),
        "rendered-value-reparsed": RuleSpec(
            "prose_as_control",
            RuleOutputShape.FINDINGS,
            "Reviews rendered values that are parsed again as source.",
            ("python",),
        ),
        "positional-semantic-overrides": RuleSpec(
            "positional_semantic_overrides",
            RuleOutputShape.FINDINGS,
            "Reviews positional arguments that override semantic defaults.",
            ("python",),
        ),
        "unexplained-empty-results": RuleSpec(
            "unexplained_empty_results",
            RuleOutputShape.FINDINGS,
            "Reviews empty results without an evident explanation.",
            ("python",),
        ),
        "embedded-semantic-overrides": RuleSpec(
            "embedded_semantic_overrides",
            RuleOutputShape.FINDINGS,
            "Reviews semantic overrides embedded in source text.",
            ("python",),
        ),
        "heuristic-total-consumption": RuleSpec(
            "heuristic_total_consumption",
            RuleOutputShape.FINDINGS,
            "Reviews heuristic assumptions about total input consumption.",
            ("python",),
        ),
        "provenance-as-ownership": RuleSpec(
            "provenance_ownership",
            RuleOutputShape.FINDINGS,
            "Reviews provenance metadata used as an ownership guarantee.",
            ("python",),
        ),
        "semantic-work-in-presentation": RuleSpec(
            "semantic_work_presentation",
            RuleOutputShape.FINDINGS,
            "Reviews semantic work placed in presentation code.",
            ("python",),
        ),
        "parallel-normalization": RuleSpec(
            "parallel_normalization",
            RuleOutputShape.FINDINGS,
            "Reviews parallel normalization implementations.",
            ("python",),
        ),
        "patch-cascade": RuleSpec(
            "patch_cascade",
            RuleOutputShape.FINDINGS,
            "Reviews ordered patch operations that can cascade across edits.",
            ("python",),
        ),
        "manual-matrix-kernels": RuleSpec(
            "manual_matrix_kernels",
            RuleOutputShape.FINDINGS,
            "Reviews configured hand-written matrix kernel patterns.",
            ("python", "numerical"),
        ),
        "manual-elimination": RuleSpec(
            "manual_elimination",
            RuleOutputShape.FINDINGS,
            "Reviews configured hand-written elimination patterns.",
            ("python", "numerical"),
        ),
        "array-representation-churn": RuleSpec(
            "array_representation_churn",
            RuleOutputShape.FINDINGS,
            "Reviews configured array representation conversion patterns.",
            ("python", "numerical"),
        ),
        "cholesky-recurrence": RuleSpec(
            "cholesky_recurrence",
            RuleOutputShape.FINDINGS,
            "Reviews configured hand-written Cholesky recurrence patterns.",
            ("python", "numerical"),
        ),
        "manual-quaternion-products": RuleSpec(
            "manual_quaternion_products",
            RuleOutputShape.FINDINGS,
            "Reviews configured hand-written quaternion product patterns.",
            ("python", "numerical"),
        ),
        "manual-quaternion-conjugation": RuleSpec(
            "manual_quaternion_conjugation",
            RuleOutputShape.FINDINGS,
            "Reviews configured hand-written quaternion conjugation patterns.",
            ("python", "numerical"),
        ),
        "manual-quaternion-normalization": RuleSpec(
            "manual_quaternion_normalization",
            RuleOutputShape.FINDINGS,
            "Reviews configured hand-written quaternion normalization patterns.",
            ("python", "numerical"),
        ),
        "manual-quaternion-inversion": RuleSpec(
            "manual_quaternion_inversion",
            RuleOutputShape.FINDINGS,
            "Reviews configured hand-written quaternion inversion patterns.",
            ("python", "numerical"),
        ),
        "manual-quaternion-vector-rotation": RuleSpec(
            "manual_quaternion_vector_rotation",
            RuleOutputShape.FINDINGS,
            "Reviews configured hand-written quaternion vector rotations.",
            ("python", "numerical"),
        ),
        "manual-quaternion-matrix-conversion": RuleSpec(
            "manual_quaternion_matrix_conversion",
            RuleOutputShape.FINDINGS,
            "Reviews configured quaternion-to-matrix conversions.",
            ("python", "numerical"),
        ),
        "ecef-enu-transform": RuleSpec(
            "ecef_enu_transform",
            RuleOutputShape.FINDINGS,
            "Reviews configured ECEF-to-ENU transform patterns.",
            ("python", "geospatial"),
        ),
        "ecef-ned-matrix-transform": RuleSpec(
            "ecef_ned_matrix_transform",
            RuleOutputShape.FINDINGS,
            "Reviews configured ECEF-to-NED matrix patterns.",
            ("python", "geospatial"),
        ),
        "ci-workflows": RuleSpec(
            "ci_workflows",
            RuleOutputShape.FINDINGS,
            "Reviews selected CI workflow commands for repeated job work.",
            ("yaml", "ci"),
            requires_files=False,
        ),
        "ned-basis-vectors": RuleSpec(
            "ned_basis_vectors",
            RuleOutputShape.FINDINGS,
            "Reviews configured NED basis vector construction patterns.",
            ("python", "geospatial"),
        ),
        "run-artifacts": RuleSpec(
            "run_artifacts",
            RuleOutputShape.FINDINGS,
            "Reviews selected Python artifact production and verification handoffs.",
            ("python", "ci"),
        ),
        "positional-interfaces": RuleSpec(
            "positional_interfaces",
            RuleOutputShape.FINDINGS,
            "Reviews configured positional parameters at Python call and API boundaries.",
            ("python",),
        ),
        "pydantic-practices": RuleSpec(
            "pydantic_practices",
            RuleOutputShape.FINDINGS,
            "Reviews configured Pydantic model declarations and validation practices.",
            ("python", "pydantic"),
        ),
        "fastapi-practices": RuleSpec(
            "fastapi_practices",
            RuleOutputShape.FINDINGS,
            "Reviews configured FastAPI route and dependency practices.",
            ("python", "fastapi"),
        ),
        "sqlalchemy-practices": RuleSpec(
            "sqlalchemy_practices",
            RuleOutputShape.FINDINGS,
            "Reviews configured SQLAlchemy model, query, and session practices.",
            ("python", "sqlalchemy"),
        ),
        "dynamic-markdown": RuleSpec(
            "dynamic_markdown",
            RuleOutputShape.FINDINGS,
            "Reviews Python string assembly that places dynamic values into Markdown structure.",
            ("python", "markdown"),
            ("documentation-generation", "markdown-publishing"),
        ),
        "suppression-reasons": RuleSpec(
            "suppression_reasons",
            RuleOutputShape.FINDINGS,
            "Reviews selected Ruff suppressions for documented reasons.",
            ("python", "ruff"),
        ),
    }
)


_FEATURE_RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {
        selector: RuleSpec(
            definition.policy_field,
            RuleOutputShape(definition.output_shape),
            definition.summary,
            definition.applies_to,
            definition.domains,
            requires_files=definition.requires_files,
        )
        for selector, definition in FEATURE_DEFINITIONS.items()
    }
)

if set(_LEGACY_RULE_SPECS) & set(_FEATURE_RULE_SPECS):
    raise RuntimeError("built-in rule has both legacy and feature-owned metadata")

_ALL_RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {**_LEGACY_RULE_SPECS, **_FEATURE_RULE_SPECS}
)

RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {
        selector: replace(
            spec,
            morphology=MORPHOLOGY_BY_SELECTOR.get(selector),
        )
        for selector, spec in _ALL_RULE_SPECS.items()
    }
)
