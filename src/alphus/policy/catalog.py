"""Built-in rule contracts shared by policy validation and profile decoding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import QualityRuleName


class RuleOutputShape(StrEnum):
    FINDINGS = "findings"
    MESSAGES = "messages"
    PYTHON_STYLE = "python-style"
    SHARED_UTILITIES = "shared-utilities"


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """The primary policy and public JSON shape for one built-in rule."""

    policy_field: str
    output_shape: RuleOutputShape
    requires_files: bool = True
    message_rule_id: str | None = None

    def __post_init__(self) -> None:
        """Keep legacy message adapters fully described by the rule catalog."""
        if (self.output_shape is RuleOutputShape.MESSAGES) != (
            self.message_rule_id is not None
        ):
            raise ValueError(
                "message rule IDs must be registered only for message outputs"
            )


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
        "runtime-types": RuleSpec(
            "runtime_types",
            RuleOutputShape.MESSAGES,
            message_rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.TYPING,
                "runtime-type-contract-violation",
            ),
        ),
        "cli": RuleSpec(
            "cli",
            RuleOutputShape.MESSAGES,
            message_rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.CORRECTNESS,
                "cli-contract-violation",
            ),
        ),
        "script-policy": RuleSpec(
            "script_policy",
            RuleOutputShape.MESSAGES,
            message_rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.SECURITY,
                "script-policy-violation",
            ),
        ),
        "package-boundaries": RuleSpec("package_boundaries", RuleOutputShape.FINDINGS),
        "dependency-locks": RuleSpec("dependency_locks", RuleOutputShape.FINDINGS),
        "repository-layout": RuleSpec("repository_layout", RuleOutputShape.FINDINGS),
        "git-ignores": RuleSpec("git", RuleOutputShape.FINDINGS, requires_files=False),
        "git-attributes": RuleSpec(
            "git", RuleOutputShape.FINDINGS, requires_files=False
        ),
        "git-history": RuleSpec("git", RuleOutputShape.FINDINGS, requires_files=False),
        "numeric-literals": RuleSpec("numeric_literals", RuleOutputShape.FINDINGS),
        "scipy-constants": RuleSpec("scipy_constants", RuleOutputShape.FINDINGS),
        "geodesy-constants": RuleSpec("geodesy_constants", RuleOutputShape.FINDINGS),
        "test-quality": RuleSpec("test_quality", RuleOutputShape.FINDINGS),
        "input-contracts": RuleSpec("input_contracts", RuleOutputShape.FINDINGS),
        "source-families": RuleSpec("source_families", RuleOutputShape.FINDINGS),
        "pydantic-practices": RuleSpec("pydantic_practices", RuleOutputShape.FINDINGS),
        "fastapi-practices": RuleSpec("fastapi_practices", RuleOutputShape.FINDINGS),
    }
)
