"""Built-in rule contracts shared by policy validation and profile decoding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


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


RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {
        "file-size": RuleSpec(
            "file_size",
            RuleOutputShape.FINDINGS,
            "Reports source files that exceed configured physical-line limits.",
            ("configurable-source",),
        ),
        "comment-markers": RuleSpec(
            "comment_markers",
            RuleOutputShape.FINDINGS,
            "Finds configured TODO-style markers in supported source comments.",
            ("python", "javascript", "c", "cpp"),
        ),
        "line-length": RuleSpec(
            "line_length",
            RuleOutputShape.FINDINGS,
            "Reports source lines that exceed configured per-extension limits.",
            ("configurable-source",),
        ),
        "json-structure": RuleSpec(
            "json_structure",
            RuleOutputShape.FINDINGS,
            "Checks configured structural expectations in JSON documents.",
            ("json",),
        ),
        "output-escaping": RuleSpec(
            "output_escaping",
            RuleOutputShape.FINDINGS,
            "Reviews dynamic values at configured HTML or shell output sinks.",
            ("python", "javascript"),
        ),
        "path-discovery": RuleSpec(
            "path_discovery",
            RuleOutputShape.FINDINGS,
            "Reviews Python filesystem discovery and path handling patterns.",
            ("python",),
        ),
        "shared-utilities": RuleSpec(
            "shared_utilities",
            RuleOutputShape.SHARED_UTILITIES,
            "Finds duplicated shared-helper implementations and direct Git calls.",
            ("python",),
        ),
        "module-roles": RuleSpec(
            "module_roles",
            RuleOutputShape.FINDINGS,
            "Checks configured Python module-role and ownership conventions.",
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
        "package-boundaries": RuleSpec(
            "package_boundaries",
            RuleOutputShape.FINDINGS,
            "Checks configured Python import and package-boundary rules.",
            ("python",),
        ),
        "dependency-locks": RuleSpec(
            "dependency_locks",
            RuleOutputShape.FINDINGS,
            "Checks consistency and pairing of configured dependency lockfiles.",
            ("python", "javascript"),
        ),
        "repository-layout": RuleSpec(
            "repository_layout",
            RuleOutputShape.FINDINGS,
            "Checks configured repository paths, required files, and layout rules.",
            ("repository",),
        ),
        "documentation-config": RuleSpec(
            "documentation_config",
            RuleOutputShape.FINDINGS,
            "Checks documentation links and repository-specific documentation configuration.",
            ("markdown", "repository"),
            requires_files=False,
        ),
        "git-ignores": RuleSpec(
            "git",
            RuleOutputShape.FINDINGS,
            "Checks tracked paths against configured Git ignore expectations.",
            ("git", "repository"),
            requires_files=False,
        ),
        "git-attributes": RuleSpec(
            "git",
            RuleOutputShape.FINDINGS,
            "Checks configured Git attributes for tracked repository paths.",
            ("git", "repository"),
            requires_files=False,
        ),
        "git-history": RuleSpec(
            "git",
            RuleOutputShape.FINDINGS,
            "Reviews repository history for configured commit and change patterns.",
            ("git", "repository"),
            requires_files=False,
        ),
        "numeric-literals": RuleSpec(
            "numeric_literals",
            RuleOutputShape.FINDINGS,
            "Matches configured exact numeric constants in Python arithmetic; "
            "it does not inspect model semantics.",
            ("python",),
            (
                "scientific-computing",
                "simulation",
                "earth-science",
                "trajectory-analysis",
            ),
        ),
        "repeated-numeric-limits": RuleSpec(
            "repeated_numeric_limits",
            RuleOutputShape.FINDINGS,
            "Reviews repeated numeric thresholds in explicitly selected Python analysis paths.",
            ("python",),
        ),
        "scipy-constants": RuleSpec(
            "scipy_constants",
            RuleOutputShape.FINDINGS,
            "Finds selected SciPy physical constants and unit-conversion factors "
            "in Python arithmetic; it does not validate units or coordinate systems.",
            ("python",),
            (
                "scientific-computing",
                "simulation",
                "earth-science",
                "trajectory-analysis",
                "physical-units",
            ),
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
        "test-quality": RuleSpec(
            "test_quality",
            RuleOutputShape.FINDINGS,
            "Reviews configured Python tests for brittle prose assertions and "
            "transient-document handling.",
            ("python",),
        ),
        "input-contracts": RuleSpec(
            "input_contracts",
            RuleOutputShape.FINDINGS,
            "Reviews local Python collection mutation and read-only input contracts.",
            ("python",),
        ),
        "source-families": RuleSpec(
            "source_families",
            RuleOutputShape.FINDINGS,
            "Flags flat similarly named source families for human architectural review.",
            ("configurable-source",),
        ),
        "markdown-shell-fences": RuleSpec(
            "markdown_shell_fences",
            RuleOutputShape.FINDINGS,
            "Checks fenced shell examples for bounded heredoc termination errors.",
            ("markdown", "shell"),
            requires_files=False,
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
        "document-style": RuleSpec(
            "document_style",
            RuleOutputShape.FINDINGS,
            "Reviews heading styles in selected Markdown, LaTeX, and source HTML documents.",
            ("markdown", "latex", "html"),
        ),
        "benchmark-docs": RuleSpec(
            "benchmark_docs",
            RuleOutputShape.FINDINGS,
            "Reviews benchmark documentation for required result context.",
            ("markdown", "benchmarking"),
        ),
        "suppression-reasons": RuleSpec(
            "suppression_reasons",
            RuleOutputShape.FINDINGS,
            "Reviews selected Ruff suppressions for documented reasons.",
            ("python", "ruff"),
        ),
        "cyclomatic-complexity": RuleSpec(
            "cyclomatic_complexity",
            RuleOutputShape.CYCLOMATIC_REPORT,
            "Measures bounded cyclomatic complexity for supported source backends.",
            ("python", "javascript", "cpp"),
            requires_files=False,
        ),
    }
)
