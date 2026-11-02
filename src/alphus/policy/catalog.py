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
            "Matches configured exact numeric constants in Python arithmetic; it does not inspect model semantics.",
            ("python",),
            (
                "scientific-computing",
                "simulation",
                "earth-science",
                "trajectory-analysis",
            ),
        ),
        "scipy-constants": RuleSpec(
            "scipy_constants",
            RuleOutputShape.FINDINGS,
            "Finds selected SciPy physical constants and unit-conversion factors in Python arithmetic; it does not validate units or coordinate systems.",
            ("python",),
            (
                "scientific-computing",
                "simulation",
                "earth-science",
                "trajectory-analysis",
                "physical-units",
            ),
        ),
        "test-quality": RuleSpec(
            "test_quality",
            RuleOutputShape.FINDINGS,
            "Reviews configured Python tests for brittle prose assertions and transient-document handling.",
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
        "cyclomatic-complexity": RuleSpec(
            "cyclomatic_complexity",
            RuleOutputShape.CYCLOMATIC_REPORT,
            "Measures bounded cyclomatic complexity for supported source backends.",
            ("python", "javascript", "cpp"),
            requires_files=False,
        ),
    }
)
