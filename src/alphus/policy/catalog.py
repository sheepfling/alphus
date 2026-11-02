"""Built-in rule contracts shared by policy validation and profile decoding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from alphus.policy.base import QualityRuleName


class RuleOutputShape(StrEnum):
    FINDINGS = "findings"
    MESSAGES = "messages"
    PYTHON_STYLE = "python-style"
    SHARED_UTILITIES = "shared-utilities"
    CYCLOMATIC_REPORT = "cyclomatic-report"


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """The primary policy and public JSON shape for one built-in rule."""

    policy_field: str
    output_shape: RuleOutputShape
    requires_files: bool = True


RULE_SPECS: Mapping[QualityRuleName, RuleSpec] = MappingProxyType(
    {
        "file-size": RuleSpec("file_size", RuleOutputShape.FINDINGS),
        "comment-markers": RuleSpec("comment_markers", RuleOutputShape.FINDINGS),
        "line-length": RuleSpec("line_length", RuleOutputShape.FINDINGS),
        "json-structure": RuleSpec("json_structure", RuleOutputShape.FINDINGS),
        "output-escaping": RuleSpec("output_escaping", RuleOutputShape.FINDINGS),
        "path-discovery": RuleSpec("path_discovery", RuleOutputShape.FINDINGS),
        "shared-utilities": RuleSpec(
            "shared_utilities", RuleOutputShape.SHARED_UTILITIES
        ),
        "module-roles": RuleSpec("module_roles", RuleOutputShape.FINDINGS),
        "python-style": RuleSpec("python_style", RuleOutputShape.PYTHON_STYLE),
        "runtime-types": RuleSpec("runtime_types", RuleOutputShape.MESSAGES),
        "cli": RuleSpec("cli", RuleOutputShape.MESSAGES),
        "script-policy": RuleSpec("script_policy", RuleOutputShape.MESSAGES),
        "package-boundaries": RuleSpec("package_boundaries", RuleOutputShape.FINDINGS),
        "dependency-locks": RuleSpec("dependency_locks", RuleOutputShape.FINDINGS),
        "repository-layout": RuleSpec("repository_layout", RuleOutputShape.FINDINGS),
        "documentation-config": RuleSpec(
            "documentation_config", RuleOutputShape.FINDINGS, requires_files=False
        ),
        "git-ignores": RuleSpec("git", RuleOutputShape.FINDINGS, requires_files=False),
        "git-attributes": RuleSpec(
            "git", RuleOutputShape.FINDINGS, requires_files=False
        ),
        "git-history": RuleSpec("git", RuleOutputShape.FINDINGS, requires_files=False),
        "numeric-literals": RuleSpec("numeric_literals", RuleOutputShape.FINDINGS),
        "scipy-constants": RuleSpec("scipy_constants", RuleOutputShape.FINDINGS),
        "test-quality": RuleSpec("test_quality", RuleOutputShape.FINDINGS),
        "input-contracts": RuleSpec("input_contracts", RuleOutputShape.FINDINGS),
        "source-families": RuleSpec("source_families", RuleOutputShape.FINDINGS),
        "positional-interfaces": RuleSpec(
            "positional_interfaces", RuleOutputShape.FINDINGS
        ),
        "pydantic-practices": RuleSpec("pydantic_practices", RuleOutputShape.FINDINGS),
        "fastapi-practices": RuleSpec("fastapi_practices", RuleOutputShape.FINDINGS),
        "sqlalchemy-practices": RuleSpec(
            "sqlalchemy_practices", RuleOutputShape.FINDINGS
        ),
        "cyclomatic-complexity": RuleSpec(
            "cyclomatic_complexity",
            RuleOutputShape.CYCLOMATIC_REPORT,
            requires_files=False,
        ),
    }
)
